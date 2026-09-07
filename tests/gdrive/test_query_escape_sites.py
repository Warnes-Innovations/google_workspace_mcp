"""Every Drive-query call site is pinned to a complete escape or a validator.

Companion to tests/gdocs/test_query_injection.py, which pins the HELPERS. This
pins the CALL SITES, because the helpers being correct says nothing about
whether they are actually used.

That gap is not hypothetical. A regex sweep for this class missed
`check_drive_file_public_access` for a week: the pattern enumerated the exact
spellings already seen (`q=f"`, `q = f"`, `query=f"`) and the site used
`query = f"` with spaces. A clean grep proved the author's assumption about
formatting, not the state of the tree. So this file asserts the property from
the AST instead of from a text search.
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# Tokens from Drive's files.list `q` grammar. Narrowing on the API's grammar
# rather than on variable names or spacing: a rename or a reformat cannot make
# this stale, which is exactly how the original sweep failed.
DRIVE_QUERY_TOKENS = (
    "in parents",
    "name =",
    "name contains",
    "fullText contains",
    "sharedWithMe",
)

# Expressions allowed inside a quoted literal of a Drive query, and why.
SAFE_EXPRESSIONS = {
    "escape_drive_query_literal(query)",  # complete escape
    "escape_drive_query_literal(file_name)",  # complete escape
    "escaped_query",  # assigned from escape_drive_query_literal
    "escaped_name",  # assigned from escape_drive_query_literal
    "mime",  # allowlisted by resolve_file_type_mime
    "safe_folder_id",  # rebound from validate_drive_id() -- the NAME carries
    # the guarantee, so a raw `folder_id` can never satisfy this set by accident
    "resolved_folder_id",  # validated inside resolve_drive_item
}

SCAN_DIRS = (
    "gdrive",
    "gdocs",
    "gmail",
    "gsheets",
    "gslides",
    "gforms",
    "gtasks",
    "core",
)


def _literal_text(node: ast.JoinedStr) -> str:
    return "".join(
        v.value
        for v in node.values
        if isinstance(v, ast.Constant) and isinstance(v.value, str)
    )


def _preceding(node: ast.JoinedStr, idx: int) -> str:
    if idx == 0:
        return ""
    prev = node.values[idx - 1]
    if isinstance(prev, ast.Constant) and isinstance(prev.value, str):
        return prev.value
    return ""


def _quoted_interpolations():
    """Yield (path, lineno, expr) for values interpolated inside a quoted literal
    of something that looks like a Drive query."""
    for directory in SCAN_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.JoinedStr):
                    continue
                if not any(t in _literal_text(node) for t in DRIVE_QUERY_TOKENS):
                    continue
                for i, part in enumerate(node.values):
                    if not isinstance(part, ast.FormattedValue):
                        continue
                    if _preceding(node, i).endswith("'"):
                        rel = path.relative_to(REPO_ROOT)
                        yield str(rel), node.lineno, ast.unparse(part.value)


def test_the_scanner_finds_something():
    """Negative control: an empty census must not pass vacuously.

    Without this, deleting the scan directories or breaking the AST walk would
    make every assertion below trivially true -- the failure mode where a check
    reports zero because it evaluated nothing.
    """
    assert list(_quoted_interpolations()), "scanner found no sites; it is broken"


@pytest.mark.parametrize("path,lineno,expr", list(_quoted_interpolations()))
def test_every_drive_query_interpolation_is_guarded(path, lineno, expr):
    """No unguarded caller value may sit inside a quoted Drive query literal.

    When this fails, do not add the expression to SAFE_EXPRESSIONS to make it
    pass. Either route the value through escape_drive_query_literal() (for free
    text) or validate_drive_id() (for an ID), then add it with the reason.
    """
    assert expr in SAFE_EXPRESSIONS, (
        f"{path}:{lineno} interpolates `{expr}` inside a quoted Drive query "
        f"literal with no recorded guard. Escape it or validate it."
    )


def _quote_only_replaces():
    """Yield sites doing a quote-escape that is NOT preceded by a backslash-escape.

    Matched on the AST, not on text. A textual search cannot tell the defect
    from the fix: the correct implementation
    `.replace("\\\\", "\\\\\\\\").replace("'", "\\\\'")` *contains* the naive form
    as its tail, and a docstring explaining the defect contains it too. Both
    produced false positives on the first attempt at this test.
    """
    for directory in SCAN_DIRS:
        base = REPO_ROOT / directory
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:  # pragma: no cover
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                if not (isinstance(func, ast.Attribute) and func.attr == "replace"):
                    continue
                if len(node.args) != 2:
                    continue
                a, b = node.args
                if not (isinstance(a, ast.Constant) and isinstance(b, ast.Constant)):
                    continue
                if a.value != "'" or b.value != "\\'":
                    continue
                # It IS a quote-escape. Safe only if the receiver is itself a
                # backslash-escape, i.e. .replace("\\", "\\\\").replace("'", "\\'").
                inner = func.value
                safe = (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "replace"
                    and len(inner.args) == 2
                    and isinstance(inner.args[0], ast.Constant)
                    and inner.args[0].value == "\\"
                )
                if not safe:
                    yield f"{path.relative_to(REPO_ROOT)}:{node.lineno}"


def test_no_naive_escape_remains_in_first_party_code():
    """A quote-escape must always be preceded by a backslash-escape.

    The quote-only form leaves a literal backslash untouched, so `x\\'` becomes
    `x\\\\'` -- Drive reads the doubled backslash as one literal backslash and
    the following quote CLOSES the string. Confirmed exploitable against the
    live Drive API, with a control proving a malformed query really does 400.
    """
    offenders = list(_quote_only_replaces())
    assert not offenders, (
        f"quote-only escape (backslash left unescaped) at: {offenders}. "
        f"Use escape_drive_query_literal() instead."
    )


def test_the_naive_escape_detector_actually_detects():
    """Negative control for the test above.

    Without this, the detector could pass by matching nothing at all -- which is
    precisely how the original regex sweep missed a live site for a week.
    """
    source = 'x = value.replace("\'", "\\\\\'")\n'
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert calls, "control source did not parse into a call"
    node = calls[0]
    assert isinstance(node.func, ast.Attribute) and node.func.attr == "replace"
    assert node.args[0].value == "'" and node.args[1].value == "\\'"
    # and its receiver is a plain Name, not a backslash-escaping .replace()
    assert not isinstance(node.func.value, ast.Call)
