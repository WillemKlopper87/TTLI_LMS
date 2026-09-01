# TTLI_LMS — Single-VM Deployment

**Scope:** a real, working cloud deployment — web app, API, worker and
database all on **one VM** — for going live before the documented Azure
Container Apps target (`06_OPERATIONS.md` §4.2, `docs/research/
devsecops-deployment.md` §2) is worth provisioning. This is a genuinely
different shape from both `infra/docker-compose.yml` (local dev only) and
`infra/docker-compose.prod.yml` (assumes managed Postgres/Redis/Blob
Storage) — neither file, nor any existing doc, covers "everything on one
box." This one does.

**Audience:** whoever is standing this up. Read `06_OPERATIONS.md` §4
first for what this deliberately isn't yet.

---

## 1. Why this exists, and when to stop using it

`docs/research/devsecops-deployment.md` §2.1 prices a Tier 0 soft launch
at ~$35–75/month on Azure Container Apps + Flexible Server + Cache for
Redis. That's the right *target* architecture — but it assumes managed
services are worth provisioning before there's a single real user. A
single VM is cheaper to reason about for exactly one deployment (one
`docker compose up`, one place to SSH into, one bill), at the cost of
everything §2 of this document lists honestly as worse.

**Move off this shape when any of these becomes true** (mirrors
`06_OPERATIONS.md` §5.5's own "nothing pre-emptive, each is a response to
a measurement" discipline):

| Trigger | What breaks on one VM |
|---|---|
| Real user data exists and matters | No point-in-time restore — nightly `pg_dump` only, see §7 |
| VM CPU sustained >70% | Postgres, the transcoder, and the app are all fighting for the same cores — no separating them without re-provisioning |
| More than a handful of concurrent video streams | ClamAV, ffmpeg transcode jobs, and Postgres all want RAM at once (§3) |
| A customer asks about disaster recovery / uptime SLA | One VM going down takes everything down, DB included |
| Enterprise tenant wants infrastructure isolation | Not offerable at all on this shape |

None of this is a redesign when the time comes — `infra/docker-
compose.prod.yml` already exists for the Container Apps target, and the
application code doesn't change; only where Postgres/Redis/storage live
does.

---

## 2. Architecture

```
Internet
   |
   v
[Caddy]  :80/:443, automatic HTTPS (Let's Encrypt)
   |
   v
[web]  Next.js standalone, port 3010 (internal only)
   |
   v  (the one path from browser to API — apps/web/app/api/bff/)
[api]  FastAPI, port 8010 (internal only, never published)
   |
   +---> [postgres]   (internal only)
   +---> [redis]      (internal only, password-protected)
   +---> [garage]     (internal only — S3-compatible object storage)
   +---> [clamav]     (internal only — scans every upload before it's readable)
   +---> [postfix-relay] (internal only — see §5)

[worker]  same image as api, runs `arq`, same dependencies
[migrate] same image, runs once (`alembic upgrade head`) before api/worker start
```

Everything except Caddy's 80/443 is unreachable from outside the VM —
enforced by `ufw` (§6) *and* by nothing else publishing a host port in
`infra/docker-compose.single-vm.yml`. Containers reach each other by
service name over the default Docker network, which is also what keeps
`DATABASE_URL`/`REDIS_URL` passing `core/config.py`'s
`check_production_safety()` — it refuses `localhost`/`127.0.0.1`, not a
service name.

Multi-tenant custom domains (organisations with their own domain,
`06_OPERATIONS.md` §7.5) work the same way here as anywhere else: point
each domain's DNS at this VM's IP, add one more site block to
`infra/Caddyfile.template`, redeploy — the app resolves the tenant from
the `Host` header itself (`core/tenancy.py`); Caddy doesn't need to know
which domain belongs to which tenant.

---

## 3. Sizing

| Tier | Spec | Fits |
|---|---|---|
| Minimum | 2 vCPU / 4 GB | Soft launch, <20 users, no concurrent video transcoding |
| Recommended | 4 vCPU / 8 GB | The Pilot-shape numbers `06_OPERATIONS.md` §5.5 scopes (50–500 learners) at rest, occasional transcode jobs |
| Tight regardless of size | Postgres + ClamAV + ffmpeg all competing for the same cores, with no isolation between them the way separate Container Apps replicas would provide |

Azure equivalent: a **B4ms** (4 vCore/16 GB burstable) is comfortable
headroom; a **B2ms** (2 vCore/8 GB) is the honest minimum for the
Recommended row above, not the Minimum row.

Disk: size for video source + transcoded ladder + Postgres + headroom.
Course video lives in the `garage` container's volume on this VM's own
disk — there is no separate managed storage tier at this shape. If your
catalogue is large (see the cost-modeling conversation this doc's sibling
question produced), a managed Blob Storage account behind
`STORAGE_BACKEND=azure` instead of self-hosted Garage is a smaller, safer
change than it looks — the storage adapter interface
(`06_OPERATIONS.md` §2.1) was built exactly so this swap is configuration,
not a rewrite. Worth doing before disk fills up, not after.

---

## 4. Reverse proxy: Caddy, not nginx

`docs/research/devsecops-deployment.md` §4.2 already looked at the
adjacent "reverse proxy in front of the app" question and leaned toward
Caddy over nginx for one concrete reason: **automatic HTTPS**. Caddy
requests and renews Let's Encrypt certificates with zero configuration;
nginx needs certbot bolted on plus a renewal cron job someone has to
remember exists. For a VM one person operates, that's a real reduction
in what can quietly expire.

`infra/Caddyfile.template` does exactly three things: terminate TLS,
reverse-proxy everything to `web:3010`, and add two headers Next's own
`proxy.ts` already sets (redundant on purpose — a proxy-level default
survives even if a future change to `proxy.ts`'s matcher regresses it).
It does not need to know about CORS or multiple origins, because the BFF
pattern (`apps/web/app/api/bff/[...path]/route.ts`) already means there's
only one origin browsers ever talk to.

If you specifically want nginx instead (team familiarity is a legitimate
reason), the only thing that changes is this one container — swap it for
`nginx` + `certbot` (or `nginx-proxy` + `acme-companion`, which automates
renewal similarly to Caddy) reverse-proxying to the same `web:3010`
target. Nothing else in the stack cares which proxy sits in front of it.

**WAF:** none at this tier, matching `devsecops-deployment.md` §4's own
"skip until log-evidenced" cut list — there's no Front Door here to give
one away for free the way there is on the Azure target. If you want the
same OWASP-CRS coverage Front Door Premium or Cloudflare Pro charge for,
§4.2 of that doc names the option: Coraza as a sidecar in front of Caddy.
Not included by default here — real operational surface (rule tuning,
CRS updates) for a threat model with no evidence yet, same reasoning that
doc already gives.

---

## 5. The email gap you must not skip

`apps/api/src/services/email.py`'s `send_sync()` is a plain
`smtplib.SMTP(host, port).send_message(...)` — no `.login()`, no
`.starttls()`. **The application can only speak to an unauthenticated,
unencrypted local relay.** This is fine in dev (Mailpit is exactly that,
and it never sends anywhere real) and is the reason
`docker-compose.prod.yml` never had to solve this — Azure's target
architecture was never designed to need this piece either, since nothing
in the documented plan runs Mailpit in production.

**On a single VM, this becomes a real gap**: every magic-link,
guest-access, and password-reset email — the entire passwordless login
model — depends on mail actually leaving the VM. Skipping this section
means logins silently don't work for anyone.

The fix ships in `infra/docker-compose.single-vm.yml` as the
`postfix-relay` service (`boky/postfix`, a small, actively-maintained
image built for exactly this): the app connects to it unauthenticated on
the internal network, exactly like it would to Mailpit, and *it*
authenticates outward to a real ESP (SendGrid, Mailgun, Brevo, Azure
Communication Services' SMTP endpoint, anything that issues SMTP-AUTH
credentials) using `SMTP_RELAY_HOST`/`_USERNAME`/`_PASSWORD` from
`.env.prod`. Zero application code changes.

**The actual fix** — adding SMTP-AUTH/STARTTLS support to
`services/email.py` directly — is a small, contained change if it's ever
worth doing instead of carrying the relay container. Flagging it here
rather than doing it silently as part of a deploy script.

---

## 6. Firewall

`scripts/deploy-single-vm.sh` configures `ufw` to allow exactly three
inbound ports: 22 (SSH), 80, 443. Everything else — Postgres, Redis,
Garage's S3 API, ClamAV, the API's own 8010 — is reachable only from
inside the VM, because nothing publishes those ports to the host in the
first place (`expose`, not `ports`, in the compose file). Two independent
layers doing the same job on purpose: a compose-file mistake alone
shouldn't be enough to make Postgres internet-reachable.

---

## 7. Backup and recovery — read this before you need it

`06_OPERATIONS.md` §5.4 targets a 15-minute RPO via managed Postgres'
continuous point-in-time restore. **This shape does not have that.**
`scripts/backup-db.sh`, cron'd nightly at 02:00, gives you:

| Metric | Documented target (§5.4) | This shape, honestly |
|---|---|---|
| RPO | 15 minutes | ~24 hours (nightly dump) |
| RTO | 4–8 hours | Untested until you run the drill — assume longer |
| Backup location | Managed, geo-redundant | Wherever your `rclone` remote points — **must be off this VM** |

The backup script refuses to run without `BACKUP_RCLONE_REMOTE`
configured, on purpose — a dump sitting next to the database it's
protecting is not a backup, it's a second copy of the same single point
of failure. Point it at any `rclone`-supported target (Azure Blob, S3,
Backblaze B2) that isn't this VM.

**Object storage** (course video, certificates, invoices, payment
proofs) is *not* covered by `backup-db.sh` — it lives in the `garage`
container's own Docker volumes, on this VM's own disk, with no backup at
all as shipped. If that content matters as much as the database (it
does — course video is expensive to re-encode, certificates and invoices
are financial/legal records), add a second `rclone sync` cron for
Garage's data volume, or move to `STORAGE_BACKEND=azure` against a real
Blob Storage account, which gets you managed redundancy for free — worth
weighing against §3's disk-sizing note either way.

**The restore drill `06_OPERATIONS.md` §7.4 already commits to
quarterly is not optional here — it's the only way to know §7's numbers
above are real and not aspirational.**

---

## 8. What you need before running the script

- A domain (or subdomain) with its A record ready to point at the VM's
  IP. Caddy's automatic HTTPS will not obtain a certificate for a domain
  that doesn't resolve here yet — the deploy script warns if it doesn't
  match at deploy time, but won't block on it (DNS propagation is often
  still in flight).
- A Sentry DSN. `check_production_safety()` refuses to start the API
  without one — sentry.io's free tier or a self-hosted instance both work.
- SMTP relay credentials from a real ESP (§5) — host:port, username,
  password.
- An `rclone` remote already configured (`rclone config`) for backups
  (§7) — or accept no backups until you set one up.
- Payfast merchant credentials, if card checkout should be enabled at
  launch — optional; EFT and purchase-order checkout work without them.
- A fresh Ubuntu 22.04/24.04 VM (the script's package-install step
  targets Debian/Ubuntu's `apt`) with a non-root sudo user, and this repo
  checked out on it (or a `REPO_URL` the script can clone).

---

## 9. Running it

```bash
git clone <your-fork-or-repo-url> /opt/ttli   # or let the script clone it — see below
cd /opt/ttli
sudo -E ./scripts/deploy-single-vm.sh
```

Or, from a bare VM with nothing checked out yet:

```bash
curl -fsSL https://raw.githubusercontent.com/<org>/<repo>/main/scripts/deploy-single-vm.sh -o deploy.sh
sudo REPO_URL=git@github.com:<org>/<repo>.git bash deploy.sh
```

First run prompts for everything in §8, generates every secret
(`SECRET_KEY`, `FIELD_ENCRYPTION_KEY`, `BLIND_INDEX_KEY`,
`APP_DB_PASSWORD`, the Postgres/Redis passwords, a fresh Garage key pair
— never the checked-in dev credentials in `infra/garage/garage.toml`),
writes `/opt/ttli/.env.prod` (`chmod 600`), builds the four application
images, brings up all nine containers, installs the nightly backup cron,
and smoke-tests `https://<your-domain>/`.

**Re-running the script later** (to deploy a new version, say) reuses
the existing `.env.prod` untouched — it will not regenerate
`FIELD_ENCRYPTION_KEY`/`BLIND_INDEX_KEY`/`APP_DB_PASSWORD`, because doing
so after real data exists makes every already-encrypted row and the
database password permanently wrong. It does rebuild images and restart
services.

**Back up `.env.prod` itself**, somewhere other than this VM (a password
manager, Key Vault) — it's the one file that reconstructs this exact
deployment from a fresh checkout. Losing it without a copy means losing
the ability to decrypt anything already in the database.

---

## 10. Day-2 operations

```bash
docker compose -f infra/docker-compose.single-vm.yml ps
docker compose -f infra/docker-compose.single-vm.yml logs -f api
docker compose -f infra/docker-compose.single-vm.yml logs -f worker
docker compose -f infra/docker-compose.single-vm.yml logs -f caddy   # cert issuance issues show up here first
./scripts/backup-db.sh                                                # run a backup on demand
crontab -l                                                            # confirm the nightly one is installed
```

**Deploying a new version day-to-day: `scripts/rolling-update.sh`, not
`deploy-single-vm.sh`.** The deploy script is for first-time setup and
for changes to infrastructure itself (a new container, a changed env
var) — it's a hard restart of everything. Routine code changes (a new
feature, a dependency bump, a CVE fix) go through `rolling-update.sh`
instead, which never touches Postgres/Redis/Garage/ClamAV/the mail relay
and swaps `api`/`worker`/`web` one at a time behind a health check — see
§12 for the full mechanics, including how this is the same path a
Trivy-flagged base-image vulnerability takes to get fixed in production.

Monitoring at this tier is intentionally minimal: Sentry (already
required to start) plus `docker compose ps`/`logs`. None of
`06_OPERATIONS.md` §5.1's fuller list (queue depth, CDN egress, container
CPU dashboards) exists here — add it incrementally if this shape lives
long enough to be worth instrumenting, or treat sustained operational
pain as itself the signal to move to §1's target architecture instead.

