# STATUS

**Updated:** 2026-08-08 (sprint 1 built — foundations, tenancy, identity, CI)
**Scope reference:** [01_PRD.md](01_PRD.md) (requirements) · [02_DATA_MODEL.md](02_DATA_MODEL.md) (schema) · [03_API_SPEC.md](03_API_SPEC.md) (endpoints) · [04_SECURITY_AND_COMPLIANCE.md](04_SECURITY_AND_COMPLIANCE.md) (controls) · [05_COMMERCIAL.md](05_COMMERCIAL.md) (packaging) · [06_OPERATIONS.md](06_OPERATIONS.md) (infra)

---

## 1. Summary

Sprint 1 of Phase 1 is built and passing every gate that does not need a database. Phase 0 remains blocked on the customer — the foundation work was brought forward deliberately, because none of it depends on the ten open decisions.

| Phase | Name | State | Done |
|---|---|---|---:|
| 0 | Discovery and sign-off | **BLOCKED** — 10 open decisions | 0% |
| 1 | Foundation | Sprint 1 of ~5 complete | ~20% |
| 2 | Public site and content funnel | Not started | 0% |
| 3 | Commerce | Not started | 0% |
| 4 | Core LMS, anti-bypass, credentials | Not started | 0% |
| 4.5 | PWA and accessibility | Not started | 0% |
| 5 | Corporate, workshops, marketing | Not started | 0% |
| 6 | AI insights | Not started | 0% |
| 7 | Hardening and cloud | Not started | 0% |

| Gate | Status |
|---|---|
| `ruff check` | **PASS** — 36 files |
| `ruff format --check` | **PASS** |
| `mypy src` (strict) | **PASS** — 27 source files |
| `pytest` | **PASS** — 31 passed, 8 skipped |
| `alembic upgrade head` | **BLOCKED** — no local Postgres |
| Migration round-trip | **BLOCKED** — no local Postgres |
| `alembic check` | **BLOCKED** — no local Postgres |
| `api-client` drift check | n/a — sprint 2 |
| Source extraction fidelity | **PASS** — `python docs/source/extract.py --check` |
| Documentation link integrity | **PASS** — `python docs/check_links.py` |

**Headline:** 39 tests (31 passing, 8 integration tests written but skipped), 3 endpoints, 8 tables.

> The 8 skips are the row-level-security suite in `tests/test_rls.py`. They are written, and they run in CI, which provisions its own Postgres service. They cannot run on this machine because **Docker Desktop's Linux engine is not running** — the named pipe `//./pipe/dockerDesktopLinuxEngine` does not exist and `docker info` exits 1. Start Docker Desktop, wait for the whale icon to settle, then:
>
> ```bash
> docker compose -f infra/docker-compose.yml up -d postgres redis
> cd apps/api && ./.venv/Scripts/python.exe -m alembic upgrade head
> ./.venv/Scripts/python.exe -m pytest
> ```

---

## 2. What exists now

### Working and verified

| Component | File | Verified by |
|---|---|---|
| Own git repository | `.git/` | `git rev-parse --show-toplevel` returns the project path, not `C:/Users/Wille` |
| Ignore rules | [.gitignore](../.gitignore) | Covers Python, Node, `.env`, transcode output, local data |
| Source extractor | [docs/source/extract.py](source/extract.py) | `--check` passes; asserts exact character counts |
| Extracted source | [docs/source/](source/) | 5 files, byte-identical to the export modulo LF normalisation |
| Documentation set | `docs/01`–`06`, `STATUS.md` | Cross-links resolve |
| Config + production safety | `src/core/config.py` | 10 tests in `tests/test_config.py` |
| Field encryption + blind index | `src/core/crypto.py` | 9 tests in `tests/test_crypto.py` |
| Argon2id, JWT, UUID v7 | `src/core/security.py`, `ids.py` | 12 tests in `tests/test_security.py` |
| Tenant resolution + RLS binding | `src/core/tenancy.py`, `db.py` | `tests/test_rls.py` (CI only) |
| Schema + RLS policies | `alembic/versions/0001_baseline_schema.py` | CI only |
| Seed: 17 permissions, 6 roles, 2 tenants | `alembic/versions/0002_seed_roles_and_tenants.py` | CI only |
| CI pipeline | `.github/workflows/api.yml` | 10 gates incl. skip detection |

### Endpoints live

