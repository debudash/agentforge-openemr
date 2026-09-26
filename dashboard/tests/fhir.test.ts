// R4 and R10: every resource is parsed by a schema into a view model, "active" is decided once
// per resource, and the clinical-safety rules are tested, not commented.
import { describe, expect, it } from "vitest";
import { AllergyResource, toAllergyList, type AllergyList } from "../src/fhir/allergy";
import { ConditionResource, toProblemList } from "../src/fhir/condition";
import { MedicationRequestResource, toMedicationList, toPrescriptionList } from "../src/fhir/medicationRequest";
import { PatientResource, toPatientView } from "../src/fhir/patient";
import { CareTeamResource, toCareTeams } from "../src/fhir/careTeam";
import { ObservationResource, toVitalsView } from "../src/fhir/vitals";
import { z } from "zod";
import { HumanName, displayName } from "../src/fhir/common";
import { recorded } from "./support";

const clinical = (code: string, system = "http://terminology.hl7.org/CodeSystem/allergyintolerance-clinical") => ({ coding: [{ system, code }] });

function allergy(id: string, extra: Record<string, unknown> = {}) {
  return AllergyResource.parse({
    resourceType: "AllergyIntolerance",
    id,
    clinicalStatus: clinical("active"),
    code: { coding: [{ display: `Substance ${id}` }] },
    ...extra,
  });
}

const items = (l: AllergyList) => (l.kind === "list" ? l.items.map((i) => i.substance) : l.kind);

describe("allergies", () => {
  it("pins severe and high-criticality allergies to the top (TPL-AL-01)", () => {
    const list = toAllergyList([
      allergy("a"),
      allergy("b", { criticality: "high" }),
      allergy("c", { criticality: "low" }),
      allergy("d", { reaction: [{ severity: "severe", manifestation: [{ text: "Anaphylaxis" }] }] }),
    ]);
    expect(items(list)).toEqual(["Substance b", "Substance d", "Substance a", "Substance c"]);
    expect(list.kind === "list" && list.items.filter((i) => i.alarm).map((i) => i.substance)).toEqual(["Substance b", "Substance d"]);
  });

  it("never renders an inactive, resolved, refuted or entered-in-error allergy (R4)", () => {
    const list = toAllergyList([
      allergy("inactive", { clinicalStatus: clinical("inactive") }),
      allergy("resolved", { clinicalStatus: clinical("resolved") }),
      allergy("refuted", { verificationStatus: { coding: [{ code: "refuted" }] } }),
      allergy("error", { verificationStatus: { coding: [{ code: "entered-in-error" }] } }),
      allergy("kept"),
    ]);
    expect(items(list)).toEqual(["Substance kept"]);
  });

  it("tells 'No Known Allergies' from 'nothing recorded' when the data allows (API-03)", () => {
    expect(toAllergyList([]).kind).toBe("none-recorded");
    const nka = allergy("nka", { code: { coding: [{ system: "http://snomed.info/sct", code: "716186003", display: "No known allergy" }] } });
    expect(toAllergyList([nka]).kind).toBe("no-known-allergies");
    expect(items(toAllergyList([nka, allergy("x")]))).toEqual(["Substance x"]);
  });

  it("omits the severity parentheses when nothing is recorded (TPL-AL-02)", () => {
    const list = toAllergyList([allergy("a")]);
    expect(list.kind === "list" && list.items[0]?.severityLabel).toBe("");
  });

  it("falls back to the narrative title when the substance is coded as data-absent", () => {
    const a = allergy("n", {
      code: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/data-absent-reason", code: "unknown", display: "Unknown" }] },
      text: { status: "additional", div: "<div xmlns='http://www.w3.org/1999/xhtml'>Peanut &amp; <b>tree nut</b></div>" },
    });
    expect(items(toAllergyList([a]))).toEqual(["Peanut & tree nut"]);
  });

  it("reads the recorded pid 3 bundle: 10 active allergies, none dropped as unreadable", () => {
    const b = recorded("pid3").AllergyIntolerance as { entry: { resource: unknown }[] };
    const parsed = b.entry.map((e) => AllergyResource.safeParse(e.resource));
    expect(parsed.every((p) => p.success)).toBe(true);
    const list = toAllergyList(parsed.flatMap((p) => (p.success ? [p.data] : [])));
    expect(list.kind === "list" && list.items.length).toBe(10);
  });
});

