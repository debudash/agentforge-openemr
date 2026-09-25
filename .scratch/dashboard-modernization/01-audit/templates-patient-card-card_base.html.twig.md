# templates/patient/card/card_base.html.twig

**Role:** the base layout every dashboard card extends: header with title and collapse toggle, optional add/edit buttons, collapsible body.
**Size:** 22 lines. **Reached from:** `{% extends %}` in 20 card templates.

## Purpose and behaviour

A `<section class="card">` with a header link that toggles `#id` via Bootstrap collapse (unless
`forceAlwaysOpen`), an expand/compress icon, and, when `auth` is true, a plus and/or pencil link.
The button shows when `card.canAdd()`/`card.canEdit()` or when `btnLabel` is literally "Add"/"Edit".
`linkMethod` chooses between an `href` (passed through the `safe_href` filter) and an inline
`onclick` built by string concatenation (L8, L11). The body is `collapse` plus `show` unless
`initiallyCollapsed`.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. `id` and `title` are escaped; `btnLink` in `onclick` is raw, but always server-built.
`auth` is only a display switch; it does not protect anything.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-CB-01 | Low | L1 | **Class names run together:** the class list and `card_bg_color` are concatenated with no space (`card` + `bg-primary` = `cardbg-primary`), so a background colour never applies. |
| TPL-CB-02 | Low | L4 | **`aria-expanded="true"` is constant**, even for collapsed cards; screen readers get the wrong state. The title is an `<a href="#">` rather than a button. |
| TPL-CB-03 | Low | L7, L10 | **Button visibility keys off English labels** (`btnLabel == "Add"`). |
| TPL-CB-04 | Medium | whole file | **Injected module content is never rendered.** Pages dispatch a `CardRenderEvent` for most cards and pass `prependedInjection`/`appendedInjection`, but this base has no place for them and no dashboard template prints them (only `portal.html.twig` imports the macro, then discards its result). The module extension point is dead on this page. |

## What the port keeps

The card chrome: title, collapse with remembered state per user, empty body states. The port reimplements collapse state in the browser (and may keep persisting it through `user_settings.php` if it is embedded in the shell).
