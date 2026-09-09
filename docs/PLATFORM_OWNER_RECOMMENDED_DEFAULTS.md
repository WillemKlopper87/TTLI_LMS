# TTLI recommended platform-owner answers

## How to use this guide

This companion to `PLATFORM_OWNER_DECISION_PACK.md` supplies a proposed answer
for all 87 decisions. Owners may answer **Accepted as proposed** or record a
replacement, but must still name the approver and attach the requested evidence.
**Owner input required** means that no responsible default can invent the fact.

The baseline assumes a South African, ZAR-denominated B2B and adult-learner
launch, beginning with a controlled pilot. It follows a risk-led ISO/IEC 27001
posture, NIST CSF operations, PCI DSS 4.0.1 payment controls, WCAG 2.2 AA
(also ISO/IEC 40500:2025), IFRS 15 accounting principles and POPIA/SARS rules.
It is informed guidance, not tax or legal advice.[^1][^2][^3][^4][^5]

## A. Business, launch and commercial owner

| ID | Proposed answer |
|---|---|
| A1 | **Owner input required:** use the exact CIPC/SARS registered seller, with trading name secondary; supply registration/VAT numbers and addresses for accountant approval. |
| A2 | Run an 8-week South African pilot, ZAR only, initially capped at 3 tenants, 500 registered learners and 100 concurrent sessions; expand only after measured load/support evidence. Owner supplies the launch date. |
| A3 | Launch individual course, named-seat team bundle and enterprise enquiry/quote; default access is 12 months. Unused seats may be reassigned, activated seats may not. **Owner input required for approved prices.** |
| A4 | Sales may discount 10%, commercial lead 20%; larger/complimentary exceptions need executive approval. Finance approves refunds only up to the original payment; legal plus executive approve contract exceptions. Replace roles with names/limits. |
| A5 | Support Mon-Fri 08:00-17:00 SAST. P1 acknowledge 30 min/target workaround 4 h; P2 4 business h/2 business days; P3 1/5 business days. Maintenance Sunday 02:00-05:00 with 72 h notice. |
| A6 | Publish versioned consumer terms, privacy/cookie/refund/accessibility documents; enterprise sales use order form/MSA, DPA and SLA/security schedule. Legal approves all effective versions. |
| A7 | Mark departments, competencies, HRIS, xAPI/LTI and CRM **not at launch** unless a signed, funded requirement exists. |

## B. Tax, invoicing and accounting

| ID | Proposed answer |
|---|---|
| B1 | Show South African public prices VAT-inclusive; business quotes show net, VAT and gross. If not VAT registered, say “No VAT charged” and do not issue a tax invoice. SARS requires VAT vendors to include VAT in advertised/quoted prices.[^6] |
| B2 | Sell only in South Africa initially. Apply the accountant-approved domestic rate; disable unsupported countries/currencies until a written B2B/B2C location/evidence/tax matrix exists. Never assume all foreign sales are zero-rated.[^7] |
| B3 | Use immutable sequential `INV-YYYY-NNNNNN`/`CRN-YYYY-NNNNNN`; issue promptly and within the legal period; show all SARS fields; retain the audit trail at least 5 years. Calculate from unrounded lines and display 2 decimals.[^8] |
| B4 | Start with controlled CSV export. Separate course/subscription revenue, deferred revenue, output VAT, gateway clearing/fees, refunds, receivables and bad debt. Recognise revenue when/as service transfers under IFRS 15.[^5] **Owner supplies accounting system/codes/reconciler.** |
| B5 | Dedicated business account; reference is immutable order ID; proof does not activate access until cleared funds reconcile. Review in 1 business day; cancel unpaid orders after 7 calendar days. **Owner supplies verified bank details and two approvers.** |
| B6 | Accept POs only from credit-approved organisations; require entity, PO/date, billing/tax details, line/value/VAT, signatory and terms. Default Net 30; finance sets limits/collections. |
| B7 | Offer a 7-day request window subject to mandatory CPA/ECTA rights; no automatic refund after material consumption/completion/certificate; fair pro-rata exceptions need finance approval; refund original rail. Legal must approve. |
| B8 | Launch subscription renewal by manual EFT/PO, with 14-day warning and 7-day grace; suspend new learning after grace. Defer recurring gateway billing until mandate/cancellation/failure journeys pass. |
| B9 | Reconcile orders, bank/gateway settlements, fees, refunds and ledger each business day and at month-end. Alert on any count mismatch, duplicate/orphan or unexplained variance over R1; escalate unresolved items after 1 business day. |

