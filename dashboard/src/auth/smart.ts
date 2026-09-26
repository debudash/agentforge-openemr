// SMART App Launch v2, standalone, public client + PKCE (spec section 4, ADR 0008).
// fhirclient does the OAuth dance and keeps the token in sessionStorage for this tab (R8); the
// app reads the token and the bound patient from it and does its own GET-only requests.
import FHIR from "fhirclient";
import type { FhirSession } from "../fhir/http";

/**
 * patient/ scopes only: OpenEMR refuses user/ scopes for public clients (API-06), and a
 * patient-bound token covers exactly the one patient chosen at login. Read-only (R2).
 * No `offline_access`: a public client in a browser has nowhere safe to keep a refresh token,
 * and a sign-in lasts one access token (an hour); the card errors say when to sign in again.
 */
export const SCOPES = [
  "openid",
  "fhirUser",
  "launch/patient",
  "patient/Patient.rs",
  "patient/AllergyIntolerance.rs",
  "patient/Condition.rs",
  "patient/MedicationRequest.rs",
  "patient/CareTeam.rs",
  "patient/Practitioner.rs",
  "patient/RelatedPerson.rs",
  "patient/Organization.rs",
  "patient/Observation.rs",
].join(" ");

export interface SignedIn extends FhirSession {
  /** Practitioner/<id> of the signed-in user, when the id token carries it. */
  readonly fhirUser: string | undefined;
  /** Epoch seconds. */
  readonly expiresAt: number | undefined;
}

export interface LaunchConfig {
  readonly clientId: string;
  /** Same origin as the app (ADR 0008): https://<openemr>/apis/default/fhir */
  readonly iss: string;
  /** https://<openemr>/public/dashboard/ — must equal the registered redirect URI. */
  readonly redirectUri: string;
}

export function launchConfig(): LaunchConfig {
  const clientId = import.meta.env.VITE_SMART_CLIENT_ID ?? "";
  const site = import.meta.env.VITE_OPENEMR_SITE ?? "default";
  return {
    clientId,
    iss: `${window.location.origin}/apis/${site}/fhir`,
    redirectUri: new URL(import.meta.env.BASE_URL, window.location.origin).href,
  };
}

export async function startLogin(config: LaunchConfig = launchConfig()): Promise<void> {
  await FHIR.oauth2.authorize({
    clientId: config.clientId,
    iss: config.iss,
    redirectUri: config.redirectUri,
    scope: SCOPES,
    pkceMode: "required",
  });
}

/** True when the URL carries an authorization response or this tab already holds a session. */
export function hasPendingOrStoredLogin(): boolean {
  const params = new URLSearchParams(window.location.search);
  if (params.has("code") || params.has("error")) return true;
  try {
    return window.sessionStorage.getItem("SMART_KEY") !== null;
  } catch {
    return false;
  }
}

export class LoginError extends Error {
  constructor(readonly reason: "no-patient" | "failed" | "wrong-server") {
    super(`SMART login ${reason}`);
    this.name = "LoginError";
  }
}

export async function completeLogin(config: LaunchConfig = launchConfig()): Promise<SignedIn> {
  let client;
  try {
    client = await FHIR.oauth2.ready();
  } catch {
    throw new LoginError("failed");
  }
  const serverUrl = client.state.serverUrl.replace(/\/+$/, "");
  // The token is only ever sent to the server this app is served with.
  if (serverUrl !== config.iss) throw new LoginError("wrong-server");
  const accessToken = client.state.tokenResponse?.access_token;
  const patientId = client.patient.id;
  if (!accessToken) throw new LoginError("failed");
  if (!patientId) throw new LoginError("no-patient");
  return {
    serverUrl,
    accessToken,
    patientId,
    fhirUser: client.getFhirUser() ?? undefined,
    expiresAt: client.state.expiresAt,
  };
}

export function signOut(): void {
  try {
    const key = window.sessionStorage.getItem("SMART_KEY");
    if (key) window.sessionStorage.removeItem(JSON.parse(key) as string);
    window.sessionStorage.removeItem("SMART_KEY");
  } catch {
    // Storage unavailable: nothing was stored either.
  }
  window.location.replace(new URL(import.meta.env.BASE_URL, window.location.origin).href);
}
