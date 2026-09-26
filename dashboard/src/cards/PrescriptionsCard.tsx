import { Card } from "./Card";
import { usePrescriptions, useReferenceNames } from "../app/queries";
import { formatDate } from "../format/dates";

export function PrescriptionsCard() {
  const query = usePrescriptions();
  const names = useReferenceNames(query.data?.value.map((p) => p.prescriberRef) ?? []);
  return (
    <Card
      id="prescriptions"
      title="Prescriptions"
      query={query}
      unreadable={(d) => d.unreadable}
      truncated={(d) => d.truncated}
      isEmpty={(d) => d.value.length === 0}
      empty={() => "None"}
    >
      {(d) => (
        <div className="table-responsive">
          <table className="table table-sm table-striped mb-0">
            <thead>
              <tr>
                <th scope="col">Drug</th>
                <th scope="col">Details</th>
                <th scope="col">Qty</th>
                <th scope="col">Refills</th>
                <th scope="col">Written</th>
                <th scope="col">Prescriber</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody>
              {d.value.map((p) => (
                <tr key={p.id} data-item={p.drug} data-status={p.status} className={p.status === "Active" ? undefined : "text-muted"}>
                  <td>{p.drug}</td>
                  <td>{p.details}</td>
                  <td>{p.quantity}</td>
                  <td>{p.refills}</td>
                  <td>{formatDate(p.dateWritten)}</td>
                  <td>{p.prescriberRef ? (names.get(p.prescriberRef) ?? "") : ""}</td>
                  <td>{p.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
