"""Office extraction must not claim a non-Office file is damaged.

`extract_office_xml_text` opens the payload as a ZIP before it dispatches on
MIME type, so before this fix it raised `OfficeXmlExtractionError` for every
non-Office input -- text/plain, CSV, JSON, PDF. That matters because
`get_doc_content` uses the raised/None distinction to choose a branch:

    try:
        office_text = extract_office_xml_text(file_content_bytes, mime_type)
    except OfficeXmlExtractionError as e:
        unreadable = "[Could not read ... it appears damaged ...]"
    if office_text:      ...
    elif unreadable:     ...        <- taken for a perfectly readable .txt
    else:                body_text = file_content_bytes.decode("utf-8")

A readable text file therefore reported itself as damaged and its content was
never decoded, because the UTF-8 fallback sits in the branch the exception
skipped.

The regression was introduced by the change that made damaged Office files
raise instead of returning None -- the fix for one conflation created another,
in the opposite direction. Reported by an automated reviewer on PR #1101 and
confirmed by running it.

These tests pin BOTH directions, so a future change cannot restore one
conflation while removing the other.
"""

import zipfile
import io

import pytest

from core.utils import OfficeXmlExtractionError, extract_office_xml_text

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


@pytest.mark.parametrize(
    "mime_type, payload",
    [
        ("text/plain", b"hello world, plain text\n"),
        ("text/csv", b"a,b,c\n1,2,3\n"),
        ("text/markdown", b"# heading\n\nbody\n"),
        ("application/json", b'{"key": "value"}'),
        ("application/pdf", b"%PDF-1.4 this is not a zip"),
        ("application/octet-stream", b"\x00\x01\x02\x03"),
        ("", b"no mime type at all"),
    ],
)
def test_non_office_mime_returns_none_rather_than_raising(mime_type, payload):
    """None is the caller's signal to fall through to its own decoding.

    Raising here is not a harmless over-report: the caller's UTF-8 fallback
    lives in the branch an exception skips, so a raise does not merely mislabel
    the file, it discards the content entirely.
    """
    assert extract_office_xml_text(payload, mime_type) is None


@pytest.mark.parametrize("mime_type", [DOCX, XLSX, PPTX])
def test_damaged_office_file_still_raises(mime_type):
    """The property the original change existed for, still holding.

    Without this, a fix aimed at the regression above could simply stop raising
    altogether and every test in the non-Office set would still pass.
    """
    with pytest.raises(OfficeXmlExtractionError):
        extract_office_xml_text(b"this is definitely not a zip archive", mime_type)


@pytest.mark.parametrize("mime_type", [DOCX, XLSX, PPTX])
def test_readable_office_file_with_no_text_still_returns_none(mime_type):
    """The other half of the original distinction: readable but empty."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("docProps/app.xml", "<Properties/>")

    assert extract_office_xml_text(buffer.getvalue(), mime_type) is None
