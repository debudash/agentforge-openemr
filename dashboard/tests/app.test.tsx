// Rules tested through the rendered dashboard: R1 (nothing before a token), R2 (GET only),
// R3 (text only), R5 (four states), R7 (accessible toggles), R8 (minimum necessary), R9 (slots).
import { beforeEach, describe, expect, it } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { App, makeQueryClient } from "../src/app/App";
import { server, seen, resetSeen } from "./msw";
import { FHIR_BASE, bundle, handlers, recorded, renderDashboard, session } from "./support";

const XSS = `<img src=x onerror="window.__xss=1">`;

function card(id: string): HTMLElement {
  const el = document.querySelector<HTMLElement>(`[data-card="${id}"]`);
  if (!el) throw new Error(`no card ${id}`);
  return el;
}

async function settled(): Promise<void> {
  await waitFor(() => {
    expect(document.querySelectorAll('[data-state="loading"]').length).toBe(0);
    expect(document.querySelector('[data-header-state="loading"]')).toBeNull();
    expect(document.querySelectorAll("[data-card]").length).toBe(6);
  });
}

beforeEach(() => {
  resetSeen();
  delete (window as unknown as { __xss?: number }).__xss;
});

describe("R1: no request before a token", () => {
  it("renders the sign-in screen and sends nothing when there is no login", async () => {
    server.use(...handlers({}));
    let started = false;
    render(
      <App
        deps={{ hasLogin: () => false, complete: () => Promise.reject(new Error("unused")), start: () => { started = true; return Promise.resolve(); } }}
        queryClient={makeQueryClient()}
      />,
    );
    const button = screen.getByRole("button", { name: "Sign in with OpenEMR" });
    await new Promise((r) => setTimeout(r, 50));
    expect(seen).toEqual([]);
    await userEvent.click(button);
    expect(started).toBe(true);
    expect(seen).toEqual([]);
  });

  it("shows a failed login as a failure, with no patient data and no requests", async () => {
    server.use(...handlers({}));
    const { LoginError } = await import("../src/auth/smart");
    render(<App deps={{ hasLogin: () => true, complete: () => Promise.reject(new LoginError("no-patient")), start: () => Promise.resolve() }} />);
    expect(await screen.findByRole("alert")).toHaveTextContent("No patient was selected");
    expect(seen).toEqual([]);
  });
});

describe("the dashboard over recorded FHIR responses (pid 1)", () => {
  it("renders the header and every card from the API, using only GET with the bearer token (R2)", async () => {
    server.use(...handlers(recorded("pid1")));
    renderDashboard(session("a2bf78a3-cba7-4956-bc38-27323998b7be"));
    await settled();

    const header = screen.getByRole("banner", { name: "Patient" });
    expect(within(header).getByText("Adan632 Dicki44")).toBeInTheDocument();
    expect(header).toHaveTextContent("(1)");
    expect(header).toHaveTextContent("DOB:1981-07-04");
    expect(header).toHaveTextContent("Sex:Male");
    expect(header).toHaveTextContent("Status:Active");

    expect(card("allergies")).toHaveTextContent("No allergies recorded");
    expect(card("problems")).toHaveTextContent("Essential hypertension (disorder)");
    await waitFor(() => expect(card("care-team")).toHaveTextContent("Dana Reyes"));
    expect(card("care-team")).toHaveTextContent("Your Clinic Name Here");
    expect(card("vitals")).toHaveTextContent("Most recent vitals from: 2018-09-22");

    expect(seen.length).toBeGreaterThan(6);
    const fhir = seen.filter((r) => r.url.startsWith(FHIR_BASE));
    expect(seen.every((r) => r.method === "GET")).toBe(true);
    expect(fhir.every((r) => r.authorization === "Bearer test-token")).toBe(true);
    // The flags request carries no token.
    expect(seen.filter((r) => r.url.includes("flags.php")).every((r) => r.authorization === null)).toBe(true);
  });

  it("links to the Co-Pilot with the FHIR patient id, never the pid (ADR 0006)", async () => {
    server.use(...handlers(recorded("pid1")));
    renderDashboard(session("a2bf78a3-cba7-4956-bc38-27323998b7be"));
    await settled();
    const link = screen.getByRole("link", { name: "Co-Pilot" });
    const url = new URL(link.getAttribute("href") ?? "");
    expect(url.pathname).toBe("/interface/modules/custom_modules/oe-module-copilot-agent/public/patient.php");
    expect([...url.searchParams.keys()]).toEqual(["patient", "site"]);
    expect(url.searchParams.get("site")).toBe("default");
    expect(url.searchParams.get("patient")).toBe("a2bf78a3-cba7-4956-bc38-27323998b7be");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(screen.queryByRole("link", { name: "Demo Data" })).toBeNull();
  });

  it("links Demo Data only when the module reports demoTools on", async () => {
    server.use(
      http.get("*/oe-module-copilot-agent/public/flags.php", () => HttpResponse.json({ demoTools: true })),
      ...handlers(recorded("pid1")),
    );
    renderDashboard(session("a2bf78a3-cba7-4956-bc38-27323998b7be"));
    await settled();
    expect(await screen.findByRole("link", { name: "Demo Data" })).toHaveAttribute(
      "href",
      expect.stringContaining("demo.php?patient=a2bf78a3-cba7-4956-bc38-27323998b7be") as string,
    );
  });

  it("puts no patient data in the window title (R8)", async () => {
    server.use(...handlers(recorded("pid1")));
    renderDashboard(session("a2bf78a3-cba7-4956-bc38-27323998b7be"));
    await settled();
    expect(document.title).not.toContain("Adan");
  });
});

