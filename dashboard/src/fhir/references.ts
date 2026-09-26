// Names for the references cards show (care team members, prescribers, facilities).
import { z } from "zod";
import { HumanName, displayName, optString } from "./common";
import { narrativeText } from "./narrative";

const Named = z.looseObject({
  resourceType: z.enum(["Practitioner", "RelatedPerson", "Organization"]),
  id: z.string(),
  name: z.union([z.array(HumanName), z.string()]).nullish(),
  text: z.looseObject({ div: optString }).nullish(),
});
export const NamedResource = Named;
export type NamedResource = z.infer<typeof Named>;

export function nameOf(r: NamedResource): string {
  if (typeof r.name === "string") return r.name.trim();
  const fromName = r.name ? displayName(r.name) : "";
  return fromName || narrativeText(r.text?.div);
}

/** Only relative references to the types above are followed; anything else is not fetched. */
export function isResolvable(ref: string | undefined): ref is string {
  return ref !== undefined && /^(Practitioner|RelatedPerson|Organization)\/[A-Za-z0-9\-.]{1,64}$/.test(ref);
}
