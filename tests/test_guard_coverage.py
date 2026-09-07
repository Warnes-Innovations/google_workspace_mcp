"""Meta-tests: a formatter cannot quietly stop routing through the forgery guards.

Why this file exists
--------------------
An AST census of this tree found 72 functions outside ``core/utils.py`` calling
``as_single_line`` / ``sanitize_display_text``, of which the behavioural tests in
``tests/test_result_row_forgery.py`` exercised 18. That gap was not theoretical:
deleting the guard at ``gtasks/tasks_tools.py`` or ``gsheets/sheets_helpers.py``
each SURVIVED the full suite. A guard nothing can observe being removed is
decoration.

Why a census and not a list of sites
------------------------------------
The obvious fix -- a hand-maintained list of "places that need the guard" --
drifts in exactly the way the bug does. It is written once against the tree as
it stands, nothing forces it to be revisited, and the formatter added next month
is missing from it for the same reason it is missing the guard. So the golden
data here is *derived mechanically from the source* and asserted whole:

  * :func:`census` walks the AST and counts guard calls per function.
  * ``GOLDEN_CENSUS`` is the committed answer.

Adding, removing or moving a guard call changes the census and fails the test.
The only way to make it pass again is to regenerate the golden data, which makes
the change a deliberate, reviewable decision rather than a silent one. That is
the property being bought -- not "the guard is present", which no static check
can establish, but "nobody changed the guards without saying so".

:func:`test_no_formatter_sanitizes_fields_without_guarding_the_line` is the one
that speaks to the original bug class directly: a function that flattens
individual fields but never guards the assembled line is precisely the shape
that let roughly seven formatters through. That set is pinned to a short list of
genuine FIELD helpers -- functions that return one field for a caller to place
in a row, where a line-level guard would be meaningless.

Both are structural. Neither replaces the behavioural forgery tests; they exist
so that a formatter added later cannot pass silently.
"""

import ast
from pathlib import Path

import pytest

GUARDS = {"as_single_line", "sanitize_display_text"}

