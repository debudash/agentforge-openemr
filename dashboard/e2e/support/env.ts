import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const repo = fileURLToPath(new URL("../../../", import.meta.url));

export const DOCTOR = "doctor1";

export function doctorPassword(): string {
  return process.env.OE_DOCTOR_PASS ?? readFileSync(`${repo}copilot/.local-doctor1-pass`, "utf8").trim();
}

/** Local credentials for the ADR 0005 restricted users (gitignored). */
export function restrictedPasswords(): Record<string, string> {
  return JSON.parse(readFileSync(`${repo}dashboard/e2e/.auth/restricted-users.json`, "utf8")) as Record<string, string>;
}

export interface StackPatient {
  readonly pid: number;
  readonly uuid: string;
  readonly pubpid: string;
}

/** Local dev stack only: reads the patient list straight from the stack's database. */
export function sql(query: string): string[][] {
  const out = execFileSync(
    "docker",
    ["compose", "exec", "-T", "mysql", "mariadb", "-uopenemr", "-popenemr", "openemr", "-N", "-B", "-e", query],
    { cwd: `${repo}docker/development-easy`, encoding: "utf8", env: { ...process.env, MSYS_NO_PATHCONV: "1" } },
  );
  return out
    .split("\n")
    .filter((l) => l !== "")
    .map((l) => l.split("\t"));
}

export function stackPatients(): StackPatient[] {
  return sql(
    "SELECT pid, LOWER(INSERT(INSERT(INSERT(INSERT(HEX(uuid),9,0,'-'),14,0,'-'),19,0,'-'),24,0,'-')), pubpid FROM patient_data ORDER BY pid",
  ).map(([pid, uuid, pubpid]) => ({ pid: Number(pid), uuid: uuid ?? "", pubpid: pubpid ?? "" }));
}
