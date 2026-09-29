// Edit in the chart (option A): the app's Edit buttons open the legacy editors the old cards open,
// through the chart page, which builds every URL and honours only its own frame and a granted
// action. Refusal paths: an unknown action, a message from outside the frame, a URL as an action.
import { test, expect, type Frame, type Page } from "@playwright/test";
import { signInToLegacy } from "./support/legacy";
import { appSettled, chartFrame, embeddedApp, openViaRTop, useRenderer } from "./support/chart";

const renderer = useRenderer("smart_app");
test.beforeAll(renderer.set);
test.afterAll(renderer.restore);

const PID = 1;

async function openApp(page: Page): Promise<{ chart: Frame; app: Frame }> {
  await signInToLegacy(page);
  await openViaRTop(page, PID);
  const chart = await chartFrame(page, PID);
  const app = await embeddedApp(chart);
  await appSettled(app);
  return { chart, app };
}

function frameMatching(page: Page, re: RegExp): Frame | undefined {
  return page.frames().find((f) => re.test(f.url()));
}

test("the chart grants Edit as the legacy cards do, and the app shows exactly those buttons", async ({ page }) => {
  const { chart, app } = await openApp(page);
  const granted = ((await chart.locator("#dashboard_smart_app").getAttribute("data-edit-actions")) ?? "").split(" ").filter(Boolean).sort();
  // doctor1 holds patients/rx write, and prescriptions are enabled on this stack.
  expect(granted).toEqual(["allergy", "medical_problem", "medication", "prescriptions"]);
  const shown = (await app.locator("[data-edit]").evaluateAll((els) => els.map((e) => e.getAttribute("data-edit") ?? ""))).sort();
  expect(shown).toEqual(granted);
  await expect(app.locator('[data-card="care-team"] [data-edit], [data-card="vitals"] [data-edit]')).toHaveCount(0);
});

for (const [card, category] of [
  ["allergies", "allergy"],
  ["problems", "medical_problem"],
  ["medications", "medication"],
] as const) {
  test(`${card}: Edit opens the legacy issue editor for this patient`, async ({ page }) => {
    const { app } = await openApp(page);
    await app.locator(`[data-card="${card}"] [data-edit]`).click();
    await expect.poll(() => frameMatching(page, new RegExp(`stats_full\\.php\\?active=all&category=${category}$`)) !== undefined, { timeout: 20000 }).toBe(true);
  });
}

test("prescriptions: Edit opens the legacy prescription editor dialog for this patient", async ({ page }) => {
  const { app } = await openApp(page);
  await app.locator('[data-card="prescriptions"] [data-edit]').click();
  await expect.poll(() => frameMatching(page, new RegExp(`controller\\.php\\?prescription&list&id=${String(PID)}(&|$)`)) !== undefined, { timeout: 20000 }).toBe(true);
});

test("an unknown action, a URL as an action, or a message from outside the app's frame opens nothing", async ({ page }) => {
  const { chart, app } = await openApp(page);
  const opened: string[] = [];
  page.on("framenavigated", (f) => {
    if (/stats_full\.php|controller\.php\?prescription|eRx\.php/.test(f.url())) opened.push(f.url());
  });
  // From the app's own frame: actions outside the granted set.
  await app.evaluate(() => {
    const post = (action: unknown) => { window.parent.postMessage({ type: "oe-dashboard-edit", action }, window.location.origin); };
    post("bogus");
    post("/interface/patient_file/summary/stats_full.php?active=all&category=allergy");
    post("__proto__");
    post(["allergy"]);
  });
  // A granted action, but not from the app's frame: the chart page posting to itself.
  await chart.evaluate(() => { window.postMessage({ type: "oe-dashboard-edit", action: "allergy" }, window.location.origin); });
  // The wrong message type from the app's frame.
  await app.evaluate(() => { window.parent.postMessage({ type: "something-else", action: "allergy" }, window.location.origin); });
  await page.waitForTimeout(3000);
  expect(opened).toEqual([]);
  await expect(chart.locator("#dashboard_smart_app")).toHaveCount(1);
});
