// ADR 0009: the new dashboard inside the chart. Switches the admin setting for a test file (and
// restores it), and finds the SMART app the chart embeds for the patient it opened.
import { expect, type Frame, type Page } from "@playwright/test";
import { sql } from "./env";

export const RENDERER = "patient_dashboard_renderer";
export const CLIENT_ID = "patient_dashboard_smart_client_id";

/** A global's current value, or null when it has no row (OpenEMR then uses its default). */
export function getGlobal(name: string): string | null {
  const rows = sql(`SELECT gl_value FROM globals WHERE gl_name='${name}' AND gl_index=0`);
  return rows[0]?.[0] ?? null;
}

export function setGlobal(name: string, value: string | null): void {
  sql(`DELETE FROM globals WHERE gl_name='${name}'`);
  if (value !== null) sql(`INSERT INTO globals (gl_name, gl_index, gl_value) VALUES ('${name}', 0, '${value}')`);
}

/**
 * Sets the dashboard renderer for the calling test file and puts the previous value back
 * afterwards. Call inside test.describe or at file level:
 *   const renderer = useRenderer("legacy"); test.beforeAll(renderer.set); test.afterAll(renderer.restore);
 */
export function useRenderer(value: "legacy" | "smart_app"): { set: () => void; restore: () => void } {
  let previous: string | null = null;
  return {
    set: () => {
      previous = getGlobal(RENDERER);
      setGlobal(RENDERER, value);
    },
    restore: () => {
      setGlobal(RENDERER, previous);
    },
  };
}

/** The OAuth screens that must never show on an in-chart launch. */
export const INTERACTIVE_OAUTH = /\/oauth2\/[^?]*(\/login|patient-select|scope-authorize)/;

/** Records every URL any frame of the page navigates to. */
export function recordNavigations(page: Page): string[] {
  const seen: string[] = [];
  page.on("framenavigated", (f) => seen.push(f.url()));
  return seen;
}

/** The shell's `pat` frame showing demographics.php for this pid. */
export async function chartFrame(page: Page, pid: number): Promise<Frame> {
  let frame: Frame | undefined;
  await expect
    .poll(() => {
      frame = page.frames().find((f) => new RegExp(`demographics\\.php\\?set_pid=${String(pid)}(&|$)`).test(f.url()));
      return frame !== undefined;
    })
    .toBe(true);
  if (!frame) throw new Error("no pat frame");
  await frame.waitForLoadState("domcontentloaded");
  return frame;
}

/** The app frame the chart embeds, once the app has settled on its header and six cards. */
export async function embeddedApp(chart: Frame): Promise<Frame> {
  const iframe = chart.locator("#dashboard_smart_app");
  await expect(iframe).toHaveCount(1);
  const current = async (): Promise<Frame | null> => {
    const f = await (await iframe.elementHandle()).contentFrame();
    return f && URL.canParse(f.url()) && new URL(f.url()).pathname === "/public/dashboard/" ? f : null;
  };
  await expect.poll(async () => (await current()) !== null, { timeout: 30_000 }).toBe(true);
  const frame = await current();
  if (!frame) throw new Error("no app frame");
  await expect(frame.locator('[data-header-state="data"], [data-header-state="error"], [role="alert"]').first()).toBeVisible({ timeout: 30_000 });
  return frame;
}

export async function appSettled(app: Frame): Promise<void> {
  await expect(app.locator("[data-card]")).toHaveCount(6);
  await expect(app.locator('[data-state="loading"]')).toHaveCount(0);
  await expect(app.locator('[data-header-state="data"], [data-header-state="error"]')).toHaveCount(1);
}

/** Opens a patient as the calendar and the finder do: top.RTop.location = demographics.php?set_pid= */
export async function openViaRTop(page: Page, pid: number): Promise<void> {
  await page.evaluate((p) => {
    const w = window as unknown as { RTop: { location: string }; webroot_url: string; restoreSession: () => void };
    w.restoreSession();
    w.RTop.location = `${w.webroot_url}/interface/patient_file/summary/demographics.php?set_pid=${String(p)}`;
  }, pid);
}

/** Opens a shell tab (as the menu does) and activates it. */
export async function openShellTab(page: Page, path: string, name: string): Promise<void> {
  await page.evaluate(
    ([u, n]) => {
      const w = window as unknown as { navigateTab: (u: string, n: string, a: () => void) => void; activateTabByName: (n: string, h: boolean) => void; webroot_url: string };
      w.navigateTab(`${w.webroot_url}${u}`, n, () => {
        w.activateTabByName(n, true);
      });
    },
    [path, name] as const,
  );
}
