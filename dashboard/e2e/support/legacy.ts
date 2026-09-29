// Drives the legacy dashboard the way a user does: signed in to the tabs shell, with the patient
// opened in the `pat` tab (demographics.php calls parent.left_nav, so it is never loaded alone).
import { expect, type Frame, type Page } from "@playwright/test";
import { DOCTOR, doctorPassword } from "./env";

export async function signInToLegacy(page: Page, user = DOCTOR, password = doctorPassword()): Promise<void> {
  await page.goto("/interface/login/login.php?site=default");
  await page.fill("#authUser", user);
  await page.fill("#clearPass", password);
  await Promise.all([page.waitForURL(/\/interface\/main\/tabs\/main\.php/), page.click("#login-button")]);
  await page.waitForLoadState("networkidle");
}

/** Opens the patient in the shell's `pat` tab and returns that frame once its cards have loaded. */
export async function openLegacyPatient(page: Page, pid: number): Promise<Frame> {
  await page.evaluate((p) => {
    const w = window as unknown as {
      navigateTab: (url: string, name: string, after: () => void, label: string) => void;
      activateTabByName: (name: string, hide: boolean) => void;
      webroot_url: string;
    };
    w.navigateTab(`${w.webroot_url}/interface/patient_file/summary/demographics.php?set_pid=${String(p)}`, "pat", () => undefined, "Patient");
    w.activateTabByName("pat", true);
  }, pid);
  let frame: Frame | undefined;
  await expect
    .poll(() => {
      frame = page.frames().find((f) => f.url().includes(`demographics.php?set_pid=${String(pid)}`));
      return frame !== undefined;
    })
    .toBe(true);
  if (!frame) throw new Error("no pat frame");
  await frame.waitForLoadState("load");
  // The Vitals card is an AJAX fragment.
  await frame.waitForFunction(() => {
    const v = document.getElementById("vitals_ps_expand");
    return !v || /Most recent vitals|No vitals/.test(v.textContent);
  });
  // The identity bar in the shell is updated by setMyPatient() on load.
  await expect(page.locator(".ptName")).toContainText(/\(\S+\)/);
  return frame;
}

export interface LegacyCards {
  readonly header: { readonly name: string; readonly mrn: string; readonly dob: string; readonly age: string };
  readonly allergies: { readonly empty: string | null; readonly items: readonly string[] } | null;
  readonly problems: { readonly empty: string | null; readonly items: readonly string[] } | null;
  readonly medications: { readonly empty: string | null; readonly items: readonly string[] } | null;
  readonly prescriptions: { readonly empty: string | null; readonly items: readonly string[] } | null;
  readonly careTeam: { readonly empty: string | null; readonly items: readonly string[] } | null;
  readonly vitals: { readonly date: string | null; readonly values: Readonly<Record<string, string>> } | null;
}

export async function extractLegacy(page: Page, frame: Frame): Promise<LegacyCards> {
  const bar = await page.evaluate(() => {
    const name = document.querySelector(".ptName span")?.textContent.trim() ?? "";
    const mrn = document.querySelector(".ptName .text-muted span")?.textContent.trim() ?? "";
    const dobText = [...document.querySelectorAll("span")].map((s) => s.textContent).find((t) => /DOB:/.test(t)) ?? "";
    return { name, mrn, dobText };
  });
  const dob = /DOB:\s*(\S+)/.exec(bar.dobText)?.[1] ?? "";
  const age = /Age(?: at death)?:\s*(.+)$/.exec(bar.dobText.trim())?.[1]?.trim() ?? "";

  const cards = await frame.evaluate(() => {
    const clean = (s: string | null | undefined) => (s ?? "").replace(/\s+/g, " ").trim();
    const list = (id: string, itemSel: string, textOf: (el: Element) => string) => {
      const root = document.getElementById(id);
      if (!root) return null;
      const rows = [...root.querySelectorAll(itemSel)];
      const texts = rows.map(textOf);
      const empties = ["Nothing Recorded", "No Known Allergies", "None"];
      if (texts.length === 1 && empties.includes(texts[0] ?? "")) return { empty: texts[0] ?? null, items: [] };
      return { empty: null, items: texts };
    };
    // "Title (Severity)" -> "Title"; the severity is compared separately by the harness.
    const allergy = (el: Element) => clean(el.querySelector(".flex-fill")?.firstChild?.textContent ?? el.textContent).replace(/\s*\($/, "");
    const rxRoot = document.getElementById("prescriptions_ps_expand");
    let prescriptions: { empty: string | null; items: string[] } | null = null;
    if (rxRoot) {
      const rows = [...rxRoot.querySelectorAll("tbody tr")].map((tr) => clean(tr.querySelector("td")?.textContent));
      prescriptions = rows.length ? { empty: null, items: rows } : { empty: clean(rxRoot.textContent), items: [] };
    }
    const ctRoot = document.getElementById("careteam_ps_expand") ?? document.getElementById("care_team_table")?.closest("section") ?? null;
    let careTeam: { empty: string | null; items: string[] } | null = null;
    if (ctRoot) {
      const rows = [...ctRoot.querySelectorAll("#care_team_table tbody tr")].map((tr) => clean(tr.querySelectorAll("td")[1]?.querySelector(".viewOnly")?.textContent));
      careTeam = rows.length ? { empty: null, items: rows } : { empty: "none", items: [] };
    }
    const vRoot = document.getElementById("vitals_ps_expand");
    let vitals: { date: string | null; values: Record<string, string> } | null = null;
    if (vRoot) {
      const date = /Most recent vitals from:\s*(\d{4}-\d{2}-\d{2})/.exec(vRoot.textContent)?.[1] ?? null;
      const values: Record<string, string> = {};
      for (const tr of vRoot.querySelectorAll("table tr")) {
        const tds = tr.querySelectorAll("td");
        if (tds.length < 2) continue;
        values[clean(tds[0]?.textContent).replace(/:$/, "")] = clean(tds[1]?.textContent);
      }
      vitals = { date, values };
    }
    return {
      allergies: list("allergy_ps_expand", ".list-group-item", allergy),
      problems: list("medical_problem_ps_expand", ".list-group-item", (el) => clean(el.textContent)),
      medications: list("medication_ps_expand", ".list-group-item", (el) => clean(el.querySelector(".font-weight-normal")?.textContent ?? el.textContent)),
      prescriptions,
      careTeam,
      vitals,
    };
  });
  return { header: { name: bar.name, mrn: bar.mrn, dob, age }, ...cards };
}
