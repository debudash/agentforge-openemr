// End to end through the real SMART login on the dev stack (4.5): the dashboard as OpenEMR
// serves it, with its CSP, against the live FHIR API.
import { test, expect, type Request } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { stackPatients } from "./support/env";
import { APP, signInToDashboard } from "./support/smart";

const patient1 = () => {
  const p = stackPatients().find((x) => x.pid === 1);
  if (!p) throw new Error("pid 1 missing on the stack");
  return p;
};

test("signs in with SMART, shows the chosen patient, and reads only with GET", async ({ page }) => {
  const consoleProblems: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error" || /Content Security Policy/i.test(m.text())) consoleProblems.push(m.text());
  });
  const appRequests: Request[] = [];
  page.on("request", (r) => {
    if (r.frame() === page.mainFrame() && r.resourceType() === "fetch") appRequests.push(r);
  });

  await signInToDashboard(page, patient1().uuid);

  // The authorization code is gone from the address bar and nothing else rode in on it (R8).
  const url = new URL(page.url());
  expect(url.pathname).toBe(APP);
  expect([...url.searchParams.keys()]).toEqual([]);

  const header = page.getByRole("banner", { name: "Patient" });
  await expect(header).toContainText("Adan632 Dicki44");
  await expect(header).toContainText("DOB:1981-07-04");
  await expect(header).toContainText("Sex:Male");
  await expect(header).toContainText("Status:Active");
  await expect(header).toContainText("Signed in as Dana Reyes");

  for (const id of ["allergies", "problems", "medications", "prescriptions", "care-team", "vitals"]) {
    await expect(page.locator(`[data-card="${id}"]`)).toHaveAttribute("data-state", /^(data|empty)$/);
  }
  await expect(page.locator('[data-card="care-team"]')).toContainText("Dana Reyes");
  await expect(page.locator('[data-card="vitals"]')).toContainText("Most recent vitals from: 2018-09-22");

  // R2: the app's own traffic (after the OAuth token exchange, which fhirclient POSTs) is GET only.
  const reads = appRequests.filter((r) => !r.url().includes("/oauth2/"));
  expect(reads.length).toBeGreaterThan(6);
  expect(reads.filter((r) => r.method() !== "GET").map((r) => `${r.method()} ${r.url()}`)).toEqual([]);
  // The token goes in a header, never a URL.
  expect(reads.filter((r) => /access_token|code=/.test(r.url()))).toEqual([]);

  expect(consoleProblems).toEqual([]);
  expect(await page.title()).toBe("Patient Dashboard");
});

test("has no serious or critical accessibility violations (WCAG 2 A/AA)", async ({ page }) => {
  await signInToDashboard(page, patient1().uuid);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const serious = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  expect(serious.map((v) => `${v.id}: ${v.help} (${String(v.nodes.length)})`)).toEqual([]);
});

test("sign out forgets the token, and the app then sends nothing", async ({ page }) => {
  await signInToDashboard(page, patient1().uuid);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("button", { name: "Sign in with OpenEMR" })).toBeVisible();
  const stored = await page.evaluate(() => Object.keys(sessionStorage));
  expect(stored).toEqual([]);
  const fhir: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes("/apis/")) fhir.push(r.url());
  });
  await page.reload();
  await expect(page.getByRole("button", { name: "Sign in with OpenEMR" })).toBeVisible();
  expect(fhir).toEqual([]);
});

test("the Co-Pilot link lands on OpenEMR's login when there is no OpenEMR session (ADR 0006)", async ({ page, context }) => {
  await signInToDashboard(page, patient1().uuid);
  const [popup] = await Promise.all([context.waitForEvent("page"), page.getByRole("link", { name: "Co-Pilot" }).click()]);
  await popup.waitForLoadState();
  // The SMART login does not create an interface session, so the module page asks for one.
  await expect(popup).toHaveURL(/\/interface\/login\/login\.php|login_screen\.php/);
  await expect(popup.locator("body")).not.toContainText("Adan632");
});
