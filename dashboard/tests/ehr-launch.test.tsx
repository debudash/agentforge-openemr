// ADR 0009: the EHR launch from the chart. The acceptance path (launch, then the chart's patient)
// and the refusal paths (another server, another patient, no launch in the chart) are tested
// with fhirclient replaced, so no test depends on a live authorization server.
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { App, makeQueryClient } from "../src/app/App";
import { server, seen, resetSeen } from "./msw";
import { handlers, recorded, renderDashboard, session } from "./support";

const fhir = vi.hoisted(() => ({ authorize: vi.fn(), ready: vi.fn() }));
vi.mock("fhirclient", () => ({ default: { oauth2: fhir } }));

const { EHR_SCOPES, SCOPES, LoginError, chartPatient, completeLogin, ehrLaunchParams, launchConfig, startEhrLaunch } = await import("../src/auth/smart");

const PID1 = "a2bf78a3-cba7-4956-bc38-27323998b7be";
const OTHER = "a2bf78a3-0000-0000-0000-000000000000";

function readyClient(patientId: string, serverUrl = launchConfig().iss) {
  return {
    state: { serverUrl, tokenResponse: { access_token: "t" }, expiresAt: 1 },
    patient: { id: patientId },
    getFhirUser: () => "Practitioner/x",
  };
}

function frameDeclaring(patient: string | null): void {
  const el = document.createElement("iframe");
  if (patient !== null) el.setAttribute("data-fhir-patient", patient);
  Object.defineProperty(window, "frameElement", { configurable: true, get: () => el });
}

beforeEach(() => {
  resetSeen();
  fhir.authorize.mockReset().mockResolvedValue(undefined);
  fhir.ready.mockReset();
  Object.defineProperty(window, "frameElement", { configurable: true, get: () => null });
  window.history.replaceState({}, "", "/");
});

describe("scopes", () => {
  it("asks for launch instead of launch/patient, and the same read-only resource scopes", () => {
    const ehr = EHR_SCOPES.split(" ");
    expect(ehr).toContain("launch");
    expect(ehr).not.toContain("launch/patient");
    expect(ehr.filter((s) => s.startsWith("patient/"))).toEqual(SCOPES.split(" ").filter((s) => s.startsWith("patient/")));
    expect(ehr.filter((s) => s.startsWith("patient/")).every((s) => s.endsWith(".rs"))).toBe(true);
  });
});

describe("launch parameters", () => {
  it("reads iss and launch from the launch URL, and needs both", () => {
    window.history.replaceState({}, "", "/?iss=https%3A%2F%2Fh%2Fapis%2Fdefault%2Ffhir&launch=abc");
    expect(ehrLaunchParams()).toEqual({ iss: "https://h/apis/default/fhir", launch: "abc" });
    window.history.replaceState({}, "", "/?launch=abc");
    expect(ehrLaunchParams()).toBeNull();
    window.history.replaceState({}, "", "/?iss=x");
    expect(ehrLaunchParams()).toBeNull();
  });
});

describe("startEhrLaunch", () => {
  it("authorizes against this server with the launch, PKCE and completion in the frame", async () => {
    const config = launchConfig();
    await startEhrLaunch({ iss: `${config.iss}/`, launch: "L1" }, config);
    expect(fhir.authorize).toHaveBeenCalledWith({
      clientId: config.clientId,
      iss: config.iss,
      launch: "L1",
      redirectUri: config.redirectUri,
      scope: EHR_SCOPES,
      pkceMode: "required",
      completeInTarget: true,
    });
  });

  it("refuses a launch from another server before any request", async () => {
    await expect(startEhrLaunch({ iss: "https://evil.example/apis/default/fhir", launch: "L1" })).rejects.toEqual(new LoginError("wrong-server"));
    expect(fhir.authorize).not.toHaveBeenCalled();
    expect(seen).toEqual([]);
  });
});

describe("chartPatient", () => {
  it("is the patient the embedding page declares on the frame", () => {
    frameDeclaring(PID1);
    expect(chartPatient()).toBe(PID1);
  });

  it("is null when the app is not framed, or the frame declares none", () => {
    expect(chartPatient()).toBeNull();
    frameDeclaring(null);
    expect(chartPatient()).toBeNull();
  });
});