describe("problem list", () => {
  const cond = (id: string, status: string, extra: Record<string, unknown> = {}) =>
    ConditionResource.parse({
      resourceType: "Condition",
      id,
      clinicalStatus: { coding: [{ code: status }] },
      category: [{ coding: [{ code: "problem-list-item" }] }],
      code: { text: `Problem ${id}` },
      ...extra,
    });

  it("shows active problems only, by title (R4, TPL-MP-01)", () => {
    const list = toProblemList([
      cond("1", "active"),
      cond("2", "resolved"),
      cond("3", "inactive"),
      cond("4", "recurrence"),
      cond("5", "active", { verificationStatus: { coding: [{ code: "entered-in-error" }] } }),
      cond("6", "active", { category: [{ coding: [{ code: "encounter-diagnosis" }] }] }),
    ]);
    expect(list.map((p) => p.title)).toEqual(["Problem 1", "Problem 4"]);
  });
});

describe("medications and prescriptions", () => {
  const med = (id: string, intent: string, status: string, extra: Record<string, unknown> = {}) =>
    MedicationRequestResource.parse({
      resourceType: "MedicationRequest",
      id,
      intent,
      status,
      medicationCodeableConcept: { text: `Drug ${id}` },
      ...extra,
    });

  it("lists active intent=plan requests as Medications, with instructions from dosageInstruction[0].text (TPL-MD-01)", () => {
    const list = toMedicationList([
      med("1", "plan", "active", { dosageInstruction: [{ text: "1 tab daily" }] }),
      med("2", "plan", "completed"),
      med("3", "order", "active"),
      med("4", "plan", "stopped"),
    ]);
    expect(list).toEqual([{ id: "1", name: "Drug 1", instructions: "1 tab daily" }]);
  });

  it("puts a space between every part of a prescription's details (TPL-ER-01)", () => {
    const [rx] = toPrescriptionList([
      med("1", "order", "active", {
        dosageInstruction: [
          { text: "take with food", route: { text: "Oral" }, timing: { code: { text: "twice daily" } }, doseAndRate: [{ doseQuantity: { value: 10, unit: "mg" } }] },
        ],
        dispenseRequest: { numberOfRepeatsAllowed: 2, quantity: { value: 30, unit: "tablet" } },
        authoredOn: "2025-06-20T02:08:57+00:00",
        requester: { reference: "Practitioner/abc" },
      }),
    ]);
    expect(rx).toMatchObject({ details: "10 mg take with food Oral twice daily", quantity: "30 tablet", refills: "2", prescriberRef: "Practitioner/abc" });
  });

  it("survives OpenEMR's malformed dosageInstruction: [[]]", () => {
    const m = med("1", "order", "active", { dosageInstruction: [[]] });
    expect(toPrescriptionList([m])[0]?.details).toBe("");
  });

  it("does not follow a requester that is not a practitioner", () => {
    const m = med("1", "order", "active", { requester: { reference: "Organization/org" } });
    expect(toPrescriptionList([m])[0]?.prescriberRef).toBeUndefined();
  });
});

