// One friendly error boundary at the UI layer (4.5). It shows no error detail: the message could
// carry data, and the clinician needs to know only that the dashboard failed, not why.
import { Component, type ReactNode } from "react";

interface State {
  readonly failed: boolean;
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  override state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  // No componentDidCatch: errors are not logged, since they may include patient data (R8).

  override render() {
    if (this.state.failed) {
      return (
        <main className="container py-4">
          <div className="alert alert-danger" role="alert">
            The dashboard stopped because of an unexpected error. Reload the page to try again; if it keeps
            happening, use the chart in OpenEMR.
          </div>
        </main>
      );
    }
    return this.props.children;
  }
}