## C. Payment gateways and fraud

| ID | Proposed answer |
|---|---|
| C1 | Launch EFT, approved PO and Payfast once-off. Payfast recurring and Netcash are later. Keep card entry with the hosted gateway; TTLI stores no card data, supporting PCI scope reduction.[^4] |
| C2 | Finance director owns merchant accounts, deployment operator configures, finance operations reconciles. Secrets live only in the audited secret manager. Replace roles with individuals and references. |
| C3 | Initially enable cards and Instant EFT only; use legal descriptor and monitored billing contact. Approve HTTPS return/cancel/public ITN URLs; browser return never confirms payment. |
| C4 | Witness success, cancellation, duplicate/replayed ITN, bad signature, wrong amount/currency, delayed ITN, refund and outage. Grant access once only after server-side signature/source/amount validation.[^9] |
| C5 | Netcash **not at launch**; add only with funded need, contract/DPA review, sandbox credentials and equivalent notification/refund/reconciliation evidence. |
| C6 | Review amount/reference mismatch, duplicate/altered proof, repeated failures, suspicious identity, refund abuse and transactions over R10,000. Two people approve high-risk refunds; never request card details. |
| C7 | Settle to the dedicated business account; reconcile gross, refund, fee and net deposit daily. **Owner supplies bank account, actual cadence, fees and merchant agreement.** |

## D. Tenant and user onboarding

| ID | Proposed answer |
|---|---|
| D1 | Launch one internal/demo and at most two named pilot tenants, `en-ZA`, `Africa/Johannesburg`, curated catalogue and monitored support. **Owner supplies names/domains/catalogues/contacts.** |
| D2 | Named accounts only: primary plus backup platform admin; customer tenant admin; separate finance/content/facilitator users. Least privilege and quarterly access review; no shared admins. |
| D3 | Operator-run tenant creation at launch using a reviewed checklist and dual verification. Defer self-service until billing, abuse and domain automation exist. |
| D4 | Allow organisation/staff invitations, guest magic links and approved OIDC JIT. Defer open registration/public paid signup. JIT default is learner; privileged roles are assigned manually. |
| D5 | Guest access 7 days, one explicit sample course, no certificate/download/export, one grant per verified email; existing full accounts do not become guest accounts. |
| D6 | MFA mandatory for platform/tenant admins, finance, content and facilitators; prefer WebAuthn/passkeys, TOTP fallback. Recovery needs identity checks, two-person approval and forced re-enrolment.[^10] |
| D7 | OIDC is opt-in per enterprise tenant with exact issuer/audience/redirects, least scopes and allowlisted group mapping. “Not at launch” without a real customer test account. |
| D8 | Managers see aggregate completion by default. Individual progress/scores require documented purpose, assigned relationship and tenant-admin approval; never expose private survey answers. |
| D9 | Company registrar/DNS accounts have two named MFA-protected custodians. Operator verifies custom domains by DNS TXT before TLS; prefer custom domains later unless contracted. |

## E. Content, learning and accreditation

| ID | Proposed answer |
|---|---|
| E1 | Launch 3-5 complete courses, one path, one workshop offer and limited approved resources; hide incomplete content. Every item has business, educational and rights owners. **Owner supplies inventory.** |
| E2 | Master video MP4/H.264 up to 1080p, AAC audio; retain originals separately. Every spoken asset has language, duration, rights territory/expiry, WebVTT captions and transcript. |
| E3 | Three gates: author verifies sources/rights; subject expert verifies accuracy; content owner publishes. Material changes create a version and repeat approval; regulated content has no self-approval. |
| E4 | Fixed prerequisites/order; proposed pass mark 70%, 3 quiz attempts, highest score; published assignment rubric and named grader; second review for failures/appeals; certificate after every mandatory pass. Accreditation overrides. |
| E5 | Accept signed expiring HLS and visible user watermark for launch; defer Widevine/FairPlay unless licensed content requires funded DRM. Record rights-owner acceptance. |
| E6 | Require WCAG 2.2 AA: captions/transcripts, alt text, keyboard/focus, contrast and accessible documents. Block inaccessible core outcomes; exception needs alternative, owner and remediation date.[^3] |
| E7 | Make **no accreditation/CPD claim at launch** until body/provider number, points, certificate, reporting and retention rules are approved. |
| E8 | Accept current pilot certificate with legal provider, learner, course/version, completion date and unique verification ID; brand/accreditation owners approve a rendered sample. |
| E9 | Synthetic people/organisations/payments in UAT. Use real content only with licence approval; redact confidential material; do not copy production personal data into staging. |
| E10 | Cohorts **not at launch**; administer pilot workshops manually until lifecycle demand is funded. |

