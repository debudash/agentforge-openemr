// Drives the spike page through the real OpenEMR login and patient picker.
import { chromium } from "@playwright/test";
import { readFileSync } from "node:fs";
const [clientId, user, passFile, patientFilter] = process.argv.slice(2);
const pass = readFileSync(passFile, "utf8").trim();
const browser = await chromium.launch();
const ctx = await browser.newContext({ ignoreHTTPSErrors: true });
const page = await ctx.newPage();
const reqs = [];
page.on("console", (m) => console.log("CONSOLE", m.type(), m.text()));
page.on("requestfailed", (r) => console.log("REQFAILED", r.method(), r.url().split("?")[0], r.failure()?.errorText));
page.on("response", (r) => { if (r.request().method()==="OPTIONS") console.log("PREFLIGHT", r.status(), r.url().split("?")[0]); });
page.on("request", (r) => { if (r.url().includes("9300")) reqs.push(r.method() + " " + r.url().split("?")[0]); });
await page.goto("http://localhost:5173/?client_id=" + encodeURIComponent(clientId));
await page.waitForURL(/9300/, { timeout: 30000 });
console.log("AT", page.url().split("?")[0]);
await page.fill("input[name=username]", user);
await page.fill("input[name=password]", pass);
await page.click("button[name=user_role][value=api]");
await page.waitForLoadState("networkidle");
console.log("AFTER LOGIN", page.url().split("?")[0]);
await page.screenshot({ path: "spike/after-login.png", fullPage: true });
const html = await page.content();
if (page.url().includes("patient")) {
  // patient picker
  if (patientFilter) { const s = page.locator("input[name=search_term], input[type=search]").first(); if (await s.count()) { await s.fill(patientFilter); } }
  await page.screenshot({ path: "spike/picker.png", fullPage: true });
  const sel = page.locator("button, a").filter({ hasText: /select/i }).first();
  await sel.click();
  await page.waitForLoadState("networkidle");
}
console.log("AT", page.url().split("?")[0]);
await page.screenshot({ path: "spike/scope.png", fullPage: true });
if (page.url().includes("scope-authorize") || (await page.locator("button[name=proceed], #proceed, button:has-text('Authorize')").count())) {
  await page.locator("button[name=proceed], button:has-text('Authorize')").first().click();
}
await page.waitForURL(/localhost:5173/, { timeout: 30000 });
await page.waitForFunction(() => document.getElementById("out")?.textContent?.match(/DONE|FAIL/), null, { timeout: 30000 });
console.log(await page.textContent("#out"));
console.log("REQUESTS\n" + reqs.join("\n"));
const tok = await page.evaluate(() => { for (const k of Object.keys(sessionStorage)) { try { const v = JSON.parse(sessionStorage.getItem(k)); if (v?.tokenResponse?.access_token) return { t: v.tokenResponse.access_token, p: v.tokenResponse.patient }; } catch {} } return null; });
for (const q of ["Patient/" + tok.p, "AllergyIntolerance?patient=" + tok.p, "Condition?patient=" + tok.p, "MedicationRequest?patient=" + tok.p, "CareTeam?patient=" + tok.p, "Observation?category=vital-signs&patient=" + tok.p]) {
  const r = await fetch("https://localhost:9300/apis/default/fhir/" + q, { headers: { Authorization: "Bearer " + tok.t, Accept: "application/fhir+json" } });
  const b = await r.json();
  console.log("NODE", r.status, q.split("?")[0], b.resourceType, b.total ?? "");
}
const pre = await fetch("https://localhost:9300/apis/default/fhir/Patient/" + tok.p, { method: "OPTIONS", headers: { Origin: "http://localhost:5173", "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization" } });
console.log("PREFLIGHT_NODE", pre.status, JSON.stringify(Object.fromEntries([...pre.headers].filter(([k]) => k.startsWith("access-control")))), (await pre.text()).slice(0, 80));
await browser.close();
// Same token, no browser: proves the server accepts it and only the browser's CORS preflight fails.
