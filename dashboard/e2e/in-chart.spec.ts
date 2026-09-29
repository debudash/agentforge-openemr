// ADR 0009: with the admin setting on the SMART app, opening a patient anywhere shows the new
// dashboard in the chart, EHR-launched for that patient, with no login, consent or picker. The
// refusal paths are tested as hard as the acceptance path: another patient's token, a user
// without patients/demo, a user without patients/med (ADR 0010: no app for them), and the setting off.
import { test, expect, type Frame, type Page } from "@playwright/test";
import { fileURLToPath } from "node:url";
import { DOCTOR, doctorPassword, restrictedPasswords, sql, stackPatients, type StackPatient } from "./support/env";
import { signInToLegacy } from "./support/legacy";
import {
  CLIENT_ID,
  INTERACTIVE_OAUTH,
  appSettled,
  chartFrame,
  embeddedApp,
  getGlobal,
  openShellTab,
  openViaRTop,
  recordNavigations,
  setGlobal,
  useRenderer,
} from "./support/chart";

const patients = new Map<number, StackPatient>(stackPatients().map((p) => [p.pid, p]));
/** Family names, to check that one patient's app never shows the other's. */
const lastNames = new Map<number, string>(sql("SELECT pid, lname FROM patient_data").map(([pid, lname]) => [Number(pid), lname ?? ""]));
function patient(pid: number): StackPatient {
  const p = patients.get(pid);
  if (!p) throw new Error(`no pid ${String(pid)} on the stack`);
  return p;
}

const SHOTS = fileURLToPath(new URL("../../dashboard-modernization/04-evidence/in-chart/", import.meta.url));

const renderer = useRenderer("smart_app");
test.beforeAll(renderer.set);
test.afterAll(renderer.restore);

/** The shell's identity bar, filled by the chart's setMyPatient(). */
async function identityBar(page: Page): Promise<{ name: string; mrn: string }> {
  await expect(page.locator(".ptName")).toContainText(/\(\S+\)/);
  return page.evaluate(() => ({
    name: document.querySelector(".ptName span")?.textContent.trim() ?? "",
    mrn: document.querySelector(".ptName .text-muted span")?.textContent.trim() ?? "",
  }));
}

/** The app is for the chart's patient: token patient, header MRN and name all match the chart. */
async function expectAppIsFor(page: Page, app: Frame, p: StackPatient): Promise<void> {
  const header = app.getByRole("banner", { name: "Patient" });
  await expect(header).toHaveAttribute("data-patient-id", p.uuid);
  await expect(header.locator('[data-field="mrn"]')).toHaveText(p.pubpid);
  const bar = await identityBar(page);
  expect(bar.mrn).toBe(p.pubpid);
  await expect(header.locator('[data-field="name"]')).toHaveText(bar.name);
}