## F. Brand, public site and marketing

| ID | Proposed answer |
|---|---|
| F1 | Accept current logo/palette and a simple system sans-serif for pilot, with professional plain-language tone; no unlicensed media. **Owner must approve or replace with rights evidence.** |
| F2 | Publish only evidence-backed claims; remove placeholder metrics/superlatives and unpermitted logos/testimonials. CTAs map only to available enrol, quote or contact journeys. |
| F3 | One canonical domain and `www` redirect; controlled tenant subdomain; monitored `support@`, `privacy@`, `billing@`; only maintained social links. **Owner supplies exact values/DNS custodians.** |
| F4 | Publish versioned privacy, terms, cookie, refund and accessibility documents; record accepted version/time; remove placeholders. Legal/IO supplies final copy. |
| F5 | Reputable transactional ESP on dedicated subdomain; aligned SPF/DKIM; DMARC monitoring, then quarantine/reject after legitimate senders pass; separate marketing/transactional streams.[^11] |
| F6 | Marketing consent separate, optional and unchecked; confirmed opt-in; record wording/time/source; granular preferences and immediate suppression. Transactional mail contains no disguised promotion. IO/legal approves. |
| F7 | English at launch unless translations receive human/legal review. Separately approve account, payment, learning, support, security and marketing templates; test mobile and major mailbox providers. |
| F8 | Quiet hours 20:00-08:00 recipient local time; normal promotion max twice weekly; hard bounces suppressed immediately; investigate complaints and pause before provider limits are breached. |
| F9 | Before consent collect necessary security/session data only; non-essential analytics after opt-in. Pilot KPIs: activation, start/completion, conversion, support, refunds and uptime; privacy threshold applies. |

## G. POPIA, Information Officer and records

| ID | Proposed answer |
|---|---|
| G1 | **Owner input required:** Responsible Party is the selling entity; supply registered Information Officer/deputies and monitored contacts with Regulator evidence.[^12] |
| G2 | Maintain/publish the applicable PAIA manual and prescribed contact path in footer/privacy notice. Legal/IO confirms current version. |
| G3 | Use contract for purchased service, legal obligation for tax, documented legitimate-interest balancing for necessary operations/security, and consent for optional marketing. Future AI has no inherited permission. Counsel approves. |
| G4 | Proposed retention: prospects 12 months; dormant accounts 24 months; learning/assessment 5 years unless accreditation says longer; invoices/VAT at least 5 years; support 24 months; security/audit 12 months; backups 30 days. Legal/accountant approve each.[^8] |
| G5 | `privacy@` DSR mailbox; acknowledge 3 business days, proportional identity check, log and target completion in 30 calendar days or shorter law. Separate fulfiller/approver where possible. |
| G6 | Delete/anonymise profile, telemetry, optional uploads and marketing when no basis remains; restrict minimum tax/audit/accreditation records and retain a non-reversible suppression token. Legal/accounting approves field matrix. |
| G7 | Written legal/IO hold only, with scope/reason, restricted access and 90-day review. Same authority releases it; normal retention resumes with full audit trail. |
| G8 | Suspected unauthorised access/loss/disclosure/alteration/destruction triggers immediate IO/security escalation and evidence preservation. IO/legal assesses and notifies Regulator/people as soon as reasonably possible where required.[^13] |
| G9 | Approve launch-essential subprocessors only; record entity/service/data/countries/DPA/security/breach/deletion/change terms. Sentry/CDN/meeting/AI stay off until approved. |
| G10 | Prefer South African hosting/backups. Each foreign transfer needs documented section 72 basis, safeguards, purpose and minimisation; provider reputation alone is insufficient. |
| G11 | Minors and special personal information **not in launch scope**; adult users only and prohibit unnecessary sensitive data in free text/uploads until dedicated legal design exists. |
| G12 | Minimum reporting group 10; below it suppress or aggregate upward; never expose identifiable survey free text. This is a conservative default, not a statutory number. |
| G13 | Named product, IO/legal, security/ops, executive and finance/tax approval before go-live. Pen-test high/critical items close or receive executive/security time-bound risk acceptance. |

