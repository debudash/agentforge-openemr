// Medications (intent=plan, the medication list) and Prescriptions (intent=order, the
// prescriptions table) view models (spec section 5). R4: "active" is decided here only.
import { z } from "zod";
import { CodeableConcept, Quantity, Reference, conceptText, optString } from "./common";

// OpenEMR sometimes sends `dosageInstruction: [[]]`; each element is parsed on its own and
// anything that is not an object is ignored rather than failing the whole resource.
const Dosage = z.looseObject({
  text: optString,
  route: CodeableConcept.nullish(),
  timing: z.looseObject({ code: CodeableConcept.nullish() }).nullish(),
  doseAndRate: z
    .array(z.looseObject({ doseQuantity: Quantity.nullish() }))
    .nullish()
    .transform((v) => v ?? []),
});
type Dosage = z.infer<typeof Dosage>;

const DosageList = z
  .array(z.unknown())
  .nullish()
  .transform((v) =>
    (v ?? []).flatMap((d): Dosage[] => {
      const parsed = Dosage.safeParse(d);
      return parsed.success && !Array.isArray(d) ? [parsed.data] : [];
    }),
  );

export const MedicationRequestResource = z.looseObject({
  resourceType: z.literal("MedicationRequest"),
  id: z.string(),
  status: optString,
  intent: optString,
  medicationCodeableConcept: CodeableConcept.nullish(),
  medicationReference: Reference.nullish(),
  authoredOn: optString,
  requester: Reference.nullish(),
  dosageInstruction: DosageList,
  dispenseRequest: z
    .looseObject({
      numberOfRepeatsAllowed: z.number().nullish().transform((v) => v ?? undefined),
      quantity: Quantity.nullish(),
    })
    .nullish(),
});
export type MedicationRequestResource = z.infer<typeof MedicationRequestResource>;

export function isActiveRequest(m: MedicationRequestResource): boolean {
  return m.status === "active";
}

export function medicationName(m: MedicationRequestResource): string {
  return conceptText(m.medicationCodeableConcept) || m.medicationReference?.display?.trim() || "Unnamed medication";
}

const quantityText = (q: Quantity | null | undefined): string =>
  q?.value === undefined ? "" : [String(q.value), q.unit ?? ""].filter((s) => s.trim() !== "").join(" ");

/** Dose, SIG, route, frequency: every part separated by a space (TPL-ER-01). */
export function dosageDetails(m: MedicationRequestResource): string {
  const d = m.dosageInstruction[0];
  if (!d) return "";
  return [quantityText(d.doseAndRate[0]?.doseQuantity), d.text ?? "", conceptText(d.route), conceptText(d.timing?.code)]
    .map((s) => s.trim())
    .filter((s) => s !== "")
    .join(" ");
}

export interface MedicationView {
  readonly id: string;
  readonly name: string;
  /** dosageInstruction[0].text, always from this one source (TPL-MD-01). */
  readonly instructions: string;
}

export function toMedicationList(resources: readonly MedicationRequestResource[]): readonly MedicationView[] {
  return resources
    .filter((m) => m.intent === "plan" && isActiveRequest(m))
    .map((m) => ({ id: m.id, name: medicationName(m), instructions: m.dosageInstruction[0]?.text?.trim() ?? "" }));
}

export interface PrescriptionView {
  readonly id: string;
  readonly drug: string;
  readonly details: string;
  readonly quantity: string;
  readonly refills: string;
  readonly dateWritten: string | undefined;
  /** Practitioner/<id> when the prescriber is a practitioner; resolved to a name by the card. */
  readonly prescriberRef: string | undefined;
}

export function toPrescriptionList(resources: readonly MedicationRequestResource[]): readonly PrescriptionView[] {
  return resources
    .filter((m) => m.intent === "order" && isActiveRequest(m))
    .map((m) => ({
      id: m.id,
      drug: medicationName(m),
      details: dosageDetails(m),
      quantity: quantityText(m.dispenseRequest?.quantity),
      refills: m.dispenseRequest?.numberOfRepeatsAllowed === undefined ? "" : String(m.dispenseRequest.numberOfRepeatsAllowed),
      dateWritten: m.authoredOn,
      prescriberRef: m.requester?.reference?.startsWith("Practitioner/") ? m.requester.reference : undefined,
    }));
}
