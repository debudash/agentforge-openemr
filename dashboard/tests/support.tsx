// Test helpers: a signed-in session, MSW handlers built from recorded fixtures, and a renderer
// for the whole dashboard.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { render } from "@testing-library/react";
import { http, HttpResponse, type HttpHandler } from "msw";
import type { SignedIn } from "../src/auth/smart";
import { App, makeQueryClient, type AppDeps } from "../src/app/App";

export const FHIR_BASE = "https://openemr.test/apis/default/fhir";

export function session(patientId = "p-1", inChart = false): SignedIn {
  return { serverUrl: FHIR_BASE, accessToken: "test-token", patientId, fhirUser: undefined, expiresAt: undefined, inChart };
}

export function bundle(resources: readonly unknown[]): unknown {
  return { resourceType: "Bundle", type: "searchset", total: resources.length, entry: resources.map((resource) => ({ resource })) };
}

export type Routes = Partial<Record<string, unknown>>;

/**
 * Routes are keyed by resource type, or "MedicationRequest-plan" / "MedicationRequest-order"
 * for the two medication cards, or "Practitioner/<id>" for reads. A value that is a function
 * is called to produce a response (for errors).
 */
export function handlers(routes: Routes): HttpHandler[] {
  return [
    http.get(`${FHIR_BASE}/:type/:id`, ({ params }) => {
      const type = String(params.type);
      const id = String(params.id);
      const key = type === "Patient" ? "Patient" : `${type}/${id}`;
      return respond(routes[key]);
    }),
    http.get(`${FHIR_BASE}/:type`, ({ params, request }) => {
      const type = String(params.type);
      const intent = new URL(request.url).searchParams.get("intent");
      const key = type === "MedicationRequest" && intent ? `MedicationRequest-${intent}` : type;
      return respond(routes[key] ?? bundle([]));
    }),
    http.get("*/oe-module-copilot-agent/public/flags.php", () => HttpResponse.json({ demoTools: false })),
  ];
}

function respond(value: unknown): Response {
  if (value === undefined) return HttpResponse.json({ error: "not found" }, { status: 404 });
  if (typeof value === "function") return (value as () => Response)();
  return HttpResponse.json(value as Record<string, unknown>);
}

/** All recorded responses for one patient, keyed as `handlers()` expects. */
export function recorded(name: string): Routes {
  const dir = join(import.meta.dirname, "fixtures", "recorded", name);
  const routes: Routes = {};
  for (const file of readdirSync(dir)) {
    const body: unknown = JSON.parse(readFileSync(join(dir, file), "utf8"));
    const base = file.replace(/\.json$/, "");
    const m = /^(Practitioner|Organization|RelatedPerson)-(.+)$/.exec(base);
    routes[m ? `${m[1] ?? ""}/${m[2] ?? ""}` : base] = body;
  }
  return routes;
}

export function signedInDeps(s: SignedIn = session()): AppDeps {
  return { hasLogin: () => true, complete: () => Promise.resolve(s), start: () => Promise.resolve() };
}

export function renderDashboard(s: SignedIn = session()) {
  return render(<App deps={signedInDeps(s)} queryClient={makeQueryClient({ retryDelayMs: 0 })} />);
}
