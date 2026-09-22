"""Click-to-source (Week 2 stage 9): render one page of a stored document and locate quotes on it.

A citation into a document carries a page and a quote. This turns that into something a clinician
can see: the page as an image, and a box around the quote, found in the PDF's own text layer. A
quote that is not on the page gets `found: false`, and the UI highlights the page rather than draw
a box it cannot justify. Nothing here involves a model: a box is either where the text is, or absent.
"""

from __future__ import annotations

import io
import re
from typing import Any

from .extract import page_images


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def locate(pdf_bytes: bytes, page_number: int, quotes: list[str]) -> dict[str, Any]:
    """Boxes for each quote on the page, normalised to 0-1 with the origin at the top left.

    Returns {"page", "pages", "width", "height", "boxes": [{"quote", "found", "bbox"}]}.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    try:
        pages = len(pdf)
        if not 1 <= page_number <= pages:
            raise ValueError(f"page {page_number} of {pages}")
        page = pdf[page_number - 1]
        width, height = page.get_size()
        textpage = page.get_textpage()
        boxes: list[dict[str, Any]] = []
        for quote in quotes:
            needle = _collapse(quote)
            hit = textpage.search(needle, match_case=False).get_next() if needle else None
            if not hit:
                boxes.append({"quote": quote, "found": False, "bbox": None})
                continue
            start, count = hit
            rects = [textpage.get_charbox(i) for i in range(start, start + count)]
            rects = [r for r in rects if r[2] > r[0] and r[3] > r[1]]   # skip zero-width (spaces)
            if not rects:
                boxes.append({"quote": quote, "found": False, "bbox": None})
                continue
            x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
            x1, y1 = max(r[2] for r in rects), max(r[3] for r in rects)
            boxes.append({"quote": quote, "found": True,
                          "bbox": [round(x0 / width, 4), round(1 - y1 / height, 4), round(x1 / width, 4), round(1 - y0 / height, 4)]})
        page.close()
        return {"page": page_number, "pages": pages, "width": width, "height": height, "boxes": boxes}
    finally:
        pdf.close()


def render(pdf_bytes: bytes, page_number: int, scale: float = 1.5) -> bytes:
    """One page as PNG. Renders only the pages up to the one asked for, so page 1 stays cheap."""
    images = page_images(pdf_bytes, max_pages=page_number, scale=scale)
    if len(images) < page_number:
        raise ValueError(f"page {page_number} of {len(images)}")
    return images[page_number - 1]
