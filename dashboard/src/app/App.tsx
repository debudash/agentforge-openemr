// The app's states: launching (EHR launch, ADR 0009) | checking -> signed out | signed in | login
// failed. Nothing patient-specific is requested or rendered until a token and its patient exist
// (R1, designs out BUG-003).
import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  chartPatient,
  completeLogin,
  ehrLaunchParams,
  hasPendingOrStoredLogin,
  startEhrLaunch,
  startLogin,
  LoginError,
  type EhrLaunch,
  type SignedIn,
} from "../auth/smart";
import { SessionProvider } from "./session";
import { shouldRetry } from "./queries";
import { Dashboard } from "./Dashboard";
import { ErrorBoundary } from "./ErrorBoundary";

type AppState =
  | { readonly kind: "launching"; readonly ehr: EhrLaunch }
  | { readonly kind: "checking" }
  | { readonly kind: "signed-out" }
  | { readonly kind: "signed-in"; readonly session: SignedIn }
  | { readonly kind: "failed"; readonly reason: LoginError["reason"] };

export interface AppDeps {
  readonly hasLogin: () => boolean;
  readonly complete: () => Promise<SignedIn>;
  readonly start: () => Promise<void>;
  /** EHR launch parameters on this page's URL; absent means a standalone start. */
  readonly ehrLaunch?: () => EhrLaunch | null;
  readonly startEhr?: (ehr: EhrLaunch) => Promise<void>;
  /** True when the chart embeds the app: it then offers no standalone sign-in. */
  readonly inChart?: () => boolean;
}

const defaultDeps: AppDeps = {
  hasLogin: hasPendingOrStoredLogin,
  complete: () => completeLogin(),
  start: () => startLogin(),
  ehrLaunch: ehrLaunchParams,
  startEhr: (ehr) => startEhrLaunch(ehr),
  inChart: () => chartPatient() !== null,
};

function initialState(deps: AppDeps): AppState {
  const ehr = deps.ehrLaunch?.() ?? null;
  if (ehr) return { kind: "launching", ehr };
  return deps.hasLogin() ? { kind: "checking" } : { kind: "signed-out" };
}

export function makeQueryClient(options: { readonly retryDelayMs?: number } = {}): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: shouldRetry,
        refetchOnWindowFocus: false,
        staleTime: 60_000,
        ...(options.retryDelayMs === undefined ? {} : { retryDelay: options.retryDelayMs }),
      },
    },
  });
}

const FAILURE_TEXT: Record<LoginError["reason"], string> = {
  "no-patient": "No patient was selected during sign-in. Sign in again and choose a patient.",
  failed: "Sign-in did not complete. Sign in again.",
  "wrong-server": "The sign-in was for a different server. Sign in again.",
  "wrong-patient": "This dashboard was opened for a different patient than the chart. Open the patient again.",
};

/** In the chart the patient is opened from the chart, never picked here. */
const IN_CHART_FAILURE_TEXT: Record<LoginError["reason"], string> = {
  "no-patient": "The chart did not pass a patient to the dashboard. Open the patient again.",
  failed: "The dashboard could not sign in. Open the patient again.",
  "wrong-server": "The dashboard was launched by a different server. Open the patient again.",
  "wrong-patient": FAILURE_TEXT["wrong-patient"],
};

export function App({ deps = defaultDeps, queryClient }: { deps?: AppDeps; queryClient?: QueryClient }) {
  const [state, setState] = useState<AppState>(() => initialState(deps));
  const [client] = useState(() => queryClient ?? makeQueryClient());
  const [inChart] = useState(() => deps.inChart?.() ?? false);

  useEffect(() => {
    if (state.kind !== "launching") return;
    let live = true;
    // Redirects to OpenEMR's authorization endpoint; only a refusal comes back here.
    (deps.startEhr ?? (() => Promise.reject(new LoginError("failed"))))(state.ehr).catch((e: unknown) => {
      if (live) setState({ kind: "failed", reason: e instanceof LoginError ? e.reason : "failed" });
    });
    return () => {
      live = false;
    };
  }, [state, deps]);

  useEffect(() => {
    if (state.kind !== "checking") return;
    let live = true;
    deps
      .complete()
      .then((session) => {
        if (live) setState({ kind: "signed-in", session });
      })
      .catch((e: unknown) => {
        if (live) setState({ kind: "failed", reason: e instanceof LoginError ? e.reason : "failed" });
      });
    return () => {
      live = false;
    };
  }, [state.kind, deps]);

  const signIn = (
    <button type="button" className="btn btn-primary" onClick={() => void deps.start()}>
      Sign in with OpenEMR
    </button>
  );

  switch (state.kind) {
    case "launching":
    case "checking":
      return (
        <main className="container py-4" role="status">
          Signing in…
        </main>
      );
    case "signed-out":
      return inChart ? (
        <main className="container py-4">
          <div className="alert alert-warning" role="alert">
            The dashboard was not launched for this patient. Open the patient again.
          </div>
        </main>
      ) : (
        <main className="container py-4">
          <h1 className="h4">Patient Dashboard</h1>
          <p>Sign in with your OpenEMR account, then choose the patient to open.</p>
          {signIn}
        </main>
      );
    case "failed":
      return (
        <main className="container py-4">
          <h1 className="h4">Patient Dashboard</h1>
          <div className="alert alert-danger" role="alert">
            {(inChart ? IN_CHART_FAILURE_TEXT : FAILURE_TEXT)[state.reason]}
          </div>
          {inChart ? null : signIn}
        </main>
      );
    case "signed-in":
      return (
        <ErrorBoundary>
          <QueryClientProvider client={client}>
            <SessionProvider session={state.session}>
              <Dashboard />
            </SessionProvider>
          </QueryClientProvider>
        </ErrorBoundary>
      );
  }
}
