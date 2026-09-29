// R1 + R2: the only module that talks to the network. It needs a session (a token and the
// patient bound to it) to exist at all, and it only ever sends GET.

export interface FhirSession {
  /** FHIR base, e.g. https://host/apis/default/fhir (no trailing slash). */
  readonly serverUrl: string;
  readonly accessToken: string;
  /** The patient the token is bound to (launch/patient). */
  readonly patientId: string;
}

export class FhirHttpError extends Error {
  constructor(
    readonly status: number,
    readonly kind: "unauthorized" | "forbidden" | "not_found" | "server" | "network" | "invalid",
  ) {
    super(`FHIR request failed (${kind}${status ? ` ${String(status)}` : ""})`);
    this.name = "FhirHttpError";
  }
}

function kindFor(status: number): FhirHttpError["kind"] {
  if (status === 401) return "unauthorized";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  return "server";
}

/** Resolves a relative path against the FHIR base and refuses anything that leaves it. */
export function resolveOnServer(session: FhirSession, pathOrUrl: string): string {
  const base = session.serverUrl.replace(/\/+$/, "") + "/";
  const url = new URL(pathOrUrl, base);
  if (!url.href.startsWith(base)) {
    // A paging link that points elsewhere would carry the bearer token off the server.
    throw new FhirHttpError(0, "invalid");
  }
  return url.href;
}

export async function fhirGet(session: FhirSession, pathOrUrl: string, signal?: AbortSignal): Promise<unknown> {
  const url = resolveOnServer(session, pathOrUrl);
  let response: Response;
  try {
    response = await fetch(url, {
      method: "GET",
      headers: { Accept: "application/fhir+json", Authorization: `Bearer ${session.accessToken}` },
      credentials: "omit",
      cache: "no-store",
      ...(signal ? { signal } : {}),
    });
  } catch {
    throw new FhirHttpError(0, "network");
  }
  if (!response.ok) throw new FhirHttpError(response.status, kindFor(response.status));
  try {
    return (await response.json()) as unknown;
  } catch {
    throw new FhirHttpError(response.status, "invalid");
  }
}

/** The Co-Pilot module's pages, same origin (ADR 0006). */
export const COPILOT_MODULE_PATH = "/interface/modules/custom_modules/oe-module-copilot-agent/public/";

/**
 * The module's public, PHI-free feature flags. No token is sent: the flags are not patient data.
 * Any failure means "no flags", so a link that depends on one is simply omitted.
 */
export async function fetchModuleFlags(signal?: AbortSignal): Promise<{ demoTools: boolean }> {
  try {
    const response = await fetch(new URL(COPILOT_MODULE_PATH + "flags.php", window.location.origin).href, {
      method: "GET",
      headers: { Accept: "application/json" },
      credentials: "omit",
      cache: "no-store",
      ...(signal ? { signal } : {}),
    });
    if (!response.ok) return { demoTools: false };
    const body = (await response.json()) as { demoTools?: unknown };
    return { demoTools: body.demoTools === true };
  } catch {
    return { demoTools: false };
  }
}
