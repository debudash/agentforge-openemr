// Layout mirrors the legacy dashboard: the three PAMI cards in a row, then Prescriptions,
// Care Team, Vitals (spec section 1; "not redesigning the interface").
import { PatientHeader } from "../header/PatientHeader";
import { AllergiesCard } from "../cards/AllergiesCard";
import { ProblemsCard } from "../cards/ProblemsCard";
import { MedicationsCard } from "../cards/MedicationsCard";
import { PrescriptionsCard } from "../cards/PrescriptionsCard";
import { CareTeamCard } from "../cards/CareTeamCard";
import { VitalsCard } from "../cards/VitalsCard";

export function Dashboard() {
  return (
    <>
      <PatientHeader />
      <main className="container-fluid">
        <div className="row">
          <div className="col-md-4 p-1">
            <AllergiesCard />
          </div>
          <div className="col-md-4 p-1">
            <ProblemsCard />
          </div>
          <div className="col-md-4 p-1">
            <MedicationsCard />
          </div>
        </div>
        <div className="row">
          <div className="col-12 p-1">
            <PrescriptionsCard />
          </div>
          <div className="col-12 p-1">
            <CareTeamCard />
          </div>
          <div className="col-12 p-1">
            <VitalsCard />
          </div>
        </div>
        <details className="small text-muted my-2 px-1">
          <summary>About this dashboard</summary>
          <p className="mb-1">
            Read-only. Every section is read from OpenEMR&apos;s FHIR API with your sign-in, for the patient you chose
            when signing in.
          </p>
          <p className="mb-1">
            OpenEMR&apos;s API checks medical-record access as a whole. Restrictions the classic dashboard applies per
            issue type or per patient group (squad) are not applied by the API, so this dashboard can show sections
            the classic one hides for such accounts.
          </p>
          <p className="mb-0">
            &quot;No Known Allergies&quot; appears only when it was recorded as an allergy entry; otherwise an empty
            list reads &quot;No allergies recorded&quot;.
          </p>
        </details>
      </main>
    </>
  );
}
