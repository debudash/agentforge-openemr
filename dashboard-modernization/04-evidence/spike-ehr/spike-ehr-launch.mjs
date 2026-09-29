// Throwaway spike: EHR launch from the legacy chart's SMART card. Deleted after the run.
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";

const [clientId, label] = process.argv.slice(2);
const B = "https://localhost:9300";
const pass = readFileSync("../copilot/.local-doctor1-pass", "utf8").trim();
const shots = process.env.SHOTS ?? ".";
const browser = await chromium.launch();
const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1400, height: 1000 } });
const page = await ctx.newPage();
const seen = [];
const note = (u) => {
  const p = u.split("?")[0].replace(B, "");
  if (seen[seen.length - 1] !== p) seen.push(p);
};
page.on("framenavigated", (f) => note(f.url()));
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));
page.on("response", (r) => {
  const xfo = r.headers()["x-frame-options"];
  if (xfo && r.url().includes("/oauth2/")) console.log("XFO", xfo, r.url().split("?")[0].replace(B, ""));
});

// 1. Doctor signs into OpenEMR normally.
await page.goto(B + "/interface/login/login.php?site=default");
await page.fill("#authUser", "doctor1");
await page.fill("#clearPass", pass);
await Promise.all([page.waitForNavigation(), page.click("#login-button")]);
await page.waitForFunction(() => typeof window.navigateTab === "function", null, { timeout: 30000 });
console.log("SIGNED_IN", page.url().replace(B, "").split("?")[0]);

// 2. Opens patient 1's chart in the pat tab, as clicking a patient does.
await page.evaluate(() => window.navigateTab(`${window.webroot_url}/interface/patient_file/summary/demographics.php?set_pid=1`, "pat", () => window.activateTabByName("pat", true), "Patient"));
let chart;
await page.waitForFunction(() => true);
for (let i = 0; i < 60 && !chart; i++) {
  chart = page.frames().find((f) => f.url().includes("demographics.php?set_pid=1"));
  if (!chart) await page.waitForTimeout(500);
}
await chart.waitForLoadState("load");
const btn = chart.locator(`.smart-launch-btn[data-client-id="${clientId}"]`);
await btn.waitFor({ state: "attached", timeout: 30000 });
if (!(await btn.isVisible())) {
  // The "SMART Enabled Apps" card starts collapsed; expand it as a user would, from its header.
  await chart.locator('[href="#smart"], [data-target="#smart"]').first().click();
}
await btn.waitFor({ timeout: 10000 });
console.log("LAUNCH_BUTTON_FOUND", await chart.locator("#smart").count() ? "in SMART card" : "");
await page.screenshot({ path: `${shots}/ehr-${label}-1-chart.png` });

// 3. Clicks Launch.
await btn.click();
const t0 = Date.now();
let app;
let loginShown = false, consentShown = false;
while (Date.now() - t0 < 60000) {
  for (const f of page.frames()) {
    const u = f.url();
    if (/\/oauth2\/.*\/login/.test(u) && !loginShown) {
      loginShown = true;
      await f.waitForLoadState("load").catch(() => undefined);
      await page.screenshot({ path: `${shots}/ehr-${label}-2-login.png` });
      await f.fill("input[name=username]", "doctor1").catch((e) => console.log("FILL", e.message));
      await f.fill("input[name=password]", pass).catch(() => undefined);
      await f.click("button[name=user_role][value=api]").catch((e) => console.log("CLICK", e.message));
    }
    if (u.includes("/oauth2/") && /patient-select|select-patient|patient_select/.test(u)) console.log("PATIENT_PICKER_SHOWN", u.split("?")[0]);
    if (u.includes("scope-authorize")) {
      consentShown = true;
      await page.screenshot({ path: `${shots}/ehr-${label}-2-consent.png` });
      const ok = f.locator("button[name=proceed], button:has-text('Authorize')").first();
      if (await ok.count()) await ok.click().catch(() => undefined);
    }
    if (u.includes("/ehr-launch-spike/index.html")) app = f;
  }
  if (app && (await app.locator("#out").textContent().catch(() => ""))?.match(/DONE|FAIL/)) break;
  await page.waitForTimeout(500);
}
await page.screenshot({ path: `${shots}/ehr-${label}-3-app.png` });
console.log("LOGIN_SCREEN_SHOWN", loginShown);
console.log("CONSENT_SCREEN_SHOWN", consentShown);
console.log("APP_OUTPUT", app ? await app.locator("#out").textContent() : "app never loaded");
console.log("NAVIGATIONS\n  " + seen.join("\n  "));
await browser.close();
