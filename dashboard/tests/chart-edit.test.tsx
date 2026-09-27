// Edit in the chart (option A): Edit buttons appear only inside the chart, only for actions the
// chart granted, and a click only names the action to the parent; the app sends no write (R2).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App, makeQueryClient } from "../src/app/App";
import type { EditAction } from "../src/app/chartEdit";
import { server, seen, resetSeen } from "./msw";
import { handlers, recorded, session, signedInDeps } from "./support";

function renderInChart(grants: readonly EditAction[], inChart = true) {
  const deps = { ...signedInDeps(session("p-1", inChart)), inChart: () => inChart, editActions: () => new Set(grants) };
  return render(<App deps={deps} queryClient={makeQueryClient({ retryDelayMs: 0 })} />);
}

async function card(id: string): Promise<HTMLElement> {
  const el = await waitFor(() => {
    const found = document.querySelector<HTMLElement>(`[data-card="${id}"][data-state]:not([data-state="loading"])`);
    if (!found) throw new Error(`card ${id} not settled`);
    return found;
  });
  return el;
}

describe("edit in the chart", () => {
  beforeEach(() => {
    server.use(...handlers(recorded("pid1")));
    resetSeen();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows Edit on exactly the granted cards", async () => {
    renderInChart(["allergy", "medication"]);
    expect(within(await card("allergies")).queryByRole("button", { name: /^Edit/ })).not.toBeNull();
    expect(within(await card("medications")).queryByRole("button", { name: /^Edit/ })).not.toBeNull();
    expect(within(await card("problems")).queryByRole("button", { name: /^Edit/ })).toBeNull();
    expect(within(await card("prescriptions")).queryByRole("button", { name: /^Edit/ })).toBeNull();
    for (const id of ["care-team", "vitals"]) expect(within(await card(id)).queryByRole("button", { name: /^Edit/ })).toBeNull();
  });

  it("shows no Edit outside the chart, even when actions are offered", async () => {
    renderInChart(["allergy", "medical_problem", "medication", "prescriptions"], false);
    await card("allergies");
    expect(screen.queryAllByRole("button", { name: /^Edit/ })).toEqual([]);
  });

  it("a click posts only the action name, to this origin, and the app still sends only GETs (R2)", async () => {
    const post = vi.spyOn(window.parent, "postMessage").mockImplementation(() => undefined);
    renderInChart(["prescriptions"]);
    await userEvent.click(within(await card("prescriptions")).getByRole("button", { name: /^Edit/ }));
    expect(post).toHaveBeenCalledTimes(1);
    expect(post).toHaveBeenCalledWith({ type: "oe-dashboard-edit", action: "prescriptions" }, window.location.origin);
    expect(seen.length).toBeGreaterThan(0);
    expect(seen.filter((r) => r.method !== "GET")).toEqual([]);
  });
});