describe("R3: stored values render as text", () => {
  it("renders markup in an allergy, problem, medication, prescription and care team as literal text", async () => {
    server.use(
      ...handlers({
        Patient: { resourceType: "Patient", id: "p-1", name: [{ family: XSS, given: ["O'Neil"] }], gender: "male" },
        AllergyIntolerance: bundle([
          { resourceType: "AllergyIntolerance", id: "a", clinicalStatus: { coding: [{ code: "active" }] }, code: { text: XSS }, reaction: [{ manifestation: [{ text: XSS }] }] },
        ]),
        Condition: bundle([
          { resourceType: "Condition", id: "c", clinicalStatus: { coding: [{ code: "active" }] }, category: [{ coding: [{ code: "problem-list-item" }] }], code: { text: XSS } },
        ]),
        "MedicationRequest-plan": bundle([
          { resourceType: "MedicationRequest", id: "m", intent: "plan", status: "active", medicationCodeableConcept: { text: XSS }, dosageInstruction: [{ text: XSS }] },
        ]),
        "MedicationRequest-order": bundle([
          { resourceType: "MedicationRequest", id: "o", intent: "order", status: "active", medicationCodeableConcept: { text: XSS } },
        ]),
        CareTeam: bundle([
          {
            resourceType: "CareTeam",
            id: "t",
            status: "active",
            name: XSS,
            participant: [{ member: { reference: "Practitioner/x1" }, role: [{ text: XSS }] }],
          },
        ]),
        "Practitioner/x1": { resourceType: "Practitioner", id: "x1", name: [{ family: XSS, given: ["Dr"] }] },
      }),
    );
    renderDashboard();
    await settled();
    await waitFor(() => expect(card("care-team")).toHaveTextContent(`Dr ${XSS}`));
    for (const id of ["allergies", "problems", "medications", "prescriptions", "care-team"]) {
      expect(card(id)).toHaveTextContent(XSS);
      expect(card(id).querySelector("img")).toBeNull();
    }
    expect(screen.getByRole("banner")).toHaveTextContent(`O'Neil ${XSS}`);
    expect(document.querySelector("img")).toBeNull();
    expect((window as unknown as { __xss?: number }).__xss).toBeUndefined();
  });
});

