// Allergies card view model (spec section 5). R4: "active" for allergies is decided here only.
// R10: severe and high-criticality allergies are pinned to the top (TPL-AL-01).
import { z } from "zod";
import { CodeableConcept, conceptText, hasCode, optString } from "./common";
import { narrativeText } from "./narrative";

export const AllergyResource = z.looseObject({
  resourceType: z.literal("AllergyIntolerance"),
  id: z.string(),
  clinicalStatus: CodeableConcept.nullish(),
  verificationStatus: CodeableConcept.nullish(),
  criticality: optString,
  code: CodeableConcept.nullish(),
  text: z.looseObject({ div: optString }).nullish(),
  reaction: z
    .array(
      z.looseObject({
        severity: optString,
        manifestation: z.array(CodeableConcept).nullish().transform((v) => v ?? []),
      }),
    )
    .nullish()
    .transform((v) => v ?? []),
});
export type AllergyResource = z.infer<typeof AllergyResource>;

export interface AllergyView {
  readonly id: string;
  readonly substance: string;
  /** "Severe", "High criticality", ... or "" when neither is recorded (no empty "()", TPL-AL-02). */
  readonly severityLabel: string;
  readonly reactions: string;
  /** Severe reaction or high criticality: pinned first and highlighted. */
  readonly alarm: boolean;
}

export type AllergyList =
  | { readonly kind: "none-recorded" }
  | { readonly kind: "no-known-allergies" }
  | { readonly kind: "list"; readonly items: readonly AllergyView[] };

const SNOMED = "http://snomed.info/sct";
/** SNOMED "No known allergy" and its common siblings (drug, food, environmental). */
const NKA_CODES = new Set(["716186003", "409137002", "429625007", "428607008"]);
const DATA_ABSENT = "http://terminology.hl7.org/CodeSystem/data-absent-reason";

export function isActiveAllergy(a: AllergyResource): boolean {
  const verification = a.verificationStatus?.coding.map((c) => c.code) ?? [];
  if (verification.includes("entered-in-error") || verification.includes("refuted")) return false;
  return hasCode(a.clinicalStatus, "active");
}

function isNka(a: AllergyResource): boolean {
  return (a.code?.coding ?? []).some((c) => c.code !== undefined && NKA_CODES.has(c.code) && (c.system === undefined || c.system === SNOMED || c.system.includes("snomed")));
}

function substanceOf(a: AllergyResource): string {
  const coded = a.code && !hasCode(a.code, "unknown", DATA_ABSENT) ? conceptText(a.code) : "";
  return coded || narrativeText(a.text?.div) || "Unknown substance";
}

const SEVERITY_LABELS: Readonly<Record<string, string>> = { mild: "Mild", moderate: "Moderate", severe: "Severe" };
const CRITICALITY_LABELS: Readonly<Record<string, string>> = {
  high: "High criticality",
  low: "Low criticality",
  "unable-to-assess": "Criticality unknown",
};

export function toAllergyView(a: AllergyResource): AllergyView {
  const severe = a.reaction.some((r) => r.severity === "severe");
  const worst = severe ? "severe" : a.reaction.find((r) => r.severity === "moderate") ? "moderate" : a.reaction.find((r) => r.severity === "mild") ? "mild" : undefined;
  const parts = [worst ? SEVERITY_LABELS[worst] : undefined, a.criticality ? CRITICALITY_LABELS[a.criticality] : undefined].filter(
    (s): s is string => Boolean(s),
  );
  const reactions = a.reaction
    .flatMap((r) => r.manifestation.map((m) => (hasCode(m, "unknown", DATA_ABSENT) ? "" : conceptText(m))))
    .filter((s) => s !== "")
    .join(", ");
  return {
    id: a.id,
    substance: substanceOf(a),
    severityLabel: parts.join(", "),
    reactions,
    alarm: severe || a.criticality === "high",
  };
}

/** Active allergies, alarms first, otherwise in server order (the legacy card's order). */
export function toAllergyList(resources: readonly AllergyResource[]): AllergyList {
  const active = resources.filter(isActiveAllergy);
  const real = active.filter((a) => !isNka(a));
  if (real.length === 0) {
    return active.length > 0 ? { kind: "no-known-allergies" } : { kind: "none-recorded" };
  }
  const views = real.map(toAllergyView);
  return { kind: "list", items: [...views.filter((v) => v.alarm), ...views.filter((v) => !v.alarm)] };
}