## H. Infrastructure, recovery and operations

| ID | Proposed answer |
|---|---|
| H1 | Single VM only for capped pilot, in South Africa under company cloud ownership. Move to managed database/object storage before broad GA or contracted HA. Owner supplies account/region/budget and migration trigger. |
| H2 | Separate staging/production domains and accounts; named MFA admins through VPN/IP allowlist; no public DB/storage/admin ports; two DNS/registrar custodians. |
| H3 | Primary/backup on-call for app/infra, security, payments and privacy; P1 pages phone/chat immediately; separate customer-comms authority; test quarterly. **Owner supplies people/contacts.** |
| H4 | Encrypted off-VM backup in separate account/failure domain; 30 daily points plus 12 monthly archives where retention permits. **Owner supplies destination, residency approval, individual owner and secret references.**[^14] |
| H5 | Pilot RPO 15 min; RTO 4 h core/8 h full media. Witness isolated restore before launch and quarterly; measure integrity and actual RPO/RTO. Better contractual target requires architecture/budget change.[^2] |
| H6 | Pilot SLO 99.5% monthly excluding announced maintenance. Alert on health failure 5 min, payment/backup/restore failure, certificate <14 d, storage >80%, error/security spikes. App logs 90 d, security logs 12 months unless policy changes. |
| H7 | Test 2× expected peak: initially 100 authenticated users, 50 video sessions, 10 checkouts/min plus reports/jobs; no loss and p95 interaction <2 s excluding media. Replace with contracted volumes. |
| H8 | Named least-privilege deployment/secrets accounts; one executes and another approves. Break-glass is time-limited, monitored, next-day reviewed and rotated after use. |
| H9 | Scan every build and weekly; routine patch monthly; exploitable internet critical within 72 h; backup check daily; restore/access review quarterly; incident exercise twice yearly; pentest before GA, annually and after major change. |
| H10 | Audited company secret manager plus offline recovery under two-person control; test retrieval quarterly without placing secrets in tickets/chat/logs. **Owner names custodians/successors.** |

## I. External integrations

| ID | Proposed answer |
|---|---|
| I1 | Manual meeting links at launch; Teams first only when a pilot customer supplies tenant/test users; Zoom/Google later. |
| I2 | Teams **not at launch** by default; if selected, dedicated Entra app, least Graph permissions, admin consent, named organiser and create/update/cancel evidence. |
| I3 | Sentry only after DPA/location approval; scrub credentials, cookies, bodies, learner content and identifiers; separate environments/least access. Otherwise use local structured logs. |
| I4 | No CDN for capped SA pilot unless load/egress evidence requires it; later provider must support signed URLs, safe caching, TLS, DPA/residency and spend alerts. |
| I5 | Spotify, CRM/API accounting, HRIS, SCORM, xAPI, LTI, webhooks and bulk import **later**; CSV accounting export at launch. Each future integration needs owner, privacy/threat review, sandbox and failure UAT. |

## J. AI gate

| ID | Proposed answer |
|---|---|
| J1 | No personal/tenant-confidential prompt data leaves SA by default. AI stays disabled until provider/region/DPA/subprocessors/retention/training and transfer basis are approved; require enterprise no-training terms. |
| J2 | First uses: drafts from approved public/course content (summaries, tags, question suggestions). Prohibit personal records, submissions, survey text, payments, credentials and security logs; output is always draft. |
| J3 | Minimum group 10; named human review; tenant kill switch; retention <=30 days; no provider training; tenant monthly hard cap. Production budget starts at zero until tests pass. NIST AI RMF governs continuously.[^15] |
| J4 | Prohibit autonomous discipline, hiring, pay, performance, accreditation, final grading and individual profiling. Disclose AI, label output, show context and provide human correction/appeal. |

