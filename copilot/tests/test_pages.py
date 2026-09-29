"""Click-to-source: quotes are located in the text layer, or reported as not found; never invented."""

from pathlib import Path

import pytest

from copilot.documents.pages import locate, render

DOCS = Path(__file__).resolve().parent.parent / "evals" / "stage2" / "fixtures" / "documents"
LAB = (DOCS / "metro-labs-jane-doe.pdf").read_bytes()
SCAN = (DOCS / "scan-blank.pdf").read_bytes()


def test_a_quote_on_the_page_gets_a_box_inside_the_page():
    out = locate(LAB, 1, ["Potassium", "Sodium                  140         mmol/L", "5.4"])
    assert out["pages"] == 2 and out["page"] == 1
    for box in out["boxes"]:
        assert box["found"], box
        x0, y0, x1, y1 = box["bbox"]
        assert 0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1
    potassium, sodium = out["boxes"][0]["bbox"], out["boxes"][1]["bbox"]
    assert potassium[1] < sodium[1], "Potassium is printed above Sodium"


def test_a_quote_not_on_the_page_is_not_found():
    out = locate(LAB, 1, ["Hemoglobin A1c", "Potassium 5.9"])
    assert [b["found"] for b in out["boxes"]] == [False, False]
    assert locate(LAB, 2, ["Hemoglobin A1c"])["boxes"][0]["found"] is True


def test_a_scan_with_no_text_layer_finds_nothing_rather_than_guessing():
    out = locate(SCAN, 1, ["Potassium"])
    assert out["boxes"] == [{"quote": "Potassium", "found": False, "bbox": None}]


def test_a_page_the_document_lacks_is_an_error():
    with pytest.raises(ValueError):
        locate(LAB, 3, ["x"])
    with pytest.raises(ValueError):
        render(LAB, 3)


def test_render_returns_a_png_for_the_requested_page():
    png = render(LAB, 2, scale=1.0)
    assert png[:8] == b"\x89PNG\r\n\x1a\n" and len(png) > 1000
