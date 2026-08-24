"""Building storage keys out of names a client supplied.

Every upload in this codebase puts the caller's filename into an object
key. That was written six different times and sanitised none of them —
a background security review of the branding upload (2026-08-21) found
it, and the same shape was already present in podcasts, media,
assessments and payment proofs.

The practical exposure was limited rather than absent: `LocalStorage`
refuses a key containing `..` (`storage/local.py`), so the filesystem
backend was never traversable, and in S3/Azure a key is a flat string
where `../` is usually literal. But "the backend happens to catch it"
is not a control, and one of the three adapters catching it is not a
guarantee. So keys are built from sanitised parts here, and the
adapters refuse a bad key independently.

Sanitising, not rejecting: a learner uploading `Report (final).pdf`
should not get an error because of the space and brackets. The name is
reduced to something safe to store and recognisable to a human, and
anything left is replaced by the fallback.
"""

from __future__ import annotations

import re
import unicodedata

# One path component, no separators, no leading dots. Anything outside
# this set becomes a hyphen rather than an error.
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")
_LEADING_DOTS = re.compile(r"^\.+")
MAX_FILENAME = 120


def safe_filename(name: str | None, *, fallback: str) -> str:
    """Reduce a client-supplied filename to a single safe path segment.

    `../../etc/passwd` becomes `etc-passwd`; `..` alone becomes the
    fallback. Never returns an empty string, a name starting with a dot,
    or anything containing a path separator.
    """
    if not name:
        return fallback

    # Normalise first: a composed U+2044 or a full-width solidus should
    # not survive as something a downstream path parser treats as "/".
    cleaned = unicodedata.normalize("NFKC", name).strip()
    cleaned = cleaned.replace("\\", "/")
    # Take the last segment, the way a browser reports a plain filename,
    # then strip anything that could reintroduce structure.
    cleaned = cleaned.rsplit("/", 1)[-1]
    cleaned = _UNSAFE.sub("-", cleaned)
    cleaned = _LEADING_DOTS.sub("", cleaned).strip("-")

    if not cleaned or cleaned in {".", ".."}:
        return fallback
    if len(cleaned) > MAX_FILENAME:
        # Keep the extension, which is what a human recognises the file
        # by, and truncate the stem.
        stem, dot, extension = cleaned.rpartition(".")
        if dot and len(extension) <= 10:
            keep = MAX_FILENAME - len(extension) - 1
            cleaned = f"{stem[:keep]}.{extension}"
        else:
            cleaned = cleaned[:MAX_FILENAME]
    return cleaned


def assert_safe_key(key: str) -> None:
    """Refuse a key no caller should ever have built.

    Belt to `safe_filename`'s braces, and the check every storage adapter
    runs so the guarantee does not depend on which backend is configured.
    """
    if not key or key.startswith("/") or ".." in key.replace("\\", "/").split("/"):
        raise ValueError(f"unsafe object key {key!r}")


def build_object_key(*prefix: object, filename: str | None, fallback: str) -> str:
    """Join server-controlled prefix segments (a tenant id, an order id,
    a literal container-style label — never client input) with a
    sanitised, client-supplied filename.

    The one way a caller should combine a filename into a storage key.
    `safe_filename` existed for a while before this did (2026-08-21's
    fix) but every call site still hand-rolled its own f-string around
    it — six of them, independently, the same shape each time (docs/
    BACKLOG.md O13). A uniqueness prefix like `uuid4().hex` belongs
    *inside* `filename` (`f"{token}-{name}"`), not as a separate
    `prefix` segment — it is sanitised along with the name, which is
    harmless since it is already in `safe_filename`'s allowed charset.
    """
    segments = [str(p) for p in prefix]
    segments.append(safe_filename(filename, fallback=fallback))
    return "/".join(segments)


__all__ = ["MAX_FILENAME", "assert_safe_key", "build_object_key", "safe_filename"]
