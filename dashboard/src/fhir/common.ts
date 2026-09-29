// R4: shared FHIR datatypes, parsed leniently. Only what the cards read is declared; every
// field is optional because OpenEMR omits (or nulls) most of them. Unknown keys pass through.
import { z } from "zod";

const optString = z.string().nullish().transform((v) => v ?? undefined);

export const Coding = z.looseObject({
  system: optString,
  code: optString,
  display: optString,
});
export type Coding = z.infer<typeof Coding>;

export const CodeableConcept = z.looseObject({
  coding: z.array(Coding).nullish().transform((v) => v ?? []),
  text: optString,
});
export type CodeableConcept = z.infer<typeof CodeableConcept>;

export const Reference = z.looseObject({
  reference: optString,
  display: optString,
  type: optString,
});
export type Reference = z.infer<typeof Reference>;

export const Period = z.looseObject({ start: optString, end: optString });

export const Quantity = z.looseObject({
  value: z.number().nullish().transform((v) => v ?? undefined),
  unit: optString,
  code: optString,
});
export type Quantity = z.infer<typeof Quantity>;

export const HumanName = z.looseObject({
  use: optString,
  text: optString,
  family: optString,
  given: z.array(z.string()).nullish().transform((v) => v ?? []),
});
export type HumanName = z.infer<typeof HumanName>;

export { optString };

/** The text a clinician would read for a concept: its text, else the first display, else the code. */
export function conceptText(c: CodeableConcept | undefined | null): string {
  if (!c) return "";
  if (c.text?.trim()) return c.text.trim();
  for (const coding of c.coding) {
    if (coding.display?.trim()) return coding.display.trim();
  }
  for (const coding of c.coding) {
    if (coding.code?.trim()) return coding.code.trim();
  }
  return "";
}

export function hasCode(c: CodeableConcept | undefined | null, code: string, system?: string): boolean {
  return (c?.coding ?? []).some((x) => x.code === code && (system === undefined || x.system === system));
}

/** "Given Family", as the legacy identity bar shows it (fname + " " + lname). */
export function displayName(names: readonly HumanName[]): string {
  const name = names.find((n) => n.use === "official") ?? names[0];
  if (!name) return "";
  const built = [name.given.join(" "), name.family ?? ""].filter((s) => s.trim() !== "").join(" ");
  return built || name.text?.trim() || "";
}