describe("R5: an error is shown as an error, never as content", () => {
  const failures: [string, () => Response][] = [
    ["a 500", () => HttpResponse.json({ error: "boom" }, { status: 500 })],
    ["a 401", () => HttpResponse.json({ error: "Unauthorized" }, { status: 401 })],
    ["a network failure", () => HttpResponse.error()],
    ["a body that is not a Bundle", () => HttpResponse.json({ resourceType: "OperationOutcome" })],
  ];

  it.each(failures)("renders each card's error state on %s", async (_label, fail) => {
    server.use(
      ...handlers({
        Patient: recorded("pid1").Patient,
        AllergyIntolerance: fail,
        Condition: fail,
        "MedicationRequest-plan": fail,
        "MedicationRequest-order": fail,
        CareTeam: fail,
        Observation: fail,
      }),
    );
    renderDashboard(session("a2bf78a3-cba7-4956-bc38-27323998b7be"));
    await settled();
    for (const id of ["allergies", "problems", "medications", "prescriptions", "care-team", "vitals"]) {
      expect(card(id)).toHaveAttribute("data-state", "error");
      expect(within(card(id)).getByRole("alert")).toBeInTheDocument();
      expect(card(id)).not.toHaveTextContent("No allergies recorded");
      expect(card(id)).not.toHaveTextContent(/^None$/);
      expect(within(card(id)).getByRole("button", { name: "Retry" })).toBeInTheDocument();
    }
  });

  it("names an expired sign-in so the clinician knows to sign in again", async () => {
    server.use(...handlers({ Patient: () => HttpResponse.json({}, { status: 401 }) }));
    renderDashboard();
    expect(await screen.findByText(/sign-in has expired/)).toBeInTheDocument();
  });

  it("counts entries it could not read instead of dropping them silently", async () => {
    server.use(
      ...handlers({
        Patient: recorded("pid1").Patient,
        AllergyIntolerance: bundle([
          { resourceType: "AllergyIntolerance", id: "ok", clinicalStatus: { coding: [{ code: "active" }] }, code: { text: "Latex" } },
          { resourceType: "AllergyIntolerance", clinicalStatus: "garbage" },
        ]),
      }),
    );
    renderDashboard();
    await settled();
    expect(card("allergies")).toHaveTextContent("Latex");
    expect(card("allergies")).toHaveTextContent("1 entry could not be read");
  });

  it("says a list is incomplete when the server has more pages than the app reads", async () => {
    server.use(
      http.get(`${FHIR_BASE}/Condition`, ({ request }) => {
        const page = Number(new URL(request.url).searchParams.get("page") ?? "1");
        return HttpResponse.json({
          ...(bundle([
            { resourceType: "Condition", id: `c${String(page)}`, clinicalStatus: { coding: [{ code: "active" }] }, category: [{ coding: [{ code: "problem-list-item" }] }], code: { text: `P${String(page)}` } },
          ]) as object),
          link: [{ relation: "next", url: `${FHIR_BASE}/Condition?patient=p-1&page=${String(page + 1)}` }],
        });
      }),
      ...handlers({ Patient: recorded("pid1").Patient }),
    );
    renderDashboard();
    await settled();
    expect(card("problems")).toHaveTextContent("This list is incomplete");
  });

  it("distinguishes loading from empty", async () => {
    let release: () => void = () => undefined;
    const gate = new Promise<void>((r) => { release = r; });
    server.use(
      http.get(`${FHIR_BASE}/AllergyIntolerance`, async () => {
        await gate;
        return HttpResponse.json(bundle([]) as Record<string, unknown>);
      }),
      ...handlers({ Patient: recorded("pid1").Patient }),
    );
    renderDashboard();
    await waitFor(() => expect(card("allergies")).toHaveAttribute("data-state", "loading"));
    expect(card("allergies")).not.toHaveTextContent("No allergies recorded");
    release();
    await waitFor(() => expect(card("allergies")).toHaveAttribute("data-state", "empty"));
    expect(card("allergies")).toHaveTextContent("No allergies recorded");
  });
});

describe("R7 and R9: card chrome", () => {
  it("uses real headings and a button whose aria-expanded follows the state", async () => {
    server.use(...handlers(recorded("pid1")));
    renderDashboard();
    await settled();
    expect(screen.getByRole("heading", { level: 2, name: "Allergies" })).toBeInTheDocument();
    const toggle = within(card("allergies")).getByRole("button", { name: /Hide/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const body = document.getElementById(toggle.getAttribute("aria-controls") ?? "");
    expect(body).toBeVisible();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(body).not.toBeVisible();
  });

  it("gives every card a before and after slot", async () => {
    server.use(...handlers(recorded("pid1")));
    renderDashboard();
    await settled();
    for (const id of ["allergies", "problems", "medications", "prescriptions", "care-team", "vitals"]) {
      expect(card(id).querySelector(`[data-slot="${id}:before"]`)).not.toBeNull();
      expect(card(id).querySelector(`[data-slot="${id}:after"]`)).not.toBeNull();
    }
  });
});
