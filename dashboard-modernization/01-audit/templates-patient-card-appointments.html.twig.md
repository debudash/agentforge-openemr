# templates/patient/card/appointments.html.twig

**Role:** the Appointments card body: future, recurring and past appointments.
**Size:** 100 lines. **Reached from:** demographics.php L2002.

## Purpose and behaviour

Three sections with macros: future appointments (category link that opens the event editor, comment
and recurrence icons, day, date, time and meridiem, provider, status, group name for therapy
groups), an "(+)" line when more exist on the overflow date, recurring appointments (title, pattern,
end date) and past appointments.

## Controls

Twig autoescaping is off app-wide (`TwigContainer.php:70`), so each `{{ }}` below is raw unless a filter escapes it. Most values `|text`; `a.jsEvent` is built with `attr_js()` in PHP; `a.bgColor` is printed
inside a `style` attribute with `|text` (admin-configured colour).

## Findings

| ID | Sev | Lines | Finding |
|---|---|---|---|
| TPL-AP-01 | Medium | L25 + demographics.php L1889 | **Provider names double-escaped**: `uname` arrives already `text()`-escaped and is escaped again (DEM-10). |
| TPL-AP-02 | Low | L5 | **CSS value through an HTML escaper** (`style="background-color: {{ a.bgColor\|text }}"`); fine for colours, wrong tool. |
| TPL-AP-03 | Low | L21 | **Meridiem wrong in edge cases** because the page computes it wrong (DEM-09). |

## What the port keeps

Candidate extra section (upcoming appointments). FHIR `Appointment?patient=&date=ge<today>`.
