// Parity rules (spec section 7): the same items, the same order rules and the same empty state,
// or a difference that matches a documented rule. Each difference is explained from the
// patient's own rows in the database, not by assumption; anything left over is unexplained.
import { sql } from "./env";
import type { LegacyCards } from "./legacy";
import type { PortCards } from "./port";

export type Verdict = "match" | "explained" | "unexplained" | "flagged";

export interface Difference {
  readonly what: string;
  readonly rule: string | null;
  /** Flagged: explained by an API constraint, but a clinician would see something different. */
  readonly flagged?: boolean;
}

export interface CardResult {
  readonly card: string;
  readonly verdict: Verdict;
  readonly legacy: readonly string[];
  readonly port: readonly string[];
  readonly differences: readonly Difference[];
}

const norm = (s: string) => s.replace(/\s+/g, " ").trim().toLowerCase();

function verdictOf(diffs: readonly Difference[]): Verdict {
  if (diffs.length === 0) return "match";
  if (diffs.some((d) => d.rule === null)) return "unexplained";
  if (diffs.some((d) => d.flagged)) return "flagged";
  return "explained";
}

const q = (s: string) => `'${s.replace(/\\/g, "\\\\").replace(/'/g, "\\'")}'`;

interface ListRow {
  readonly title: string;
  readonly outcome: number;
  readonly occurrence: number;
  readonly activity: number;
  readonly enddate: string;
}

function listRows(pid: number, type: string, title: string): ListRow[] {
  return sql(
    `SELECT title, IFNULL(outcome,0), IFNULL(occurrence,0), IFNULL(activity,0), IFNULL(enddate,'') FROM lists WHERE pid=${String(pid)} AND type=${q(type)} AND title=${q(title)}`,
  ).map(([t, o, oc, a, e]) => ({ title: t ?? "", outcome: Number(o), occurrence: Number(oc), activity: Number(a), enddate: e ?? "" }));
}

const past = (d: string) => d !== "" && new Date(d.replace(" ", "T")) <= new Date();
const future = (d: string) => d !== "" && !past(d);

/** Why an issue row is active on one side and not the other (BUG-028: three definitions of active). */
function explainListItem(type: "allergy" | "medical_problem" | "medication", row: ListRow, side: "legacy-only" | "port-only"): string | null {
  const legacyActive = row.outcome !== 1 && (row.enddate === "" || future(row.enddate));
  let fhirActive: boolean;
  let fhirRule: string;
  switch (type) {
    case "allergy":
      fhirActive = row.enddate === "";
      fhirRule = "API: AllergyIntolerance is active only while enddate is empty (FhirAllergyIntoleranceService L117-121)";
      break;
    case "medical_problem":
      fhirActive = !past(row.enddate) && row.outcome !== 1 && row.occurrence !== 1;
      fhirRule = "API: Condition is resolved when outcome=1 or occurrence=1, inactive when enddate has passed (FhirConditionTrait::computeClinicalStatus)";
      break;
    case "medication":
      fhirActive = row.activity === 1 && row.enddate === "";
      fhirRule = "API: a medication-list MedicationRequest is active only with activity=1 and no enddate (PrescriptionService L235-236)";
      break;
  }
  // An end date still in the future is a current entry the API reports as ended: not a rule.
  if (future(row.enddate) && type !== "medical_problem") return null;
  if (side === "legacy-only" && legacyActive && !fhirActive) return `R4/BUG-028 (one definition of active): ${fhirRule}; the legacy card uses outcome and enddate only`;
  if (side === "port-only" && fhirActive && !legacyActive) return `R4/BUG-028 (one definition of active): ${fhirRule}; the legacy card hides it (outcome=${String(row.outcome)}, enddate=${row.enddate || "none"})`;
  return null;
}

