import { Card } from "./Card";
import { useVitals } from "../app/queries";
import { formatDate } from "../format/dates";

export function VitalsCard() {
  const query = useVitals();
  return (
    <Card
      id="vitals"
      title="Vitals"
      query={query}
      unreadable={(d) => d.unreadable}
      truncated={(d) => d.truncated}
      isEmpty={(d) => d.value === null || d.value.rows.length === 0}
      empty={() => "No vitals have been documented."}
    >
      {(d) =>
        d.value ? (
          <>
            <div className="px-1 font-weight-bold" data-vitals-date={d.value.takenAt.slice(0, 10)}>
              Most recent vitals from: {formatDate(d.value.takenAt)}
            </div>
            <table className="table table-sm mb-0">
              <tbody>
                {d.value.rows.map((r) => (
                  <tr key={r.key} data-item={r.key} data-value={r.value}>
                    <th scope="row" className="font-weight-normal">
                      {r.label}
                    </th>
                    <td>{r.value}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null
      }
    </Card>
  );
}
