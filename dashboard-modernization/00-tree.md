# 00 — Entry point and dependency tree

Phase 0 of the patient dashboard modernization. It maps what the current dashboard is made of,
so the audit (01) knows what to read and the migration spec (03) knows what it replaces.

Source: this repository at `week2-baseline` (`1ac7529`), OpenEMR 8.2.0-dev.

## Boundary

- **Dashboard-owned** files are audited cover to cover in `01-audit/`: the entry page, the
  fragments it loads, the card classes and templates it renders, its menu, and the identity bar
  it feeds.
- **Leaves** are listed with one line on what the dashboard uses from them and are not audited:
  bootstrap, database layer, shared services and libraries, and pages the dashboard only links to.

## Entry point

```
interface/patient_file/summary/demographics.php          2,080 lines — the "Medical Record Dashboard"
```

Reached two ways:

1. **From the tabs shell** (`interface/main/tabs/main.php`): selecting a patient loads
   `demographics.php?set_pid=<pid>` into the `pat` tab. `set_pid` makes it the active patient in
   the session, then the page pushes the patient into the persistent identity bar.
2. **Directly**, without `set_pid`: it renders for the patient already in the session
   (`$_SESSION['pid']`), or `?pid=` if the session has none (L73-75).

## Tree

Legend: `[A]` audited in `01-audit/`, `[L]` leaf (listed, not audited), `→` loaded by AJAX after
page load, `⇢` link or dialog only (the dashboard navigates there; nothing renders inline).

