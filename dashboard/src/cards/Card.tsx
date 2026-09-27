// Card chrome shared by every card.
// R5: loading, empty, error and data are four distinct states; an error is never shown as content.
// R7: the collapse toggle is a <button> whose aria-expanded follows the state; the title is a heading.
// R9: named slots before and after each card body, empty unless something registers content.
import { createContext, useContext, useId, useState, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { FhirHttpError } from "../fhir/http";
import { ChartEditContext, requestChartEdit, type EditAction } from "../app/chartEdit";

export type CardId = "allergies" | "problems" | "medications" | "prescriptions" | "care-team" | "vitals";

export interface CardSlotContent {
  readonly before?: ReactNode;
  readonly after?: ReactNode;
}
export const CardSlotsContext = createContext<Partial<Record<CardId, CardSlotContent>>>({});

const STORAGE_PREFIX = "dashboard.card.collapsed.";

function readCollapsed(id: CardId): boolean {
  try {
    return window.localStorage.getItem(STORAGE_PREFIX + id) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(id: CardId, collapsed: boolean): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + id, collapsed ? "1" : "0");
  } catch {
    // A preference that cannot be stored is not an error.
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof FhirHttpError) {
    switch (error.kind) {
      case "unauthorized":
        return "Your sign-in has expired or was revoked. Sign in again to reload this section.";
      case "forbidden":
        return "OpenEMR did not allow this section to be read for this patient.";
      case "not_found":
        return "OpenEMR could not find this data.";
      case "network":
        return "OpenEMR could not be reached.";
      case "invalid":
        return "OpenEMR sent a response this dashboard could not read.";
      case "server":
        return "OpenEMR returned an error.";
    }
  }
  return "This section could not be loaded.";
}

interface CardProps<T> {
  readonly id: CardId;
  readonly title: string;
  readonly query: UseQueryResult<T>;
  /** True when the loaded data has nothing to show; `empty` is rendered instead of `children`. */
  readonly isEmpty: (data: T) => boolean;
  readonly empty: (data: T) => ReactNode;
  readonly children: (data: T) => ReactNode;
  /** Count of entries that failed their schema (R4); shown, never hidden. */
  readonly unreadable?: (data: T) => number;
  /** True when the server had more entries than were read. */
  readonly truncated?: (data: T) => boolean;
  /** The chart editor this card's Edit button opens, shown only when the chart grants it. */
  readonly edit?: EditAction;
}

export function Card<T>({ id, title, query, isEmpty, empty, children, unreadable, truncated, edit }: CardProps<T>) {
  const [collapsed, setCollapsed] = useState(() => readCollapsed(id));
  const bodyId = useId();
  const headingId = useId();
  const slots = useContext(CardSlotsContext)[id];
  const editGrants = useContext(ChartEditContext);
  const canEdit = edit !== undefined && editGrants.has(edit);

  const toggle = () => {
    setCollapsed((c) => {
      writeCollapsed(id, !c);
      return !c;
    });
  };

  let state: "loading" | "error" | "empty" | "data";
  let body: ReactNode;
  if (query.isPending) {
    state = "loading";
    body = (
      <div className="text-muted px-2 py-1" role="status">
        Loading…
      </div>
    );
  } else if (query.isError) {
    state = "error";
    body = (
      <div className="alert alert-danger m-1 py-1 px-2" role="alert">
        <span>{errorMessage(query.error)}</span>{" "}
        <button type="button" className="btn btn-link btn-sm p-0 align-baseline" onClick={() => void query.refetch()}>
          Retry
        </button>
      </div>
    );
  } else {
    const data = query.data;
    const bad = unreadable ? unreadable(data) : 0;
    const cut = truncated ? truncated(data) : false;
    state = isEmpty(data) ? "empty" : "data";
    body = (
      <>
        {state === "empty" ? <div className="list-group-item p-0 pl-1">{empty(data)}</div> : children(data)}
        {bad > 0 ? (
          <div className="alert alert-warning m-1 py-1 px-2" role="alert">
            {bad === 1 ? "1 entry" : `${String(bad)} entries`} could not be read and {bad === 1 ? "is" : "are"} not shown. Check the chart in OpenEMR.
          </div>
        ) : null}
        {cut ? (
          <div className="alert alert-warning m-1 py-1 px-2" role="alert">
            This list is incomplete: OpenEMR has more entries than the dashboard loads. Check the chart in OpenEMR.
          </div>
        ) : null}
      </>
    );
  }

  return (
    <section className="card mb-2" data-card={id} data-state={state} aria-labelledby={headingId}>
      <div className="card-header d-flex justify-content-between align-items-center py-1 px-2">
        <h2 id={headingId} className="h6 mb-0 font-weight-bold">
          {title}
        </h2>
        <div>
          {canEdit ? (
            <button type="button" className="btn btn-sm btn-link text-decoration-none" data-edit={edit} onClick={() => {
              requestChartEdit(edit);
            }}>
              Edit<span className="sr-only"> {title}</span>
            </button>
          ) : null}
        <button
          type="button"
          className="btn btn-sm btn-link text-decoration-none"
          aria-expanded={!collapsed}
          aria-controls={bodyId}
          onClick={toggle}
        >
          {collapsed ? "Show" : "Hide"}
          <span className="sr-only"> {title}</span>
        </button>
        </div>
      </div>
      <div id={bodyId} className="card-body p-1" hidden={collapsed}>
        <div data-slot={`${id}:before`}>{slots?.before}</div>
        <div data-card-body={id}>{body}</div>
        <div data-slot={`${id}:after`}>{slots?.after}</div>
      </div>
    </section>
  );
}
