# TTLI_LMS — Deployment Versioning & Rollback Strategy

**Scope:** fills the gap between `06_OPERATIONS.md` §4.5's one-paragraph pipeline sketch and an
actually-implementable Phase 7 deploy pipeline: how an upgrade is detected, how it's versioned,
how a canary/rollback actually works on the already-chosen platform (Azure Container Apps, §1.5 of
`devsecops-deployment.md`), and how a database migration stays rollback-safe.

**Audience:** whoever implements Phase 7 Terraform + the deploy stage of `.github/workflows/ci.yml`.

**Method note, same convention as `devsecops-deployment.md`:** claims are marked **verified**
(sourced against official docs) or **synthesis** (this document's reasoning). Researched August 2026.

**Template this follows:** `C:\applications\docs\templates\DEPLOYMENT_ROLLBACK_PLAYBOOK_TEMPLATE.md`
— that file is the project-agnostic version; this is Pattern A (orchestrator with native
revisions/traffic-split) filled in for this specific stack.

---

## 1. Trigger / detection — a bot PR, not a special workflow

Add **Dependabot** (`.github/dependabot.yml`, zero new infra, GitHub-native) watching:

- `apps/api/requirements-dev.txt` (pip)
- `apps/web/package-lock.json` and `packages/api-client/package-lock.json` (npm)
- `apps/api/Dockerfile` and `apps/web/Dockerfile` base images (docker)
- `.github/workflows/*.yml` action versions (github-actions)

Security advisories: daily. Version updates: weekly, grouped (one PR for related patch/minor
bumps rather than one per package — cuts review noise). Major-version bumps: never automerged.

**The bot's PR runs `ci.yml` exactly as written today — no changes needed to the workflow for this
to work.** That's already correct: `quality`, `secrets`, `images`, `web`, and `authenticated-e2e`
all trigger on `pull_request` regardless of who opened it. The only new work is what happens
*after* that gate passes on `main` (§2 onward) — today the pipeline stops at green CI with no
deploy step at all.

## 2. Versioning scheme

- Tag every built image with the **git SHA** (`ttli-api:${{ github.sha }}`, `ttli-web:${{ github.sha }}`).
  The `images` job already builds `ttli-api:ci` / `ttli-web:ci` — change those tags to the SHA once
  a registry exists, and push instead of just building.
- Tag with semver (`v1.4.2`) additionally on an intentional release (a git tag push), for human-
  readable release notes; the SHA tag remains the one Terraform/Container Apps actually references.
- **Registry: Azure Container Registry (ACR)**, in the same South Africa North region as everything
  else in `06_OPERATIONS.md` §4.2 — keeps image pulls in-region and avoids a new cross-border data
  question. Enable ACR's built-in vulnerability scanning (Defender for Cloud) on push, in addition
  to the Trivy step CI already runs — belt and suspenders, cheap at this scale. *(Synthesis — pricing
  not independently re-verified here, same caveat as `devsecops-deployment.md`.)*
- Never deploy `ttli-api:ci` / `:latest` / any floating tag past the `images` CI job. That tag exists
  only to prove the Dockerfile builds; it is not a deployable artifact.

## 3. Environments & promotion

Four environments per `06_OPERATIONS.md` §4.5: local, dev, staging, production. Encode staging and
production as **GitHub Environments** (`Settings → Environments`), not just words in a doc:

- `staging`: no required reviewers — auto-deploys the SHA that just passed `main`'s CI.
- `production`: **required reviewers** (at least one human) — this is the "manual approval" step
  `06_OPERATIONS.md` §4.5 already names; a GitHub Environment protection rule is what actually
  enforces it instead of it being a convention someone can skip under deadline pressure.

Promotion is one build, two deploys: the exact image SHA that passed staging smoke tests is what
gets promoted to production — never a rebuild between the two.

## 4. Deployment topology — Azure Container Apps revisions (Pattern A)

**Verified:** Container Apps creates a new **revision** on every template change (image, env vars,
scale rules) rather than replacing the running one in place. In **multiple revision mode**, several
revisions run simultaneously and traffic is split between them by weight
(`az containerapp ingress traffic set --revision-weight <name>=<pct>`, or by revision label).
[MS Learn — Revisions](https://learn.microsoft.com/en-us/azure/container-apps/revisions) ·
[MS Learn — Traffic splitting](https://learn.microsoft.com/en-us/azure/container-apps/traffic-splitting)

**Rollout for `web` and `api` (the two components with real user traffic):**

1. Deploy the new SHA as a new revision at **5% traffic**, hold **≥30 minutes**, watching the
   thresholds in §5.
2. **25% → 50% → 100%**, same hold, same thresholds at each step. Script this as an Actions job
   looping `traffic set` calls with a sleep and a metrics check — not a manual sequence of commands
   someone has to remember to run four times.
3. **Rollback at any step = shift weight back to the previous revision (`100%` old / `0%` new).**
   Both revisions are already running — this is a routing change, not a redeploy, and it's why
   Container Apps was the right pick over a platform without this primitive.

**Worker (arq) and ClamAV** don't take user-facing traffic, so they don't need the percentage ramp —
deploy the new revision directly, keep the previous one available to reactivate if the new one
fails its own health check, matching the `minReplicas: 0` (worker, via KEDA) / `minReplicas: 1`
(ClamAV) shape `devsecops-deployment.md` §2.1 already specifies.

**Retention:** keep the **last 5 revisions** active in Container Apps (a config value, not a
default to inherit blindly) and the **last 10 SHA-tagged images** in ACR — covers "roll back
further than one step" without unbounded registry growth.

## 5. Automated rollback triggers — concrete numbers

Reuse the thresholds `06_OPERATIONS.md` §5.2 already defines for alerting — don't invent a second
set:

| Signal | Threshold | Action |
|---|---|---|
| HTTP error rate | > 2% for 10 minutes | Halt ramp, shift traffic back to previous revision |
| API p95 latency | > 800ms for 10 minutes | Halt ramp, shift traffic back to previous revision |
| `/health` / `/readyz`-equivalent failing | 3 consecutive checks | Halt ramp immediately, do not wait for the 10-minute window |
| Payment webhook failure | Any | Halt ramp immediately (already a page-now alert in §5.2) |
| Invoice sequence gap | Any | Halt ramp immediately (already the one alert §5.2 says must never be routed to a digest) |

**Verified pattern this mirrors:** progressive-delivery tooling (Flagger is the commonly-cited
example) enforces success-rate/latency thresholds automatically and reverts after N consecutive
failed checks rather than a single blip.
[Akuity — Argo Rollouts](https://akuity.io/blog/automating-blue-green-and-canary-deployments-with-argo-rollouts)
This project doesn't need Flagger/Argo specifically — Container Apps' own revision weights plus a
scripted Actions check loop against Azure Monitor achieves the same thing at this scale, without
adding a Kubernetes-shaped dependency to a platform chosen partly to avoid one.

## 6. Database migrations — decoupled from the code rollback above

`06_OPERATIONS.md` §4.5 already states the rule in one sentence: *"Migrations are backward-
compatible: add nullable, backfill, constrain — never all three in one release."* Concretely:

- **Expand** (release N): add the new nullable column/table. Old and new app code both still work
  against it.
- **Migrate** (release N, same release or shortly after): backfill data, dual-write if needed.
- **Contract** (release N+k, once nothing reads the old shape): drop/constrain. Only ever in a
  release where §4's revision-rollback path is not simultaneously needed for that same change —
  i.e., don't ship a contract step in the same rollout you're least sure about.
- `alembic downgrade -1` stays what CI's "Migration round-trip" step already checks — that's a
  **CI correctness check**, not the production rollback mechanism. Production rollback is
  **forward-fix**: if a migration causes a problem after reaching production, ship a new migration
  that corrects it, rather than running `alembic downgrade` against live data.
- Run the migration step (`alembic upgrade head`) **before** the traffic ramp in §4 starts, and
  make it required-green before revision 5%-traffic begins — a migration that fails should block
  the rollout the same way a failed CI gate blocks merge, not be discovered mid-canary.

**Verified, sourced:** this expand/migrate/contract shape and the N/N-1 compatibility rule it
depends on is the standard zero-downtime migration pattern, not a project-specific invention.
[Harness — Zero-downtime migrations](https://www.harness.io/blog/zero-downtime-database-migrations-safe-schema-changes) ·
[Tim Wellhausen — Expand and Contract](https://www.tim-wellhausen.de/papers/ExpandAndContract/ExpandAndContract.html)

## 7. What Phase 7 actually needs to build

This document doesn't change `06_OPERATIONS.md` §4.5's decisions — it makes them concrete enough
to implement. The delta from "nothing provisioned yet" (per `devsecops-deployment.md` §"deployment
artefacts... no registry push, because there is no deployment target yet") to done:

1. Provision ACR + Container Apps environment in Terraform (Phase 7, already planned).
2. `.github/dependabot.yml` (§1) — this one can land today, independent of Phase 7, since it only
   produces PRs that run the existing gate.
3. Extend `ci.yml`'s `images` job (or a new `deploy` job gated on `main` + the `images`/`quality`
   jobs passing) to push SHA-tagged images to ACR instead of building only.
4. `staging` and `production` GitHub Environments with the protection rule in §3.
5. The traffic-ramp script (§4) as a reusable Actions step/composite action — write it once, use it
   for both `web` and `api`.
6. Wire the §5 thresholds into whatever queries Azure Monitor during the ramp — Log Analytics
   queries against the metrics `06_OPERATIONS.md` §5.1 already lists as tracked.

None of this requires re-deciding hosting, WAF, or A/B infra — those stay exactly as
`devsecops-deployment.md` already concluded.

---

*Researched August 2026. Re-verify Container Apps API/CLI surface and ACR pricing before
implementing — this is a snapshot, not a standing source of truth, same caveat as
`devsecops-deployment.md`.*
