// Edit in the chart (option A): inside the chart, a card's Edit button asks the chart page to open
// the same legacy editor its old card opens. The chart page decides which actions this user gets
// and builds every URL itself; the app only names an action from this closed set. Writes stay in
// OpenEMR's own editors, with their own permission checks, and the app still sends only GETs (R2).
import { createContext } from "react";

export type EditAction = "allergy" | "medical_problem" | "medication" | "prescriptions";

const ACTIONS: readonly EditAction[] = ["allergy", "medical_problem", "medication", "prescriptions"];

export const MESSAGE_TYPE = "oe-dashboard-edit";

export const ChartEditContext = createContext<ReadonlySet<EditAction>>(new Set());

const isAction = (s: string): s is EditAction => (ACTIONS as readonly string[]).includes(s);

/** The actions the chart page declares on this app's frame; empty outside the chart. */
export function chartEditActions(): ReadonlySet<EditAction> {
  try {
    const declared = window.frameElement?.getAttribute("data-edit-actions") ?? "";
    return new Set(declared.split(" ").filter(isAction));
  } catch {
    return new Set();
  }
}

/** Asks the chart page, and only a same-origin one, to open the editor for `action`. */
export function requestChartEdit(action: EditAction): void {
  window.parent.postMessage({ type: MESSAGE_TYPE, action }, window.location.origin);
}
