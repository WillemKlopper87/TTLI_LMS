# TTLI platform-owner decision pack

**Prepared:** 2026-09-09  
**Purpose:** one answer pack that lets engineering finish production hardening,
configure a representative staging tenant, complete acceptance testing, and
prepare a controlled launch. This is a decision and evidence request, not tax
or legal advice; the named accountant and legal/privacy advisers must approve
their sections.

## How to complete it

For a proposed answer to every item, use
[`PLATFORM_OWNER_RECOMMENDED_DEFAULTS.md`](PLATFORM_OWNER_RECOMMENDED_DEFAULTS.md).
Owners may accept a proposal verbatim or replace it, but must still name the
approver and attach the requested evidence. The companion does not invent
entity details, prices, bank accounts, officers or credentials.

For every item, provide **one explicit answer**, a **named approver**, and the
requested **evidence or secure access**. “Not at launch” is valid where offered.
Do not put passwords, private keys or gateway secrets in this document: provide
the secret-manager location and grant the deployment operator access.

The pack is complete only when every **Launch gate** item is answered. **Later
scope** items may be answered “not at launch”; that decision still prevents the
team from building an unapproved assumption. Dates mean calendar dates in the
Africa/Johannesburg timezone unless the owner specifies otherwise.

---

## A. Business, launch and commercial owner

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| A1 | Launch | What legal entity sells the training: registered name, trading name, company/registration number, VAT number (or confirmation it is not VAT registered), physical and postal address? | Accountant-approved legal-entity sheet. |
| A2 | Launch | What is the launch date, pilot duration, launch countries, currencies and expected learner/tenant/concurrent-user volumes? | One approved launch-scope row per market. |
| A3 | Launch | Which three offers are actually sold at launch: individual course, team bundle, enterprise enquiry? For each, state inclusions, duration, seat rules, support level and approved price. | Signed price/package sheet; replace all illustrative figures in `05_COMMERCIAL.md`. |
| A4 | Launch | Who may approve pricing, discounts, refunds, credits, complimentary access and contract exceptions? | Names/roles plus monetary limits. |
| A5 | Launch | What are the support hours, channels, response targets, escalation contacts and maintenance window? | Approved support/SLA schedule. |
| A6 | Launch | Which customer contracts are required (consumer terms, enterprise MSA/order form, DPA, SLA), and who approves them? | Final versioned documents and effective dates. |
| A7 | Later scope | Are departments/business units, cohort scheduling, custom certificates, competencies, HRIS, xAPI/LTI or external CRM required at launch? | “At launch” or “not at launch” for each; named priority for any selected item. |

## B. Tax, invoicing and accounting

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| B1 | Launch | Are public prices VAT-inclusive or VAT-exclusive, and what tax wording must appear at catalogue, checkout, invoice and quote? | Accountant-approved wording and current domestic VAT rule. |
| B2 | Launch | For every launch country and B2B/B2C combination, what VAT/tax rule applies, what customer location/tax-number evidence is required, and when must a sale be refused? | Written accountant/tax memo; no verbal summary. SARS publishes separate electronic-services guidance, so “international = zero-rated” is not an acceptable blanket answer. |
| B3 | Launch | What invoice/credit-note fields, numbering prefix/series, issue timing, rounding method and retention period are required? | Sample approved tax invoice and credit note. |
| B4 | Launch | Which accounting system receives exports, which chart-of-accounts/tax codes map to sales, VAT, gateway fees, refunds, deferred revenue and receivables, and who imports/reconciles them? | Mapping sheet plus named reconciler and cadence. |
| B5 | Launch | What are the EFT bank details, beneficiary wording, payment-reference format, proof requirements, approval SLA and stale-payment cancellation rule? | Approved bank-detail sheet; finance approver list. |
| B6 | Launch | What PO fields and document types are mandatory, who may approve credit, and what payment terms/overdue process apply? | PO acceptance policy and invoice terms. |
| B7 | Launch | What refund/cancellation policy applies by product, timing and payment rail; are partial refunds allowed; who authorises them? | Legal/accounting-approved matrix. |
| B8 | Launch | How are subscriptions funded at launch: manual EFT/PO renewal as built, Payfast recurring billing, or not offered? Define grace period, upgrade/downgrade, cancellation and failed-renewal rules. | One selected model and customer-facing wording. |
| B9 | Launch | What daily/monthly reconciliation reports and variance thresholds must alert finance? | Report recipients, schedule and accepted tolerance. |

