import { useEffect, useState } from "react";
import "./DeliverablesPage.css";
import { openMailDraft } from "../utils/mailDraft";
import { request } from "../services/api";
type Props = {
  organization: string;
  project: string;
  team: string;
  teamName: string;
  iterationId: string;
  pat?: string;
};
export async function planningRequest(
  path: string,
  props: Props,
  options: RequestInit = {},
  extra: Record<string, string> = {},
) {
  const params = new URLSearchParams({
    organization: props.organization,
    project: props.project,
    team: props.team,
    iteration_id: props.iterationId,
    ...extra,
  });
  return request<any>(`/api/v1/planning${path}?${params}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(props.pat ? { "X-ADO-PAT": props.pat } : {}),
      ...options.headers,
    },
  });
}
export function PlanningAssistant(props: Props) {
  const [data, setData] = useState<any>(null),
    [settings, setSettings] = useState<any>(null),
    [error, setError] = useState(""),
    [message, setMessage] = useState(""),
    [draft, setDraft] = useState<any>(null),
    [proposal, setProposal] = useState<any>(null),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    setData(null);
    setDraft(null);
    setProposal(null);
    setError("");
    if (props.team && props.iterationId)
      planningRequest("", props)
        .then((d) => {
          if (alive) {
            setData(d);
            setSettings(d.settings);
            setProposal(d.proposal);
          }
        })
        .catch((e) => {
          if (alive) setError(e.message);
        });
    return () => {
      alive = false;
    };
  }, [
    props.organization,
    props.project,
    props.team,
    props.iterationId,
    props.pat,
  ]);
  async function action(work: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await work();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    await planningRequest("/settings", props, {
      method: "PUT",
      body: JSON.stringify(settings),
    });
    setMessage(
      "Settings saved for this team; responses and proposals remain scoped to the selected sprint.",
    );
  }
  async function prepare(kind: string, id: string) {
    await save();
    const d = await planningRequest(
      "/draft",
      props,
      { method: "POST" },
      { kind, person_id: id },
    );
    const link = new URL(window.location.origin + window.location.pathname);
    link.hash = new URLSearchParams({ planning_response: d.token }).toString();
    setDraft({
      ...d,
      subject: `[TEST] ${kind === "leave" ? "Leave plans" : "Sprint priorities"} — ${props.teamName} — ${d.sprint}`,
      body: `Testing only. Intended respondent: ${d.intended_person}.\nPlease submit ${kind === "leave" ? "your tentative or confirmed leave plans, or confirm no leave" : "ranked priority outcomes and relevant work item IDs"} for ${d.sprint}.\n${link.toString()}\nNo Azure DevOps assignments will be changed.`,
    });
  }
  return (
    <section className="deliverables planningAssistant">
      <h2>Planning Assistant</h2>
      <p>{props.teamName} · Proposal only — no Azure DevOps writes.</p>
      <p>
        Test mode: every draft targets hrushikeshboora@gmail.com. Automatic
        sending is unavailable until an approved provider is connected.
      </p>
      {error && <p role="alert">{error}</p>}
      {message && <p role="status">{message}</p>}
      {!data && (
        <p>Select a team and sprint, or wait for planning inputs to load.</p>
      )}
      {data && settings && (
        <>
          <h3>Planning schedule</h3>
          <label>
            Planning day{" "}
            <input
              type="number"
              min="1"
              max="28"
              value={settings.planning_day}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  planning_day: Number(e.target.value),
                })
              }
            />
          </label>
          <label>
            Period{" "}
            <select
              value={settings.period}
              onChange={(e) =>
                setSettings({ ...settings, period: e.target.value })
              }
            >
              <option value="current">Current month</option>
              <option value="next">Following month</option>
            </select>
          </label>
          <label>
            Reminder days (up to three){" "}
            <input
              value={settings.reminder_days.join(",")}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  reminder_days: e.target.value.split(",").map(Number),
                })
              }
            />
          </label>
          <p>
            The selected Azure DevOps sprint dates determine the actual response
            period. These schedule settings are saved, but no background emails
            are sent.
          </p>
          <h3>Leave reminders</h3>
          <label>
            <input
              type="checkbox"
              disabled
              checked={settings.leave_automatic}
            />{" "}
            Automatic reminders (provider required)
          </label>
          <p>Select intended team recipients:</p>
          {data.members.map((m: any) => (
            <label key={m.id} style={{ display: "block" }}>
              <input
                type="checkbox"
                checked={settings.leave_recipients.includes(m.id)}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    leave_recipients: e.target.checked
                      ? [...settings.leave_recipients, m.id]
                      : settings.leave_recipients.filter(
                          (id: string) => id !== m.id,
                        ),
                  })
                }
              />
              {m.name} —{" "}
              {data.responses["leave:" + m.id]
                ? "Responded"
                : "Awaiting response"}{" "}
              <button
                disabled={busy || !settings.leave_recipients.includes(m.id)}
                onClick={() => action(() => prepare("leave", m.id))}
              >
                Prepare test reminder
              </button>
            </label>
          ))}
          <h3>Priority requests</h3>
          <label>
            Lead email addresses (separate with semicolons)
            <input
              style={{ width: "100%" }}
              value={settings.lead_emails.join(";")}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  lead_emails: e.target.value
                    .split(";")
                    .map((v) => v.trim())
                    .filter(Boolean),
                })
              }
            />
          </label>
          <label>
            <input
              type="checkbox"
              disabled
              checked={settings.priorities_automatic}
            />{" "}
            Automatic requests (provider required)
          </label>
          {settings.lead_emails.map((email: string) => (
            <p key={email}>
              {email} —{" "}
              {data.responses["priorities:" + email]
                ? "Responded"
                : "Awaiting response"}{" "}
              <button
                disabled={busy}
                onClick={() => action(() => prepare("priorities", email))}
              >
                Prepare test priority request
              </button>
            </p>
          ))}
          <button disabled={busy} onClick={() => action(save)}>
            Save settings
          </button>
          <button
            disabled={busy}
            onClick={() =>
              action(async () => {
                await save();
                setProposal(
                  await planningRequest("/proposal", props, { method: "POST" }),
                );
              })
            }
          >
            Generate proposal now
          </button>
          <button
            onClick={() =>
              action(async () => {
                const d = await planningRequest("", props);
                setData(d);
                setMessage("Responses refreshed.");
              })
            }
          >
            Refresh responses
          </button>
          {draft && (
            <div>
              <h3>Test email preview</h3>
              <p>To: {draft.to.join("; ")}</p>
              <p>Subject: {draft.subject}</p>
              <textarea
                readOnly
                className="deliverablesPreview"
                value={draft.body}
              />
              <button
                onClick={() =>
                  action(async () => {
                    await navigator.clipboard.writeText(
                      `To: ${draft.to.join("; ")}\nSubject: ${draft.subject}\n\n${draft.body}`,
                    );
                    setMessage("Email copied.");
                  })
                }
              >
                Copy Email
              </button>
              <button
                onClick={() =>
                  action(async () => {
                    try {
                      setMessage(await openMailDraft(draft));
                    } catch {
                      throw Error(
                        "Clipboard access is unavailable. Copy the preview manually, then use Outlook with the displayed recipient and subject.",
                      );
                    }
                  })
                }
              >
                Open Outlook Draft
              </button>
              <a
                href={
                  window.location.pathname +
                  "#" +
                  new URLSearchParams({
                    planning_response: draft.token,
                  }).toString()
                }
                target="_blank"
                rel="noreferrer"
              >
                Open test response form
              </a>
            </div>
          )}
          {proposal && (
            <div>
              <h3>Proposed sprint — review required</h3>
              <p>{proposal.message}</p>
              {proposal.warnings.map((w: string) => (
                <p key={w}>{w}</p>
              ))}
              <table>
                <thead>
                  <tr>
                    <th>Priority</th>
                    <th>Work item</th>
                    <th>Suggested person</th>
                    <th>Estimated hours</th>
                    <th>Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {proposal.items.map((i: any) => (
                    <tr key={i.id}>
                      <td>{i.rank}</td>
                      <td>
                        #{i.id} {i.title}
                      </td>
                      <td>{i.person || "Unassigned"}</td>
                      <td>{i.hours ?? "Missing estimate"}</td>
                      <td>{i.reason}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <h4>Capacity scenarios</h4>
              {proposal.capacity.map((c: any) => (
                <p key={c.id}>
                  {c.name}: base {c.base ?? "unavailable"} h; confirmed-leave
                  scenario {c.confirmed ?? "unavailable"} h; including tentative{" "}
                  {c.tentative ?? "unavailable"} h
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </section>
  );
}
export function PlanningResponseForm({ token }: { token: string }) {
  const [data, setData] = useState<any>(null),
    [error, setError] = useState(""),
    [saved, setSaved] = useState(false),
    [noLeave, setNoLeave] = useState(false),
    [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [tentative, setTentative] = useState(true),
    [hours, setHours] = useState(""),
    [leave, setLeave] = useState<any[]>([]),
    [outcome, setOutcome] = useState(""),
    [rank, setRank] = useState(1),
    [ids, setIds] = useState(""),
    [priorities, setPriorities] = useState<any[]>([]);
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    let current = true;
    setData(null);
    setError("");
    setSaved(false);
    request<any>("/api/v1/planning/response?" + new URLSearchParams({ token }))
      .then((d) => {
        if (!current) return;
        setData(d);
        if (d.existing) {
          setNoLeave(d.existing.no_leave);
          setLeave(d.existing.leave || []);
          setPriorities(d.existing.priorities || []);
        }
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [token]);
  async function submit() {
    setError("");
    setSubmitting(true);
    try {
      await request(
        "/api/v1/planning/response?" + new URLSearchParams({ token }),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            person_id: data.person_id,
            no_leave: noLeave,
            leave: noLeave ? [] : leave,
            priorities,
          }),
        },
      );
      setSaved(true);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }
  return (
    <main className="deliverables planningResponse">
      <h2>Planning response</h2>
      <p>
        Test submission. Existing application sign-in is required. This link
        identifies the intended respondent; do not forward it.
      </p>
      {error && <p role="alert">{error}</p>}
      {saved ? (
        <p role="status">Response saved. You may close this page.</p>
      ) : (
        data && (
          <>
            <p>
              Request: {data.kind} · Sprint: {data.sprint || data.scope[3]}
            </p>
            {data.existing && (
              <p>A previous response exists. Submitting replaces it.</p>
            )}
            {data.kind === "leave" ? (
              <>
                <label>
                  <input
                    type="checkbox"
                    checked={noLeave}
                    onChange={(e) => setNoLeave(e.target.checked)}
                  />
                  No leave planned
                </label>
                {!noLeave && (
                  <>
                    <label>
                      Start
                      <input
                        type="date"
                        value={start}
                        onChange={(e) => setStart(e.target.value)}
                      />
                    </label>
                    <label>
                      End
                      <input
                        type="date"
                        value={end}
                        onChange={(e) => setEnd(e.target.value)}
                      />
                    </label>
                    <label>
                      Hours per day (blank = full configured day)
                      <input
                        type="number"
                        value={hours}
                        onChange={(e) => setHours(e.target.value)}
                      />
                    </label>
                    <label>
                      <input
                        type="checkbox"
                        checked={tentative}
                        onChange={(e) => setTentative(e.target.checked)}
                      />
                      Tentative
                    </label>
                    <button
                      onClick={() => {
                        if (!start || !end || end < start) {
                          setError("Choose valid leave dates.");
                          return;
                        }
                        setLeave([
                          ...leave,
                          {
                            start,
                            end,
                            tentative,
                            hours_per_day: hours ? Number(hours) : null,
                          },
                        ]);
                      }}
                    >
                      Add leave period
                    </button>
                    {leave.map((l, i) => (
                      <p key={i}>
                        {l.start} to {l.end} ·{" "}
                        {l.tentative ? "Tentative" : "Confirmed"}{" "}
                        <button
                          onClick={() =>
                            setLeave(leave.filter((_, j) => i !== j))
                          }
                        >
                          Remove
                        </button>
                      </p>
                    ))}
                  </>
                )}
              </>
            ) : (
              <>
                <label>
                  Priority outcome
                  <input
                    value={outcome}
                    onChange={(e) => setOutcome(e.target.value)}
                  />
                </label>
                <label>
                  Rank
                  <input
                    type="number"
                    min="1"
                    value={rank}
                    onChange={(e) => setRank(Number(e.target.value))}
                  />
                </label>
                <label>
                  Work item IDs (comma separated)
                  <input value={ids} onChange={(e) => setIds(e.target.value)} />
                </label>
                <button
                  onClick={() => {
                    setPriorities([
                      ...priorities,
                      {
                        outcome,
                        rank,
                        work_item_ids: ids
                          .split(",")
                          .filter((v) => v.trim())
                          .map(Number),
                      },
                    ]);
                    setOutcome("");
                    setIds("");
                  }}
                >
                  Add priority
                </button>
                {priorities.map((p, i) => (
                  <p key={i}>
                    {p.rank}: {p.outcome}{" "}
                    <button
                      onClick={() =>
                        setPriorities(priorities.filter((_, j) => i !== j))
                      }
                    >
                      Remove
                    </button>
                  </p>
                ))}
              </>
            )}
            <button disabled={submitting} onClick={submit}>
              {submitting ? "Saving response…" : "Submit response"}
            </button>
          </>
        )
      )}
    </main>
  );
}