---

## 12. Shipping a code change without a maintenance window

Two triggers, one mechanism:

- **A feature push** — you merge to `main`, CI's Trivy scan
  (`.github/workflows/ci.yml`) passes because nothing new is vulnerable
  *yet*, and you want it live.
- **A vulnerability fix** — `.github/workflows/image-scan-weekly.yml`
  runs every Monday against the *currently pinned, unchanged* base
  images and re-scans them with that day's Trivy database. If a CVE was
  disclosed since the digest was last resolved, it opens a GitHub issue
  (it never auto-bumps the pin or auto-merges anything — `apps/api/
  Dockerfile` and `apps/web/Dockerfile` are both explicit that digest
  re-resolution is deliberate, not scheduled). A human re-resolves the
  digest (`docker buildx imagetools inspect <image>:<tag>`, per the
  Dockerfiles' own comments), bumps the pin, and pushes — from here on
  it's identical to a feature push.

Either way, getting the fix into production is the same four steps:

1. `git pull` on the VM (or let `rolling-update.sh` do it).
2. **Build first, while the old version keeps serving traffic.**
   `docker compose build api web` costs real time but zero downtime —
   nothing is swapped yet.
3. **Migrate.** `docker compose run --rm migrate` runs against the
   *old* api/web still running. This is exactly why
   `06_OPERATIONS.md` §4.5's backward-compatible-migration rule ("add
   nullable, backfill, constrain — never all three in one release")
   isn't optional at this tier the way it might feel skippable on a
   platform with instant multi-replica cutover: on one VM, there's a
   real window, however short, where the old code is the only thing
   running against the new schema. If the migration fails, nothing else
   has changed yet — `rolling-update.sh` retags the images back and
   exits, and the site is exactly as it was.
4. **Swap one service at a time**, health-checked, with automatic
   rollback per service: `api`, then `worker` (same image, checked for
   "still running" rather than an HTTP health check — arq has no
   endpoint to poll), then `web`. `docker compose up -d --no-deps
   <service>` recreates only that one container; Postgres, Redis,
   Garage, ClamAV and the mail relay are never restarted, never
   rebuilt, never even looked at.

**What "swap" actually costs**: a few seconds per service — the old
container stops, the new one starts, Docker's health check confirms it,
then the next service goes. That's a real, brief interruption to
whichever *one* service is mid-swap, not a maintenance page and not the
whole site — the other two of three app containers keep serving the
entire time. `infra/docker-compose.single-vm.yml`'s healthchecks on
`api` (`/health`) and `web` (a plain HTTP GET, since that image has no
curl/wget) are what `rolling-update.sh` polls before calling a swap
successful.

**If a swap fails its health check**, the script retags the previous
image back (captured before the build moved the tag forward) and
recreates the container again — automatic, no one has to remember the
previous image's ID by hand. A failed `api` or `web` swap aborts the
rest of the rollout; a failed `worker` swap is logged loudly but doesn't
block `web` from proceeding, since a broken worker delays background
jobs (email, transcode) without taking the site itself down.

**What this isn't**: true zero-dropped-connections blue/green, where two
full replicas run simultaneously behind a load balancer that only cuts
over once the new one is proven healthy under real traffic. That's
achievable on one VM (Docker Compose's `--scale` plus round-robin DNS
between replicas of the same service name is one real way to get there),
but it's meaningfully more moving parts for a gap this shape's actual
traffic (Tier 0–Pilot, §1) is unlikely to notice. Worth building if this
VM is still the production shape once uptime during a deploy starts
mattering enough for someone to ask — not before.

---

## 13. Open questions

1. **Object storage backup** (§7) — not automated by this pass; decide
   before real course content is uploaded, not after.
2. **The SMTP-AUTH gap** (§5) — carried via a relay container here;
   worth a real code fix (`services/email.py`) if this shape, or a
   future one, needs to drop the extra container.
3. **Restore drill** — `06_OPERATIONS.md` §7.4's quarterly commitment
   applies here too, and matters more here than on the managed target.
4. **When to split Postgres off this VM** — the cheapest single step
   back toward the documented architecture, if the VM's own resource
   contention (§3) becomes the bottleneck before anything else does.
5. **Hot standby / a second VM for redundancy** — genuinely not
   designed here. This shape has one Postgres instance with no
   replication target, so "add a second host" is a real project (WAL
   streaming or logical replication to a standby, a decision on
   automatic vs. manual failover, and — the part that's easy to get
   wrong — what a split-brain looks like if both VMs think they're
   primary) rather than a configuration change. Worth scoping properly
   once it's an actual requirement, not bolted on as an afterthought to
   this doc.