function compareIssueList(
  card: string,
  type: "allergy" | "medical_problem" | "medication",
  pid: number,
  legacy: { empty: string | null; items: readonly string[] } | null,
  port: { state: string; text: string; items: readonly string[] } | undefined,
): CardResult {
  const diffs: Difference[] = [];
  const legacyItems = legacy?.items ?? [];
  const portItems = port?.items ?? [];
  if (!legacy) diffs.push({ what: "legacy card not rendered", rule: null });
  if (!port || port.state === "error") diffs.push({ what: `port card state ${port?.state ?? "missing"}`, rule: null });

  const lSet = new Map(legacyItems.map((i) => [norm(i), i]));
  const pSet = new Map(portItems.map((i) => [norm(i), i]));
  for (const [k, item] of lSet) {
    if (pSet.has(k)) continue;
    const rows = listRows(pid, type, item);
    const why = rows.map((r) => explainListItem(type, r, "legacy-only")).find((r) => r !== null) ?? null;
    diffs.push({ what: `only in legacy: ${item}`, rule: why });
  }
  for (const [k, item] of pSet) {
    if (lSet.has(k)) continue;
    const rows = listRows(pid, type, item);
    const why = rows.map((r) => explainListItem(type, r, "port-only")).find((r) => r !== null) ?? null;
    diffs.push({ what: `only in port: ${item}`, rule: why });
  }

  // Order: the common items in the same relative order, except allergies, where the port pins
  // severe / high-criticality entries first (R10, TPL-AL-01).
  const common = legacyItems.filter((i) => pSet.has(norm(i))).map(norm);
  const portCommon = portItems.filter((i) => lSet.has(norm(i))).map(norm);
  if (common.join("|") !== portCommon.join("|")) {
    diffs.push({
      what: "different order",
      rule: type === "allergy" ? "R10/TPL-AL-01: severe and high-criticality allergies pinned first" : null,
    });
  }

  // Empty state wording: the legacy card uses list_touch, which FHIR does not carry (API-03).
  if (legacyItems.length === 0 && portItems.length === 0 && legacy && port) {
    const lEmpty = legacy.empty ?? "";
    const pEmpty = port.text;
    if (norm(lEmpty) !== norm(pEmpty)) {
      diffs.push({ what: `empty state "${lEmpty}" vs "${pEmpty}"`, rule: "API-03/BUG-014: the legacy wording depends on list_touch, which FHIR does not carry; the port says 'No allergies recorded' (allergies) or 'None'" });
    }
  }
  return { card, verdict: verdictOf(diffs), legacy: legacyItems, port: portItems, differences: diffs };
}

function comparePrescriptions(pid: number, legacy: LegacyCards["prescriptions"], port: PortCards["cards"][string] | undefined): CardResult {
  const diffs: Difference[] = [];
  const legacyItems = legacy?.items ?? [];
  const portItems = port?.items ?? [];
  if (!port || port.state === "error") diffs.push({ what: `port card state ${port?.state ?? "missing"}`, rule: null });
  const remaining = [...portItems.map(norm)];
  for (const item of legacyItems) {
    const i = remaining.indexOf(norm(item));
    if (i >= 0) {
      remaining.splice(i, 1);
      continue;
    }
    const rows = sql(`SELECT IFNULL(end_date,''), active FROM prescriptions WHERE patient_id=${String(pid)} AND drug=${q(item)}`);
    // Explained only when the end date has passed. A future end date would still be a current
    // prescription, which the API would wrongly report completed: that stays unexplained.
    const ended = rows.some(([end, active]) => active === "1" && end !== undefined && end !== "" && past(end));
    diffs.push({
      what: `only in legacy: ${item}`,
      rule: ended
        ? "R4/BUG-028 (one definition of active): the prescription has an end date, so the API reports it completed; the legacy card lists every row with active=1"
        : null,
    });
  }
  for (const item of remaining) diffs.push({ what: `only in port: ${item}`, rule: null });
  if (legacyItems.length === 0 && portItems.length === 0 && legacy && port && norm(legacy.empty ?? "") !== norm(port.text)) {
    diffs.push({ what: `empty state "${legacy.empty ?? ""}" vs "${port.text}"`, rule: null });
  }
  return { card: "prescriptions", verdict: verdictOf(diffs), legacy: legacyItems, port: portItems, differences: diffs };
}

function compareCareTeam(pid: number, legacy: LegacyCards["careTeam"], port: PortCards["cards"][string] | undefined): CardResult {
  const diffs: Difference[] = [];
  const legacyItems = legacy?.items ?? [];
  const portItems = port?.items ?? [];
  if (!port || port.state === "error") diffs.push({ what: `port card state ${port?.state ?? "missing"}`, rule: null });
  // The legacy row copies the member's name from the edit form's option text, "Last, First"
  // (CTC-05); the port writes "Given Family" as the header does. Same person, compared as such.
  const person = (s: string) => {
    const m = /^([^,]+),\s*(.+)$/.exec(s.trim());
    return norm(m ? `${m[2] ?? ""} ${m[1] ?? ""}` : s);
  };
  const lSet = new Set(legacyItems.map(person));
  const pNames = portItems.map(person);
  for (const item of legacyItems) {
    if (!pNames.includes(person(item))) diffs.push({ what: `only in legacy: ${item}`, rule: null });
    else if (norm(item) !== person(item)) {
      diffs.push({ what: `name order "${item}"`, rule: "CTC-05: the legacy row copies the option text (Last, First); the port shows Given Family, as the header does" });
    }
  }
  for (const item of portItems) {
    if (lSet.has(person(item))) continue;
    const inactive = sql(
      `SELECT m.status FROM care_team_member m JOIN care_teams t ON t.id=m.care_team_id JOIN users u ON u.id=m.user_id WHERE t.pid=${String(pid)} AND CONCAT(u.fname,' ',u.lname)=${q(item)} AND m.status<>'active'`,
    );
    diffs.push({
      what: `only in port: ${item}`,
      rule: inactive.length
        ? "API-08: FHIR CareTeam participants carry no status, so a member marked inactive is listed; the legacy card lists active members only"
        : null,
      ...(inactive.length ? { flagged: true } : {}),
    });
  }
  return { card: "care-team", verdict: verdictOf(diffs), legacy: legacyItems, port: portItems, differences: diffs };
}

