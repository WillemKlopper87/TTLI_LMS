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
LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.M)
STRIP_MARKUP = re.compile(r"`|\*\*|\*|~~")
KEEP = re.compile(r"[^a-z0-9 _-]")


def slug(heading: str) -> str:
    text = STRIP_MARKUP.sub("", heading).lower()
    return KEEP.sub("", text).replace(" ", "-")


def main() -> int:
    files = sorted(p for p in ROOT.rglob("*.md") if ".git" not in p.parts)
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

    for problem in problems:
        print(f"BROKEN: {problem}", file=sys.stderr)

    if problems:
        print(f"\n{len(problems)} broken of {links} relative links", file=sys.stderr)
        return 1

    print(f"OK: {links} relative links across {len(files)} files resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
