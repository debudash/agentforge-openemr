// Characterization tests for accepted constraints (ADR 0010). Each one proves a limit exists on
// the stack today. It is expected to FAIL once upstream fixes the API; that failure is the
// signal to remove the test, the constraint row and the chart guard that works around it.
import { test, expect } from "@playwright/test";
import { restrictedPasswords, stackPatients } from "./support/env";
import { signInToDashboard } from "./support/smart";

test("known-limit: patient-scoped token skips the user's ACL (API-11, BUG-110)", async ({ page }) => {
  // dash-demoview holds patients/demo view only (ADR 0005). The legacy cards hide the clinical
  // record from this user; the FHIR API, for a patient/-scoped token, does not check patients/med
  // (HttpRestRouteHandler.php L62-67, FhirGenericRestController.php L93-102).
  const clinical = new Map<string, number>();
  page.on("response", (r) => {
    const m = /\/apis\/default\/fhir\/(Condition|AllergyIntolerance|MedicationRequest|Observation)\?/.exec(r.url());
    if (m?.[1]) clinical.set(m[1], r.status());
  });
  const pid1 = stackPatients().find((p) => p.pid === 1);
  if (!pid1) throw new Error("no pid 1 on the stack");
  await signInToDashboard(page, pid1.uuid, "dash-demoview", restrictedPasswords()["dash-demoview"] ?? "");

  expect([...clinical.keys()].sort()).toEqual(["AllergyIntolerance", "Condition", "MedicationRequest", "Observation"]);
  for (const [type, status] of clinical) expect(status, `${type}: the API now refuses; the limit is fixed`).toBe(200);
  await expect(page.locator('[data-card="problems"]')).toHaveAttribute("data-state", "data");
  await expect(page.locator('[data-card="problems"]')).toContainText("Essential hypertension");
});