const VITAL_KEYS: Readonly<Record<string, string>> = {
  Weight: "weight",
  Height: "height",
  "Blood Pressure": "bp",
  Pulse: "pulse",
  Respiration: "respiration",
  Temperature: "temperature",
  "Oxygen Saturation": "spo2",
  BMI: "bmi",
  "Head Circumference": "head",
};
const IGNORED_VITAL_LABELS = new Set(["Last Updated", "BMI Status", "Temp Location", "Note", "Waist Circumference", "Oxygen Flow Rate", "Inhaled Oxygen Concentration"]);

function firstNumbers(s: string): number[] {
  return [...s.matchAll(/-?\d+(?:\.\d+)?/g)].map((m) => Number(m[0]));
}

function compareVitals(legacy: LegacyCards["vitals"], port: PortCards): CardResult {
  const diffs: Difference[] = [];
  const legacyValues = legacy?.values ?? {};
  const portValues = port.vitals.values;
  if ((legacy?.date ?? null) !== port.vitals.date) diffs.push({ what: `date ${legacy?.date ?? "none"} vs ${port.vitals.date ?? "none"}`, rule: null });
  for (const [label, value] of Object.entries(legacyValues)) {
    if (IGNORED_VITAL_LABELS.has(label)) continue;
    const key = VITAL_KEYS[label];
    if (!key) {
      diffs.push({ what: `legacy row "${label}" has no port row`, rule: null });
      continue;
    }
    const p = portValues[key];
    if (p === undefined) {
      diffs.push({ what: `only in legacy: ${label} ${value}`, rule: null });
      continue;
    }
    const [l0, l1] = firstNumbers(value);
    const [p0, p1] = firstNumbers(p);
    const tolerance = key === "bmi" ? 0.5 : 0.051;
    const same = l0 !== undefined && p0 !== undefined && Math.abs(l0 - p0) <= tolerance && (key !== "bp" || l1 === p1);
    if (!same) diffs.push({ what: `${label}: legacy "${value}" vs port "${p}"`, rule: null });
    else if (key === "bmi" && l0 !== p0) {
      diffs.push({ what: `BMI ${value} vs ${p}`, rule: "R6: the port shows the recorded value; the legacy report rounds BMI to a whole number" });
    }
  }
  const legacyKeys = new Set(Object.keys(legacyValues).map((l) => VITAL_KEYS[l]));
  for (const [key, value] of Object.entries(portValues)) if (!legacyKeys.has(key)) diffs.push({ what: `only in port: ${key} ${value}`, rule: null });
  return {
    card: "vitals",
    verdict: verdictOf(diffs),
    legacy: Object.entries(legacyValues).map(([k, v]) => `${k}: ${v}`),
    port: Object.entries(portValues).map(([k, v]) => `${k}: ${v}`),
    differences: diffs,
  };
}

function compareHeader(legacy: LegacyCards["header"], port: PortCards["header"]): CardResult {
  const diffs: Difference[] = [];
  for (const f of ["name", "mrn", "dob", "age"] as const) {
    if (norm(legacy[f]) !== norm(port[f])) diffs.push({ what: `${f}: "${legacy[f]}" vs "${port[f]}"`, rule: f === "age" && /month/.test(legacy.age) ? "R6: months pluralised" : null });
  }
  if (!port.sex) diffs.push({ what: "port shows no sex", rule: null });
  if (!port.status) diffs.push({ what: "port shows no status", rule: null });
  return {
    card: "header",
    verdict: verdictOf(diffs),
    legacy: [legacy.name, legacy.mrn, legacy.dob, legacy.age],
    port: [port.name, port.mrn, port.dob, port.age, port.sex, port.status],
    differences: diffs,
  };
}

export function comparePatient(pid: number, legacy: LegacyCards, port: PortCards): CardResult[] {
  return [
    compareHeader(legacy.header, port.header),
    compareIssueList("allergies", "allergy", pid, legacy.allergies, port.cards.allergies),
    compareIssueList("problems", "medical_problem", pid, legacy.problems, port.cards.problems),
    compareIssueList("medications", "medication", pid, legacy.medications, port.cards.medications),
    comparePrescriptions(pid, legacy.prescriptions, port.cards.prescriptions),
    compareCareTeam(pid, legacy.careTeam, port.cards["care-team"]),
    compareVitals(legacy.vitals, port),
  ];
}
