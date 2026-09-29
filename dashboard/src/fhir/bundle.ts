// R4: search results are parsed entry by entry. An entry that fails its schema is counted, not
// dropped silently: a card must say "some entries could not be read" rather than show a shorter
// list as if it were complete (an unreadable allergy is still an allergy).
import { z } from "zod";
import { fhirGet, FhirHttpError, type FhirSession } from "./http";

const BundleLink = z.looseObject({ relation: z.string(), url: z.string() });
const Bundle = z.looseObject({
  resourceType: z.literal("Bundle"),
  entry: z
    .array(z.looseObject({ resource: z.unknown() }))
    .nullish()
    .transform((v) => v ?? []),
  link: z
    .array(BundleLink)
    .nullish()
    .transform((v) => v ?? []),
});

export interface Parsed<T> {
  readonly items: readonly T[];
  /** Entries of the right type that did not match the schema. */
  readonly unreadable: number;
  /** The server had more pages than the app reads (MAX_PAGES); the list is known to be incomplete. */
  readonly truncated: boolean;
}

/** OpenEMR truncates silently with _count (no next link, total rewritten), so it is never sent. */
const MAX_PAGES = 20;

export async function searchAll<T>(
  session: FhirSession,
  resourceType: string,
  params: Readonly<Record<string, string>>,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<Parsed<T>> {
  const query = new URLSearchParams({ patient: session.patientId, ...params });
  let next: string | undefined = `${resourceType}?${query.toString()}`;
  const items: T[] = [];
  let unreadable = 0;
  for (let page = 0; next !== undefined && page < MAX_PAGES; page += 1) {
    const raw = await fhirGet(session, next, signal);
    const bundle = Bundle.safeParse(raw);
    if (!bundle.success) throw new FhirHttpError(0, "invalid");
    for (const entry of bundle.data.entry) {
      const resource = entry.resource as { resourceType?: unknown } | null | undefined;
      if (resource?.resourceType !== resourceType) continue; // OperationOutcome, _include, etc.
      const parsed = schema.safeParse(resource);
      if (parsed.success) items.push(parsed.data);
      else unreadable += 1;
    }
    next = bundle.data.link.find((l) => l.relation === "next")?.url;
  }
  return { items, unreadable, truncated: next !== undefined };
}

export async function readOne<T>(
  session: FhirSession,
  path: string,
  schema: z.ZodType<T>,
  signal?: AbortSignal,
): Promise<T> {
  const raw = await fhirGet(session, path, signal);
  const parsed = schema.safeParse(raw);
  if (!parsed.success) throw new FhirHttpError(0, "invalid");
  return parsed.data;
}
