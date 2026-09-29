// R6: the one place dates, times, ages and deceased wording are formatted.
// Rules follow the legacy helpers so the port reads the same:
//   age        PatientService::getPatientAge()   (months up to 24 months, then years)
//   age at death  oeFormatAge() format 0          (same thresholds, measured to the date of death)
//   deceased   deceasedDays() in demographics.php L282-305
// FHIR dates are calendar dates ("2026-09-25") or instants; both are read as calendar dates in
// local time, never through `new Date("YYYY-MM-DD")`, which is UTC and shifts the day west of it.

export type DateOrder = "ymd" | "mdy" | "dmy"; // OpenEMR date_display_format 0 / 1 / 2

export interface CalendarDate {
  readonly year: number;
  readonly month: number; // 1-12
  readonly day: number;
}

const DATE_PREFIX = /^(\d{4})-(\d{2})-(\d{2})/;

export function parseCalendarDate(value: string | undefined | null): CalendarDate | null {
  if (!value) return null;
  const m = DATE_PREFIX.exec(value);
  if (!m) return null;
  const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (month < 1 || month > 12 || day < 1 || day > 31) return null;
  return { year, month, day };
}

export function today(now: Date = new Date()): CalendarDate {
  return { year: now.getFullYear(), month: now.getMonth() + 1, day: now.getDate() };
}

const pad = (n: number): string => String(n).padStart(2, "0");

export function formatDate(value: string | undefined | null, order: DateOrder = "ymd"): string {
  const d = parseCalendarDate(value);
  if (!d) return "";
  const [y, m, dd] = [String(d.year), pad(d.month), pad(d.day)];
  switch (order) {
    case "ymd":
      return `${y}-${m}-${dd}`;
    case "mdy":
      return `${m}/${dd}/${y}`;
    case "dmy":
      return `${dd}/${m}/${y}`;
  }
}

/** 24-hour or 12-hour clock; midnight is 12:xx AM, noon 12:xx PM (DEM-09). */
export function formatTime(hours: number, minutes: number, clock: "24h" | "12h" = "24h"): string {
  if (clock === "24h") return `${pad(hours)}:${pad(minutes)}`;
  const meridiem = hours < 12 ? "AM" : "PM";
  const h12 = hours % 12 === 0 ? 12 : hours % 12;
  return `${String(h12)}:${pad(minutes)} ${meridiem}`;
}

function monthsBetween(from: CalendarDate, to: CalendarDate): number {
  let months = (to.year * 12 + to.month) - (from.year * 12 + from.month);
  if (to.day < from.day) months -= 1;
  return months;
}

function yearsBetween(from: CalendarDate, to: CalendarDate): number {
  let years = to.year - from.year;
  if (to.month < from.month || (to.month === from.month && to.day < from.day)) years -= 1;
  return years;
}

/** "45" for adults; "18 months" (or "1 month") up to 24 months, as the legacy bar does. */
export function formatAge(birthDate: string | undefined | null, asOf: CalendarDate = today()): string {
  const dob = parseCalendarDate(birthDate);
  if (!dob) return "";
  const months = monthsBetween(dob, asOf);
  if (months < 0) return "";
  if (months > 24) return String(yearsBetween(dob, asOf));
  return months === 1 ? "1 month" : `${String(months)} months`;
}

/** oeFormatAge(format 0): years from 24 months, months below. */
export function formatAgeAtDeath(birthDate: string | undefined | null, deathDate: string | undefined | null): string {
  const dob = parseCalendarDate(birthDate);
  const dod = parseCalendarDate(deathDate);
  if (!dob || !dod) return "";
  const months = monthsBetween(dob, dod);
  if (months < 0) return "";
  if (months >= 24) return String(yearsBetween(dob, dod));
  return months === 1 ? "1 month" : `${String(months)} months`;
}

function daysBetween(from: CalendarDate, to: CalendarDate): number {
  const a = Date.UTC(from.year, from.month - 1, from.day);
  const b = Date.UTC(to.year, to.month - 1, to.day);
  return Math.round((b - a) / 86_400_000);
}

/** deceasedDays(): Today / 1 day ago / N days ago (<90) / ~N months ago (<731) / More than N years ago. */
export function deceasedRelative(deathDate: string | undefined | null, asOf: CalendarDate = today()): string {
  const dod = parseCalendarDate(deathDate);
  if (!dod) return "";
  const days = daysBetween(dod, asOf);
  if (days <= 0) return "Today";
  if (days === 1) return "1 day ago";
  if (days < 90) return `${String(days)} days ago`;
  if (days < 731) return `~${String(Math.round(days / 30))} months ago`;
  return `More than ${String(Math.round(days / 365))} years ago`;
}

/** "Deceased - 2026-09-01 (24 days ago)", or "Deceased" when only deceasedBoolean is known. */
export function deceasedText(deathDate: string | undefined | null, order: DateOrder = "ymd", asOf: CalendarDate = today()): string {
  const date = formatDate(deathDate, order);
  if (!date) return "Deceased";
  return `Deceased - ${date} (${deceasedRelative(deathDate, asOf)})`;
}
