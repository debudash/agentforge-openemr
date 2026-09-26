// Care Team view model (spec section 5). Members are references; their names come from
// Practitioner / RelatedPerson reads, and the facility from the Organization the member acts for.
import { z } from "zod";
import { CodeableConcept, Period, Reference, conceptText, optString } from "./common";

export const CareTeamResource = z.looseObject({
  resourceType: z.literal("CareTeam"),
  id: z.string(),
  status: optString,
  name: optString,
  participant: z
    .array(
      z.looseObject({
        role: z.array(CodeableConcept).nullish().transform((v) => v ?? []),
        member: Reference.nullish(),
        onBehalfOf: Reference.nullish(),
        period: Period.nullish(),
      }),
    )
    .nullish()
    .transform((v) => v ?? []),
});
export type CareTeamResource = z.infer<typeof CareTeamResource>;

export type MemberKind = "provider" | "related-person";

export interface CareTeamMemberView {
  readonly key: string;
  readonly kind: MemberKind;
  /** Practitioner/<id> or RelatedPerson/<id>; the card resolves it to a name. */
  readonly memberRef: string;
  readonly memberDisplay: string | undefined;
  readonly role: string;
  readonly facilityRef: string | undefined;
  readonly since: string | undefined;
  readonly until: string | undefined;
}

export interface CareTeamView {
  readonly id: string;
  readonly name: string;
  readonly status: string;
  readonly members: readonly CareTeamMemberView[];
}

const STATUS_LABELS: Readonly<Record<string, string>> = {
  active: "Active",
  proposed: "Proposed",
  suspended: "Suspended",
  inactive: "Inactive",
  "entered-in-error": "Entered in error",
};

/**
 * The patient's own participant and facility-as-member rows are not shown: the legacy card
 * lists providers and related persons only, with the facility as a column.
 */
export function toCareTeamView(t: CareTeamResource): CareTeamView {
  const members = t.participant.flatMap((p, i): CareTeamMemberView[] => {
    const ref = p.member?.reference ?? "";
    const kind: MemberKind | undefined = ref.startsWith("Practitioner/")
      ? "provider"
      : ref.startsWith("RelatedPerson/")
        ? "related-person"
        : undefined;
    if (!kind) return [];
    return [
      {
        key: `${t.id}-${String(i)}`,
        kind,
        memberRef: ref,
        memberDisplay: p.member?.display ?? undefined,
        role: p.role.map(conceptText).filter((s) => s !== "").join(", "),
        facilityRef: p.onBehalfOf?.reference?.startsWith("Organization/") ? p.onBehalfOf.reference : undefined,
        since: p.period?.start,
        until: p.period?.end,
      },
    ];
  });
  return {
    id: t.id,
    name: t.name ?? "Care team",
    status: STATUS_LABELS[t.status ?? ""] ?? (t.status ?? ""),
    members,
  };
}

/** Active teams only, as the legacy card shows the patient's active team (spec section 5, `status=active`). */
export function toCareTeams(resources: readonly CareTeamResource[]): readonly CareTeamView[] {
  return resources.filter((t) => t.status === "active").map(toCareTeamView);
}
