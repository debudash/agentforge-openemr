# templates/patient/card/smart_launch.html.twig

**Role:** the SMART app launch card body.
**Size:** 33 lines. **Reached from:** the SMART launch listener registered by `SmartLaunchController` (demographics.php L99-100).

## Purpose and behaviour

One Launch button per registered SMART client (name, client id, intent), a decision-support info
link for DSI clients, and a script that initialises `oeSMART.initLaunch(webroot, csrf)`.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Names and ids `|attr`-escaped; the script uses `js_escape`.

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-SL-01 | Low | L14 | **`\|attr` used in text context**; correct output, wrong filter. |

## What the port keeps

Outside the brief. Relevant to the architecture: the new dashboard could itself be registered as a SMART app and launched from here.
