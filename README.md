# TTLI LMS — Executive Training Platform

A multi-tenant platform for selling and delivering executive and leadership training in South Africa and internationally: storefront, Payfast/Netcash/EFT/purchase-order payments, an LMS with enforced completion rules, verifiable certificates and LinkedIn-shareable badges, live workshops through Microsoft Teams, an in-house CRM and billing spine, and anonymised AI insights — launched on infrastructure lean enough that hosting cost does not consume early revenue.

**Status: Phase 0 blocked on customer sign-off; Phase 1 foundation in progress.** See [docs/STATUS.md](docs/STATUS.md) for build state.

---

## Documentation

| Document | Contents |
|---|---|
| [docs/01_PRD.md](docs/01_PRD.md) | Product definition, personas, functional requirements with traceable IDs, workflow state machines, **technical decisions with rationale**, NFRs, delivery plan, risks |
| [docs/02_DATA_MODEL.md](docs/02_DATA_MODEL.md) | Postgres schema: conventions, tenancy, append-only tables, all entity groups, the field-protection matrix, retention, scheduled integrity jobs |
| [docs/03_API_SPEC.md](docs/03_API_SPEC.md) | REST conventions, error envelope, idempotency, every module's endpoints, the anti-bypass heartbeat contract, testing requirements |
| [docs/04_SECURITY_AND_COMPLIANCE.md](docs/04_SECURITY_AND_COMPLIANCE.md) | Authentication, the policy model and its four ABAC rules, encryption and key management, POPIA, AI safety, audit logging, financial compliance |
| [docs/05_COMMERCIAL.md](docs/05_COMMERCIAL.md) | Six-tier packaging, the full feature matrix mapped to delivery phases, add-ons, commercial terms |
| [docs/06_OPERATIONS.md](docs/06_OPERATIONS.md) | Local Compose topology, storage, the media pipeline, Azure blueprint, monitoring and alerts, backup and DR, the administrator runbook |
| [docs/STATUS.md](docs/STATUS.md) | Live build state, phase percentages, quality gates, open questions |
| [docs/source/](docs/source/) | The original AI-generated planning material, extracted and preserved |

> **`chat-export-1786178220416.json` and everything under `docs/source/` are reference material, not the plan.** That material was generated without knowledge of the existing internal systems and contradicts itself on several expensive decisions. [docs/01_PRD.md §5](docs/01_PRD.md#5-technical-decisions) is the authority; [docs/source/README.md](docs/source/README.md) maps each contradiction to the section that settles it.

---

## Stack

| Layer | Choice |
|---|---|
| Web | Next.js 15 App Router, TypeScript, Tailwind — public site, storefront, learner and admin portals |
| API | FastAPI, SQLAlchemy 2.0 async, Alembic, Pydantic v2 — the system of record |
| Type contract | `openapi.json` → `openapi-typescript` → `packages/api-client`, with a CI drift gate |
| Database | PostgreSQL 16, row-level security for tenant isolation |
| Queue and cache | arq + Redis 7 |
| Identity | Self-issued JWT, Argon2id, magic links, TOTP; per-tenant SAML/OIDC via `msal` |
| Object storage | S3 / Azure Blob / local adapter — MinIO in development |
| Video | Self-hosted HLS ladder ported from the in-house `Streaming_Server`; DRM behind a flag |
| Email | External ESP |
| AI | Provider abstraction over OpenAI, Anthropic, Gemini and Azure OpenAI, behind a PII-redaction gateway |
| Analytics | First-party events in Postgres — no third-party tracker |
| Deployment | Docker Compose now; Azure South Africa North documented as the production target |

Rationale and rejected alternatives for each: [docs/01_PRD.md §5](docs/01_PRD.md#5-technical-decisions).

---

## Layout

```
apps/
  web/                     Next.js 15 — login + admin shell, BFF proxy   ✅
  api/                     FastAPI — identity, tenancy, storage, worker  ✅
    src/{core,models,schemas,routers,services,workers}/
    alembic/  tests/
packages/
  api-client/              generated types + thin client; drift-gated    ✅
infra/
  docker-compose.yml       Postgres, Redis, MinIO, Mailhog               ✅
  postgres-init/           extensions bootstrap                          ✅
docs/                      the documentation set                         ✅
  source/                  preserved planning material                   ✅
chat-export-1786178220416.json    original export, reference only
```

---

## Local development

```bash
cp .env.example .env                      # DATABASE_URL has no default, by design
docker compose -f infra/docker-compose.yml up -d
cd apps/api && alembic upgrade head && uvicorn src.main:app --reload --port 8010
cd apps/web && npm install && npm run dev # login + admin shell on :3010
```

Visit http://localhost:3010 for the demo tenant; add `127.0.0.1 meridian.localhost`
to your hosts file and visit http://meridian.localhost:3010 to see the second
tenant's branding on the same code. The break-glass admin credentials are in
your `.env`. The arq worker (maintenance jobs) runs with
`arq src.workers.main.WorkerSettings` from `apps/api`.

Verification:

```bash
cd apps/api && pytest                     # 82 tests; needs the compose stack up
python docs/source/extract.py --check     # verify the extracted source against the export
python docs/check_links.py                # every doc link resolves
```

---

## Ports are deliberately non-default

Several projects share this machine. Every port below was checked against `Agentic_development_worksorder` (5442/6389/9110/9111/1125/8125), `Agentic_development_collab_platform` (5433/6380/9002/9003) and `Agentic_development_Internal_Booking` (55532/56379/55672).

| Service | Port | Default it avoids |
|---|---:|---:|
| Postgres | 5452 | 5432 |
| Redis | 6399 | 6379 |
| MinIO API | 9140 | 9000 |
| MinIO console | 9141 | 9001 |
| Mailhog SMTP | 1145 | 1025 |
| Mailhog web | 8145 | 8025 |
| API | 8010 | 8000 |
| Web | 3010 | 3000 |

---

## Current status

**Phase 0 of 7, blocked.** Ten decisions sit with the customer and nothing may start until they are signed — the list is at [docs/01_PRD.md §1.4](docs/01_PRD.md#14-open-decisions-blocking-phase-0-sign-off).

> The blockers that matter most: the accountants' position on VAT for international digital services, whether signed HLS plus watermarking is accepted as "industry standard" in place of full DRM at launch, and whether prompt data may leave South Africa after redaction. Each of those changes the build, not just the schedule.
>
> Separately: no pricing in [docs/05_COMMERCIAL.md](docs/05_COMMERCIAL.md) is quotable until a unit-cost model exists, and that needs the content inventory first.
