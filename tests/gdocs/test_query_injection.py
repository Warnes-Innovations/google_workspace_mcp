"""Drive query injection guards for the gdocs tools.

The injection these guard against was demonstrated against the LIVE Drive API on
2026-09-07, not inferred:

    name contains 'unterminated                        -> HTTP 400 Invalid Value
    name contains 'x\\\\' or name contains 'y'            -> HTTP 200, accepted
    name contains 'nomatch\\\\' or mimeType = '...folder' -> returned a FOLDER

The first is the control: a malformed query really does 400, so the second's
acceptance means something. The third is conclusive — a *name* search cannot
return a folder, so the injected clause was evaluated, not merely tolerated.

Google documents \\' as the escape for a single quote but does not document
whether a literal backslash must be doubled. That undocumented half is exactly
where the common `.replace("'", "\\\\'")` fails.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

from core.utils import UserInputError  # noqa: E402
from gdrive.drive_helpers import (  # noqa: E402
    escape_drive_query_literal,
    validate_drive_id,
)


# --------------------------------------------------------------------------
# escape_drive_query_literal
# --------------------------------------------------------------------------


def _closes_literal(escaped: str) -> bool:
    """True if `escaped` would terminate the surrounding single-quoted literal.

    Walks the string the way a backslash-escaping parser does. Derived from the
    parser's rule rather than restating an expected output, so it stays valid
    for inputs nobody thought to enumerate.
    """
    i = 0
    while i < len(escaped):
        if escaped[i] == "\\":
            i += 2  # backslash consumes the next character
            continue
        if escaped[i] == "'":
            return True  # an unescaped quote ends the literal
        i += 1
    return False


@pytest.mark.parametrize(
    "hostile",
    [
        "x\\' or mimeType = 'application/vnd.google-apps.folder",
        "nomatch\\' or trashed = true or 'y",
        "trailing-backslash\\",
        "a'b",
        "\\",
        "'",
        "\\\\'",
        "'; DROP",
    ],
)
def test_escape_never_lets_a_value_close_its_own_literal(hostile):
    """No input may terminate the literal it is embedded in."""
    assert not _closes_literal(escape_drive_query_literal(hostile))


def test_naive_escape_is_the_thing_being_fixed():
    """Negative control: the previous escape DOES let the literal close.

    Without this, the test above could pass against an implementation that
    never worked -- it pins that the guard changed the outcome.
    """
    hostile = "x\\' or mimeType = 'application/vnd.google-apps.folder"
    naive = hostile.replace("'", "\\'")
    assert _closes_literal(naive), "the naive escape should be broken"
    assert not _closes_literal(escape_drive_query_literal(hostile))


def test_escape_leaves_ordinary_queries_alone():
    assert escape_drive_query_literal("budget 2026") == "budget 2026"
    assert escape_drive_query_literal("Valentine's Day") == "Valentine\\'s Day"


def test_backslash_is_escaped_before_the_quote():
    """Order is the defect. Escaping the quote first re-breaks it."""
    assert escape_drive_query_literal("\\'") == "\\\\\\'"


# --------------------------------------------------------------------------
# validate_drive_id
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "good",
    ["root", "appDataFolder", "0ASharedDriveId", "1LS1utVX7Bv-cdnXiPvja_h", "abc123"],
)
def test_validate_accepts_real_drive_ids(good):
    assert validate_drive_id(good) == good


@pytest.mark.parametrize(
    "bad",
    [
        "root' or trashed = true or 'x",  # the demonstrated payload
        "abc'def",
        "abc\\def",
        "abc def",
        "",
        "   ",
        "abc\ndef",
    ],
)
def test_validate_rejects_anything_that_could_break_out(bad):
    with pytest.raises(UserInputError):
        validate_drive_id(bad)


def test_validate_error_names_the_field():
    """The message must be actionable about WHICH parameter was wrong."""
    with pytest.raises(UserInputError, match="folder_id"):
        validate_drive_id("bad'id", field="folder_id")