async function expectPatientMenuHasModuleTabs(chart: Frame): Promise<void> {
  // The patient menu (PatientMenuRole) with the Co-Pilot module's tabs, outside the app frame.
  const menu = chart.getByRole("navigation").filter({ has: chart.getByRole("link", { name: "Dashboard" }) });
  await expect(menu.getByRole("link", { name: "Co-Pilot" })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Demo Data" })).toBeVisible();
}

function noInteractiveScreens(navigations: readonly string[]): void {
  expect(navigations.filter((u) => INTERACTIVE_OAUTH.test(u)), "login, consent or picker shown").toEqual([]);
}

test.describe("as doctor1, setting on the SMART app", () => {
  test("calendar: clicking a scheduled patient opens the new dashboard for that patient", async ({ page }) => {
    await signInToLegacy(page);
    const navigations = recordNavigations(page);
    // doctor1's latest scheduled day, so the test does not depend on today's date.
    const [[day, pidText]] = sql(
      "SELECT DATE_FORMAT(pc_eventDate,'%Y%m%d'), pc_pid FROM openemr_postcalendar_events e JOIN users u ON u.id=e.pc_aid WHERE u.username='doctor1' AND pc_pid<>'' ORDER BY pc_eventDate DESC, pc_startTime LIMIT 1",
    ) as [[string, string]];
    const p = patient(Number(pidText));
    await openShellTab(page, `/interface/main/calendar/index.php?module=PostCalendar&func=view&viewtype=day&Date=${day}`, "cal");
    let calendar: Frame | undefined;
    await expect.poll(() => (calendar = page.frames().find((f) => f.url().includes("calendar/index.php") && f.url().includes(day))) !== undefined).toBe(true);
    if (!calendar) throw new Error("no calendar");
    const link = calendar.locator(`a.link_title[data-pid="${String(p.pid)}"]`).first();
    await link.click();

    const chart = await chartFrame(page, p.pid);
    const app = await embeddedApp(chart);
    await appSettled(app);
    await expectAppIsFor(page, app, p);
    await expectPatientMenuHasModuleTabs(chart);
    noInteractiveScreens(navigations);
    await expect(chart.locator("#allergy_ps_expand, #medical_problem_ps_expand")).toHaveCount(0);
    await page.screenshot({ path: `${SHOTS}in-chart-calendar.png` });
  });

  test("patient finder: clicking a row opens the new dashboard for that patient", async ({ page }) => {
    await signInToLegacy(page);
    const navigations = recordNavigations(page);
    await openShellTab(page, "/interface/main/finder/dynamic_finder.php", "fin");
    let finder: Frame | undefined;
    await expect.poll(() => (finder = page.frames().find((f) => f.url().includes("dynamic_finder.php"))) !== undefined).toBe(true);
    if (!finder) throw new Error("no finder");
    // The finder's first row, whichever patient it is (the list is paged and sorted server-side).
    const row = finder.locator('#pt_table tbody tr[id^="pid_"]').first();
    await expect(row).toBeVisible();
    const p = patient(Number((await row.getAttribute("id"))?.slice(4)));
    await row.click();

    const chart = await chartFrame(page, p.pid);
    const app = await embeddedApp(chart);
    await appSettled(app);
    await expectAppIsFor(page, app, p);
    await expectPatientMenuHasModuleTabs(chart);
    noInteractiveScreens(navigations);
    await page.screenshot({ path: `${SHOTS}in-chart-finder.png` });
  });

  test("switching quickly between two patients never shows the previous patient", async ({ page }) => {
    await signInToLegacy(page);
    const a = patient(1);
    const b = patient(3);
    // Each open settles, then the other; then a burst where the next open starts before the
    // previous app has loaded. On every settled open, the app must be the chart's patient.
    for (const p of [a, b, a, b]) {
      await openViaRTop(page, p.pid);
      const app = await embeddedApp(await chartFrame(page, p.pid));
      await appSettled(app);
      await expectAppIsFor(page, app, p);
      await expect(app.locator("body")).not.toContainText(lastNames.get(p === a ? b.pid : a.pid) ?? "?");
    }
    for (const p of [a, b, a]) await openViaRTop(page, p.pid);
    await openViaRTop(page, b.pid);
    const app = await embeddedApp(await chartFrame(page, b.pid));
    await appSettled(app);
    await expectAppIsFor(page, app, b);
  });

  test("a launch that races a patient switch is refused, not shown for the other patient", async ({ page, context }) => {
    await signInToLegacy(page);
    const a = patient(1);
    const b = patient(3);
    // Hold the chart's launch request for A until the session has moved to B, the way a second
    // window opening B would. OpenEMR then builds the launch for B inside A's chart.
    let release: () => void = () => undefined;
    const held = new Promise<void>((r) => (release = r));
    await page.route("**/interface/smart/ehr-launch-client.php*", async (route) => {
      await held;
      await route.continue();
    });
    await openViaRTop(page, a.pid);
    const chart = await chartFrame(page, a.pid);
    await expect(chart.locator("#dashboard_smart_app")).toHaveAttribute("data-fhir-patient", a.uuid);
    const other = await context.newPage();
    await other.route("**/interface/smart/ehr-launch-client.php*", (r) => r.abort());
    const res = await other.goto(`/interface/patient_file/summary/demographics.php?set_pid=${String(b.pid)}`);
    expect(res?.status()).toBe(200);
    await other.close();
    release();

    const app = await embeddedApp(chart);
    await expect(app.getByRole("alert")).toContainText("opened for a different patient than the chart");
    await expect(app.locator("[data-card]")).toHaveCount(0);
    await expect(app.locator("body")).not.toContainText(lastNames.get(b.pid) ?? "?");
    await page.unroute("**/interface/smart/ehr-launch-client.php*");
  });
});

test.describe("restricted users, setting on the SMART app", () => {
  test("a user without patients/demo gets 403 and no app", async ({ page }) => {
    const launches: string[] = [];
    page.on("request", (r) => {
      if (/ehr-launch-client\.php|\/public\/dashboard\/|\/oauth2\//.test(r.url())) launches.push(r.url());
    });
    await signInToLegacy(page, "dash-nodemo", restrictedPasswords()["dash-nodemo"] ?? "");
    const responses: number[] = [];
    page.on("response", (r) => {
      if (r.url().includes("demographics.php?set_pid=3")) responses.push(r.status());
    });
    await openViaRTop(page, 3);
    const chart = await chartFrame(page, 3);
    await expect(chart.locator("body")).toContainText("Not Authorized");
    expect(responses).toContain(403);
    await expect(chart.locator("#dashboard_smart_app")).toHaveCount(0);
    expect(launches).toEqual([]);
  });

  test("a user without patients/med gets the legacy page, no app and no clinical card (ADR 0010)", async ({ page }) => {
    // The FHIR API would skip this user's ACL for a patient-scoped token (API-11), so the chart
    // must not launch the app for them at all.
    const launches: string[] = [];
    page.on("request", (r) => {
      if (/ehr-launch-client\.php|\/public\/dashboard\/|\/oauth2\/|\/apis\/default\/fhir\//.test(r.url())) launches.push(r.url());
    });
    await signInToLegacy(page, "dash-demoview", restrictedPasswords()["dash-demoview"] ?? "");
    const p = patient(1);
    await openViaRTop(page, p.pid);
    const chart = await chartFrame(page, p.pid);
    await chart.waitForLoadState("load");
    await expect(chart.locator("body")).not.toContainText("Not Authorized");
    await expect(page.locator(".ptName")).toContainText(p.pubpid);
    await expect(chart.locator("#dashboard_smart_app")).toHaveCount(0);
    // The legacy cards check their own ACLs: none of the clinical cards is drawn for this user.
    for (const id of ["allergy_ps_expand", "medical_problem_ps_expand", "medication_ps_expand", "vitals_ps_expand"]) {
      await expect(chart.locator(`#${id}`), id).toHaveCount(0);
    }
    await expect(chart.locator("body")).not.toContainText("Essential hypertension");
    await page.waitForLoadState("networkidle");
    expect(launches).toEqual([]);
    await page.screenshot({ path: `${SHOTS}in-chart-no-med.png` });
  });
  test("a user with patients/med but without an issue ACL gets the legacy page and no app (ADR 0010)", async ({ page }) => {
    // Restrict the allergy issue type to admin/super, which doctor1 does not hold; restore after.
    const [[previous]] = sql("SELECT aco_spec FROM issue_types WHERE category='default' AND type='allergy'") as [[string]];
    sql("UPDATE issue_types SET aco_spec='admin|super' WHERE category='default' AND type='allergy'");
    try {
      const launches: string[] = [];
      page.on("request", (r) => {
        if (/ehr-launch-client\.php|\/public\/dashboard\/|\/oauth2\//.test(r.url())) launches.push(r.url());
      });
      await signInToLegacy(page);
      await openViaRTop(page, 1);
      const chart = await chartFrame(page, 1);
      await chart.waitForLoadState("load");
      await expect(chart.locator("#dashboard_smart_app")).toHaveCount(0);
      await expect(chart.locator("#medical_problem_ps_expand")).toHaveCount(1);
      await expect(chart.locator("#allergy_ps_expand")).toHaveCount(0);
      expect(launches).toEqual([]);
    } finally {
      sql(`UPDATE issue_types SET aco_spec='${previous}' WHERE category='default' AND type='allergy'`);
    }
  });
});

test.describe("fallbacks to the legacy cards", () => {
  test("with the setting on legacy the old cards render and no app is launched", async ({ page }) => {
    const legacy = useRenderer("legacy");
    legacy.set();
    try {
      await signInToLegacy(page);
      await openViaRTop(page, 3);
      const chart = await chartFrame(page, 3);
      await expect(chart.locator("#medical_problem_ps_expand")).toHaveCount(1);
      await expect(chart.locator("#dashboard_smart_app")).toHaveCount(0);
    } finally {
      legacy.restore();
    }
  });

  test("with the SMART app selected but no client ID the old cards render", async ({ page }) => {
    const previous = getGlobal(CLIENT_ID);
    setGlobal(CLIENT_ID, null);
    try {
      await signInToLegacy(page, DOCTOR, doctorPassword());
      await openViaRTop(page, 3);
      const chart = await chartFrame(page, 3);
      await expect(chart.locator("#medical_problem_ps_expand")).toHaveCount(1);
      await expect(chart.locator("#dashboard_smart_app")).toHaveCount(0);
    } finally {
      setGlobal(CLIENT_ID, previous);
    }
  });
});
