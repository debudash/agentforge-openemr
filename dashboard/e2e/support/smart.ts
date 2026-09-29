// Signs in to the new dashboard through the real SMART flow: the app's own button, OpenEMR's
// login page, the patient picker and the scope approval.
import { expect, type Page } from "@playwright/test";
import { DOCTOR, doctorPassword } from "./env";

export const APP = "/public/dashboard/";

export async function signInToDashboard(page: Page, patientUuid: string, user = DOCTOR, password = doctorPassword()): Promise<void> {
  await page.goto(APP);
  await page.getByRole("button", { name: "Sign in with OpenEMR" }).click();
  await page.waitForURL(/\/oauth2\/default\/provider\/login/);
  await page.fill("input[name=username]", user);
  await page.fill("input[name=password]", password);
  await page.click("button[name=user_role][value=api]");
  await page.waitForURL(/\/smart\/patient-select/);
  await page.click(`button[data-patient-id="${patientUuid}"]`);
  await page.waitForURL(/scope-authorize/);
  await page.click("#authorize-btn");
  await page.waitForURL((u) => u.pathname === APP);
  await dashboardSettled(page);
}

export async function dashboardSettled(page: Page): Promise<void> {
  await expect(page.locator("[data-card]")).toHaveCount(6);
  await expect(page.locator('[data-state="loading"]')).toHaveCount(0);
  await expect(page.locator('[data-header-state="data"], [data-header-state="error"]')).toHaveCount(1);
  // Reference names (care team members, prescribers) resolve after the card data.
  await page.waitForLoadState("networkidle");
}
