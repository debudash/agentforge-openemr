// ADR 0004 / 0005: the legacy dashboard's Critical and High findings, reproduced as the user the
// finding is about, then fixed. Local dev stack only; the restricted users come from
// e2e/setup/restricted-users.php. Each test restores the data it changes.
import { test, expect, request, type APIRequestContext } from "@playwright/test";
import { DOCTOR, doctorPassword, restrictedPasswords, sql } from "../support/env";

const LEGACY_BASE = "http://localhost:8300";
const DASHBOARD = "/interface/patient_file/summary/demographics.php";
const SUMMARY = "/interface/patient_file/summary";

async function signIn(user: string, password: string): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: LEGACY_BASE });
  await ctx.get("/interface/login/login.php?site=default");
  const res = await ctx.post("/interface/main/main_screen.php?auth=login&site=default", {
    form: { new_login_session_management: "1", authUser: user, clearPass: password, languageChoice: "1" },
  });
  expect(res.url(), `login as ${user}`).toContain("/interface/main/tabs/main.php");
  return ctx;
}

const asDoctor = () => signIn(DOCTOR, doctorPassword());
const asDemoView = () => signIn("dash-demoview", restrictedPasswords()["dash-demoview"] ?? "");
const asNoDemo = () => signIn("dash-nodemo", restrictedPasswords()["dash-nodemo"] ?? "");

async function openDashboard(ctx: APIRequestContext, pid: number): Promise<string> {
  const res = await ctx.get(`${DASHBOARD}?set_pid=${String(pid)}`);
  return res.text();
}

function field(html: string, name: string): string {
  const m = new RegExp(`name="${name}" value="([^"]+)"`).exec(html);
  if (!m?.[1]) throw new Error(`no ${name} on the page`);
  return m[1];
}

