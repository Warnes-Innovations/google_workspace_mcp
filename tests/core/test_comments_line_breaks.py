"""Comment tool output must use real line breaks, not the two-character `\\n`.

Every return in `core/comments.py` was built with `"\\\\n"` in the source, which
is a backslash followed by `n` — not a newline. The tools therefore returned one
physical line containing literal `\\n` text, so a reader (human or model) saw the
escape sequence rather than a formatted record list.

The assertions are written against `splitlines()` rather than against the absence
of a particular character, so they pin the PROPERTY (this output is multi-line)
rather than one spelling of the bug.
"""

from unittest.mock import MagicMock

import pytest

from core.comments import (
    _create_comment_impl,
    _read_comments_impl,
    _reply_to_comment_impl,
    _resolve_comment_impl,
)

LITERAL_ESCAPE = "\\" + "n"  # the two characters, never a newline


def _service(payload):
    service = MagicMock()
    service.comments.return_value.list.return_value.execute.return_value = payload
    service.comments.return_value.create.return_value.execute.return_value = payload
    service.replies.return_value.create.return_value.execute.return_value = payload
    return service


COMMENT = {
    "id": "c1",
    "author": {"displayName": "Alice"},
    "content": "First note",
    "createdTime": "2026-01-01",
    "resolved": False,
    "replies": [],
}


@pytest.mark.asyncio
async def test_read_comments_returns_real_lines():
    out = await _read_comments_impl(_service({"comments": [COMMENT]}), "docs", "f1")

    assert LITERAL_ESCAPE not in out
    # One record spans several lines: header, blank, then the fields.
    assert len(out.splitlines()) > 1
    assert "Comment ID: c1" in out.splitlines()


@pytest.mark.parametrize(
    "impl, args",
    [
        (_create_comment_impl, ("docs", "f1", "hello")),
        (_reply_to_comment_impl, ("docs", "f1", "c1", "a reply")),
        (_resolve_comment_impl, ("docs", "f1", "c1")),
    ],
)
@pytest.mark.asyncio
async def test_write_confirmations_return_real_lines(impl, args):
    """The three write paths built their confirmations the same way.

    They are covered explicitly because a fix aimed only at the `.join` in the
    read path leaves these behind — they are f-strings, not joins, so a grep for
    the join shape does not reach them.
    """
    out = await impl(_service(COMMENT), *args)

    assert LITERAL_ESCAPE not in out
    assert len(out.splitlines()) > 1
