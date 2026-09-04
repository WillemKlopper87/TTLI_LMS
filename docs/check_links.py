#!/usr/bin/env python3
"""Verify every relative markdown link and heading anchor in the docs set.

Anchor slugs follow GitHub's rule: lowercase, drop everything that is not
alphanumeric / space / hyphen / underscore, then spaces to hyphens. Consecutive
hyphens are NOT collapsed -- "Video -- self-hosted" really does produce a double
hyphen, and a checker that collapses them reports false failures.

Usage:
    python docs/check_links.py     # exit 1 if any link or anchor is broken
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
# Vendored and generated trees are not ours to validate.
EXCLUDED = {".git", ".venv", "venv", "node_modules", "site-packages", ".mypy_cache", ".ruff_cache"}
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
STRIP_MARKUP = re.compile(r"`|\*\*|\*|~~")
KEEP = re.compile(r"[^a-z0-9 _-]")

# A narrow, mechanical check (TTLI_Audit_Report_2026-09-02.md M9), not a
# general contradiction-detector: this repo's own prose convention for
# stating the migration count is `` `0001`-`0NNN` `` (an en-dash or hyphen
# range in backticks, e.g. NEXT_AGENT_BRIEF.md:42) -- catch it going stale
# again the way it already had (claimed 0031, actual head was 0040) before
# this check existed. Deliberately does not touch STATUS.md/HANDOFF.md --
# both carry a banner declaring their historical numbers frozen on purpose.
# Dash class built from chr() rather than a literal en dash in source --
# ASCII source only, no ambiguous-unicode lint noise, same match either way.
MIGRATION_RANGE = re.compile(r"`0001`[" + chr(0x2013) + r"-]`0(\d{3})`")
CURRENT_STATE_DOCS = ("README.md", "docs/NEXT_AGENT_BRIEF.md", "docs/BACKLOG.md")


def latest_migration_number(root: Path) -> int:
    versions = (root / "apps" / "api" / "alembic" / "versions").glob("*.py")
    numbers = [int(p.name[:4]) for p in versions if p.name[:4].isdigit()]
    if not numbers:
        raise RuntimeError("no alembic migrations found -- did the versions directory move?")
    return max(numbers)


def slug(heading: str) -> str:
    text = STRIP_MARKUP.sub("", heading).lower()
    return KEEP.sub("", text).replace(" ", "-")


def main() -> int:
    files = sorted(p for p in ROOT.rglob("*.md") if not EXCLUDED.intersection(p.parts))
    anchors = {
        p: {slug(m.group(1)) for m in HEADING.finditer(p.read_text(encoding="utf-8"))}
        for p in files
    }

    problems: list[str] = []
    links = 0

    for path in files:
        for match in LINK.finditer(path.read_text(encoding="utf-8")):
            target = match.group(2)
            if target.startswith(("http://", "https://", "mailto:", "#!")):
                continue
            links += 1
            file_part, _, fragment = target.partition("#")
            resolved = (path.parent / file_part).resolve() if file_part else path.resolve()

            if not resolved.exists():
                problems.append(f"{path.relative_to(ROOT)} -> {target} (no such file)")
                continue
            if fragment and resolved in anchors and fragment not in anchors[resolved]:
                problems.append(f"{path.relative_to(ROOT)} -> {target} (no such anchor)")

    latest = latest_migration_number(ROOT)
    for rel in CURRENT_STATE_DOCS:
        path = ROOT / rel
        if not path.exists():
            continue
        for match in MIGRATION_RANGE.finditer(path.read_text(encoding="utf-8")):
            claimed = int(match.group(1))
            if claimed != latest:
                problems.append(
                    f"{rel} claims migrations up to `0{claimed:03d}`, "
                    f"actual latest is `{latest:04d}`"
                )

    for problem in problems:
        print(f"BROKEN: {problem}", file=sys.stderr)

    if problems:
        print(f"\n{len(problems)} broken of {links} relative links", file=sys.stderr)
        return 1

    print(f"OK: {links} relative links across {len(files)} files resolve")
    print(f"OK: migration-count claims in {', '.join(CURRENT_STATE_DOCS)} match `{latest:04d}`")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
