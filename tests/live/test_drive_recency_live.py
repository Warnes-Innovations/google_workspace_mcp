"""Does Drive actually understand the orderBy keys list_recent_files sends?

Every other test for `resolve_recency_order_by` is against a mock, so it proves
we send the string we meant to send and says nothing about whether Google
accepts it or sorts by it. Those are different questions, and only the second
one is what the tool promises its caller.

Read-only: `files.list` with a minimal field mask. Nothing here writes.
"""

import pytest
from googleapiclient.errors import HttpError

from gdrive.drive_helpers import RECENCY_ORDER_BY_MAP, resolve_recency_order_by

# The distinct Drive sort keys behind the friendly aliases. Derived from the map
# rather than restated, so a key added there is exercised here automatically --
# a hand-copied list is the thing that silently stops covering new entries.
DRIVE_SORT_KEYS = sorted(set(RECENCY_ORDER_BY_MAP.values()))

# Keys whose timestamp Drive does NOT return in a files.list response, so the
# ordering cannot be checked from the result -- acceptance is all we can assert.
NOT_SELF_DESCRIBING = {
    "recency",
    "modifiedByMeTime",
    "viewedByMeTime",
    "sharedWithMeTime",
}


@pytest.mark.parametrize("sort_key", DRIVE_SORT_KEYS)
def test_drive_accepts_every_order_by_we_send(live_drive_service, sort_key):
    """Each mapped key is a real Drive sort key, not a plausible-looking typo."""
    try:
        live_drive_service.files().list(
            orderBy=f"{sort_key} desc", pageSize=1, fields="files(id)"
        ).execute()
    except HttpError as exc:
        pytest.fail(
            f"Drive rejected orderBy={sort_key!r} with HTTP {exc.resp.status}. "
            "RECENCY_ORDER_BY_MAP points at a key the API does not know."
        )


def test_drive_rejects_an_unknown_order_by(live_drive_service):
    """THE CONTROL, and the test above is worthless without it.

    If Drive silently ignored an unrecognised orderBy, every 'accepted' result
    would prove only that the request was well-formed. It does not: an unknown
    key is a 400. This also pins that the API is case-SENSITIVE, which is how a
    lowercase transcription of a camelCase key would slip through review.
    """
    for bogus in ("notARealSortKey", "modifiedtime"):
        with pytest.raises(HttpError) as caught:
            live_drive_service.files().list(
                orderBy=f"{bogus} desc", pageSize=1, fields="files(id)"
            ).execute()
        assert caught.value.resp.status == 400, (
            f"expected 400 for orderBy={bogus!r}, got {caught.value.resp.status}"
        )


@pytest.mark.parametrize(
    "sort_key,time_field",
    [("modifiedTime", "modifiedTime"), ("createdTime", "createdTime")],
)
def test_results_are_actually_descending(live_drive_service, sort_key, time_field):
    """Acceptance is not application: assert the rows really come back sorted.

    Only possible for the two keys Drive will return as a field. The other four
    are covered by acceptance alone -- see NOT_SELF_DESCRIBING, and note the
    tool's own docstring already warns that Drive may ignore the sort for
    accounts with very large file counts.
    """
    resp = (
        live_drive_service.files()
        .list(
            orderBy=f"{sort_key} desc",
            pageSize=10,
            fields=f"files(id,{time_field})",
        )
        .execute()
    )
    stamps = [f[time_field] for f in resp.get("files", []) if time_field in f]
    if len(stamps) < 2:
        pytest.skip(f"need 2+ files carrying {time_field} to check ordering")
    assert stamps == sorted(stamps, reverse=True), (
        f"orderBy={sort_key} desc did not come back descending: {stamps}"
    )


def test_every_sort_key_is_classified():
    """NOT_SELF_DESCRIBING is a claim about coverage, so it has to be enforced.

    Left as a bare comment it would rot: someone adds a key to
    RECENCY_ORDER_BY_MAP, the acceptance test picks it up automatically, and it
    quietly joins neither the ordering-checked set nor the documented
    can't-check set. This fails until the new key is deliberately put in one.
    """
    ordering_checked = {"modifiedTime", "createdTime"}
    classified = ordering_checked | NOT_SELF_DESCRIBING
    unclassified = set(DRIVE_SORT_KEYS) - classified
    assert not unclassified, (
        f"new Drive sort key(s) {sorted(unclassified)}: decide whether the "
        "ordering can be verified from the response, and add to "
        "ordering_checked or NOT_SELF_DESCRIBING"
    )
    assert not (ordering_checked & NOT_SELF_DESCRIBING)


def test_every_alias_resolves_to_a_key_this_module_exercises():
    """Guards the derivation above: if resolve_recency_order_by ever returns
    something outside the map's values, the live coverage silently has a hole."""
    for alias in RECENCY_ORDER_BY_MAP:
        resolved = resolve_recency_order_by(alias)
        assert resolved.endswith(" desc"), resolved
        assert resolved[: -len(" desc")] in DRIVE_SORT_KEYS, resolved
