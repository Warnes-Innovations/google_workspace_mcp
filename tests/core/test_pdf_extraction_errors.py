"""Tests that extract_pdf_text distinguishes UNREADABLE from EMPTY.

Both used to return None, so a caller could not tell "this PDF is damaged" from
"this PDF is readable but holds no text". They call for different responses: an
image-only PDF is answered with OCR or a download link, a damaged one is not.
Conflating them made get_drive_file_content report a corrupt PDF as
"the file may be scanned/image-only", sending the reader after a problem that
was not there.

Sibling of tests/core/test_office_extraction_errors.py, which covers the same
conflation for Office/OOXML files.
"""

import io

import pytest

from tests.helpers import _make_minimal_pdf
from core.utils import (
    DocumentExtractionError,
    PdfExtractionError,
    extract_pdf_text,
)


def _blank_pdf() -> bytes:
    """A structurally valid PDF whose single page carries no text."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _encrypted_pdf() -> bytes:
    """A valid PDF we are not able to decrypt — readable header, locked pages."""
    from pypdf import PdfReader, PdfWriter

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(_make_minimal_pdf("secret text"))))
    writer.encrypt("a-password-we-do-not-have")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class TestUnreadableRaises:
    def test_not_a_pdf_raises(self):
        with pytest.raises(PdfExtractionError):
            extract_pdf_text(b"this is not a pdf")

    def test_empty_bytes_raises(self):
        with pytest.raises(PdfExtractionError):
            extract_pdf_text(b"")

    def test_truncated_pdf_raises(self):
        good = _make_minimal_pdf("Hello World")
        with pytest.raises(PdfExtractionError):
            extract_pdf_text(good[: len(good) // 2])

    def test_broken_xref_raises(self):
        """The header parses; the cross-reference table does not."""
        good = _make_minimal_pdf("Hello World")
        with pytest.raises(PdfExtractionError):
            extract_pdf_text(good.replace(b"startxref", b"startxrEf"))

    def test_undecryptable_pdf_raises(self):
        """Opening succeeds and reaching the pages fails.

        This is the case the page loop's own handler exists for: a failure that
        arrives AFTER the reader was constructed. Swallowing it would report a
        locked document as an image-only one.
        """
        with pytest.raises(PdfExtractionError):
            extract_pdf_text(_encrypted_pdf())

    def test_message_names_the_size(self):
        """The report should say what it failed to read."""
        with pytest.raises(PdfExtractionError) as excinfo:
            extract_pdf_text(b"this is not a pdf")
        assert "17 bytes" in str(excinfo.value)

    def test_original_cause_is_chained(self):
        """`raise ... from e` keeps the underlying pypdf error for debugging."""
        with pytest.raises(PdfExtractionError) as excinfo:
            extract_pdf_text(b"this is not a pdf")
        assert excinfo.value.__cause__ is not None


class TestExceptionTaxonomy:
    def test_pdf_error_is_a_document_extraction_error(self):
        """A caller that responds the same way to any damaged file can catch
        the shared base instead of enumerating formats."""
        assert issubclass(PdfExtractionError, DocumentExtractionError)

    def test_office_and_pdf_errors_are_distinct_types(self):
        """Reusing the Office-specific type for PDFs would make a caller word
        its report for the wrong format."""
        from core.utils import OfficeXmlExtractionError

        assert not issubclass(PdfExtractionError, OfficeXmlExtractionError)
        assert not issubclass(OfficeXmlExtractionError, PdfExtractionError)
        assert issubclass(OfficeXmlExtractionError, DocumentExtractionError)


class TestReadableButEmptyStillReturnsNone:
    """The whole point of the change: these must NOT become errors.

    A readable PDF with no extractable text is a scanned/image-only document,
    and the caller's scanned/image-only guidance is the right answer for it.
    """

    def test_blank_page_returns_none(self):
        assert extract_pdf_text(_blank_pdf()) is None

    def test_whitespace_only_text_returns_none(self):
        assert extract_pdf_text(_make_minimal_pdf("   ")) is None


class TestSuccessPathUnchanged:
    def test_normal_pdf_still_extracts(self):
        result = extract_pdf_text(_make_minimal_pdf("Hello World"))
        assert result is not None
        assert "Hello World" in result