## C. Payment gateways and fraud operations

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| C1 | Launch | Which rails launch: EFT, PO, Payfast once-off, Payfast recurring, Netcash, or an explicit subset? | Mark each “launch”, “later” or “never”. |
| C2 | Launch | Who owns the Payfast merchant account and sandbox account? | Sandbox access for testing; production merchant ID/key/passphrase delivered through the secret manager. Payfast recommends a merchant-specific sandbox and requires a public notification URL for ITN testing. |
| C3 | Launch | Which Payfast payment methods are enabled, what statement descriptor/customer support details appear, and are return/cancel/notification URLs approved? | Merchant-dashboard screenshots/config export with secrets redacted. |
| C4 | Launch | Who performs the real Payfast acceptance run and signs off success, cancellation, duplicate ITN, invalid signature, amount mismatch, delayed notification and refund? | Completed test record with Payfast transaction IDs. |
| C5 | Launch if selected | Who owns the Netcash account, Pay Now service key and test mode, and which payment methods/notification URLs are enabled? | Test access and production secret reference; otherwise “not at launch”. |
| C6 | Launch | What fraud/manual-review triggers apply to payment proofs, repeated failures, amount mismatch, suspicious identity or refund abuse? | Decision table and escalation owner. |
| C7 | Launch | What is the settlement bank account, payout cadence, fee schedule and finance owner for each gateway? | Current merchant agreement/fee schedule and reconciler. |

## D. Tenant and user onboarding

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| D1 | Launch | Which tenant(s) launch first, with what legal/display name, primary hostname, catalogue, locale/timezone and support contact? | One onboarding sheet per tenant. |
| D2 | Launch | Who are the initial platform super-admin, tenant admin, finance, content-author and facilitator users? | Individual names/emails; no shared admin accounts. |
| D3 | Launch | Is tenant creation an operator-run onboarding step at launch, or must customers self-create a tenant? | Choose one. Self-service tenant creation is not currently built. |
| D4 | Launch | Which learner registration paths are allowed: guest form + magic link, staff/org invitation, SSO JIT provisioning, or public paid-account signup? | Choose and describe identity proof. Public general-purpose `/register` is not currently built. |
| D5 | Launch | Is guest access 7 or 14 days, what sample content is granted, and may an existing full account request guest access? | One duration and entitlement list. |
| D6 | Launch | Is MFA mandatory for super-admin/admin/finance/content/facilitator roles, and what is the lost-device recovery process? | Role-by-role rule and recovery approvers. |
| D7 | Launch | Which tenants use Entra/OIDC SSO, what domains and role/group mappings apply, and who can provide a real test account? | IdP metadata/client secret reference and named test user; otherwise “not at launch”. |
| D8 | Launch | May managers see individual learner progress/scores, for which courses, and who can enable that exception? | Default plus exception-approval policy. |
| D9 | Launch | Who controls DNS and may add verification/TLS records for custom domains? | Named contact and access path. Domain verification automation is not yet built. |

## E. Content, learning and accreditation

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| E1 | Launch | What content launches: courses, paths, workshops, coaching, podcasts, articles, books and downloadable resources? | Inventory with owner, status and target tenant/product. |
| E2 | Launch | For every video/audio asset, provide duration, source format/resolution, captions/transcript status, language, rights owner and licence territory/expiry. | Machine-readable inventory plus source files. |
| E3 | Launch | Who approves educational accuracy, copyright/licensing and final publication? | Named content owner and approval workflow. |
| E4 | Launch | For each course/path, what are prerequisites, lesson order, completion rules, pass mark, attempts, assignment rubric, grading/moderation owner and certificate trigger? | Signed course-definition sheet. |
| E5 | Launch | Is signed HLS plus visible watermark accepted for launch, or is Widevine/FairPlay DRM mandatory? | Explicit acceptance or funded DRM provider/project. |
| E6 | Launch | Are captions, transcripts, alt text and downloadable accessible alternatives mandatory for every asset before publication? What exception process exists? | Accessibility publication standard. |
| E7 | Launch | Which accreditation/CPD body applies, and what provider number, points/hours, certificate fields, validity/expiry and reporting export are required? | Accreditation rules and sample approved certificate; otherwise “no accreditation at launch”. |
| E8 | Launch | What certificate/badge design is approved? Is the fixed current layout acceptable or is custom certificate design required before launch? | Approved sample or “current layout accepted”. |
| E9 | Launch | What real content may be used in staging/UAT, and what must be synthetic or redacted? | UAT dataset and handling rule. |
| E10 | Later scope | Are cohorts scheduled runs of courses/paths required at launch, and what capacity/date/facilitator rules apply? | “Not at launch” or complete lifecycle rules. |

