"""Storage-key sanitising (`core/object_keys.py`).

Written after a background security review found the branding logo
upload putting an unsanitised client filename straight into an object
key on 2026-08-21. The same shape was already present at five other
upload sites; these tests pin the shared helper they all now use.

`build_object_key` (docs/BACKLOG.md O13, 2026-08-24) closes the gap
`safe_filename` alone left open: every one of those six sites still
hand-rolled its own f-string joining a sanitised name onto a prefix,
so a seventh call site could still skip sanitising by accident. These
tests pin the one function that now does both steps together.
"""

from __future__ import annotations

import uuid

import pytest
from src.core.object_keys import MAX_FILENAME, assert_safe_key, build_object_key, safe_filename


@pytest.mark.parametrize(
    ("supplied", "expected"),
    [
        ("report.pdf", "report.pdf"),
        # Traversal is flattened, not rejected — the upload still works,
        # it just cannot escape its prefix.
        ("../../etc/passwd", "passwd"),
        (r"..\..\windows\system32", "system32"),
        ("nested/path/file.png", "file.png"),
        # A name that is nothing but traversal has no usable leaf.
        ("..", "fallback"),
        (".", "fallback"),
        ("", "fallback"),
        (None, "fallback"),
        # Hidden files do not stay hidden.
        (".env", "env"),
        # Ordinary human filenames survive recognisably.
        ("Report (final) v2.pdf", "Report-final-v2.pdf"),
    ],
)
def test_filenames_are_reduced_to_one_safe_segment(supplied: str | None, expected: str) -> None:
    result = safe_filename(supplied, fallback="fallback")
    assert result == expected
    assert "/" not in result and "\\" not in result
    assert not result.startswith(".")


def test_unicode_lookalikes_cannot_reintroduce_a_separator() -> None:
    """NFKC folds a fullwidth solidus to "/" — normalising after the
    split would have let it through as structure."""
    assert "/" not in safe_filename("a\uff0f..\uff0fb.png", fallback="x")


def test_long_names_are_truncated_but_keep_their_extension() -> None:
    name = f"{'a' * 400}.pdf"
    result = safe_filename(name, fallback="x")
    assert len(result) <= MAX_FILENAME
    assert result.endswith(".pdf"), "a human recognises the file by its extension"


def test_assert_safe_key_refuses_what_no_caller_should_build() -> None:
    assert_safe_key("tenant-branding/abc/logo.png")
    for bad in ("../secrets", "a/../../b", "/absolute", "", r"a\..\b"):
        with pytest.raises(ValueError):
            assert_safe_key(bad)


def test_build_object_key_joins_prefix_segments_with_a_sanitised_name() -> None:
    key = build_object_key(
        "video-assets", "asset-1", "source", filename="my video.mp4", fallback="x"
    )
    assert key == "video-assets/asset-1/source/my-video.mp4"


def test_build_object_key_stringifies_non_string_prefix_segments() -> None:
    """Every real call site passes a UUID object (a tenant/order/asset
    id), not a string — the same `str(x)` an f-string would have done
    implicitly."""
    tenant_id = uuid.UUID(int=1)
    key = build_object_key(tenant_id, filename="a.pdf", fallback="x")
    assert key == f"{tenant_id}/a.pdf"


def test_build_object_key_never_lets_traversal_through_the_filename() -> None:
    key = build_object_key("orders", "order-1", filename="../../etc/passwd", fallback="x")
    assert key == "orders/order-1/passwd"
    assert_safe_key(key)


def test_build_object_key_uses_the_fallback_for_an_unusable_name() -> None:
    key = build_object_key("orders", "order-1", filename=None, fallback="proof")
    assert key == "orders/order-1/proof"


def test_build_object_key_with_no_prefix_is_just_the_sanitised_name() -> None:
    assert build_object_key(filename="a.pdf", fallback="x") == "a.pdf"
