"""Run: python .scratch/dashboard-modernization/tools/build_catalog.py

Build 02-bug-catalog.md from the Phase 1 audit tables plus a hand-written triage map.

Every finding row in 01-audit/*.md must appear in TRIAGE (or be merged into one that does);
the script fails otherwise, so the catalog cannot silently drop a finding.
"""
import re
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIT = ROOT / "01-audit"

row_re = re.compile(r"^\| ([A-Z]+(?:-[A-Z]+)?-\d+) \| (Critical|High|Medium|Low) \| ([^|]*) \| (.*) \|$")
findings = OrderedDict()
for f in sorted(AUDIT.glob("*.md")):
    for line in f.read_text(encoding="utf-8").splitlines():
        m = row_re.match(line)
        if m:
            fid, sev, lines, text = m.groups()
            title = re.search(r"\*\*(.+?)\*\*", text)
            findings[fid] = dict(sev=sev, lines=lines.strip(), title=(title.group(1) if title else text)[:160].rstrip("."), file=f.name)

# Disposition codes
#   PORT  designed out by the port (the new code path does not have it)
#   REQ   parity requirement: the port must implement this correctly
#   LEGACY fix in the legacy PHP dashboard, which stays in the product (separate PR / upstream)
#   CONST accepted constraint of "no backend changes"; documented in the spec and the defense
#   NONE  no action (dead or cosmetic in legacy code the port does not reuse)

T = {}
def t(ids, cat, mit, disp):
    ids = ids.split()
    T[ids[0]] = dict(cat=cat, mit=mit, disp=disp, merged=ids[1:])

