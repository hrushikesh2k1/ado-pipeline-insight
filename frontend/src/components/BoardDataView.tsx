import { useEffect, useState } from "react";
import ReactECharts from "echarts-for-react";
import { planningRequest } from "./PlanningAssistant";
type Props = {
  view: string;
  organization: string;
  project: string;
  team: string;
  teamName: string;
  iterationId: string;
  pat?: string;
};
export function BoardDataView(props: Props) {
  const [data, setData] = useState<any>(null),
    [error, setError] = useState(""),
    [selection, setSelection] = useState({ scope: "", level: "" }),
    [refresh, setRefresh] = useState(0);
  const scope = JSON.stringify([props.organization, props.project, props.team]);
  const level = selection.scope === scope ? selection.level : "";
  const setLevel = (value: string) => setSelection({ scope, level: value });
  useEffect(() => {
    let alive = true;
    setData(null);
    setError("");
    if (props.team && props.iterationId)
      planningRequest(
        "/board-view",
        props,
        {},
        {
          view: props.view,
          ...(level && props.view === "backlog" ? { level } : {}),
        },
      )
        .then((d) => {
          if (alive) setData(d);
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    return () => {
      alive = false;
    };
  }, [
    props.view,
    props.organization,
    props.project,
    props.team,
    props.iterationId,
    props.pat,
    level,
    refresh,
  ]);
  return (
    <section className="deliverables">
      <h2>{props.view.charAt(0).toUpperCase() + props.view.slice(1)}</h2>
      <button onClick={() => setRefresh((v) => v + 1)}>
        Refresh Azure DevOps data
      </button>
      {error && <p role="alert">{error}</p>}
      {!data && !error && <p role="status">Loading Azure DevOps data…</p>}
      {data && (
        <>
          <p>{data.source}</p>
          {props.view === "capacity" && (
            <>
              <p>Working days: {data.working_days.join(", ")}</p>
              <p>
                Team days off:{" "}
                {data.team_days_off
                  .map(
                    (d: any) =>
                      `${d.start.slice(0, 10)} – ${d.end.slice(0, 10)}`,
                  )
                  .join("; ") || "None recorded"}
              </p>
              <table>
                <thead>
                  <tr>
                    <th>Person</th>
                    <th>Daily activities</th>
                    <th>Days off</th>
                    <th>Available hours</th>
                  </tr>
                </thead>
                <tbody>
                  {data.people.map((p: any) => (
                    <tr key={p.person.id}>
                      <td>{p.person.name}</td>
                      <td>
                        {p.activities
                          .map((a: any) => `${a.name}: ${a.capacityPerDay} h`)
                          .join("; ")}
                      </td>
                      <td>
                        {p.days_off
                          .map(
                            (d: any) =>
                              `${d.start.slice(0, 10)} – ${d.end.slice(0, 10)}`,
                          )
                          .join("; ") || "None recorded"}
                      </td>
                      <td>{p.available_hours ?? "Unavailable"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {props.view === "backlog" && (
            <>
              <label>
                Backlog level
                <select
                  value={level || data.selected_level}
                  onChange={(e) => setLevel(e.target.value)}
                >
                  {data.levels.map((l: any) => (
                    <option key={l.id} value={l.id}>
                      {l.name}
                    </option>
                  ))}
                </select>
              </label>
              <table>
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Title</th>
                    <th>Type</th>
                    <th>State</th>
                    <th>Owner</th>
                    <th>Priority</th>
                    <th>Iteration</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((i: any) => (
                    <tr key={i.id}>
                      <td><a href={i.web_url} target="_blank" rel="noreferrer">#{i.id}</a></td>
                      <td>{i.fields["System.Title"]}</td>
                      <td>{i.fields["System.WorkItemType"]}</td>
                      <td>{i.fields["System.State"]}</td>
                      <td>
                        {i.fields["System.AssignedTo"]?.displayName ||
                          "Unassigned"}
                      </td>
                      <td>
                        {i.fields["Microsoft.VSTS.Common.Priority"] ??
                          "Not configured"}
                      </td>
                      <td>{i.fields["System.IterationPath"]}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
          {props.view === "analytics" && (
            <>
              <p>{data.warning}</p>
              <ReactECharts
                option={{
                  tooltip: { trigger: "axis" },
                  xAxis: {
                    type: "category",
                    data: data.points.map((p: any) => p.date),
                  },
                  yAxis: { type: "value", name: "Remaining hours" },
                  series: [
                    {
                      type: "line",
                      name: "Remaining task work",
                      data: data.points.map((p: any) => p.remaining_hours),
                    },
                  ],
                }}
              />
              <table>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Remaining hours</th>
                    <th>Tasks</th>
                    <th>Missing values</th>
                  </tr>
                </thead>
                <tbody>
                  {data.points.map((p: any) => (
                    <tr key={p.date}>
                      <td>{p.date}</td>
                      <td>{p.remaining_hours}</td>
                      <td>{p.tasks}</td>
                      <td>{p.missing_remaining_work}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </>
          )}
        </>
      )}
    </section>
  );
}
