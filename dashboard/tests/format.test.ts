// R6: one formatting module (DEM-09, PVM-01, DEM-10).
import { describe, expect, it } from "vitest";
import {
  deceasedRelative,
  deceasedText,
  formatAge,
  formatAgeAtDeath,
  formatDate,
  formatTime,
  parseCalendarDate,
} from "../src/format/dates";

const asOf = { year: 2026, month: 9, day: 25 };

describe("dates", () => {
  it("reads a FHIR date as a calendar date, not a UTC instant", () => {
    expect(parseCalendarDate("1981-07-04")).toEqual({ year: 1981, month: 7, day: 4 });
    expect(parseCalendarDate("2018-09-22T01:28:41+00:00")).toEqual({ year: 2018, month: 9, day: 22 });
    expect(parseCalendarDate("not a date")).toBeNull();
    expect(parseCalendarDate(undefined)).toBeNull();
  });

  it("formats in OpenEMR's three date orders", () => {
    expect(formatDate("1981-07-04")).toBe("1981-07-04");
    expect(formatDate("1981-07-04", "mdy")).toBe("07/04/1981");
    expect(formatDate("1981-07-04", "dmy")).toBe("04/07/1981");
    expect(formatDate("")).toBe("");
  });
});

describe("times (DEM-09)", () => {
  it("shows midnight as 12 AM on a 12-hour clock, not 0", () => {
    expect(formatTime(0, 5, "12h")).toBe("12:05 AM");
    expect(formatTime(12, 0, "12h")).toBe("12:00 PM");
    expect(formatTime(13, 30, "12h")).toBe("1:30 PM");
  });

  it("uses no meridiem on a 24-hour clock", () => {
    expect(formatTime(0, 5, "24h")).toBe("00:05");
    expect(formatTime(23, 59, "24h")).toBe("23:59");
  });
});

describe("age (PatientService::getPatientAge)", () => {
  it("counts whole years for adults", () => {
    expect(formatAge("1981-07-04", asOf)).toBe("45");
    expect(formatAge("1981-09-26", asOf)).toBe("44"); // birthday tomorrow
    expect(formatAge("1981-09-25", asOf)).toBe("45"); // birthday today
  });

  it("counts months up to 24 months", () => {
    expect(formatAge("2025-09-25", asOf)).toBe("12 months");
    expect(formatAge("2026-08-25", asOf)).toBe("1 month");
    expect(formatAge("2024-09-25", asOf)).toBe("24 months");
    expect(formatAge("2024-08-25", asOf)).toBe("2");
  });

  it("is empty for a missing or future birth date", () => {
    expect(formatAge(undefined, asOf)).toBe("");
    expect(formatAge("2027-01-01", asOf)).toBe("");
  });

  it("measures age at death to the date of death (oeFormatAge format 0)", () => {
    expect(formatAgeAtDeath("1950-03-10", "2020-03-09")).toBe("69");
    expect(formatAgeAtDeath("2019-01-01", "2020-06-01")).toBe("17 months");
  });
});

describe("deceased wording (deceasedDays)", () => {
  it("follows the legacy thresholds", () => {
    expect(deceasedRelative("2026-09-25", asOf)).toBe("Today");
    expect(deceasedRelative("2026-09-24", asOf)).toBe("1 day ago");
    expect(deceasedRelative("2026-07-01", asOf)).toBe("86 days ago");
    expect(deceasedRelative("2025-09-25", asOf)).toBe("~12 months ago");
    expect(deceasedRelative("2020-01-01", asOf)).toBe("More than 7 years ago");
  });

  it("builds the banner text, or plain 'Deceased' with no date", () => {
    expect(deceasedText("2026-09-24", "ymd", asOf)).toBe("Deceased - 2026-09-24 (1 day ago)");
    expect(deceasedText(undefined, "ymd", asOf)).toBe("Deceased");
  });
});
