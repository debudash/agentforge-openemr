"""A guard for one class of UI bug the rest of the suite cannot see.

The module's pages show and hide things with the `hidden` attribute, from markup and from JS.
Bootstrap's Reboot backs that with `[hidden] { display: none !important }` (bootstrap.css line
352), so `hidden` beats an ordinary component class like `.card`, whose `display: flex` carries
no `!important`. It does not beat the display utilities: `.d-flex` (line 7028) is *also*
`!important` and has the same specificity, so the later rule wins and the element stays visible
while `element.hidden` reads true. Everything that asks the page what it is showing then agrees
with the page, and the clinician sees otherwise.

That is a source-order accident, not something a reviewer reliably spots, so it is checked here:
an element that is hidden anywhere, in markup or by script, must not carry a `d-*` display
utility unless its own stylesheet takes the hiding back with a rule of higher specificity.

Deterministic, no browser, no network. Run: python -m evals.ui_guard
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PAGES = Path(__file__).resolve().parents[2] / "interface" / "modules" / "custom_modules" \
    / "oe-module-copilot-agent" / "public"

# The Bootstrap 4 utilities that declare `display` with !important after Reboot's [hidden] rule.
# Shape and names taken from the shipped bootstrap.css: `d-{value}` and `d-{breakpoint}-{value}`.
DISPLAY_UTILITY = re.compile(
    r"d-(?:(?:sm|md|lg|xl|print)-)?"
    r"(?:none|inline|inline-block|block|table|table-row|table-cell|flex|inline-flex)"
)
ELEMENT = re.compile(r"<(?P<tag>[a-z]+)(?P<attrs>[^>]*)\bid=\"(?P<id>[^\"]+)\"(?P<rest>[^>]*)>")
HIDDEN_IN_MARKUP = re.compile(r"(?:^|\s)hidden(?:=|\s|$)")
HIDDEN_BY_SCRIPT = re.compile(r"getElementById\(\"(?P<id>[^\"]+)\"\)[^;\n]*?\.hidden\s*=")
# A page may take the hiding back itself, e.g. `.cpa-stale[hidden] { display: none; }`.
OWN_OVERRIDE = re.compile(r"\.(?P<cls>[a-zA-Z0-9_-]+)\[hidden\]\s*\{[^}]*display\s*:\s*none")


def classes_of(attrs: str) -> set[str]:
    match = re.search(r"class=\"([^\"]*)\"", attrs)
    return set(match.group(1).split()) if match else set()


def findings_for(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    protected = {m.group("cls") for m in OWN_OVERRIDE.finditer(text)}
    toggled_by_script = {m.group("id") for m in HIDDEN_BY_SCRIPT.finditer(text)}

    found: list[str] = []
    for element in ELEMENT.finditer(text):
        attrs = element.group("attrs") + element.group("rest")
        element_id = element.group("id")
        hidden = bool(HIDDEN_IN_MARKUP.search(attrs)) or element_id in toggled_by_script
        if not hidden:
            continue
        classes = classes_of(attrs)
        clashing = sorted(c for c in classes if DISPLAY_UTILITY.fullmatch(c))
        if clashing and not (classes & protected):
            line = text[:element.start()].count("\n") + 1
            found.append(
                f"{path.name}:{line}: #{element_id} is hidden but carries {', '.join(clashing)}. "
                f"That utility's `display` is !important and declared after Reboot's [hidden] rule, "
                f"so the element stays visible while .hidden reads true. Lay it out with a class of "
                f"your own, or add `.<class>[hidden] {{ display: none; }}`."
            )
    return found


def main() -> int:
    pages = sorted(PAGES.glob("*.php"))
    if not pages:
        print(f"UI GUARD: no pages found under {PAGES}", file=sys.stderr)
        return 1
    findings = [f for page in pages for f in findings_for(page)]
    for finding in findings:
        print(finding)
    print(f"\n{len(pages)} page(s) checked, {len(findings)} finding(s)")
    print("UI GUARD: FAIL" if findings else "UI GUARD: PASS")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
