// Throwaway: SMART standalone launch, public client + PKCE, against the local stack.
import FHIR from "fhirclient";

const out = document.getElementById("out")!;
const log = (s: string) => { out.textContent += "\n" + s; };

const params = new URLSearchParams(location.search);
const clientId = params.get("client_id") ?? sessionStorage.getItem("spike_client_id") ?? "";
if (clientId) sessionStorage.setItem("spike_client_id", clientId);

FHIR.oauth2.init({
  iss: "https://localhost:9300/apis/default/fhir",
  clientId,
  redirectUri: location.origin + location.pathname,
  scope: "openid fhirUser launch/patient patient/Patient.rs patient/AllergyIntolerance.rs patient/Condition.rs patient/MedicationRequest.rs patient/CareTeam.rs patient/Practitioner.rs patient/Observation.rs",
  pkceMode: "required",
}).then(async (client) => {
  log("TOKEN_OK scopes=" + (client.state.tokenResponse?.scope ?? ""));
  log("patient=" + client.patient.id);
  const p: any = await client.patient.read();
  log("PATIENT " + JSON.stringify({ id: p.id, name: p.name?.[0], birthDate: p.birthDate, gender: p.gender }));
  for (const q of ["AllergyIntolerance", "Condition", "MedicationRequest", "CareTeam", "Observation?category=vital-signs"]) {
    const sep = q.includes("?") ? "&" : "?";
    try {
      const b: any = await client.request(q + sep + "patient=" + client.patient.id);
      log("RES " + q + " total=" + (b.total ?? b.entry?.length ?? 0));
    } catch (e) { log("ERR " + q + " " + String(e)); }
  }
  log("DONE");
}).catch((e) => log("FAIL " + String(e)));