# --- Critical / High security ---------------------------------------------------------------
t("DEM-01", "AuthZ / Privacy", "Move the `patients/demo` + ViewEvent check to the top of the script, before `set_pid` handling, CDR and any output; emit nothing patient-specific until it passes. Port: the SPA renders nothing until the token and patient read succeed.", "LEGACY + PORT")
t("CTC-01", "AuthZ", "Require `patients/demo` write (and the squad check) inside `handleFormSubmission()`; move the save to its own POST endpoint instead of the card constructor.", "LEGACY")
t("TPC-01 CEC-01", "AuthZ / IDOR", "Check write ACL in `handlePost()`; scope service `update`/`delete` with `WHERE id = ? AND patient_id = ?`; move writes out of render.", "LEGACY")
t("TPL-CT-01", "XSS (stored)", "Build rows with `textContent`/`createElement`, or escape with `jsText()` before `innerHTML`; never interpolate DB values into template literals bound to `innerHTML`. Port renders text nodes only.", "LEGACY + PORT")
t("TPL-PR-01", "XSS (stored)", "Parenthesise: `(pref.observation_code_text ?? pref.code_display)|text`; derive `observation_code_text` server-side from the LOINC list instead of trusting the hidden input.", "LEGACY")
t("TPL-PR-02", "XSS (attribute)", "Use `|attr` on the JSON (`data-pref=\"{{ pref|json_encode|attr }}\"`) or `json_encode` with `JSON_HEX_APOS|JSON_HEX_QUOT`.", "LEGACY")
t("DEM-02", "AuthZ / Integrity", "Same fix as DEM-01: no session change, recent-list write or CDR run before authorization.", "LEGACY")
t("DEM-03", "AuthZ", "Treat `$thisauth == 0` after the squad check as a full stop (render the unauthorized partial and exit), not a header-only switch. Port: cannot enforce squads client-side (see API-01).", "LEGACY + CONST")
t("TPC-02 CEC-02", "Architecture / Integrity", "Handle POSTs in a controller before rendering; `getTemplateVariables()` must be side-effect free.", "LEGACY")
t("DSF-01 LBD-01 VTF-01 LBF-01", "AuthZ", "Each fragment re-checks the same ACL (and squad) the page used to show the card, and LBF re-checks the form's `grp_aco_spec`. Port: no fragments; data comes from API routes that enforce their own ACL.", "LEGACY + PORT")
t("API-01", "AuthZ / API constraint", "Document in the spec and the defense: the port inherits the API's `patients/med` granularity and cannot hide per-issue-type or squad-restricted data. Mitigation without backend change: request only the scopes the dashboard needs; show an explicit note in the app. Real fix is server-side (upstream).", "CONST")
# --- Medium ---------------------------------------------------------------------------------
t("DEM-04", "AuthZ / Clinical safety", "Look up the encounter with `WHERE encounter = ? AND pid = ?` and ignore it when it does not belong to the patient.", "LEGACY")
t("DEM-05 STA-07", "Data correctness", "One definition of \"active\" (clinical status active, not resolved, end date empty or in the future) in one service method used by every card. Port: `clinical-status=active` on every query.", "REQ")
t("DEM-06", "Data correctness", "Use `formname=<grp_form_id>` for each LBF card's Trend link (as `lbf_fragment.php` L48 already does).", "LEGACY")
t("DEM-07", "Dead code / Data", "Compute the eRx flag in the page itself or drop the card; today it can never render.", "LEGACY")
t("DEM-08", "Performance / Error handling", "Async requests; reload at most once per page view; treat non-success responses as errors, not as \"changed\".", "LEGACY")
t("DEM-09 TPL-AP-03", "Data correctness", "Format times with one helper (`oeFormatTime`) for both lists; set meridiem only in 12-hour mode; show 12, not 0, at midnight.", "LEGACY")
t("DEM-10 TPL-AP-01", "Escaping / Display", "Escape once, at output: drop `text()` in PHP (L1889, L1991) and keep `|text` in the template.", "LEGACY")
t("DEM-11 TPL-LD-01", "Error handling", "Check `response.ok`; render an error state in the card; stop the spinner. Port: every card has loading, empty and error states.", "LEGACY + REQ")
t("DEM-12", "Architecture", "Render the prescription list from `PrescriptionService` in Twig; remove `chdir()` or restore the directory in a `finally`.", "LEGACY")
t("DEM-13 CTC-03 TPC-04", "Performance", "Load only what is rendered (lazy option lists, `EXISTS` instead of `SELECT *`, bounded encounter list, batch user lookups); skip `CardRenderEvent` dispatches while nothing renders injections. Port: one request per card, cached per session.", "LEGACY + PORT")
t("CTC-02", "Integrity", "Create the contact record on first *edit*, not on view.", "LEGACY")
t("TPC-03", "AuthZ", "Use the `acl` option key so the card carries `patients/demo`.", "LEGACY")
t("STA-01", "AuthZ", "Gate Immunizations on `patients/med` (as Vitals is) and pass the real write permission to `auth`.", "LEGACY")
t("STA-02 TPL-IM-01", "Data correctness", "Print the computed `field` (escaped) in the template, not raw `cvx_text`; show the date.", "LEGACY")
t("STA-03 TPL-DL-01", "CSRF / Privacy", "POST the token in a form body instead of a URL.", "LEGACY")
t("STA-04", "UI bug", "Pass `id` (not `label`) for the Old Medication card.", "LEGACY")
t("PNF-01", "AuthZ", "Move the Completed handler below the notes ACL + squad check and require notes write.", "LEGACY")
t("TAF-01 CRF-01 PRF-01", "AuthZ", "Re-check the card's ACL in the fragment (Tracks needs one assigned first).", "LEGACY")
t("BVC-01", "AuthZ / Privacy", "Give the Billing card an ACL (`acct/rep` or `acct/bill`).", "LEGACY")
t("IVC-01 TPL-IN-02", "CSRF", "Add the CSRF token to the eligibility form and check it before `requestEligibleTransaction()`; move the trigger to its own endpoint.", "LEGACY")
t("IVC-02 TPL-IN-01", "Privacy", "Mask the SSN (last 4) on the dashboard; full value only on the edit page with write access.", "LEGACY")
t("PTC-01", "Architecture", "Move the portal checks into `PortalCard` (or a service) and take `pid` in the constructor.", "LEGACY")
t("TPL-CB-04 TPL-MC-01 TPL-PO-01", "Extensibility", "Render `prependedInjection`/`appendedInjection` in `card_base` via the macro, or stop dispatching the events. Port: expose named slots per card so the extension idea survives.", "LEGACY + REQ")
t("TPL-CT-02 TPL-PR-03", "Markup / Performance", "Remove the nested `<html><head>` and load the date picker once in the page header.", "LEGACY")
t("TPL-PH-02", "Architecture", "Move `image_widget()` into a class the Twig function can call; do not depend on a page-local function.", "LEGACY")
t("TPL-AD-02", "AuthZ", "Gate Advance Directives on the documents ACL.", "LEGACY")
t("TPL-AL-01", "Clinical safety", "Sort severe, life-threatening and fatal allergies first, as the template's own header promises. Port: required behaviour with a test.", "LEGACY + REQ")
t("BAR-01", "Parity gap", "Port adds sex (`Patient.gender`) and a status field (see API-02) to the header; the legacy bar is unchanged.", "REQ")
t("API-02", "API constraint", "Do not show `Patient.active` as status (always true). Header status = \"Active\" unless `deceasedDateTime`/`deceasedBoolean` is set, then \"Deceased <date>\". Defined in the spec.", "CONST + REQ")
t("API-03", "API constraint / Data", "Empty allergy list shows \"No allergies recorded\"; an NKA entry (SNOMED 716186003) shows \"No Known Allergies\". Document the difference from the legacy card's list_touch rule.", "CONST + REQ")
# --- Low ------------------------------------------------------------------------------------
t("DEM-14", "Maintainability", "Rename to what it means or use the row count; nothing depends on it today.", "NONE")
t("DEM-15", "Dead code", "Pass `$apptStyle` to the template or delete it.", "LEGACY")
t("DEM-16", "Dead code", "Remove the placeholder `btnLink => 'test'`.", "LEGACY")
t("DEM-17 TPL-RX-01", "i18n", "Wrap visible labels in `xl()`.", "LEGACY")
t("DEM-18", "Markup", "Emit the conflict alert inside the page's `<head>` script.", "LEGACY")
t("DEM-19", "Code quality", "Declare with `let`/`const`, take `event` as a parameter, remove `console.log`.", "LEGACY")
t("DEM-20", "CSRF", "Use `csrf_token_form` consistently.", "LEGACY")
t("DEM-21", "Code quality", "Read `hide_dashboard_cards` through `OEGlobalsBag`.", "LEGACY")
t("DEM-22 STA-08 TPL-APP-01 TPL-DM-01 TPL-EL-01", "Dead code", "Delete: `print_as_money()`, `deleteme()`, `$condition_str`/`$showEligibility` readers, `getPrescriptions()`, `$rowclass`, `appointments_past.html.twig`, `demographics.html.twig`, empty `eligibility.html.twig`.", "NONE")
t("DEM-23", "Code quality", "Lower-case the extension before matching; handle no extension.", "LEGACY")
t("DEM-24", "Code quality", "Use distinct variable names for the patient row and later result sets.", "LEGACY")
t("STA-05 TPL-TP-01", "UI bug", "Fix `$formRws`, collect rows into a list, title and id per form.", "LEGACY")
t("STA-06", "Performance", "Reuse the first `getListData()` result.", "LEGACY")
t("PNF-02 PNF-03 DSF-03 VTF-02 TAF-03 TPL-IN-03 TPL-BL-01", "Markup", "Fix the malformed tags, quote attributes, give each fragment a unique container id.", "LEGACY")
t("PNF-04", "Robustness", "Validate `docid` with `filter_var(..., FILTER_VALIDATE_INT)`.", "LEGACY")
t("DSF-02", "Robustness", "Guard `$event[1]` (use the whole event name when there is no hyphen).", "LEGACY")
t("DSF-04", "Config", "Read the count from a global (as messages do).", "NONE")
t("LBD-02", "Data correctness", "Pick the newest report per order, then its first code deterministically (`ORDER BY` + `LIMIT 1`).", "LEGACY")
t("LBD-03", "UI bug", "Open the encounter through `top.navigateTab`/`left_nav.loadFrame`, not frame `RBot`.", "LEGACY")
t("VTF-03", "Code quality", "Fix the comment.", "NONE")
t("TAF-02", "Data correctness", "Group by `form_id` (or select `MAX(form_id)`), so the link target is deterministic.", "LEGACY")
t("HDR-01 HDR-02", "Code quality", "Reuse the page's Twig container; drop unused variables.", "NONE")
t("CTC-04 CTC-05", "Code quality", "Rename `getViewArgs()`; provide the display fields the template reads.", "LEGACY")
t("TPC-05 CEC-03", "Maintainability", "Extract one `PreferenceViewCard` parameterised by type and service.", "LEGACY")
t("DVC-01 DVC-02", "Code quality", "Consistent class name; set options once.", "NONE")
t("BVC-02", "UI bug", "Read the setting with the card's real id.", "LEGACY")
t("IVC-03", "Dead code", "Return the flag or remove the page's reader.", "LEGACY")
t("IVC-04", "Robustness", "`$policy_types[$type] ?? false`.", "LEGACY")
t("IVC-05", "Dead code", "Remove the unused method or share it with the page.", "NONE")
t("PTC-02 PTC-03 PTC-04", "Code quality", "Add the card only to the secondary section; construct without `$GLOBALS`; handle a missing layout row.", "LEGACY")
t("MNU-01", "XSS (config)", "Escape `on_click` with `attr()` or whitelist it.", "LEGACY")
t("MNU-02", "Error handling", "Log and fall back to the standard menu instead of `die()`.", "LEGACY")
t("MNU-03 MNU-04", "Code quality", "Drop the unused argument; write the condition as `if (!zhAclCheck(...)) continue;`.", "NONE")
t("BAR-02", "Code quality", "Map the display style to fixed template fragments.", "NONE")
t("PVM-01", "Parity / Data", "Port builds DOB and age separately from `Patient.birthDate` and formats them locally.", "REQ")
t("PVM-02", "Performance", "None needed.", "NONE")
t("FPX-01", "Integrity", "Only the page that set the session patient should push identity; check pid against the session.", "LEGACY")
t("FPX-02", "Privacy", "Keep `WindowTitleAddPatient` off in shared-screen settings; port does not put names in the title.", "REQ")
t("TPL-CB-01", "UI bug", "Add the missing space before `card_bg_color`.", "LEGACY")
t("TPL-CB-02", "Accessibility", "`aria-expanded` follows the collapsed state; use a `<button>` for the toggle. Port: required.", "LEGACY + REQ")
t("TPL-CB-03", "i18n / Code quality", "Decide button visibility from `canAdd()`/`canEdit()`, not label text.", "LEGACY")
t("TPL-AL-02", "Display", "Omit the parentheses when severity is empty.", "LEGACY + REQ")
t("TPL-MP-01", "Parity note", "None: parity is title-only; the port may add onset date as an enhancement, flagged as such.", "NONE")
t("TPL-MD-01", "Data correctness", "One data source for medications, always including dosage instructions. Port: `dosageInstruction[0].text`.", "REQ")
t("TPL-RX-02", "Architecture", "Replace the Smarty fragment with a Twig list (see DEM-12).", "LEGACY")
t("TPL-ER-01", "Display", "Separate form and unit with a space.", "LEGACY")
t("TPL-IM-02", "Display", "Show the administered date.", "LEGACY")
t("TPL-AD-01", "Code quality", "Remove the leftover `{{ a }}`.", "LEGACY")
t("TPL-AP-02", "Code quality", "Validate the colour as a CSS colour value.", "NONE")
t("TPL-RC-01", "UI bug", "Pass the patient (and recall) id to the recall board.", "LEGACY")
t("TPL-AM-01", "UI bug", "Fix the `btnCLass` key.", "LEGACY")
t("TPL-PH-01", "UI bug", "Gate the photo loop on `patientPhotoCategoryName`.", "LEGACY")
t("TPL-SL-01", "Code quality", "Use `|text` in text context.", "NONE")
t("TPL-IN-04", "Markup", "Prefix ids (`insurance-primary`).", "LEGACY")
t("TPL-IN-05", "UI bug", "Bind the handler to the anchor, or read `closest('a')`.", "LEGACY")
t("TPL-CT-03", "Code quality", "Remove the unused class.", "NONE")
t("TPL-PR-04", "Code quality", "Scope handlers to the card's own section.", "LEGACY")
t("TPL-PR-05", "Dead code", "Remove the non-existent block overrides.", "NONE")
t("TPL-PR-06", "Robustness", "Guard the date filter (`|date` only on valid values).", "LEGACY")
t("TPL-PO-02", "Clarity", "Parenthesise the intended condition.", "LEGACY")
t("TPL-DC-01 TPL-DL-02 TPL-EX-01", "Documentation", "Fix the copied header comments.", "NONE")
t("API-04", "API constraint", "Serve the dashboard same-origin from `public/dashboard/` (ADR 0008). Upstream: register CORSListener above the authorization listener, fix L69, and restrict origins to registered clients.", "CONST")
t("API-06", "API constraint", "Request `patient/*.rs` scopes; the token covers the one patient chosen at login.", "CONST")
t("API-05", "API constraint", "Prove public client + PKCE end to end as rewrite step 1 before building cards.", "CONST")

