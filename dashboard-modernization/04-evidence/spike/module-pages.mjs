// Spike: do the Co-Pilot patient.php and demo.php render outside the tabs shell?
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
const pass = readFileSync("../copilot/.local-doctor1-pass", "utf8").trim();
const B = "http://localhost:8300";
const M = B + "/interface/modules/custom_modules/oe-module-copilot-agent/public";
const browser = await chromium.launch();
const ctx = await browser.newContext();
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push("pageerror " + e.message));
page.on("console", (m) => { if (m.type() === "error") errors.push("console " + m.text()); });
await page.goto(B + "/interface/login/login.php?site=default");
await page.fill("#authUser", "doctor1");
await page.fill("#clearPass", pass);
await Promise.all([page.waitForNavigation(), page.click("#login-button")]);
await page.waitForLoadState("networkidle");
console.log("logged in:", page.url().split("?")[0]);
// make pid 1 the session patient without the tabs shell
const sp = await ctx.request.get(B + "/interface/patient_file/summary/demographics.php?set_pid=1");
console.log("set_pid status", sp.status());
for (const name of ["patient.php", "demo.php"]) {
  errors.length = 0;
  await page.goto(M + "/" + name);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2500); // one poll of checkPatientStillInView
  const title = await page.title();
  const h = (await page.locator("body").innerText()).slice(0, 300).replace(/\s+/g, " ");
  const stale = await page.locator("#cpa-stale").isVisible().catch(() => "n/a");
  console.log(`\n== ${name}\ntitle: ${title}\nstale banner visible: ${stale}\nbody: ${h}\nerrors: ${errors.length ? errors.join(" | ") : "none"}`);
  await page.screenshot({ path: `spike/${name}.png`, fullPage: true });
}
await browser.close();
