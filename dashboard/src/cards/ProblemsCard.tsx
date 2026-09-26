import { Card } from "./Card";
import { useProblems } from "../app/queries";

export function ProblemsCard() {
  const query = useProblems();
  return (
    <Card
      id="problems"
      title="Medical Problems"
      query={query}
      unreadable={(d) => d.unreadable}
      truncated={(d) => d.truncated}
      isEmpty={(d) => d.value.length === 0}
      empty={() => "None"}
    >
      {(d) => (
        <ul className="list-group list-group-flush">
          {d.value.map((p) => (
            <li key={p.id} className="list-group-item py-1 px-1" data-item={p.title}>
              {p.title}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
