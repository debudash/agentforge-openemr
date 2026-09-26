// Problem List view model (spec section 5). R4: "active" for conditions is decided here only.
// The server's clinical-status search is not used: it returns nothing for Condition and fails
// with a 500 when combined with category (API-07), so the filter is applied to what comes back.
import { z } from "zod";
import { CodeableConcept, conceptText, hasCode, optString } from "./common";

export const ConditionResource = z.looseObject({
  resourceType: z.literal("Condition"),
  id: z.string(),
  clinicalStatus: CodeableConcept.nullish(),
  verificationStatus: CodeableConcept.nullish(),
  category: z.array(CodeableConcept).nullish().transform((v) => v ?? []),
  code: CodeableConcept.nullish(),
  onsetDateTime: optString,
});
export type ConditionResource = z.infer<typeof ConditionResource>;

export interface ConditionView {
  readonly id: string;
  readonly title: string;
}

export function isActiveProblem(c: ConditionResource): boolean {
  if (!c.category.some((cat) => hasCode(cat, "problem-list-item"))) return false;
  if (hasCode(c.verificationStatus, "entered-in-error") || hasCode(c.verificationStatus, "refuted")) return false;
  return hasCode(c.clinicalStatus, "active") || hasCode(c.clinicalStatus, "recurrence") || hasCode(c.clinicalStatus, "relapse");
}

/** Parity is title only (TPL-MP-01), in server order. */
export function toProblemList(resources: readonly ConditionResource[]): readonly ConditionView[] {
  return resources.filter(isActiveProblem).map((c) => ({ id: c.id, title: conceptText(c.code) || "Unnamed problem" }));
}