/** The fragments are loaded with the page's form CSRF token (demographics.php L420-ish). */
function fragmentToken(html: string): string {
  const m = /csrf_token_form['"]?\s*[,:]\s*['"]?([0-9a-f]{20,})/.exec(html) ?? /name="csrf_token_form" value="([0-9a-f]+)"/.exec(html);
  if (!m?.[1]) throw new Error("no csrf_token_form on the page");
  return m[1];
}

const PATIENT = { pid: 3, fname: "Blaine377", lname: "Swift555", dob: "2009-03-21" };

test.describe("BUG-003 / BUG-008: nothing about the patient before authorization", () => {
  test("a user without patients/demo gets no PHI from demographics.php?set_pid=", async () => {
    const ctx = await asNoDemo();
    const html = await openDashboard(ctx, PATIENT.pid);
    expect(html).toContain("Not Authorized");
    for (const phi of [PATIENT.fname, PATIENT.lname, PATIENT.dob]) expect(html, `leaked ${phi}`).not.toContain(phi);
    expect(html).not.toContain("setPatient(");
  });

  test("and no side effects: the recent-patients list is not written", async () => {
    const [[uid]] = sql("SELECT id FROM users WHERE username='dash-nodemo'") as [[string]];
    sql(`DELETE FROM recent_patients WHERE user_id=${uid}`);
    const ctx = await asNoDemo();
    await openDashboard(ctx, PATIENT.pid);
    expect(sql(`SELECT patients FROM recent_patients WHERE user_id=${uid}`)).toEqual([]);
  });

  test("an authorized user still gets the dashboard and the identity bar", async () => {
    const ctx = await asDoctor();
    const html = await openDashboard(ctx, PATIENT.pid);
    expect(html).toContain("setPatient(");
    expect(html).toContain(PATIENT.lname);
    expect(html).toContain('id="medical_problem_ps_expand"');
  });
});

test.describe("BUG-005: a squad restriction stops the whole dashboard", () => {
  const SQUAD_PID = 44;
  test.beforeAll(() => {
    sql(`UPDATE patient_data SET squad='dashsquad' WHERE pid=${String(SQUAD_PID)}`);
  });
  test.afterAll(() => {
    sql(`UPDATE patient_data SET squad='' WHERE pid=${String(SQUAD_PID)}`);
  });

  test("a user outside the patient's squad sees no card", async () => {
    const ctx = await asDemoView();
    const html = await openDashboard(ctx, SQUAD_PID);
    expect(html).toContain("Not Authorized");
    for (const card of ["allergy_ps_expand", "medical_problem_ps_expand", "medication_ps_expand", "careteam_ps_expand"]) {
      expect(html, `${card} rendered for an out-of-squad user`).not.toContain(`id="${card}"`);
    }
  });
});

test.describe("BUG-006: the fragments authorize their own data", () => {
  const cases: [string, string, RegExp][] = [
    ["vitals (patients/med)", "vitals_fragment.php", /Most recent vitals|No vitals have been documented/],
    ["labs (patients/lab)", "labdata_fragment.php", /lab data|Most recent lab/i],
    ["disclosures (patients/disclosure)", "disc_fragment.php", /disclosure/i],
    ["an LBF form by name (the form's own ACO, or not an LBF form at all)", "lbf_fragment.php?formname=vitals", /Most recent from|None have been documented/],
  ];
  for (const [name, path, content] of cases) {
    test(`${name}: refused for a user who holds only patients/demo`, async () => {
      const ctx = await asDemoView();
      const html = await openDashboard(ctx, PATIENT.pid);
      const res = await ctx.post(`${SUMMARY}/${path}`, { form: { csrf_token_form: fragmentToken(html) } });
      const body = await res.text();
      expect(body, "the fragment answered with patient data").not.toMatch(content);
      expect(res.status()).toBe(403);
    });
  }

  test("vitals still load for a user who holds patients/med", async () => {
    const ctx = await asDoctor();
    const html = await openDashboard(ctx, PATIENT.pid);
    const res = await ctx.post(`${SUMMARY}/vitals_fragment.php`, { form: { csrf_token_form: fragmentToken(html) } });
    expect(res.status()).toBe(200);
    expect(await res.text()).toMatch(/Most recent vitals from/);
  });
});

test.describe("BUG-001: saving a care team needs write permission", () => {
  const CT_PID = 1;
  let original = "";
  test.beforeAll(() => {
    original = sql(`SELECT team_name FROM care_teams WHERE pid=${String(CT_PID)}`)[0]?.[0] ?? "";
  });
  test.afterAll(() => {
    sql(`UPDATE care_teams SET team_name='${original.replace(/'/g, "''")}' WHERE pid=${String(CT_PID)}`);
  });

  async function postTeamName(ctx: APIRequestContext, name: string) {
    const html = await openDashboard(ctx, CT_PID);
    return ctx.post(DASHBOARD, {
      form: {
        pid: String(CT_PID),
        team_id: field(html, "team_id"),
        csrf_token_form: field(html, "csrf_token_form"),
        team_name: name,
        team_status: "active",
        save_care_team: "true",
        "team[0][member_type]": "user",
        "team[0][user_id]": "8",
        "team[0][role]": "physician",
        "team[0][facility_id]": "3",
        "team[0][provider_since]": "2024-01-15",
        "team[0][status]": "active",
        "team[0][note]": "PCP; O'Neil clinic",
      },
    });
  }

  test("a read-only user cannot replace the patient's care team", async () => {
    const ctx = await asDemoView();
    const res = await postTeamName(ctx, "Changed by a read-only user");
    expect(sql(`SELECT team_name FROM care_teams WHERE pid=${String(CT_PID)}`)[0]?.[0]).toBe(original);
    expect(res.status()).toBe(403);
  });

  test("a user with patients/demo write still can", async () => {
    const ctx = await asDoctor();
    await postTeamName(ctx, `${original} (edited)`);
    expect(sql(`SELECT team_name FROM care_teams WHERE pid=${String(CT_PID)}`)[0]?.[0]).toBe(`${original} (edited)`);
  });
});

test.describe("BUG-002 / BUG-004: preference writes are authorized and scoped to the patient", () => {
  const TABLE = "patient_treatment_intervention_preferences";
  const MARK = "dashboard-e2e";
  test.afterAll(() => {
    sql(`DELETE FROM ${TABLE} WHERE note LIKE '${MARK}%'`);
  });

  async function postPref(ctx: APIRequestContext, pid: number, form: Record<string, string>) {
    const html = await openDashboard(ctx, pid);
    const token = /name="csrf_token" value="([^"]+)"/.exec(html)?.[1] ?? "";
    return ctx.post(DASHBOARD, { form: { csrf_token: token, pref_type: "treatment_intervention", ...form } });
  }

  const newPref = (note: string) => ({
    action: "save",
    id: "",
    observation_code: "95541-9",
    observation_code_text: "Treatment intervention preference",
    value_type: "text",
    value_text: "prefers oral route",
    status: "final",
    effective_datetime: "2026-09-25 10:00:00",
    note,
  });

  test("a read-only user cannot add a preference", async () => {
    const ctx = await asDemoView();
    const res = await postPref(ctx, 3, newPref(`${MARK} read-only add`));
    expect(sql(`SELECT id FROM ${TABLE} WHERE note='${MARK} read-only add'`)).toEqual([]);
    expect(res.status()).toBe(403);
  });

  test("a writer adds a preference to the patient on screen, once", async () => {
    const ctx = await asDoctor();
    await postPref(ctx, 3, newPref(`${MARK} writer add`));
    expect(sql(`SELECT patient_id FROM ${TABLE} WHERE note='${MARK} writer add'`)).toEqual([["3"]]);
  });

  test("a writer cannot void another patient's preference from this patient's dashboard", async () => {
    const ctx = await asDoctor();
    await postPref(ctx, 5, newPref(`${MARK} belongs to pid 5`));
    const [[otherId]] = sql(`SELECT id FROM ${TABLE} WHERE note='${MARK} belongs to pid 5'`) as [[string]];
    await postPref(ctx, 3, { action: "delete", id: otherId });
    expect(sql(`SELECT status FROM ${TABLE} WHERE id=${otherId}`)).toEqual([["final"]]);
    await postPref(ctx, 3, { ...newPref(`${MARK} overwrite attempt`), id: otherId });
    expect(sql(`SELECT note FROM ${TABLE} WHERE id=${otherId}`)).toEqual([[`${MARK} belongs to pid 5`]]);
  });
});