`GET /health` · `GET /health/ready` · `POST /api/v1/auth/login` · `GET /api/v1/auth/me`

---

## 3. Phase 0 — Discovery and sign-off (BLOCKED)

Blocked on the customer, not on engineering. No code may start until this closes.

### Done

- [x] Requirement extraction from the source material, with traceability ([01 §3.12](01_PRD.md#312-requirement-traceability))
- [x] Nine internal contradictions in the source identified and adjudicated ([source/README.md](source/README.md))
- [x] Stack decided and justified ([01 §5](01_PRD.md#5-technical-decisions))
- [x] Delivery plan replacing the source's two irreconcilable schedules ([01 §8](01_PRD.md#8-delivery-plan))
- [x] Data model, API surface, security model, packaging and operations documented
- [x] `Streaming_Server` reuse assessed — what ports, what does not ([06 §3](06_OPERATIONS.md#3-media-pipeline))

### Outstanding

- [ ] **Decision register signed by the customer** — all 10 items in [01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off)
- [ ] Accountants' written position on VAT for international digital services
- [ ] Azure Container Apps availability in South Africa North confirmed
- [ ] Content inventory — video count, total duration, source formats
- [ ] Unit-cost model built from that inventory ([06 §6](06_OPERATIONS.md#6-cost-model))
- [ ] Brand and design system
- [ ] Wireframes for the six persona views
- [ ] Payfast and Netcash sandbox accounts registered
- [ ] Information Officer registered with the Information Regulator (customer obligation)

---

## 4. Phase 1 — Foundation (~20%)

### Done — sprint 1

- [x] Monorepo skeleton: `apps/api`, `infra/`, `.github/`
- [x] `infra/docker-compose.yml` on the reserved ports ([06 §1.1](06_OPERATIONS.md#11-services))
- [x] `.env.example` and `check_production_safety()` returning a list of problems
- [x] FastAPI skeleton, structlog, request IDs, the error envelope
- [x] Alembic baseline with `citext`, `pg_trgm`, `pgcrypto`
- [x] Tenancy: `tenant_id`, hostname resolution, `SET LOCAL app.tenant_id`, RLS policies with `FORCE`
- [x] Identity: Argon2id, JWT issue and verify, lockout, timing-equalised login
- [x] Field encryption (AES-GCM) and HMAC blind index
- [x] Append-only audit log — a raising trigger, not a silent `DO INSTEAD NOTHING` rule
- [x] Seed migration: 17 permissions, 6 roles, 2 tenants, break-glass admin refused in production
- [x] `.github/workflows/api.yml` with the full gate set ([06 §4.5](06_OPERATIONS.md#45-deployment))

### Outstanding — sprints 2 to 5

- [ ] Magic links and TOTP; refresh-token rotation with family revocation on reuse
- [ ] Storage adapter across S3, Azure Blob and local
- [ ] Events table, partitioned
- [ ] `packages/api-client` generation with a CI drift gate
- [ ] Redis-backed rate limiting and the tenant-config cache
- [ ] Run the migration and RLS suites locally (blocked on Docker)

**Demo target:** two tenants resolving to different themes; login with MFA; an empty admin shell.

---

## 5. Phase 2 — Public site and content funnel (0%)

Marketing pages, resource hub, podcasts, gated content, consent management, lead capture with UTM attribution, guest accounts with expiry and watermarking, event tracking.

**Demo target:** the whole funnel, from a podcast to a working guest login, with the lead visible in admin.

---

## 6. Phase 3 — Commerce (0%)

Catalogue, cart, checkout, Payfast and Netcash sandboxes, EFT with proof upload and finance approval, PO capture, sequential invoicing, append-only ledger, VAT engine, entitlements.

**Demo target:** three purchase paths each producing an auditable invoice; a rejected EFT; a credit note.

> Nothing is sellable at the end of this phase — there is no course player yet. A working checkout demo will look like a finished business and is not one. See [05 §3](05_COMMERCIAL.md#what-is-sellable-and-when).

---

## 7. Phase 4 — Core LMS, anti-bypass, credentials (0%)

Course authoring, the ported media ladder, signed HLS, watermarking, heartbeat validation, the server-side completion rule engine, quizzes, surveys with per-survey anonymity, certificates with public verification, badges with LinkedIn sharing.

**Demo target:** attempt to skip a lesson and be refused with the specific unmet requirements listed; complete properly; verify the certificate from a phone.

---

## 8. Phases 4.5–7 (0%)

| Phase | Demo target |
|---|---|
| 4.5 PWA and accessibility | Installable app; WCAG 2.1 AA audit passed |
| 5 Corporate and workshops | A manager who cannot see individual scores until an admin enables it for one course |
| 6 AI insights | 500 survey responses summarised with zero identifiers transmitted, shown beside the redaction log |
| 7 Hardening and cloud | Load test at 100 concurrent; restore drill completed; POPIA matrix delivered |

---

## 9. Known gaps in what is already written

### Closed since the source material

- Two irreconcilable delivery schedules → one dependency-ordered plan
- Multi-tenancy contradiction → schema-ready now, white-label features later
- DRM contradiction → signed HLS at launch, DRM flag-gated
- Certificates/badges split → one engine, one phase
- Mobile contradiction → responsive web, then PWA, native deferred
- Encrypted email versus bulk marketing → resolved in [04 §4.4](04_SECURITY_AND_COMPLIANCE.md#44-how-marketing-works-against-encrypted-email)
- Azure Media Services recommendation → recorded as retired and unusable
- Two AI providers silently dropped → all four restored
- "Salt and hash everything" → corrected to hash-what-you-verify, encrypt-what-you-read

### Still open

- **[02 §13](02_DATA_MODEL.md#13-open-questions-for-engineering-review)** — UUID v7 generation, events partitioning granularity, blind index rotation, bespoke enterprise lesson modelling, cohort definition, heartbeat interval
- **[03 §13](03_API_SPEC.md#13-open-questions-for-engineering-review)** — heartbeat tolerance, concurrent session scope, verification rate limit, bulk invite ceiling, webhook replay window
- **[04 §11](04_SECURITY_AND_COMPLIANCE.md#11-open-questions)** — pepper rotation, blind index rotation, impersonation scope, legal hold, breach notification, minimum group size
- **[06 §8](06_OPERATIONS.md#8-open-questions)** — Container Apps region, CDN provider, transcode compute placement, backup residency, staging sanitisation
- **[05 §7](05_COMMERCIAL.md#7-before-any-of-this-is-quotable)** — the entire unit-cost model. No pricing is quotable until it exists

### Corrections made to the source material

| Source claim | Correction |
|---|---|
| "Azure Media Services (with DRM)" as a primary video option | Retired mid-2024. Not usable |
| Gate durations summing to 52–83 weeks alongside a stated 9–14 month total | Both discarded; one plan published |
| AI stack table naming only Azure OpenAI plus two fallbacks | The customer asked for four providers; Gemini and Copilot restored |
| "Salt and hash" all captured information | Impossible for data that must be read back; see [04 §4.1](04_SECURITY_AND_COMPLIANCE.md#41-what-the-customer-asked-for-and-what-is-actually-correct) |
| 15 roles at launch | Phased: 6 in Phase 1, corporate roles in Phase 5 |
| Illustrative pricing presented in quotable form | Marked not-quotable pending a cost model |

---

## 10. Recommended next three steps

1. **Put the decision register to the customer.** All ten items in [01 §1.4](01_PRD.md#14-open-decisions-blocking-phase-0-sign-off), as one document, for signature. Nothing else can start.
2. **Get the content inventory.** Video count, total duration, source formats. It feeds the transcode sizing *and* the cost model, and the cost model gates every price in [05_COMMERCIAL.md](05_COMMERCIAL.md).
3. **Verify Azure region availability and register the payment sandboxes.** Both have external lead times; neither should be discovered on the Phase 3 critical path.

### Running the verification that exists today

```bash
python docs/source/extract.py --check     # source fidelity against the export
python docs/check_links.py                # every relative link and anchor resolves
git rev-parse --show-toplevel             # repository isolation
```

---

## 11. Schedule reality

The source material claims 9–14 months for the full ecosystem while its own gate durations sum to 52–83 weeks. Neither figure survived review.

What can honestly be said: **Phase 0 is the only thing on the critical path right now, and it is entirely in the customer's hands.** Engineering ranges for Phases 1–7 exist in [01 §8](01_PRD.md#8-delivery-plan) but they are ranges for a small team against a signed scope, and there is no signed scope yet. Publishing a date before the decision register is closed would be inventing one.

The first genuinely sellable configuration arrives at the end of Phase 4, not Phase 3.