```
demographics.php  [A]
│
├── bootstrap
│   ├── interface/globals.php                       [L] autoload, session, site, DB, $GLOBALS, module kernel
│   ├── library/lists.inc.php                       [L] getListTouch(), issue helpers
│   ├── library/patient.inc.php                     [L] getPatientData(), getEmployerData(), getInsuranceData(), is_patient_deceased()
│   ├── library/options.inc.php                     [L] generate_display_field(), getLayoutProperties(), display_layout_tabs*()
│   ├── library/options.js.php                      [L] checkSkipConditions() for layout skip rules
│   ├── interface/patient_file/history/history.inc.php  [L]
│   ├── library/clinical_rules.php                  [L] allergy_conflict(), active_alert_summary(), resolve_rules_sql()
│   ├── library/group.inc.php                       [L] getGroup() (therapy groups)
│   ├── library/appointments.inc.php                [L] fetchNextXAppts(), fetchXPastAppts(), fetchRecurrences()
│   ├── library/pid.inc.php                         [L] setpid() — only when ?set_pid
│   └── src/Core/Header.php                         [L] setupHeader(['common','utility']) — jQuery 3.7, Bootstrap 4.6, dialog, utility.js
│
├── services and classes called directly
│   ├── src/Services/PatientService.php             [L] findByPid(), touchRecentPatientList()  (WRITE on set_pid)
│   ├── src/Services/AllergyIntoleranceService.php  [L] Allergies card data
│   ├── src/Services/PatientIssuesService.php       [L] Medical Problems and Medications card data
│   ├── src/FHIR/SMART/SmartLaunchController.php    [L] registers SMART app-launch card listeners
│   ├── src/Reminder/BirthdayReminder.php           [L] birthday popup decision
│   ├── src/OeUI/OemrUI.php                         [L] page heading, expand/collapse container
│   ├── src/Common/Twig/TwigContainer.php           [L] Twig environment — autoescape is OFF (L70)
│   ├── src/Common/Twig/TwigExtension.php           [L] tabRow/tabData/imageWidget functions (imageWidget calls image_widget() defined in demographics.php)
│   ├── library/classes/Controller.php + Smarty     [L] prescription "fragment" rendered into the Rx card (chdir hack)
│   └── src/Menu/PatientMenuRole.php                [A] horizontal patient menu
│       └── interface/main/tabs/menu/menus/patient_menus/standard.json   [L]
│
├── header
│   └── interface/patient_file/summary/dashboard_header.php   [A]
│       └── templates/patient/dashboard_header.html.twig      [A] prints OemrUI::pageHeading()
│
├── identity bar (lives in the tabs shell, fed by this page)
│   ├── setMyPatient() in demographics.php <head>             [A] (part of demographics.php)
│   ├── interface/main/tabs/js/frame_proxies.js               [A] left_nav.setPatient / setPatientEncounter
│   ├── interface/main/tabs/js/patient_data_view_model.js     [A] Knockout model: pname, pid, pubpid, str_dob, encounters
│   └── interface/main/tabs/templates/patient_data_template.php  [A] the rendered bar
│
├── cards rendered server-side (in page order)
│   ├── Allergies            templates/patient/card/allergies.html.twig          [A]
│   ├── Medical Problems     templates/patient/card/medical_problems.html.twig   [A]
│   ├── Medications          templates/patient/card/medication.html.twig         [A]
│   ├── Current Medications  templates/patient/card/erx.html.twig                [A] (eRx; never renders — see audit)
│   ├── Prescriptions        templates/patient/card/rx.html.twig                 [A] + Smarty prescription fragment [L]
│   ├── Care Team            src/Patient/Cards/CareTeamViewCard.php              [A]
│   │                        templates/patient/card/manage_care_team.html.twig   [A]
│   │                        src/Services/CareTeamService.php, ContactService, ContactRelationService, ListService  [L]
│   ├── Treatment Intervention Preferences
│   │                        src/Patient/Cards/TreatmentPreferenceViewCard.php   [A]
│   │                        templates/patient/card/preference_card_inline.html.twig  [A]
│   │                        src/Services/TreatmentInterventionPreferenceService.php  [L] (update/delete checked)
│   ├── Care Experience Preferences
│   │                        src/Patient/Cards/CareExperiencePreferenceViewCard.php  [A]
│   │                        (same template)   src/Services/CareExperiencePreferenceService.php [L]
│   ├── Deceased banner      templates/patient/partials/deceased.html.twig       [A]
│   ├── section "primary" (SectionEvent — modules may add cards)
│   │   ├── Demographics     src/Patient/Cards/DemographicsViewCard.php          [A]
│   │   │                    templates/patient/card/tab_base.html.twig           [A] → display_layout_tabs*() [L]
│   │   ├── Billing          src/Patient/Cards/BillingViewCard.php               [A]
│   │   │                    templates/patient/card/billing.html.twig            [A]
│   │   └── Insurance        src/Patient/Cards/InsuranceViewCard.php             [A]
│   │                        templates/patient/card/insurance.html.twig          [A]
│   │                        src/Billing/EDI270.php                              [L] eligibility (X12 270/271)
│   ├── Messages             templates/patient/card/loader.html.twig             [A] → pnotes_fragment.php
│   ├── Patient Reminders    loader                                              → patient_reminders_fragment.php
│   ├── Disclosures          loader                                              → disc_fragment.php
│   ├── Amendments           templates/patient/card/amendments.html.twig         [A]
│   ├── Labs                 loader                                              → labdata_fragment.php
│   ├── Vitals               loader                                              → vitals_fragment.php
│   ├── one card per charted LBF form   loader                                   → lbf_fragment.php
│   ├── section "secondary"
│   │   └── Patient Portal / API Access   src/Patient/Cards/PortalCard.php       [A]
│   │                                     templates/patient/partials/portal.html.twig  [A]
│   ├── eRx buttons          templates/patient/partials/erx.html.twig            [A]
│   ├── ID Card / Photos     templates/patient/card/photo.html.twig              [A]
│   ├── Advance Directives   templates/patient/card/adv_dir.html.twig            [A]
│   ├── Clinical Reminders   loader                                              → clinical_reminders_fragment.php
│   ├── Appointments         templates/patient/card/appointments.html.twig       [A]
│   ├── Recall               templates/patient/card/recall.html.twig             [A]
│   ├── stats_div            (empty container)                                   → stats.php
│   ├── Tracks               loader                                              → track_anything_fragment.php
│   └── Delete Patient       templates/patient/partials/delete.html.twig         [A]
│
├── loaded after page load  (fetch POST with csrf_token_form, HTML injected via innerHTML)
│   ├── stats.php                        [A] other issue types, Immunizations, Old Medication, Injury Log
│   │   └── templates: medical_problems, medication, erx, immunizations, tp_il  [A]
│   ├── pnotes_fragment.php              [A]  (also POST ?docUpdateId → marks a message done)
│   ├── disc_fragment.php                [A]
│   ├── labdata_fragment.php             [A]
│   ├── vitals_fragment.php              [A]  → interface/forms/vitals/report.php [L]
│   ├── track_anything_fragment.php      [A]
│   ├── lbf_fragment.php                 [A]  → interface/forms/LBF/report.php [L]
│   ├── clinical_reminders_fragment.php  [A]  → clinical_summary_widget() [L]
│   ├── patient_reminders_fragment.php   [A]  → patient_reminder_widget() [L]
│   ├── library/ajax/user_settings.php   [L]  saves card expand/collapse per user
│   └── interface/soap_functions/soap_patientfullmedication.php, soap_allergy.php  [L] eRx (NewCrop/Ensora) sync, synchronous XHR
│
├── shared card plumbing
│   ├── templates/patient/card/card_base.html.twig    [A] every card extends it
│   ├── templates/patient/macros/card.macro.twig      [A] injectedContent() — never called with output
│   ├── src/Events/Patient/Summary/Card/*             [L] CardModel, RenderEvent, SectionEvent
│   └── src/Events/PatientDemographics/*              [L] ViewEvent (authorization hook), RenderEvent (page hooks)
│
├── templates present but not reached from this page
│   ├── templates/patient/card/appointments_past.html.twig   [A] dead: contains PHP source as text
│   ├── templates/patient/card/eligibility.html.twig         [A] empty (0 bytes)
│   ├── templates/patient/card/demographics.html.twig        [A] superseded by tab_base
│   └── templates/patient/card/smart_launch.html.twig        [A] rendered by the SMART listener into a section
│
└── ⇢ linked or opened in dialogs only (not audited)
    stats_full.php, demographics_full.php, insurance_edit.php, pnotes_full.php, disclosure_full.php,
    list_amendments.php, add_edit_amendments.php, labdata.php, ../encounter/trend_form.php,
    ../reminder/clinical_reminders.php, ../reminder/patient_reminders.php, ../reminder/active_reminder_popup.php,
    ../birthday_alert/birthday_pop.php, ../../main/calendar/add_edit_event.php, advancedirectives.php,
    create_portallogin.php, ../deleter.php, ../education.php, ../../forms/track_anything/*,
    ../../super/rules/index.php, controller.php?document&retrieve (images), controller.php?prescription&list,
    interface/eRx.php, main/messages/messages.php
```

