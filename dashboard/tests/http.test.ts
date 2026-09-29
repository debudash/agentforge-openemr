// R1/R2 at the network boundary: GET only, the token only to the FHIR base, errors typed.
import { describe, expect, it } from "vitest";
import { HttpResponse, http } from "msw";
import { fhirGet, FhirHttpError, resolveOnServer } from "../src/fhir/http";
import { searchAll } from "../src/fhir/bundle";
import { AllergyResource } from "../src/fhir/allergy";
import { server, seen, resetSeen } from "./msw";
import { FHIR_BASE, bundle, session } from "./support";

describe("fhirGet", () => {
  it("sends GET with the bearer token and FHIR accept header", async () => {
    resetSeen();
    let headers: Headers | undefined;
    server.use(
      http.get(`${FHIR_BASE}/Patient/p-1`, ({ request }) => {
        headers = request.headers;
        return HttpResponse.json({ resourceType: "Patient", id: "p-1" });
      }),
    );
    await fhirGet(session(), "Patient/p-1");
    expect(seen.map((r) => r.method)).toEqual(["GET"]);
    expect(headers?.get("authorization")).toBe("Bearer test-token");
    expect(headers?.get("accept")).toBe("application/fhir+json");
  });

  it("refuses to send the token anywhere but the FHIR base", () => {
    expect(() => resolveOnServer(session(), "https://evil.test/steal")).toThrow(FhirHttpError);
    expect(() => resolveOnServer(session(), "//evil.test/x")).toThrow(FhirHttpError);
    expect(() => resolveOnServer(session(), "../../api/patient")).toThrow(FhirHttpError);
    expect(resolveOnServer(session(), "Condition?patient=p-1")).toBe(`${FHIR_BASE}/Condition?patient=p-1`);
  });

  it.each([
    [401, "unauthorized"],
    [403, "forbidden"],
    [404, "not_found"],
    [500, "server"],
  ] as const)("maps HTTP %i to %s", async (status, kind) => {
    server.use(http.get(`${FHIR_BASE}/Patient/p-1`, () => HttpResponse.json({}, { status })));
    await expect(fhirGet(session(), "Patient/p-1")).rejects.toMatchObject({ kind, status });
  });

  it("maps a network failure to 'network'", async () => {
    server.use(http.get(`${FHIR_BASE}/Patient/p-1`, () => HttpResponse.error()));
    await expect(fhirGet(session(), "Patient/p-1")).rejects.toMatchObject({ kind: "network" });
  });
});

describe("searchAll", () => {
  it("scopes every search to the token's patient and follows next links on the same server", async () => {
    const urls: string[] = [];
    server.use(
      http.get(`${FHIR_BASE}/AllergyIntolerance`, ({ request }) => {
        urls.push(request.url);
        const page2 = new URL(request.url).searchParams.get("page") === "2";
        const res = {
          ...(bundle([{ resourceType: "AllergyIntolerance", id: page2 ? "b" : "a", clinicalStatus: { coding: [{ code: "active" }] } }]) as object),
          link: page2 ? [] : [{ relation: "next", url: `${FHIR_BASE}/AllergyIntolerance?patient=p-1&page=2` }],
        };
        return HttpResponse.json(res);
      }),
    );
    const r = await searchAll(session(), "AllergyIntolerance", {}, AllergyResource);
    expect(r.items.map((i) => i.id)).toEqual(["a", "b"]);
    expect(new URL(urls[0] ?? "").searchParams.get("patient")).toBe("p-1");
  });

  it("says when the list is incomplete instead of stopping silently at the page limit", async () => {
    server.use(
      http.get(`${FHIR_BASE}/AllergyIntolerance`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? "1");
        return HttpResponse.json({
          ...(bundle([{ resourceType: "AllergyIntolerance", id: `a${String(page)}`, clinicalStatus: { coding: [{ code: "active" }] } }]) as object),
          link: [{ relation: "next", url: `${FHIR_BASE}/AllergyIntolerance?patient=p-1&page=${String(page + 1)}` }],
        });
      }),
    );
    const r = await searchAll(session(), "AllergyIntolerance", {}, AllergyResource);
    expect(r.items).toHaveLength(20);
    expect(r.truncated).toBe(true);
  });

  it("does not follow a next link that leaves the server", async () => {
    server.use(
      http.get(`${FHIR_BASE}/AllergyIntolerance`, () =>
        HttpResponse.json({ ...(bundle([]) as object), link: [{ relation: "next", url: "https://evil.test/AllergyIntolerance" }] }),
      ),
    );
    await expect(searchAll(session(), "AllergyIntolerance", {}, AllergyResource)).rejects.toMatchObject({ kind: "invalid" });
  });

  it("skips entries of other types (OperationOutcome) without counting them as unreadable", async () => {
    server.use(
      http.get(`${FHIR_BASE}/AllergyIntolerance`, () =>
        HttpResponse.json(bundle([{ resourceType: "OperationOutcome", issue: [] }]) as Record<string, unknown>),
      ),
    );
    const r = await searchAll(session(), "AllergyIntolerance", {}, AllergyResource);
    expect(r).toEqual({ items: [], unreadable: 0, truncated: false });
  });
});