describe("completeLogin in the chart", () => {
  it("accepts the token when its patient is the chart's patient", async () => {
    fhir.ready.mockResolvedValue(readyClient(PID1));
    const s = await completeLogin(launchConfig(), PID1);
    expect(s.patientId).toBe(PID1);
    expect(s.inChart).toBe(true);
  });

  it("refuses a token for any other patient (a launch that raced a patient switch)", async () => {
    fhir.ready.mockResolvedValue(readyClient(OTHER));
    await expect(completeLogin(launchConfig(), PID1)).rejects.toEqual(new LoginError("wrong-patient"));
  });

  it("outside the chart, keeps the standalone behaviour", async () => {
    fhir.ready.mockResolvedValue(readyClient(OTHER));
    const s = await completeLogin(launchConfig(), null);
    expect(s.patientId).toBe(OTHER);
    expect(s.inChart).toBe(false);
  });

  it("still refuses a token from another server", async () => {
    fhir.ready.mockResolvedValue(readyClient(PID1, "https://evil.example/apis/default/fhir"));
    await expect(completeLogin(launchConfig(), PID1)).rejects.toEqual(new LoginError("wrong-server"));
  });
});

describe("the app on an EHR launch", () => {
  const noLogin = { hasLogin: () => false, complete: () => Promise.reject(new Error("unused")), start: () => Promise.reject(new Error("unused")) };

  it("starts the EHR launch at once, shows no sign-in button and requests no patient data", async () => {
    const startEhr = vi.fn(() => new Promise<void>(() => undefined));
    render(<App deps={{ ...noLogin, ehrLaunch: () => ({ iss: "i", launch: "l" }), startEhr, inChart: () => true }} queryClient={makeQueryClient()} />);
    expect(await screen.findByRole("status")).toHaveTextContent("Signing in");
    expect(startEhr).toHaveBeenCalledWith({ iss: "i", launch: "l" });
    expect(screen.queryByRole("button", { name: "Sign in with OpenEMR" })).toBeNull();
    expect(seen).toEqual([]);
  });

  it("shows a refused launch as a failure, with no sign-in button inside the chart", async () => {
    render(
      <App
        deps={{ ...noLogin, ehrLaunch: () => ({ iss: "i", launch: "l" }), startEhr: () => Promise.reject(new LoginError("wrong-server")), inChart: () => true }}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("launched by a different server");
    expect(screen.queryByRole("button")).toBeNull();
    expect(seen).toEqual([]);
  });

  it("shows a token for another patient as a failure, never as that patient's data", async () => {
    server.use(...handlers(recorded("pid1")));
    render(
      <App deps={{ hasLogin: () => true, complete: () => Promise.reject(new LoginError("wrong-patient")), start: () => Promise.resolve(), inChart: () => true }} />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("opened for a different patient than the chart");
    expect(document.querySelector("[data-card]")).toBeNull();
    expect(seen).toEqual([]);
  });

  it("in the chart without a launch, asks to open the patient again instead of offering a sign-in", () => {
    render(<App deps={{ ...noLogin, inChart: () => true }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Open the patient again");
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("the header in the chart", () => {
  it("keeps the patient's identity and leaves the Co-Pilot links and Sign out to the chart", async () => {
    server.use(...handlers(recorded("pid1")));
    renderDashboard(session(PID1, true));
    const header = await screen.findByRole("banner", { name: "Patient" });
    expect(await within(header).findByText("Adan632 Dicki44")).toBeInTheDocument();
    expect(header).toHaveAttribute("data-patient-id", PID1);
    expect(within(header).queryByRole("link", { name: "Co-Pilot" })).toBeNull();
    expect(within(header).queryByRole("button", { name: "Sign out" })).toBeNull();
  });

  it("standalone, still has them", async () => {
    server.use(...handlers(recorded("pid1")));
    renderDashboard(session(PID1, false));
    const header = await screen.findByRole("banner", { name: "Patient" });
    expect(await within(header).findByRole("link", { name: "Co-Pilot" })).toBeInTheDocument();
    expect(within(header).getByRole("button", { name: "Sign out" })).toBeInTheDocument();
  });
});
