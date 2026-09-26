// The app's states: checking -> signed out | signed in | login failed. Nothing patient-specific
// is requested or rendered until a token and its patient exist (R1, designs out BUG-003).
import { useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { completeLogin, hasPendingOrStoredLogin, startLogin, LoginError, type SignedIn } from "../auth/smart";
import { SessionProvider } from "./session";
import { shouldRetry } from "./queries";
import { Dashboard } from "./Dashboard";
import { ErrorBoundary } from "./ErrorBoundary";

type AppState =
  | { readonly kind: "checking" }
  | { readonly kind: "signed-out" }
  | { readonly kind: "signed-in"; readonly session: SignedIn }
  | { readonly kind: "failed"; readonly reason: LoginError["reason"] };

export interface AppDeps {
  readonly hasLogin: () => boolean;
  readonly complete: () => Promise<SignedIn>;
  readonly start: () => Promise<void>;
}

const defaultDeps: AppDeps = { hasLogin: hasPendingOrStoredLogin, complete: () => completeLogin(), start: () => startLogin() };

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
};

export function App({ deps = defaultDeps, queryClient }: { deps?: AppDeps; queryClient?: QueryClient }) {
  const [state, setState] = useState<AppState>(() => (deps.hasLogin() ? { kind: "checking" } : { kind: "signed-out" }));
  const [client] = useState(() => queryClient ?? makeQueryClient());

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
    case "checking":
      return (
        <main className="container py-4" role="status">
          Signing in…
        </main>
      );
    case "signed-out":
      return (
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
            {FAILURE_TEXT[state.reason]}
          </div>
          {signIn}
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
