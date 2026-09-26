// Vitals view model (ADR 0003, spec section 5): the latest set, which OpenEMR records as one
// vitals form and exposes as Observations sharing that form's effectiveDateTime.
import { z } from "zod";
import { CodeableConcept, Quantity, conceptText, optString } from "./common";

export const ObservationResource = z.looseObject({
  resourceType: z.literal("Observation"),
  id: z.string(),
  status: optString,
  code: CodeableConcept.nullish(),
  effectiveDateTime: optString,
  valueQuantity: Quantity.nullish(),
  component: z
    .array(z.looseObject({ code: CodeableConcept.nullish(), valueQuantity: Quantity.nullish() }))
    .nullish()
    .transform((v) => v ?? []),
});
export type ObservationResource = z.infer<typeof ObservationResource>;

export interface VitalRow {
  readonly key: string;
  readonly label: string;
  readonly value: string;
}

export interface VitalsView {
  readonly takenAt: string;
  readonly rows: readonly VitalRow[];
}

// Display order follows the legacy vitals report.
const SINGLE: readonly (readonly [string, string, readonly string[]])[] = [
  ["weight", "Weight", ["29463-7"]],
  ["height", "Height", ["8302-2"]],
  ["pulse", "Pulse", ["8867-4"]],
  ["respiration", "Respiration", ["9279-1"]],
  ["temperature", "Temperature", ["8310-5"]],
  ["spo2", "Oxygen saturation", ["59408-5", "2708-6"]],
  ["bmi", "BMI", ["39156-5"]],
  ["head", "Head circumference", ["9843-4", "8287-5"]],
];
const BP_PANEL = "85354-9";
const SYSTOLIC = "8480-6";
const DIASTOLIC = "8462-4";

const codeOf = (o: { code?: z.infer<typeof CodeableConcept> | null | undefined }): readonly string[] =>
  (o.code?.coding ?? []).map((c) => c.code ?? "");

function number(q: z.infer<typeof Quantity> | null | undefined): string {
  if (q?.value === undefined) return "";
  const v = Math.round(q.value * 100) / 100;
  return String(v);
}

/** UCUM codes OpenEMR sends as the unit, shown the way the legacy report writes them. */
const UNIT_LABELS: Readonly<Record<string, string>> = {
  in_i: "in",
  "[in_i]": "in",
  "[lb_av]": "lb",
  lb_av: "lb",
  Cel: "°C",
  "[degF]": "°F",
  degF: "°F",
  "kg/m2": "kg/m²",
  "mm[Hg]": "mmHg",
};

export function unitLabel(unit: string | undefined): string {
  const u = (unit ?? "").trim();
  return UNIT_LABELS[u] ?? u;
}

function withUnit(q: z.infer<typeof Quantity> | null | undefined): string {
  const n = number(q);
  if (!n) return "";
  const unit = unitLabel(q?.unit ?? q?.code);
  return unit ? `${n} ${unit}` : n;
}

export function toVitalsView(observations: readonly ObservationResource[]): VitalsView | null {
  const usable = observations.filter((o) => o.status !== "entered-in-error" && o.status !== "cancelled" && o.effectiveDateTime);
  if (usable.length === 0) return null;
  // ISO instants sort as strings; the latest form wins.
  const takenAt = usable.map((o) => o.effectiveDateTime ?? "").sort().at(-1) ?? "";
  const latest = usable.filter((o) => o.effectiveDateTime === takenAt);
  const rows: VitalRow[] = [];

  const bp = latest.find((o) => codeOf(o).includes(BP_PANEL));
  if (bp) {
    const sys = bp.component.find((c) => codeOf(c).includes(SYSTOLIC))?.valueQuantity;
    const dia = bp.component.find((c) => codeOf(c).includes(DIASTOLIC))?.valueQuantity;
    const s = number(sys);
    const d = number(dia);
    if (s || d) {
      const unit = unitLabel(sys?.unit ?? dia?.unit);
      rows.push({ key: "bp", label: "Blood pressure", value: `${s || "?"}/${d || "?"}${unit ? ` ${unit}` : ""}` });
    }
  }
  for (const [key, label, codes] of SINGLE) {
    const obs = latest.find((o) => codeOf(o).some((c) => codes.includes(c)) && o.valueQuantity?.value !== undefined);
    if (obs) rows.push({ key, label, value: withUnit(obs.valueQuantity) });
  }
  // Anything else recorded in the same set, so nothing charted is hidden.
  const known = new Set([BP_PANEL, SYSTOLIC, DIASTOLIC, ...SINGLE.flatMap(([, , c]) => c)]);
  for (const o of latest) {
    if (o.valueQuantity?.value === undefined || codeOf(o).some((c) => known.has(c))) continue;
    rows.push({ key: o.id, label: conceptText(o.code) || "Other", value: withUnit(o.valueQuantity) });
  }
  return { takenAt, rows };
}
