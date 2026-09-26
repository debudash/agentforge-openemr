// The persistent identity bar: name, DOB, age, sex, MRN and status (brief; spec section 5).
// The status never comes from Patient.active (API-02). The Co-Pilot links carry the FHIR
// patient id, never the internal pid (ADR 0006); the module page refuses a mismatch.
import { useQuery } from "@tanstack/react-query";
import { usePatient, useSignedInUserName } from "../app/queries";
import { useSession } from "../app/session";
import { COPILOT_MODULE_PATH, fetchModuleFlags } from "../fhir/http";
import { errorMessage } from "../cards/Card";
import { signOut } from "../auth/smart";

export function moduleLink(page: "patient.php" | "demo.php", patientId: string): string {
  const url = new URL(COPILOT_MODULE_PATH + page, window.location.origin);
  url.searchParams.set("patient", patientId);
  // Without a site OpenEMR answers a session-less request with 400 instead of its login page.
  url.searchParams.set("site", import.meta.env.VITE_OPENEMR_SITE ?? "default");
  return url.href;
}

function CopilotLinks({ patientId }: { patientId: string }) {
  const flags = useQuery({ queryKey: ["module-flags"], queryFn: ({ signal }) => fetchModuleFlags(signal), staleTime: Infinity });
  return (
    <nav aria-label="Co-Pilot" className="d-flex">
      <a className="btn btn-sm btn-outline-primary mr-1" href={moduleLink("patient.php", patientId)} target="_blank" rel="noopener noreferrer">
        Co-Pilot
      </a>
      {flags.data?.demoTools ? (
        <a className="btn btn-sm btn-outline-secondary" href={moduleLink("demo.php", patientId)} target="_blank" rel="noopener noreferrer">
          Demo Data
        </a>
      ) : null}
    </nav>
  );
}

export function PatientHeader() {
  const session = useSession();
  const patient = usePatient();
  const userName = useSignedInUserName();

  return (
    <header className="bg-white border-bottom mb-2 px-2 py-2" aria-label="Patient">
      <div className="d-flex flex-wrap justify-content-between align-items-start">
        <div data-header-state={patient.isPending ? "loading" : patient.isError ? "error" : "data"}>
          {patient.isPending ? (
            <span role="status">Loading patient…</span>
          ) : patient.isError ? (
            <span className="text-danger" role="alert">
              {errorMessage(patient.error)}
            </span>
          ) : (
            <>
              <h1 className="h5 mb-1">
                <span data-field="name">{patient.data.name}</span>{" "}
                <span className="text-muted">
                  (<span data-field="mrn">{patient.data.mrn}</span>)
                </span>
              </h1>
              <dl className="d-flex flex-wrap mb-0 small">
                <dt className="mr-1">DOB:</dt>
                <dd className="mr-3 mb-0" data-field="dob">
                  {patient.data.dob}
                </dd>
                <dt className="mr-1">{patient.data.ageLabel}:</dt>
                <dd className="mr-3 mb-0" data-field="age">
                  {patient.data.age}
                </dd>
                <dt className="mr-1">Sex:</dt>
                <dd className="mr-3 mb-0" data-field="sex">
                  {patient.data.sex}
                </dd>
                <dt className="mr-1">Status:</dt>
                <dd className={`mb-0 ${patient.data.status.kind === "deceased" ? "text-danger font-weight-bold" : ""}`} data-field="status">
                  {patient.data.status.label}
                </dd>
              </dl>
            </>
          )}
        </div>
        <div className="d-flex align-items-center">
          <CopilotLinks patientId={session.patientId} />
          <span className="small text-muted mx-2">{userName ? `Signed in as ${userName}` : null}</span>
          <button type="button" className="btn btn-sm btn-outline-secondary" onClick={signOut}>
            Sign out
          </button>
        </div>
      </div>
    </header>
  );
}
