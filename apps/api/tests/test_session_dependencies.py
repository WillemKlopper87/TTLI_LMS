from __future__ import annotations

from typing import get_args

import pytest
from fastapi.params import Depends
from src.core.deps import AuditedSessionDep, SessionDep

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("dependency", [SessionDep, AuditedSessionDep])
def test_transaction_teardown_finishes_before_response(dependency: object) -> None:
    """A create response must never outrun the transaction that created it."""
    metadata = get_args(dependency)[1:]
    marker = next(item for item in metadata if isinstance(item, Depends))

    assert marker.scope == "function"
