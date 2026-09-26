// Local dev stack only: gives two patients a care team through the legacy dashboard's own
// Care Team form, so the port's Care Team card and the parity harness have data to compare.
// Removal: see dashboard-modernization/04-evidence/stack-changes.md.
import { request } from "@playwright/test";

const BASE = process.env.OE_BASE_URL ?? "http://localhost:8300";
const ADMIN_PASS = process.env.OE_ADMIN_PASS ?? "pass";

const teams = [
  {
    pid: 1,
    name: "Primary care team",
    members: [
      { member_type: "user", user_id: "8", role: "physician", facility_id: "3", provider_since: "2024-01-15", status: "active", note: "PCP; O'Neil clinic" },
      { member_type: "user", user_id: "9", role: "nurse_practitioner", facility_id: "3", provider_since: "2025-06-01", status: "inactive", note: "" },
    ],
  },
  {
    pid: 3,
    name: "Pediatrics",
    members: [{ member_type: "user", user_id: "9", role: "physician", facility_id: "3", provider_since: "2023-03-02", status: "active", note: "" }],
  },
];

const ctx = await request.newContext({ baseURL: BASE });
await ctx.get("/interface/login/login.php?site=default");
const login = await ctx.post("/interface/main/main_screen.php?auth=login&site=default", {
  form: { new_login_session_management: "1", authUser: "admin", clearPass: ADMIN_PASS, languageChoice: "1" },
});
if (!login.url().includes("tabs/main.php")) throw new Error("admin login failed");

for (const team of teams) {
  const page = await (await ctx.get(`/interface/patient_file/summary/demographics.php?set_pid=${team.pid}`)).text();
  const form = page.slice(page.indexOf('id="care_team_form"') > 0 ? page.indexOf('id="care_team_form"') : page.indexOf("save_care_team") - 4000);
  const csrf = /name="csrf_token_form" value="([^"]+)"/.exec(form)?.[1];
  const teamId = /name="team_id" value="([^"]*)"/.exec(form)?.[1] ?? "";
  if (!csrf) throw new Error(`no care team form for pid ${team.pid}`);
  const body = { pid: String(team.pid), team_id: teamId, csrf_token_form: csrf, team_name: team.name, team_status: "active", save_care_team: "true" };
  team.members.forEach((m, i) => Object.entries(m).forEach(([k, v]) => { body[`team[${i}][${k}]`] = v; }));
  const res = await ctx.post("/interface/patient_file/summary/demographics.php", { form: body });
  console.log(`pid ${team.pid}: care team saved (HTTP ${res.status()})`);
}
await ctx.dispose();