## F. Brand, public site and marketing

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| F1 | Launch | Approve or replace the logo variants, colours, fonts, photography, icon style and tone of voice. | Final brand pack with usage/licence rights. |
| F2 | Launch | Approve every public-page claim, biography, testimonial, client logo, course description, price and call to action. | Versioned copy deck; written permission for people/logos/testimonials. |
| F3 | Launch | What are the final primary domain, tenant subdomains, contact details and footer social URLs? | DNS owner plus exact URLs/addresses. |
| F4 | Launch | Which privacy notice, terms, cookie notice, refund policy and accessibility statement versions go live? | Final legal copy, version IDs and effective dates. The code currently stamps an unpublished placeholder policy version. |
| F5 | Launch | Which email/ESP provider and sending domain are used; who configures SPF, DKIM and DMARC; what From/Reply-To addresses apply? | Provider access, DNS records and verified sender evidence. |
| F6 | Launch | What marketing-consent wording, lawful basis, double-opt-in rule, suppression rule and email preference categories apply? | Legal-approved form/email wording. |
| F7 | Launch | Which transactional and marketing templates are approved, in which languages, and who signs off deliverability/content? | Template pack and test recipient list. |
| F8 | Launch | What campaign cadence, audience rules, quiet hours, unsubscribe handling and bounce thresholds apply? | Marketing operating policy and owner. |
| F9 | Launch | Which analytics are allowed before/after consent, which cookies may be set, and what reporting KPIs define pilot success? | Consent/cookie matrix and KPI targets. |

## G. POPIA, Information Officer and records governance

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| G1 | Launch | Who is the Responsible Party, registered Information Officer and any Deputy Information Officers? | Registration confirmation, names and official contact details. The Information Regulator provides the registration route and guidance. |
| G2 | Launch | Is a PAIA manual required/published, and where must the privacy/PAIA contact details appear? | Legal answer and final document/URL. |
| G3 | Launch | What lawful basis applies to account administration, learning records, assessments, manager reporting, marketing, analytics, recordings and future AI? | Legal-approved purpose/basis matrix. |
| G4 | Launch | What retention period applies to each data class: prospects, users, learning activity, assessment answers, video telemetry, uploads, email events, support, audit, invoices/ledger, backups and security logs? | Approved retention schedule with legal citations/owner. |
| G5 | Launch | What is the data-subject request mailbox and identity-verification process; who approves access, correction, portability, objection and erasure; what SLA applies? | DSR procedure, template responses and escalation contacts. |
| G6 | Launch | Which fields must be anonymised versus retained when a person requests erasure, especially where financial/accreditation records must survive? | Legal/accounting-approved erasure matrix. |
| G7 | Launch | What starts/ends a legal hold, who authorises it, which records are frozen, and how is the subject/audit trail handled? | Legal-hold procedure and owner. |
| G8 | Launch | What constitutes a security compromise, who assesses/notifies the Regulator and affected people, and what contacts/templates are used? | Approved incident procedure aligned with the Information Regulator's current section 22 notification guidance. |
| G9 | Launch | Approve every subprocessor and data location: hosting/storage, backup provider, CDN, Sentry, email/ESP, Payfast/Netcash, meeting providers and—later—AI. | Subprocessor register, DPA links, countries and data categories. |
| G10 | Launch | For transfers outside South Africa, what section 72 mechanism/legal basis is approved and which data may leave? | Written legal determination per subprocessor. |
| G11 | Launch | Are minors or special personal information in scope? If yes, what consent/authorisation and additional controls apply? | Explicit “not in scope” or legal-approved rules. |
| G12 | Launch | What minimum reporting group protects anonymity, and what happens below it: suppress, combine upward, or obtain another lawful basis? | One number/rule for survey/manager reporting; AI remains separately gated. |
| G13 | Launch | Who signs off the POPIA compliance matrix, penetration test, access review and residual risks before go-live? | Named approvers and due dates. |

## H. Infrastructure, recovery and operations

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| H1 | Launch | Is launch hosted on the documented single VM or Azure managed target, in which South African region/account, and who owns the cloud subscription/billing? | Architecture choice, account access and budget owner. |
| H2 | Launch | What are staging and production domains, DNS access, TLS owner and allowed administrator source networks? | Access grants and network rule. |
| H3 | Launch | Who is on call for application, infrastructure, security, payments and privacy incidents, and through which alert channels? | Primary/backup rota with phone/email/chat routes. |
| H4 | Launch | Who is the individual backup owner, which off-VM `rclone crypt` destination is approved, where is it hosted, and is 7–30-day retention acceptable? | Owner ID/email, remote configured on production, provider/residency approval. |
| H5 | Launch | Are RPO 15 minutes and RTO 4–8 hours accepted? Who witnesses and signs the first backup plus isolated restore drill? | Passing uploaded drill report and sign-off. |
| H6 | Launch | What monitoring/alert thresholds, log retention, uptime target and status/incident communication channel are required? | Operating SLO/alert matrix. |
| H7 | Launch | What production capacity and load profile must be proved: concurrent learners, streams, checkouts, campaign volume and storage growth? | Approved load-test profile and pass thresholds. |
| H8 | Launch | Who may deploy/rollback, approve production changes, access secrets and invoke break-glass access? | Access matrix and review cadence. |
| H9 | Launch | What maintenance, patching, restore-test, access-review, vulnerability-review and penetration-test cadence is approved? | Operations calendar and owners. |
| H10 | Launch | Where is `.env.prod`/key recovery material escrowed, who can retrieve it, and how is recovery tested without exposing secrets? | Secret-manager/key-escrow record and two-person recovery process. |

