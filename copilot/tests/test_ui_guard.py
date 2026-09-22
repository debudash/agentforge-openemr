"""The UI guard has to catch the bug that got past everything else, or it is decoration.

The bug: an element hidden with the `hidden` attribute while carrying a Bootstrap display
utility. The utility's `display` is !important and declared after Reboot's `[hidden]` rule, so
the element stays on screen while `element.hidden` reads true. Every assertion that asks the
page what it is showing agrees with the page; only a browser disagrees.
"""

from pathlib import Path

import pytest

from evals.ui_guard import PAGES, findings_for


def page(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "page.php"
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def test_the_shipped_pages_are_clean():
    assert [f for p in sorted(PAGES.glob("*.php")) for f in findings_for(p)] == []


def test_the_original_bug_is_caught(tmp_path):
    """Exactly what shipped and had to be fixed: an alert laid out with d-flex, hidden by default."""
    found = findings_for(page(tmp_path, '<div class="alert alert-warning d-flex" id="cpa-stale" hidden></div>'))
    assert len(found) == 1
    assert "#cpa-stale" in found[0] and "d-flex" in found[0]


def test_taking_the_hiding_back_in_the_page_stylesheet_is_accepted(tmp_path):
    body = ('<style>.cpa-stale { display: flex; } .cpa-stale[hidden] { display: none; }</style>'
            '<div class="alert cpa-stale d-flex" id="cpa-stale" hidden></div>')
    assert findings_for(page(tmp_path, body)) == []


def test_an_element_hidden_only_from_script_is_checked_too(tmp_path):
    """The attribute need not be in the markup: the clash is the same when JS sets .hidden."""
    body = ('<div class="d-block" id="cpa-panel"></div>'
            '<script>document.getElementById("cpa-panel").hidden = true;</script>')
    found = findings_for(page(tmp_path, body))
    assert len(found) == 1 and "#cpa-panel" in found[0]


@pytest.mark.parametrize("markup", [
    '<div class="card" id="a" hidden></div>',            # .card display is not !important; hidden wins
    '<div class="card-body border-top" id="b" hidden></div>',
    '<div class="alert d-flex" id="c"></div>',           # never hidden, so no clash
])
def test_safe_markup_is_left_alone(tmp_path, markup):
    assert findings_for(page(tmp_path, markup)) == []


def test_responsive_display_utilities_are_caught(tmp_path):
    found = findings_for(page(tmp_path, '<div class="d-md-flex" id="d" hidden></div>'))
    assert len(found) == 1 and "d-md-flex" in found[0]
