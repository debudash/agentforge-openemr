// One query per card (spec section 5): request -> schema -> view model. The view models are
// the only thing components receive (R4).
import { useQueries, useQuery, type UseQueryResult } from "@tanstack/react-query";
import { readOne, searchAll } from "../fhir/bundle";
import { FhirHttpError } from "../fhir/http";
import { AllergyResource, toAllergyList, type AllergyList } from "../fhir/allergy";
import { ConditionResource, toProblemList, type ConditionView } from "../fhir/condition";
import {
  MedicationRequestResource,
  toMedicationList,
  toPrescriptionList,
  type MedicationView,
  type PrescriptionView,
} from "../fhir/medicationRequest";
import { CareTeamResource, toCareTeams, type CareTeamView } from "../fhir/careTeam";
import { ObservationResource, toVitalsView, type VitalsView } from "../fhir/vitals";
import { PatientResource, toPatientView, type PatientView } from "../fhir/patient";
import { NamedResource, isResolvable, nameOf } from "../fhir/references";
import { useSession } from "./session";

export interface CardData<T> {
  readonly value: T;
  /** Entries the server sent that did not match the schema (R4, shown by the card). */
  readonly unreadable: number;
  /** More pages existed than were read; the card says the list is incomplete. */
  readonly truncated: boolean;
}

/** 401/403 and malformed responses are not retried: retrying cannot fix them. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof FhirHttpError && ["unauthorized", "forbidden", "invalid", "not_found"].includes(error.kind)) return false;
  return failureCount < 1;
}

export function usePatient(): UseQueryResult<PatientView> {
  const s = useSession();
  return useQuery({
    queryKey: ["Patient", s.patientId],
    queryFn: async ({ signal }) => toPatientView(await readOne(s, `Patient/${encodeURIComponent(s.patientId)}`, PatientResource, signal)),
  });
}

export function useAllergies(): UseQueryResult<CardData<AllergyList>> {
  const s = useSession();
  return useQuery({
    queryKey: ["AllergyIntolerance", s.patientId],
    queryFn: async ({ signal }) => {
      const r = await searchAll(s, "AllergyIntolerance", {}, AllergyResource, signal);
      return { value: toAllergyList(r.items), unreadable: r.unreadable, truncated: r.truncated };
    },
  });
}

export function useProblems(): UseQueryResult<CardData<readonly ConditionView[]>> {
  const s = useSession();
  return useQuery({
    queryKey: ["Condition", "problem-list-item", s.patientId],
    queryFn: async ({ signal }) => {
      const r = await searchAll(s, "Condition", { category: "problem-list-item" }, ConditionResource, signal);
      return { value: toProblemList(r.items), unreadable: r.unreadable, truncated: r.truncated };
    },
  });
}

export function useMedications(): UseQueryResult<CardData<readonly MedicationView[]>> {
  const s = useSession();
  return useQuery({
    queryKey: ["MedicationRequest", "plan", s.patientId],
    queryFn: async ({ signal }) => {
      const r = await searchAll(s, "MedicationRequest", { intent: "plan", status: "active" }, MedicationRequestResource, signal);
      return { value: toMedicationList(r.items), unreadable: r.unreadable, truncated: r.truncated };
    },
  });
}

export function usePrescriptions(): UseQueryResult<CardData<readonly PrescriptionView[]>> {
  const s = useSession();
  return useQuery({
    queryKey: ["MedicationRequest", "order", s.patientId],
    queryFn: async ({ signal }) => {
      const r = await searchAll(s, "MedicationRequest", { intent: "order", status: "active" }, MedicationRequestResource, signal);
      return { value: toPrescriptionList(r.items), unreadable: r.unreadable, truncated: r.truncated };
    },
  });
}

export function useCareTeams(): UseQueryResult<CardData<readonly CareTeamView[]>> {
  const s = useSession();
  return useQuery({
    queryKey: ["CareTeam", s.patientId],
    queryFn: async ({ signal }) => {
      const r = await searchAll(s, "CareTeam", {}, CareTeamResource, signal);
      return { value: toCareTeams(r.items), unreadable: r.unreadable, truncated: r.truncated };
    },
  });
}

export function useVitals(): UseQueryResult<CardData<VitalsView | null>> {
  const s = useSession();
  return useQuery({
    queryKey: ["Observation", "vital-signs", s.patientId],
    queryFn: async ({ signal }) => {
      const r = await searchAll(s, "Observation", { category: "vital-signs" }, ObservationResource, signal);
      return { value: toVitalsView(r.items), unreadable: r.unreadable, truncated: r.truncated };
    },
  });
}

/** Names for Practitioner / RelatedPerson / Organization references; unresolvable ones are skipped. */
export function useReferenceNames(refs: readonly (string | undefined)[]): ReadonlyMap<string, string> {
  const s = useSession();
  const unique = [...new Set(refs.filter(isResolvable))].sort();
  const results = useQueries({
    queries: unique.map((ref) => ({
      queryKey: ["ref", ref],
      queryFn: async ({ signal }: { signal: AbortSignal }) => nameOf(await readOne(s, ref, NamedResource, signal)),
      staleTime: 10 * 60_000,
    })),
  });
  const names = new Map<string, string>();
  unique.forEach((ref, i) => {
    const name = results[i]?.data;
    if (name) names.set(ref, name);
  });
  return names;
}

export function useSignedInUserName(): string | undefined {
  const s = useSession();
  const names = useReferenceNames([s.fhirUser]);
  return s.fhirUser ? names.get(s.fhirUser) : undefined;
}