## I. External integrations

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| I1 | Launch | Which meeting providers launch: manual, Teams, Zoom and/or Google Meet? | Selection plus real tenant/app credentials and test users for each selected provider. |
| I2 | Launch | If Teams launches, who provides the Entra app, Graph permissions/admin consent and organiser mailbox? | Tenant/client secret reference, organiser UPN and live test booking. |
| I3 | Launch | Which Sentry organisation/project and alert recipients are approved, and what PII-scrubbing policy applies? | DSN via secret manager and approved scrub rule. |
| I4 | Launch | Is a CDN required for launch video delivery; if yes, which provider/domain, cache policy, signed-URL support and egress budget? | Provider access and approved configuration. |
| I5 | Later scope | Are Spotify enrichment, external CRM, accounting API, HRIS sync, SCORM, xAPI, LTI 1.3, completion webhooks or bulk history import required? | “At launch”, “later” or “never” for each. SCORM is currently recorded as not required; confirm or supersede that decision. |

## J. AI gate (answer now; implementation remains after hardening)

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| J1 | Later scope | May redacted prompt data leave South Africa? Which provider(s), region(s), models and DPA/contract terms are approved? | Written legal/privacy decision and provider DPA. |
| J2 | Later scope | Which purposes and data sources may AI process, what consent/lawful basis applies, and which data is prohibited? | Approved AI purpose/data matrix. |
| J3 | Later scope | What minimum anonymity group, human-review workflow, retention, tenant kill switch and monthly budget apply? | Policy, reviewers and per-tenant limits. |
| J4 | Later scope | Which uses are expressly prohibited (discipline, hiring, performance decisions, individual profiling), and what user-facing explanation/appeal path applies? | Approved AI acceptable-use and governance statement. |

## K. Acceptance and go-live authority

| ID | Gate | Question to answer | Evidence / exact output required |
|---|---|---|---|
| K1 | Launch | Who are the UAT users for guest, learner, organisation admin, manager, facilitator, content author, finance, tenant admin and platform operator? | Individual test-user list and availability window. |
| K2 | Launch | Which representative journey must each persona sign off, including failure/refund/cancellation paths? | Approved UAT script and expected result per persona. |
| K3 | Launch | What defects block launch by severity, who accepts residual risk, and what evidence is required for retest closure? | Go/no-go policy. |
| K4 | Launch | Who gives final product, finance, legal/privacy, security/operations and executive approval? | Named signatories; all five approvals required. |

---

## Return checklist

The owner should return:

- this pack with every Launch item answered and dated;
- accountant-approved tax/invoice/reconciliation material;
- final legal/policy/contract copy and Information Officer evidence;
- launch package/pricing sheet, brand pack and approved public copy;
- complete content/accreditation inventory and usable UAT content;
- named users/owners/on-call contacts and a UAT sign-off plan;
- secret-manager references and access grants for every selected integration;
- cloud, DNS, email-domain, gateway sandbox and production-account access;
- an explicit “later/never” decision for every unselected gateway/integration;
- signed acceptance of the target RPO/RTO and residual launch risks.

Answers unlock engineering completion; production readiness still requires the
resulting objective evidence: green CI, real gateway/integration tests, staged
UAT, load/security checks, monitored deployment/rollback proof, the production
restore drill, and final go-live sign-off.

## Official references for the accountable advisers

- [SARS — Value-Added Tax](https://www.sars.gov.za/types-of-tax/value-added-tax/)
- [SARS — electronic-services VAT FAQs](https://www.sars.gov.za/wp-content/uploads/Ops/Guides/Legal-Pub-FAQs-VAT02-FAQs-VAT-on-Supplies-of-Electronic-Services.pdf)
- [Information Regulator — Information Officer guidance](https://inforegulator.org.za/wp-content/uploads/2020/07/InfoRegSA-GuidanceNote-IO-DIO-20210401.pdf)
- [Information Regulator — section 22 security-compromise notification guidance](https://www.inforegulator.org.za/wp-content/uploads/2020/07/Guidelines-on-completing-a-Security-Compromise-Notification-ito-Section-22-POPIA.pdf)
- [Payfast — checkout, ITN and sandbox documentation](https://developers.payfast.co.za/docs/itn-instant-transaction-notification/)