## Forms and write paths reachable from the page

The dashboard is read-mostly, but these requests change data. Each is examined in the audit.

| Trigger | Handled by | Writes |
|---|---|---|
| `GET ?set_pid=` | demographics.php L84-94 | session pid/encounter; recent-patients list |
| Card expand/collapse | library/ajax/user_settings.php | user settings |
| Message "Completed" | pnotes_fragment.php L22-24 | `pnotes.activity`, `message_status` |
| Care Team form `POST save_care_team=true` | CareTeamViewCard::handleFormSubmission (constructor) | care team tables |
| Care Team render | CareTeamViewCard L154 `getOrCreateForEntity` | `contact` row for the patient |
| Preference forms `POST pref_type=… action=save/delete` | *PreferenceViewCard::handlePost (during render) | preference tables |
| Eligibility form `POST status_update=true` | InsuranceViewCard::getEligibilityOutput | outbound X12 270 + stored response |
| eRx sync on load | soap_functions/*.php | medication and allergy lists |

## COM objects

**None.** No PHP COM, DOTNET or VARIANT use anywhere in the repository (`new COM(`, `com_*`
functions, `new DOTNET(`, `new VARIANT(`: zero hits outside vendor). Browser-side `ActiveXObject`
appears only in code the dashboard does not load: `interface/forms/CAMOS/new.php`, old jQuery
copies under `interface/modules/zend_modules/public/js/lib/`, `interface/forms/eye_mag/js/`,
`public/assets/modified/dygraphs-2-0-0/` (used by trend pages, not the dashboard), and the
EHI export documentation. The dashboard's own external dependencies are HTTP only: SOAP to the
eRx vendor and X12 270/271 to the eligibility clearinghouse.

## Counts

| | |
|---|---|
| Audited files | 51 (22 PHP/JS sources, 29 Twig templates) |
| Server-rendered cards | up to 22, plus one per charted LBF form and any module cards |
| AJAX fragments | 9 (+ user settings, + 2 eRx sync calls) |
| Event dispatches per page view | ~25 (ViewEvent, 4 RenderEvent points, 2 SectionEvent, ~18 CardRenderEvent) |
