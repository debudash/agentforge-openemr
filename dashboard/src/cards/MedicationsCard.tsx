import { Card } from "./Card";
import { useMedications } from "../app/queries";

export function MedicationsCard() {
  const query = useMedications();
  return (
    <Card
      id="medications"
      title="Medications"
      query={query}
      unreadable={(d) => d.unreadable}
      truncated={(d) => d.truncated}
      isEmpty={(d) => d.value.length === 0}
      empty={() => "None"}
    >
      {(d) => (
        <ul className="list-group list-group-flush">
          {d.value.map((m) => (
            <li key={m.id} className="list-group-item p-0 pl-1" data-item={m.name}>
              <span className="font-weight-normal">{m.name}</span>
              {m.instructions ? <span> {m.instructions}</span> : null}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
