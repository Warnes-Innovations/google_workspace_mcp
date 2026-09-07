"""Shared test helpers."""

import asyncio
import io
import threading
import warnings


def own_thread_sleep(record=None):
    """Build an ``asyncio.sleep`` replacement scoped to the calling thread.

    ``monkeypatch.setattr("asyncio.sleep", ...)`` -- and equally
    ``monkeypatch.setattr("some.module.asyncio.sleep", ...)``, which resolves to
    the very same attribute -- replaces ONE module attribute shared by every
    event loop in the process, not just the loop under test. If any background
    loop is alive (a uvicorn server left serving in a daemon thread, say), its
    own ``await asyncio.sleep(...)`` lands in the replacement too. Recording
    those delays corrupts the assertion, and returning without awaiting turns
    that loop's poll into a busy spin (measured on this suite: >500,000 stray
    calls in 0.5s -- see commit bcda13e).

    So: record and short-circuit only for the thread that installed this, and
    hand every other caller the genuine ``asyncio.sleep``.
    """
    owner = threading.get_ident()
    real_sleep = asyncio.sleep

    async def _sleep(delay):
        if threading.get_ident() != owner:
            return await real_sleep(delay)
        if record is not None:
            record.append(delay)

    return _sleep


def own_thread_to_thread(replacement):
    """Scope an ``asyncio.to_thread`` *replacement* to the calling thread.

    Same hazard as :func:`own_thread_sleep`: ``some.module.asyncio.to_thread``
    is not a module-local name, it is the asyncio module's own global
    attribute, so a stand-in installed by one test is what *every* live event
    loop in the process resolves. A foreign loop's ``await
    asyncio.to_thread(fn)`` then runs ``fn`` inline on that loop's thread
    instead of in a worker -- blocking it -- and, where the stand-in records
    concurrency, silently inflates what the installing test measures.

    Delegate to the genuine ``asyncio.to_thread`` for every caller except the
    thread that installed this.
    """
    owner = threading.get_ident()
    real_to_thread = asyncio.to_thread

    async def _to_thread(fn, *args, **kwargs):
        if threading.get_ident() != owner:
            return await real_to_thread(fn, *args, **kwargs)
        return await replacement(fn, *args, **kwargs)

    return _to_thread


def _make_minimal_pdf(text: str = "Hello World") -> bytes:
    """Build a tiny valid PDF with one page containing *text* using pypdf."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        DictionaryObject,
        DecodedStreamObject,
        NameObject,
    )

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)

    page = writer.pages[0]
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode())

    font_dict = DictionaryObject()
    font_dict[NameObject("/Type")] = NameObject("/Font")
    font_dict[NameObject("/Subtype")] = NameObject("/Type1")
    font_dict[NameObject("/BaseFont")] = NameObject("/Helvetica")

    font_res = DictionaryObject()
    font_res[NameObject("/F1")] = font_dict

    resources = DictionaryObject()
    resources[NameObject("/Font")] = font_res

    add_object = getattr(writer, "add_object", None)
    if add_object is None:
        warnings.warn(
            "PdfWriter.add_object() is unavailable; falling back to private "
            "PdfWriter._add_object() in test helper.",
            stacklevel=2,
        )
        add_object = writer._add_object

    page[NameObject("/Resources")] = resources
    page[NameObject("/Contents")] = add_object(stream)

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