describe("patient header", () => {
  const patient = (extra: Record<string, unknown> = {}) =>
    PatientResource.parse({
      resourceType: "Patient",
      id: "p",
      active: true,
      name: [{ use: "official", family: "O'Brien", given: ["Siobhán"] }],
      birthDate: "1981-07-04",
      gender: "female",
      identifier: [
        { type: { coding: [{ code: "SS" }] }, value: "999-99-9999" },
        { type: { coding: [{ system: "http://terminology.hl7.org/CodeSystem/v2-0203", code: "PT" }] }, value: "1042" },
      ],
      ...extra,
    });
  const asOf = { year: 2026, month: 9, day: 25 };

  it("shows name, DOB, age, sex and the PT identifier as MRN, and nothing else (R8)", () => {
    const v = toPatientView(patient(), "ymd", asOf);
    expect(v).toMatchObject({ name: "Siobhán O'Brien", dob: "1981-07-04", ageLabel: "Age", age: "45", sex: "Female", mrn: "1042" });
    expect(JSON.stringify(v)).not.toContain("999-99-9999");
  });

  it("derives status from deceased fields, never from Patient.active (API-02)", () => {
    expect(toPatientView(patient({ active: false }), "ymd", asOf).status).toEqual({ kind: "active", label: "Active" });
    const dead = toPatientView(patient({ deceasedDateTime: "2026-09-24T10:00:00Z" }), "ymd", asOf);
    expect(dead.status).toEqual({ kind: "deceased", label: "Deceased - 2026-09-24 (1 day ago)" });
    expect(dead).toMatchObject({ ageLabel: "Age at death", age: "45" });
    expect(toPatientView(patient({ deceasedBoolean: true }), "ymd", asOf).status.label).toBe("Deceased");
  });

  it("labels sex from the value set and falls back to Unknown", () => {
    expect(toPatientView(patient({ gender: "male" })).sex).toBe("Male");
    expect(toPatientView(patient({ gender: undefined })).sex).toBe("Unknown");
  });

  it("builds 'Given Family' from the official name, as the legacy bar does", () => {
    const names = z.array(HumanName).parse([{ use: "usual", family: "X", given: ["Y"] }, { use: "official", family: "Dicki44", given: ["Adan632"] }]);
    expect(displayName(names)).toBe("Adan632 Dicki44");
  });
});

describe("care team", () => {
  it("lists providers and related persons, not the patient or the facility-as-member", () => {
    const [team] = toCareTeams([CareTeamResource.parse((recorded("pid1").CareTeam as { entry: { resource: unknown }[] }).entry[0]?.resource)]);
    expect(team?.name).toBe("Primary care team");
    expect(team?.status).toBe("Active");
    expect(team?.members.map((m) => [m.kind, m.memberRef.split("/")[0], m.role, m.since])).toEqual([
      ["provider", "Practitioner", "Physician", "2024-01-15"],
      ["provider", "Practitioner", "Nurse Practitioner", "2025-06-01"],
    ]);
  });

  it("shows active teams only", () => {
    const t = (id: string, status: string) => CareTeamResource.parse({ resourceType: "CareTeam", id, status, name: id });
    const teams = [t("old", "inactive"), t("bad", "entered-in-error"), t("now", "active"), t("maybe", "proposed"), t("paused", "suspended")];
    expect(toCareTeams(teams).map((x) => x.name)).toEqual(["now"]);
  });
});

describe("vitals", () => {
  const obs = (id: string, code: string, value: number, unit: string, when = "2018-09-22T01:28:41+00:00") =>
    ObservationResource.parse({ resourceType: "Observation", id, status: "final", code: { coding: [{ code }] }, effectiveDateTime: when, valueQuantity: { value, unit } });

  it("shows the latest set only, BP from its components, units as recorded", () => {
    const bp = ObservationResource.parse({
      resourceType: "Observation",
      id: "bp",
      status: "final",
      code: { coding: [{ code: "85354-9" }] },
      effectiveDateTime: "2018-09-22T01:28:41+00:00",
      component: [
        { code: { coding: [{ code: "8480-6" }] }, valueQuantity: { value: 120, unit: "mm[Hg]" } },
        { code: { coding: [{ code: "8462-4" }] }, valueQuantity: { value: 80, unit: "mm[Hg]" } },
      ],
    });
    const v = toVitalsView([obs("old", "8867-4", 60, "/min", "2017-01-01T00:00:00+00:00"), obs("p", "8867-4", 90, "/min"), obs("h", "8302-2", 173.7, "in_i"), bp]);
    expect(v?.takenAt).toBe("2018-09-22T01:28:41+00:00");
    expect(v?.rows.map((r) => [r.label, r.value])).toEqual([
      ["Blood pressure", "120/80 mmHg"],
      ["Height", "173.7 in"],
      ["Pulse", "90 /min"],
    ]);
  });

  it("is empty when nothing is recorded", () => {
    expect(toVitalsView([])).toBeNull();
  });
});
