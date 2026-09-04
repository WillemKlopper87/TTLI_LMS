# Archive

Dated, one-off reviews and synthesis documents — reference material, not the
plan. `docs/BACKLOG.md` is the sole task-status authority for product/feature
work; `docs/REMEDIATION_LEDGER.md` is the sole authority for audit/review
*findings*. Nothing here should be read as current for either.

- **`latest_critique.md`** (28 Aug 2026) and **`TTLI_Code_report.md`** (28 Aug
  2026) — two independently produced whole-codebase critiques from the same
  day, both superseded by `TTLI_Audit_Report_2026-09-02.md`.
- **`what_next.md`** (28 Aug 2026) — a synthesis reconciling `latest_critique.md`
  against `docs/BACKLOG.md` and the live codebase. Its "new backlog items"
  section (six items not previously tracked) was folded into `docs/BACKLOG.md`
  as P17–P19, O14 and R15 before this file was archived — do not re-add them
  from here without checking whether they're already tracked there.
- **`TTLI_Audit_Report_2026-09-02.md`** (2 Sep 2026) — whole-codebase audit,
  findings H1–H2/M1–M9. Superseded `latest_critique.md`/`TTLI_Code_report.md`
  above. Its own findings are now tracked in `docs/REMEDIATION_LEDGER.md`
  Part A — read this file only for the original file:line evidence, not for
  current status.
- **`fable5.1_review.md`** (3 Sep 2026) — a fresh whole-codebase review (six
  independent read-only reviewers, merged and re-ranked), findings
  C-1–C-3/H-1–H-20 plus ~45 Medium/~60 Low. Tracked in
  `docs/REMEDIATION_LEDGER.md` Part B, same caveat as above.

Do not implement from these files, and do not treat a claim in one as current
just because it reads confidently — check it against the actual code,
`docs/BACKLOG.md`, or `docs/REMEDIATION_LEDGER.md` first.