## K. Acceptance and go-live authority

| ID | Proposed answer |
|---|---|
| K1 | Independent named UAT user for guest, learner, org admin/manager, facilitator/content author, finance, tenant admin and operator; reserve 2 weeks. Developer is not sole approver. **Owner supplies people.** |
| K2 | Sign discover/contact/guest; invite/login/MFA/recovery; browse/buy and payment failures/refunds; learn/video/assessment/certificate; report/author/publish; privacy/admin/audit/rollback, including mobile/accessibility. |
| K3 | P0 security/data loss/privacy and P1 broken core journey block launch. P2 needs workaround, named risk owner/date; P3 enters backlog. Every blocker gets independent retest; implementer cannot self-downgrade. |
| K4 | Five written approvals: product/UAT, finance/tax, legal/privacy, security/operations and executive. Waivers state scope, compensating control and expiry. **Owner supplies signatories/deputies.** |

## Acceptance template

> **Decision:** Accepted as proposed / replacement decision  
> **Approver:** Full name and role  
> **Evidence:** Signed document, ticket, URL or secret-manager reference  
> **Effective date:** YYYY-MM-DD  
> **Review date or trigger:** YYYY-MM-DD / event

A proposal becomes a TTLI decision only through recorded owner acceptance and
the requested evidence. Credentials and private keys never belong in either
document.

## Sources

[^1]: ISO, [ISO/IEC 27001:2022](https://www.iso.org/standard/27001), information security management systems.
[^2]: NIST, [Cybersecurity Framework 2.0](https://www.nist.gov/cyberframework), February 2024.
[^3]: W3C, [WCAG 2 Overview](https://www.w3.org/WAI/standards-guidelines/wcag/), including WCAG 2.2 and ISO/IEC 40500:2025.
[^4]: PCI Security Standards Council, [PCI DSS v4.0.1](https://www.pcisecuritystandards.org/document_library/?class=pcidss&doc=pci_dss), June 2024.
[^5]: IFRS Foundation, [IFRS 15 Revenue from Contracts with Customers](https://www.ifrs.org/issued-standards/list-of-standards/ifrs-15-revenue-from-contracts-with-customers/).
[^6]: SARS, [Obligations of a VAT vendor](https://www.sars.gov.za/types-of-tax/value-added-tax/obligations-of-a-vat-vendor/).
[^7]: SARS, [FAQs: Supplies of Electronic Services](https://www.sars.gov.za/lapd-vat-g16-vat-faqs-supplies-of-electronic-services/).
[^8]: SARS, [Tax Invoices](https://www.sars.gov.za/businesses-and-employers/government/tax-invoices/) and [VAT-vendor record keeping](https://www.sars.gov.za/types-of-tax/value-added-tax/obligations-of-a-vat-vendor/).
[^9]: Payfast, [Instant Transaction Notification](https://developers.payfast.co.za/docs/itn-instant-transaction-notification/).
[^10]: NIST, [SP 800-63B Authenticators](https://pages.nist.gov/800-63-4/sp800-63b/authenticators/).
[^11]: IETF, [RFC 9989: DMARC](https://www.rfc-editor.org/info/rfc9989), 2026.
[^12]: Information Regulator, [Information Officer guidance](https://inforegulator.org.za/wp-content/uploads/2020/07/InfoRegSA-GuidanceNote-IO-DIO-20210401.pdf).
[^13]: Information Regulator, [Section 22 security-compromise guidance](https://www.inforegulator.org.za/wp-content/uploads/2020/07/Guidelines-on-completing-a-Security-Compromise-Notification-ito-Section-22-POPIA.pdf).
[^14]: CISA, [#StopRansomware Guide](https://www.cisa.gov/stopransomware/ransomware-guide), encrypted isolated backups and restore testing.
[^15]: NIST, [AI Risk Management Framework 1.0](https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-ai-rmf-10), January 2023.