# ---- completeness check -------------------------------------------------------------------
covered = set()
for k, v in T.items():
    covered.add(k); covered.update(v["merged"])
missing = [f for f in findings if f not in covered]
unknown = [f for f in covered if f not in findings]
assert not missing, f"not triaged: {missing}"
assert not unknown, f"triaged but not in audits: {unknown}"

SEV_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
rows = []
for n, (k, v) in enumerate(T.items()):
    ids = [k] + v["merged"]
    sev = min((findings[i]["sev"] for i in ids), key=SEV_ORDER.get)
    where = "; ".join(f"`{findings[i]['file'].replace('.md','').replace('-','/',2)}` {findings[i]['lines']}" for i in ids)
    rows.append(dict(ids=ids, sev=sev, cat=v["cat"], title=findings[k]["title"], mit=v["mit"], disp=v["disp"], where=where))
rows.sort(key=lambda r: (SEV_ORDER[r["sev"]], r["cat"]))

sev_counts = Counter(r["sev"] for r in rows)
disp_counts = Counter()
for r in rows:
    for d in r["disp"].split(" + "):
        disp_counts[d] += 1

def refs(r):
    return ", ".join(r["ids"])

lines = []
for i, r in enumerate(rows, 1):
    lines.append(f"| BUG-{i:03d} | {r['sev']} | {r['cat']} | {r['title']} | {r['mit']} | {r['disp']} | {refs(r)} |")

