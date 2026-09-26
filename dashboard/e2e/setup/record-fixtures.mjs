// Records the FHIR responses the dashboard reads, for one patient, into tests/fixtures/recorded/.
// Local dev stack only (synthetic Synthea patients). Signs in as doctor1 through the real
// authorize page (headless), exchanges the code with PKCE here, then issues the app's GETs.
//
//   node e2e/setup/record-fixtures.mjs <patient-uuid> <name>
import { chromium } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import crypto from "node:crypto";

const BASE = process.env.OE_BASE_URL ?? "https://localhost:9300";
const [patientUuid, name] = process.argv.slice(2);
if (!patientUuid || !name) throw new Error("usage: record-fixtures.mjs <patient-uuid> <name>");
const clientId = /VITE_SMART_CLIENT_ID=(\S+)/.exec(readFileSync(".env.local", "utf8"))?.[1];
const pass = process.env.OE_DOCTOR_PASS ?? readFileSync("../copilot/.local-doctor1-pass", "utf8").trim();
const redirect = `${BASE}/public/dashboard/`;
const scope =
  "openid fhirUser launch/patient patient/Patient.rs patient/AllergyIntolerance.rs patient/Condition.rs patient/MedicationRequest.rs patient/CareTeam.rs patient/Practitioner.rs patient/RelatedPerson.rs patient/Organization.rs patient/Observation.rs";

const b64u = (b) => b.toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const verifier = b64u(crypto.randomBytes(32));
const challenge = b64u(crypto.createHash("sha256").update(verifier).digest());
const authorize = new URL(`${BASE}/oauth2/default/authorize`);
for (const [k, v] of Object.entries({
  response_type: "code", client_id: clientId, redirect_uri: redirect, scope, state: `s${Date.now()}`,
  aud: `${BASE}/apis/default/fhir`, code_challenge: challenge, code_challenge_method: "S256",
})) authorize.searchParams.set(k, v);

const browser = await chromium.launch();
const page = await (await browser.newContext({ ignoreHTTPSErrors: true })).newPage();
await page.goto(authorize.href);
await page.fill("input[name=username]", "doctor1");
await page.fill("input[name=password]", pass);
await page.click("button[name=user_role][value=api]");
await page.waitForURL(/patient-select/);
await page.click(`button[data-patient-id="${patientUuid}"]`);
await page.waitForURL(/scope-authorize/);
let code = null;
page.on("request", (r) => {
  const m = /\/public\/dashboard\/\?.*code=([^&]+)/.exec(r.url());
  if (m) code = decodeURIComponent(m[1]);
});
await page.click("#authorize-btn");
await page.waitForURL(/public\/dashboard/);
await browser.close();

process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
const tokenResponse = await fetch(`${BASE}/oauth2/default/token`, {
  method: "POST",
  headers: { "Content-Type": "application/x-www-form-urlencoded" },
  body: new URLSearchParams({ grant_type: "authorization_code", code, redirect_uri: redirect, client_id: clientId, code_verifier: verifier }),
});
const { access_token: token, patient } = await tokenResponse.json();

const P = encodeURIComponent(patient);
const reads = {
  Patient: `Patient/${P}`,
  AllergyIntolerance: `AllergyIntolerance?patient=${P}`,
  Condition: `Condition?patient=${P}&category=problem-list-item`,
  "MedicationRequest-plan": `MedicationRequest?patient=${P}&intent=plan&status=active`,
  "MedicationRequest-order": `MedicationRequest?patient=${P}&intent=order&status=active`,
  CareTeam: `CareTeam?patient=${P}`,
  Observation: `Observation?patient=${P}&category=vital-signs`,
};
const dir = `tests/fixtures/recorded/${name}`;
mkdirSync(dir, { recursive: true });
const get = async (path) => {
  const r = await fetch(`${BASE}/apis/default/fhir/${path}`, { headers: { Authorization: `Bearer ${token}`, Accept: "application/fhir+json" } });
  return { status: r.status, body: await r.json() };
};
for (const [file, path] of Object.entries(reads)) {
  const { status, body } = await get(path);
  writeFileSync(`${dir}/${file}.json`, JSON.stringify(body, null, 2) + "\n");
  console.log(file, status);
}
// Referenced names the cards resolve.
const careTeam = JSON.parse(readFileSync(`${dir}/CareTeam.json`, "utf8"));
const refs = new Set();
for (const e of careTeam.entry ?? []) for (const p of e.resource.participant ?? []) {
  for (const r of [p.member?.reference, p.onBehalfOf?.reference]) if (r && !r.startsWith("Patient/")) refs.add(r);
}
for (const ref of refs) {
  const { status, body } = await get(ref);
  writeFileSync(`${dir}/${ref.replace("/", "-")}.json`, JSON.stringify(body, null, 2) + "\n");
  console.log(ref, status);
}