test.describe("BUG-010: a care team note is text, not markup", () => {
  const CT_PID = 3;
  let before: string[][] = [];
  test.beforeAll(() => {
    before = sql(`SELECT m.id, IFNULL(m.note,'') FROM care_team_member m JOIN care_teams t ON t.id=m.care_team_id WHERE t.pid=${String(CT_PID)}`);
    for (const [id] of before) sql(`UPDATE care_team_member SET note='<img src=x onerror="window.__bug010=1">' WHERE id=${id ?? "0"}`);
  });
  test.afterAll(() => {
    for (const [id, note] of before) sql(`UPDATE care_team_member SET note='${(note ?? "").replace(/'/g, "''")}' WHERE id=${id ?? "0"}`);
  });

  test("the stored note does not run in the dashboard", async ({ browser }) => {
    expect(before.length).toBeGreaterThan(0);
    const context = await browser.newContext({ baseURL: LEGACY_BASE });
    const page = await context.newPage();
    await page.goto("/interface/login/login.php?site=default");
    await page.fill("#authUser", DOCTOR);
    await page.fill("#clearPass", doctorPassword());
    await Promise.all([page.waitForURL(/tabs\/main\.php/), page.click("#login-button")]);
    await page.goto(`${DASHBOARD}?set_pid=${String(CT_PID)}`);
    await page.waitForLoadState("networkidle");
    const ran = await page.evaluate(() => (window as unknown as { __bug010?: number }).__bug010 === 1);
    expect(ran, "the stored note executed as script").toBe(false);
    await expect(page.locator("#care_team_table")).toContainText('<img src=x onerror="window.__bug010=1">');
    await context.close();
  });
});
