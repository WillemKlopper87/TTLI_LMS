# Source material

## Provenance

Everything in this directory derives from `../../chat-export-1786178220416.json` (578 KB), an exported chat titled *"Advanced LMS with Payment and CRM Integration"*.

| | |
|---|---|
| Model | Qwen3.8-Max |
| Turns | 4 user messages, 4 assistant answers |
| Volume | ~185,000 characters of generated planning material |
| Exported | Timestamps in the export run from 1786171061 |

The export stores each assistant answer inside `content_list` under `phase == "answer"`; the sibling `content` field is empty. A naive read of the JSON therefore looks like the answers are missing, and the payload duplicates each answer, so a grep returns everything twice. `extract.py` handles both.

## This is a reference blueprint, not the plan

The generated material is substantive and worth keeping, but it was produced without knowledge of this developer's existing systems, and it contradicts itself on several of the most expensive decisions. **`../01_PRD.md` section 5 is the authority.** Every place the plan departs from the source is recorded there with a rationale and an explicit *Not chosen* note.

Do not implement from these files. Read them for context and for the requirement history.

## Files

| File | Source | Chars |
|---|---|---:|
| [00_user_requirements.md](00_user_requirements.md) | The four customer messages, verbatim — the actual requirement source of truth | 2,019 / 1,002 / 2,467 / 432 |
| [01_architecture.md](01_architecture.md) | Answer 1 — architecture, functional deep dive, RBAC/ABAC, stack, data model, phases 0–4 | 63,357 |
| [02_delivery_plan.md](02_delivery_plan.md) | Answer 2 — gates 0–11, design concepts, 7 workflows, mobile, storage, DB security | 55,327 |
| [03_sa_clarifications.md](03_sa_clarifications.md) | Answer 3 — the South African rewrite: multi-tenancy, DRM, PII redaction, SARS | 11,447 |
| [04_solution_and_pricing.md](04_solution_and_pricing.md) | Answer 4 — technical solution document (27 sections) + feature matrix and pricing tiers | 55,446 |

`extract.py` regenerates all five and asserts those character counts:

```bash
python docs/source/extract.py           # regenerate
python docs/source/extract.py --check   # verify against the export, exit 1 on drift
```

The only alteration made to the source text is collapsing CRLF to LF; the export mixes line endings and Windows text-mode translation would otherwise make the round-trip check unsettleable.

## Contradictions found in the source, and where each is resolved

The source could not be transcribed — it had to be adjudicated. Each row is a genuine conflict *within* the generated material, not a disagreement with it.

| # | Contradiction | Resolved in |
|---|---|---|
| 1 | Gate durations sum to 52–83 weeks against a stated total of 9–14 months | [01_PRD.md §8](../01_PRD.md#8-delivery-plan) |
| 2 | Multi-tenancy is "nice to have later, Phase 4" (Answer 1) and foundation work at Gate 1 (Answer 3) | [01_PRD.md §5.5](../01_PRD.md#55-tenancy--schema-ready-now-white-label-later) |
| 3 | DRM is optional and risk-based (Answer 1 §11.8) and mandatory Widevine+FairPlay (Answer 3) | [01_PRD.md §5.8](../01_PRD.md#58-video--self-hosted-ladder-drm-behind-a-flag) |
| 4 | Certificates and badges ship together at Gate 5 but split across MVP/Phase 2 in the summary | [01_PRD.md §8](../01_PRD.md#8-delivery-plan) |
| 5 | Native mobile is Gate 10 *and* "a later phase after PWA" | [01_PRD.md §5.9](../01_PRD.md#59-mobile--responsive-web-then-pwa-native-deferred) |
| 6 | Email is encrypted with a blind index, yet Gate 8 needs segmentation, campaigns and bounce handling over the same addresses | [04_SECURITY_AND_COMPLIANCE.md §4.4](../04_SECURITY_AND_COMPLIANCE.md#44-how-marketing-works-against-encrypted-email) |
| 7 | Answer 1 §7.5 warns Azure changed its media strategy; Answer 3 then recommends Azure Media Services, which was retired in mid-2024 | [06_OPERATIONS.md §3](../06_OPERATIONS.md#3-media-pipeline) |
| 8 | The customer asked for four AI providers; Answer 3's stack table silently drops Gemini and Copilot | [01_PRD.md §3.9](../01_PRD.md#39-crm-marketing-and-ai-insights) |
| 9 | The customer's final message demands lean infrastructure, but Answer 3 (written earlier) had already added multi-tenancy, DRM and Azure-everything | [06_OPERATIONS.md §4](../06_OPERATIONS.md#4-infrastructure) |

## Requirements the source asked about and nobody answered

Carried forward to [01_PRD.md §1.4](../01_PRD.md#14-open-decisions-blocking-phase-0-sign-off) rather than quietly resolved:

- **SCORM/xAPI** — asked in Answer 1's clarifying questions, skipped in the customer's reply.
- **VAT treatment of international digital services** — the source itself defers to the customer's accountants.
- **CPD/accreditation body** — "an option, plan for this" is not a specification.
- **Subscriptions** — "this is an option".
- **Guest access expiry** — 7 days and 14 days both offered, never chosen.
- **Brand and design system, budget, launch date** — all recorded as TBA.