out = f"""# 02 — Bug catalog

Phase 2 of the patient dashboard modernization. Every finding from the per-file audits in
`01-audit/`, condensed to one row: severity, category, a concrete mitigation, and who resolves it.
Findings reported in more than one file are merged into one row that cites all of them. The
catalog is generated from the audit tables by a script that fails if any audit finding is missing,
so the two cannot drift.

**{len(findings)} audit findings → {len(rows)} catalog rows.**

## How to read it

**Severity**

| | Meaning |
|---|---|
| Critical | A user with ordinary dashboard access can read PHI they are not allowed to see, or change another record, with no special setup. |
| High | A security flaw that needs one precondition (a restricted user, stored input, a crafted request), or a missing check on a PHI endpoint. |
| Medium | A functional bug users can see, wrong or missing clinical data, a privacy excess, or a defence-in-depth gap. |
| Low | Cosmetic, dead code, maintainability, or a latent bug nothing triggers today. |

**Disposition** — who resolves it

| Code | Meaning | Rows |
|---|---|---|
| PORT | Designed out: the new dashboard has no equivalent code path. | {disp_counts['PORT']} |
| REQ | A requirement the port must meet (parity, or a rule the legacy page promised and broke). Each becomes a test in Phase 4. | {disp_counts['REQ']} |
| LEGACY | Fix in the PHP dashboard, which stays in the product alongside the port. Separate change, candidate for upstream. | {disp_counts['LEGACY']} |
| CONST | Accepted constraint of "no backend changes"; stated in the spec and in `PATIENT_DASHBOARD_MIGRATION.md`. | {disp_counts['CONST']} |
| NONE | No action: dead or cosmetic legacy code the port does not reuse. | {disp_counts['NONE']} |

A row can carry two codes (e.g. `LEGACY + PORT`: the legacy page needs a fix, and the port avoids
the defect by design).

**Verification.** Every row cites the file and lines it came from. Findings were verified by
reading the cited code. The Critical and High authorization and XSS findings (BUG rows citing
DEM-01, CTC-01, TPC-01, TPL-CT-01, TPL-PR-01/02) have **not been reproduced live**: that needs a
restricted user on the dev stack, which was not created without the owner's approval. Each is
listed in the spec as a failing test to write first.

## Summary

| Severity | Rows |
|---|---|
| Critical | {sev_counts['Critical']} |
| High | {sev_counts['High']} |
| Medium | {sev_counts['Medium']} |
| Low | {sev_counts['Low']} |

**The pattern behind the worst rows:** the dashboard authorizes *rendering*, not *data*. The page
decides which cards to draw; the endpoints behind them (fragments, card POST handlers) assume the
page already checked. Three separate write paths run inside card rendering with no permission
check, and three template sinks print stored values unescaped under an app-wide `autoescape =>
false`. A port that fetches data from endpoints that authorize every request, and renders only text
nodes, removes the whole class — which is the case for moving the presentation layer rather than
patching it.

## Catalog

| ID | Sev | Category | Finding | Mitigation | Disposition | Audit refs |
|---|---|---|---|---|---|---|
""" + "\n".join(lines) + """

## Systemic note

Twig autoescaping is disabled for the whole application (`src/Common/Twig/TwigContainer.php:70`,
`['autoescape' => false]`). It is recorded in every template audit rather than as a finding of its
own, because turning it on is an application-wide change far outside this work — but it is the
root cause of the XSS rows above, and the port's framework must escape by default (see the spec).
"""
(ROOT / "02-bug-catalog.md").write_text(out, encoding="utf-8", newline="\n")
import sys; sys.path.insert(0, str(Path(__file__).resolve().parent)); from escape_pipes import fix_file; fix_file(ROOT / "02-bug-catalog.md")
print(f"{len(findings)} findings -> {len(rows)} rows", dict(sev_counts), dict(disp_counts))
