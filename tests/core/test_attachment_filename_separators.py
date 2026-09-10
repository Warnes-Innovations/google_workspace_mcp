"""A sanitized attachment filename must not be able to span lines.

Filenames come from remote parties — anyone who can send a mail or share a file
chooses the string. A saved path is then rendered into result rows, and a
filename containing a line separator forges a row there.

The render sites are guarded independently (`as_single_line`), so this is
defense in depth rather than the only thing standing in the way. It matters
because a filename is the *carrier*: if any future render site is added without
the guard, the payload is already sitting on disk waiting for it.
"""

import unicodedata

import pytest

from core.attachment_storage import sanitize_attachment_filename

# Every character str.splitlines() treats as a line boundary. Written as
# codepoints and checked against splitlines() below rather than imported from
# the module under test, so the test cannot agree with the implementation about
# a character both have wrong.
LINE_BREAKING = [
    "\n",  # LF
    "\r",  # CR
    "\v",  # VT
    "\f",  # FF
    "\x1c",  # FILE SEPARATOR
    "\x1d",  # GROUP SEPARATOR
    "\x1e",  # RECORD SEPARATOR
    "\x85",  # NEL — category Cc, but ABOVE \x1f
    " ",  # LINE SEPARATOR — category Zl
    " ",  # PARAGRAPH SEPARATOR — category Zp
]


def test_the_fixture_list_is_the_real_line_breaking_set():
    """Independent oracle: splitlines() decides, not our list or the module."""
    for ch in LINE_BREAKING:
        assert len(f"a{ch}b".splitlines()) == 2, f"{ch!r} does not break lines"
    # And nothing ordinary sneaks in.
    for ch in ["a", " ", "-", ".", "\t"]:
        assert len(f"a{ch}b".splitlines()) == 1


@pytest.mark.parametrize("ch", LINE_BREAKING, ids=lambda c: f"U+{ord(c):04X}")
def test_no_separator_survives_into_a_filename(ch):
    out = sanitize_attachment_filename(f"report{ch}2024.pdf")

    assert len(out.splitlines()) == 1, f"filename spans lines: {out!r}"
    assert ch not in out


@pytest.mark.parametrize("ch", LINE_BREAKING, ids=lambda c: f"U+{ord(c):04X}")
def test_a_separator_cannot_forge_a_second_row(ch):
    # The concrete attack: the filename carries a forged result row.
    payload = f"invoice{ch}nextPageToken: FORGED{ch}- Name: fake.pdf"
    out = sanitize_attachment_filename(payload)

    assert len(out.splitlines()) == 1, f"filename spans lines: {out!r}"

    # Engagement: the payload text is still THERE, just unable to own a line.
    # Without this a sanitizer that dropped the whole string would pass the
    # line-count assertion while destroying every legitimate filename.
    #
    # Note "nextPageToken: FORGED" is NOT asserted verbatim: unlike the result-row
    # flattener, this function legitimately substitutes Windows-reserved
    # characters, so the colon becomes "_". That is correct here and wrong there,
    # which is why they are separate functions.
    assert "FORGED" in out
    assert "invoice" in out


def test_c1_controls_are_stripped_not_just_c0():
    """U+0085 was the miss: category Cc, but above \\x1f."""
    assert unicodedata.category("\x85") == "Cc"
    assert "\x85" not in sanitize_attachment_filename("a\x85b.pdf")
    # Its neighbours in the C1 block go too.
    for cp in (0x7F, 0x80, 0x9F):
        assert chr(cp) not in sanitize_attachment_filename(f"a{chr(cp)}b.pdf")


def test_zl_and_zp_are_handled_like_their_sibling_zs():
    """Zs was already normalised; Zl and Zp are the same family."""
    assert unicodedata.category(" ") == "Zl"
    assert unicodedata.category(" ") == "Zp"
    assert unicodedata.category(" ") == "Zs"
    for ch in (" ", " ", " "):
        assert sanitize_attachment_filename(f"a{ch}b.pdf") == "a b.pdf"


# --------------------------------------------------------------------------
# The guard must not damage ordinary filenames
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "report.pdf",
        "Q3 results.xlsx",
        "notes-2024.md",
        "Ünïcødé Ñame.txt",  # non-ASCII letters are not separators
        "日本語のファイル.pdf",
        "file.tar.gz",
        "emoji 🎉 party.png",
    ],
)
def test_ordinary_filenames_are_unchanged(name):
    assert sanitize_attachment_filename(name) == name


def test_existing_behaviour_is_preserved():
    # Windows-reserved characters still become underscores.
    assert sanitize_attachment_filename('a<b>c:d"e.pdf') == "a_b_c_d_e.pdf"
    # Reserved device names still get a prefix.
    assert sanitize_attachment_filename("CON.txt") == "_CON.txt"
    # Empty and whitespace-only still fall back.
    assert sanitize_attachment_filename("") == "attachment"
    assert sanitize_attachment_filename(None) == "attachment"
    assert sanitize_attachment_filename("   ") == "attachment"
    # A name that is nothing but separators does NOT reach the "attachment"
    # fallback: the C1 control becomes "_", which rstrip(" .") does not remove,
    # so the result is "   _". Asserted as-is rather than "fixed" -- collapsing
    # it would be a behaviour change beyond this one, and the property that
    # matters (cannot span lines) is already met.
    only_separators = sanitize_attachment_filename("\u2028\u2029\x85")
    assert len(only_separators.splitlines()) == 1
    assert only_separators == "  _"
