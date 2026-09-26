import { Card } from "./Card";
import { useCareTeams, useReferenceNames } from "../app/queries";
import { formatDate } from "../format/dates";

export function CareTeamCard() {
  const query = useCareTeams();
  const refs = (query.data?.value ?? []).flatMap((t) => t.members.flatMap((m) => [m.memberRef, m.facilityRef]));
  const names = useReferenceNames(refs);
  return (
    <Card
      id="care-team"
      title="Care Team"
      query={query}
      unreadable={(d) => d.unreadable}
      truncated={(d) => d.truncated}
      isEmpty={(d) => d.value.length === 0}
      empty={() => "No care team"}
    >
      {(d) => (
        <>
          {d.value.map((team) => (
            <div key={team.id} className="mb-1">
              <div className="px-1">
                <span className="font-weight-bold">{team.name}</span>{" "}
                <span className={`badge ${team.status === "Active" ? "badge-success" : "badge-secondary"}`}>{team.status}</span>
              </div>
              {team.members.length === 0 ? (
                <div className="px-1 text-muted">No members listed</div>
              ) : (
                <div className="table-responsive">
                  <table className="table table-sm mb-0">
                    <thead>
                      <tr>
                        <th scope="col">Type</th>
                        <th scope="col">Member</th>
                        <th scope="col">Role</th>
                        <th scope="col">Facility</th>
                        <th scope="col">Since</th>
                      </tr>
                    </thead>
                    <tbody>
                      {team.members.map((m) => {
                        const name = names.get(m.memberRef) ?? m.memberDisplay ?? "";
                        return (
                          <tr key={m.key} data-item={name}>
                            <td>
                              <span className={`badge ${m.kind === "provider" ? "badge-primary" : "badge-info"}`}>
                                {m.kind === "provider" ? "Provider" : "Related person"}
                              </span>
                            </td>
                            <td>{name || "Unknown member"}</td>
                            <td>{m.role}</td>
                            <td>{m.facilityRef ? (names.get(m.facilityRef) ?? "") : ""}</td>
                            <td>{formatDate(m.since)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          ))}
        </>
      )}
    </Card>
  );
}
