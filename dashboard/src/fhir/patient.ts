// Patient header view model (spec section 5, "Patient header").
import { z } from "zod";
import { CodeableConcept, HumanName, displayName, optString } from "./common";
import {
  deceasedText,
  formatAge,
  formatAgeAtDeath,
  formatDate,
  today,
  type CalendarDate,
  type DateOrder,
} from "../format/dates";

export const PatientResource = z.looseObject({
  resourceType: z.literal("Patient"),
  id: z.string(),
  name: z.array(HumanName).nullish().transform((v) => v ?? []),
  birthDate: optString,
  gender: optString,
  deceasedBoolean: z.boolean().nullish().transform((v) => v ?? undefined),
  deceasedDateTime: optString,
  identifier: z
    .array(z.looseObject({ type: CodeableConcept.nullish(), value: optString }))
    .nullish()
    .transform((v) => v ?? []),
});
export type PatientResource = z.infer<typeof PatientResource>;

export type PatientStatus =
  | { readonly kind: "active"; readonly label: "Active" }
  | { readonly kind: "deceased"; readonly label: string };

export interface PatientView {
  readonly id: string;
  readonly name: string;
  readonly dob: string;
  /** "Age: 45", or "Age at death: 70" when deceased. */
  readonly ageLabel: "Age" | "Age at death";
  readonly age: string;
  readonly sex: string;
  readonly mrn: string;
  readonly status: PatientStatus;
}

const SEX_LABELS: Readonly<Record<string, string>> = {
  male: "Male",
  female: "Female",
  other: "Other",
  unknown: "Unknown",
};

/** MRN = the identifier typed PT (v2-0203), i.e. OpenEMR's pubpid. */
export function mrnOf(p: PatientResource): string {
  const pt = p.identifier.find((i) => (i.type?.coding ?? []).some((c) => c.code === "PT"));
  return pt?.value ?? "";
}

/**
 * Status is NOT Patient.active, which OpenEMR always sends as true (API-02). It is "Active"
 * unless the patient is deceased, worded as the legacy deceased banner is.
 */
export function toPatientView(p: PatientResource, order: DateOrder = "ymd", asOf: CalendarDate = today()): PatientView {
  const deathDate = p.deceasedDateTime;
  const deceased = Boolean(deathDate) || p.deceasedBoolean === true;
  return {
    id: p.id,
    name: displayName(p.name),
    dob: formatDate(p.birthDate, order),
    ageLabel: deceased ? "Age at death" : "Age",
    age: deceased ? formatAgeAtDeath(p.birthDate, deathDate) : formatAge(p.birthDate, asOf),
    sex: SEX_LABELS[p.gender ?? ""] ?? "Unknown",
    mrn: mrnOf(p),
    status: deceased ? { kind: "deceased", label: deceasedText(deathDate, order, asOf) } : { kind: "active", label: "Active" },
  };
}