# gdrive/ is deliberately absent: on this branch it carries no guard call sites
# at all. See the NOTE in core/utils.py.
PACKAGES = (
    "core",
    "gappsscript",
    "gcalendar",
    "gchat",
    "gcontacts",
    "gdocs",
    "gforms",
    "gmail",
    "gsearch",
    "gsheets",
    "gslides",
    "gtasks",
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _source_files():
    for package in PACKAGES:
        directory = REPO_ROOT / package
        assert directory.is_dir(), f"package {package} vanished; update PACKAGES"
        for path in sorted(directory.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


def _functions(tree):
    """Map dotted qualname -> function node, for every def in the module."""
    found = {}

    def walk(node, stack):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = stack + [child.name]
                found[".".join(qualname)] = child
                walk(child, qualname)
            elif isinstance(child, ast.ClassDef):
                walk(child, stack + [child.name])
            else:
                walk(child, stack)

    walk(tree, [])
    return found


def _guard_calls(fn):
    """Count guard calls in fn's OWN body, not in functions nested inside it.

    Nested functions are counted against their own qualname instead, so moving
    a guard into or out of a closure is a visible change rather than a wash.
    """
    counts = {}

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if isinstance(child, ast.Call):
                name = getattr(child.func, "id", None) or getattr(
                    child.func, "attr", None
                )
                if name in GUARDS:
                    counts[name] = counts.get(name, 0) + 1
            walk(child)

    walk(fn)
    return counts


def census():
    """file::qualname -> {guard_name: call_count} for every guard-calling function."""
    result = {}
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for qualname, fn in _functions(tree).items():
            counts = _guard_calls(fn)
            if counts:
                result[f"{path.relative_to(REPO_ROOT).as_posix()}::{qualname}"] = counts
    return result


# Functions that return a single FIELD for a caller to place into a row, rather
# than a row of their own. A line-level guard on a field is meaningless -- the
# row it lands in carries that guard -- so these are expected to call only
# `sanitize_display_text`. Anything else appearing here is a formatter that
# flattens its fields and forgets its line, which is the exact defect this file
# was written for.
FIELD_HELPERS = {
    "core/utils.py::as_single_line",
    "gcalendar/calendar_helpers.py::_format_event_time",
    "gcalendar/calendar_helpers.py::_format_person",
    "gcalendar/calendar_helpers.py::_get_meeting_link",
    "gchat/chat_tools.py::_extract_rich_links",
    "gchat/chat_tools.py::_resolve_sender",
    "gdocs/docs_tools.py::get_doc_content.extract_text_from_elements",
    "gmail/gmail_tools.py::_extract_attachments.search_parts",
}


def test_no_formatter_sanitizes_fields_without_guarding_the_line():
    """The M2 bug class, pinned.

    `sanitize_display_text` on a field is defense in depth; `as_single_line` on
    the assembled row is the load-bearing guard. A function doing the first and
    not the second is the shape that let roughly seven formatters through -- it
    reads as guarded, and its own docstring's promise ("one record stays one
    line") does not hold for any field nobody thought to list.
    """
    per_field_only = {
        key
        for key, counts in census().items()
        if set(counts) == {"sanitize_display_text"}
    }
    unexpected = sorted(per_field_only - FIELD_HELPERS)
    assert not unexpected, (
        "These flatten individual fields but never guard the assembled line.\n"
        "Either wrap the returned row(s) in as_single_line(), or -- if the "
        "function really does return one FIELD rather than a row -- add it to "
        "FIELD_HELPERS with a reason:\n  " + "\n  ".join(unexpected)
    )
    vanished = sorted(FIELD_HELPERS - per_field_only)
    assert not vanished, (
        "FIELD_HELPERS names functions that no longer match. If one gained a "
        "line-level guard or was renamed, drop it from the set:\n  "
        + "\n  ".join(vanished)
    )


def test_guard_census_matches_the_committed_golden_data():
    """Every guard call site in the tree, counted and pinned.

    Counts rather than presence, deliberately: several functions call
    `as_single_line` more than once, so a set-membership check would not notice
    one of them being deleted -- which is the mutation that survived the suite
    and prompted this file.

    When this fails, read the diff it prints. A deletion is a guard someone
    removed; an addition is a formatter someone guarded. Both are fine, and both
    should be seen. Regenerate GOLDEN_CENSUS only once the change is intended.
    """
    actual = census()
    missing = {k: v for k, v in GOLDEN_CENSUS.items() if k not in actual}
    added = {k: v for k, v in actual.items() if k not in GOLDEN_CENSUS}
    changed = {
        k: (GOLDEN_CENSUS[k], actual[k])
        for k in set(actual) & set(GOLDEN_CENSUS)
        if actual[k] != GOLDEN_CENSUS[k]
    }
    assert not (missing or added or changed), (
        f"guard census drifted from the golden data.\n"
        f"  gone (guard removed, or function renamed/deleted): {sorted(missing)}\n"
        f"  new (formatter guarded, or function added):        {sorted(added)}\n"
        f"  count changed (golden -> actual):                  {changed}"
    )


def test_the_census_can_actually_see_a_guard():
    """Negative control: the analyzer must detect a guard, and its absence.

    Without this, a census that silently returned {} for everything would make
    both tests above pass vacuously -- the "guard that has never been shown to
    fire" failure, one level up.
    """
    guarded = ast.parse(
        "def f(x):\n    return as_single_line(f'a {x}')\n",
    )
    unguarded = ast.parse("def f(x):\n    return f'a {x}'\n")
    assert _guard_calls(_functions(guarded)["f"]) == {"as_single_line": 1}
    assert _guard_calls(_functions(unguarded)["f"]) == {}

    twice = ast.parse(
        "def f(x):\n"
        "    a = as_single_line(f'a {x}')\n"
        "    b = as_single_line(f'b {x}')\n"
        "    return a + b\n"
    )
    assert _guard_calls(_functions(twice)["f"]) == {"as_single_line": 2}, (
        "the census must COUNT, not just detect -- a presence-only check cannot "
        "see one of two guard calls being deleted"
    )


def test_the_census_is_not_empty():
    """Second half of the negative control, against the real tree."""
    actual = census()
    assert len(actual) > 50, f"census collapsed to {len(actual)} entries"
    assert any(k.startswith("core/comments.py::") for k in actual)


@pytest.mark.parametrize("package", PACKAGES)
def test_every_declared_package_is_scanned(package):
    """A package renamed out from under PACKAGES would silently stop being checked."""
    assert (REPO_ROOT / package).is_dir()


# Generated by walking the AST of every package above; regenerate deliberately
# when a guard is added or removed, never to make a red test go green.
GOLDEN_CENSUS = {
    "core/comments.py::_create_comment_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "core/comments.py::_read_comments_impl": {"as_single_line": 1},
    "core/comments.py::_reply_to_comment_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "core/comments.py::_resolve_comment_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "core/utils.py::as_single_line": {"sanitize_display_text": 1},
    "gappsscript/apps_script_tools.py::_join_result_lines": {"as_single_line": 1},
    "gcalendar/calendar_helpers.py::EventBoundary.render": {"as_single_line": 1},
    "gcalendar/calendar_helpers.py::_format_attachment_details": {"as_single_line": 4},
    "gcalendar/calendar_helpers.py::_format_attendee_details": {"as_single_line": 1},
    "gcalendar/calendar_helpers.py::_format_event_detail_lines.add": {
        "as_single_line": 1
    },
    "gcalendar/calendar_helpers.py::_format_event_time": {"sanitize_display_text": 1},
    "gcalendar/calendar_helpers.py::_format_person": {"sanitize_display_text": 2},
    "gcalendar/calendar_helpers.py::_get_meeting_link": {"sanitize_display_text": 2},
    "gcalendar/calendar_tools.py::_create_event_impl": {"as_single_line": 1},
    "gcalendar/calendar_tools.py::_list_focus_time_events_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 2,
    },
    "gcalendar/calendar_tools.py::_list_ooo_events_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 2,
    },
    "gcalendar/calendar_tools.py::_modify_event_impl": {"as_single_line": 1},
    "gcalendar/calendar_tools.py::_rsvp_event_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gcalendar/calendar_tools.py::_update_focus_time_event_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gcalendar/calendar_tools.py::_update_ooo_event_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gcalendar/calendar_tools.py::create_calendar": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gcalendar/calendar_tools.py::get_events": {
        "as_single_line": 7,
        "sanitize_display_text": 2,
    },
    "gcalendar/calendar_tools.py::list_calendars": {"as_single_line": 1},
    "gchat/chat_tools.py::_extract_rich_links": {"sanitize_display_text": 1},
    "gchat/chat_tools.py::_resolve_sender": {"sanitize_display_text": 3},
    "gchat/chat_tools.py::download_chat_attachment": {
        "as_single_line": 6,
        "sanitize_display_text": 2,
    },
    "gchat/chat_tools.py::get_messages": {
        "as_single_line": 4,
        "sanitize_display_text": 1,
    },
    "gchat/chat_tools.py::list_spaces": {"as_single_line": 1},
    "gchat/chat_tools.py::search_messages": {"as_single_line": 1},
    "gcontacts/contacts_helpers.py::_format_contact": {"as_single_line": 1},
    "gcontacts/contacts_tools.py::get_contact_group": {
        "as_single_line": 6,
        "sanitize_display_text": 1,
    },
    "gcontacts/contacts_tools.py::list_contact_groups": {
        "as_single_line": 5,
        "sanitize_display_text": 1,
    },
    "gcontacts/contacts_tools.py::manage_contact_group": {
        "as_single_line": 5,
        "sanitize_display_text": 2,
    },
    "gdocs/docs_markdown.py::_format_footnote": {"as_single_line": 1},
    "gdocs/docs_markdown.py::format_comments_appendix": {"as_single_line": 1},
    "gdocs/docs_tools.py::export_doc_to_pdf": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gdocs/docs_tools.py::get_doc_content": {"as_single_line": 2},
    "gdocs/docs_tools.py::get_doc_content.extract_text_from_elements": {
        "sanitize_display_text": 1
    },
    "gdocs/docs_tools.py::insert_doc_image": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gdocs/docs_tools.py::list_docs_in_folder": {"as_single_line": 1},
    "gdocs/docs_tools.py::search_docs": {"as_single_line": 1},
    "gforms/forms_tools.py::get_form": {
        "as_single_line": 2,
        "sanitize_display_text": 3,
    },
    "gforms/forms_tools.py::get_form_response": {"as_single_line": 2},
    "gmail/gmail_tools.py::_export_full_message": {"as_single_line": 1},
    "gmail/gmail_tools.py::_extract_attachments.search_parts": {
        "sanitize_display_text": 2
    },
    "gmail/gmail_tools.py::_format_gmail_results_plain": {"as_single_line": 1},
    "gmail/gmail_tools.py::_format_message_header_lines": {"as_single_line": 1},
    "gmail/gmail_tools.py::_format_thread_content": {
        "as_single_line": 9,
        "sanitize_display_text": 10,
    },
    "gmail/gmail_tools.py::list_gmail_filters": {"as_single_line": 2},
    "gmail/gmail_tools.py::list_gmail_labels": {
        "as_single_line": 2,
        "sanitize_display_text": 1,
    },
    "gsearch/search_tools.py::search_custom": {
        "as_single_line": 5,
        "sanitize_display_text": 3,
    },
    "gsheets/sheets_helpers.py::_format_conditional_rules_section": {
        "as_single_line": 3
    },
    "gsheets/sheets_helpers.py::_format_sheet_error_section": {"as_single_line": 5},
    "gsheets/sheets_helpers.py::_format_sheet_formula_section": {"as_single_line": 2},
    "gsheets/sheets_helpers.py::_format_sheet_hyperlink_section": {"as_single_line": 2},
    "gsheets/sheets_helpers.py::_format_sheet_notes_section": {"as_single_line": 2},
    "gsheets/sheets_helpers.py::_summarize_conditional_rule": {"as_single_line": 3},
    "gsheets/sheets_tools.py::create_sheet": {
        "as_single_line": 2,
        "sanitize_display_text": 1,
    },
    "gsheets/sheets_tools.py::get_spreadsheet_info": {"as_single_line": 2},
    "gsheets/sheets_tools.py::list_sheet_tables": {
        "as_single_line": 5,
        "sanitize_display_text": 1,
    },
    "gsheets/sheets_tools.py::list_spreadsheets": {"as_single_line": 1},
    "gsheets/sheets_tools.py::manage_conditional_formatting": {
        "as_single_line": 3,
        "sanitize_display_text": 3,
    },
    "gsheets/sheets_tools.py::modify_sheet_values": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gslides/slides_tools.py::_describe_elements": {"as_single_line": 1},
    "gslides/slides_tools.py::_describe_speaker_notes": {"as_single_line": 1},
    "gslides/slides_tools.py::get_presentation": {
        "as_single_line": 3,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::_create_task_impl": {
        "as_single_line": 2,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::_create_task_list_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::_move_task_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::_update_task_impl": {
        "as_single_line": 2,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::_update_task_list_impl": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::get_task": {
        "as_single_line": 2,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::get_task_list": {
        "as_single_line": 1,
        "sanitize_display_text": 1,
    },
    "gtasks/tasks_tools.py::list_task_lists": {"as_single_line": 1},
    "gtasks/tasks_tools.py::serialize_tasks": {"as_single_line": 2},
}
