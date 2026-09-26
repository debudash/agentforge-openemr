import { Card } from "./Card";
import { useAllergies } from "../app/queries";

export function AllergiesCard() {
  const query = useAllergies();
  return (
    <Card
      id="allergies"
      title="Allergies"
      query={query}
      unreadable={(d) => d.unreadable}
      truncated={(d) => d.truncated}
      isEmpty={(d) => d.value.kind !== "list"}
      empty={(d) => (d.value.kind === "no-known-allergies" ? "No Known Allergies" : "No allergies recorded")}
    >
      {(d) =>
        d.value.kind === "list" ? (
          <ul className="list-group list-group-flush">
            {d.value.items.map((a) => (
              <li key={a.id} className="list-group-item p-1" data-item={a.substance} data-alarm={a.alarm ? "true" : undefined}>
                <span className={a.alarm ? "bg-warning font-weight-bold px-1" : undefined}>{a.substance}</span>
                {a.severityLabel ? <span> ({a.severityLabel})</span> : null}
                {a.reactions ? <div className="small text-muted">Reaction: {a.reactions}</div> : null}
              </li>
            ))}
          </ul>
        ) : null
      }
    </Card>
  );
}
