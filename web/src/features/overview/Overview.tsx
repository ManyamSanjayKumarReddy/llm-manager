import { api } from "../../api/client";
import type { ModelStatus, StatusData } from "../../api/types";
import { CountUp } from "../../components/CountUp";
import { Reveal } from "../../components/Reveal";
import { Deco } from "../../components/Stickers";
import { Alert, Empty, PageHead, Pill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { clock, seconds } from "../../lib/format";
import { Icon } from "../../components/Icon";
import { Link } from "../../router/Link";

const REFRESH_MS = 2000;

export function Overview() {
  const status = useAsync(() => api.status(), REFRESH_MS);
  const data = status.data;
  return (
    <div className="page">
      <PageHead eyebrow="Live" title="Overview">
        What your GPUs are doing right now: which models are loaded, who holds each GPU, and what woke or slept recently. Updates every couple of seconds.
      </PageHead>
      {status.error ? <Alert notice={{ kind: "error", text: `Live status unavailable: ${status.error}` }} /> : null}
      {data ? <Content data={data} /> : null}
    </div>
  );
}

const NO_SERVER = "this-server";

/** The models of one server and the GPUs they may use, in the order the servers were first seen. */
interface Group {
  name: string;
  models: [string, ModelStatus][];
  gpus: { gpu: number; model: string | null; state: string | null }[];
}

function groupByServer(data: StatusData): Group[] {
  const groups = new Map<string, Group>();
  const of = (name: string) => {
    let group = groups.get(name);
    if (!group) {
      group = { name, models: [], gpus: [] };
      groups.set(name, group);
    }
    return group;
  };
  for (const entry of Object.entries(data.models)) of(entry[1].server ?? NO_SERVER).models.push(entry);
  for (const server of data.servers ?? []) of(server.name).gpus = server.gpus;
  return [...groups.values()].sort((a, b) => a.name.localeCompare(b.name));
}

function Content({ data }: { data: StatusData }) {
  const models = Object.entries(data.models);
  const groups = groupByServer(data);
  const awake = models.filter(([, m]) => m.state === "awake").length;
  const requests = models.reduce((sum, [, m]) => sum + m.requests, 0);
  // GPUs are counted per server when the router says so, else from the flat list.
  const gpuTotal = data.servers ? groups.reduce((n, g) => n + g.gpus.length, 0) : Object.keys(data.gpus).length;
  const gpusBusy = data.servers ? groups.reduce((n, g) => n + g.gpus.filter((x) => x.model !== null).length, 0) : Object.values(data.gpus).filter(Boolean).length;
  const wakes = models.filter(([, m]) => m.avg_wake_s != null);
  const avgWake = wakes.length ? wakes.reduce((s, [, m]) => s + (m.avg_wake_s ?? 0), 0) / wakes.length : null;

  return (
    <>
      <Reveal>
        <div className="stats">
          <Stat label="Models awake" value={<><CountUp value={awake} />/{models.length}</>} />
          <Stat label="GPUs in use" value={<><CountUp value={gpusBusy} />/{gpuTotal}</>} />
          <Stat label="Requests since start" value={<CountUp value={requests} />} />
          <Stat label="Average wake" value={avgWake == null ? "–" : seconds(avgWake)} />
        </div>
      </Reveal>

      <div className="section-title">
        <h2>Your servers</h2>
        <span className="count">{groups.length} {groups.length === 1 ? "server" : "servers"} · {models.length} models · router up {seconds(data.uptime_s)}</span>
      </div>
      {models.length === 0 ? (
        <Empty
          sticker={<Deco name="thinking" size={120} />}
          title="No models yet"
          action={<Link className="btn primary" to="/models"><Icon name="plus" /> Add a model</Link>}
        >
          Register the vLLM containers you run, and they appear here.
        </Empty>
      ) : (
        groups.map((group, i) => (
          <Reveal key={group.name} delay={i * 70}>
            <ServerGroup group={group} />
          </Reveal>
        ))
      )}

      <Reveal>
        <section className="surface stack">
          <div className="section-title">
            <h2>Recent events</h2>
            <span className="count">wakes, sleeps and failures</span>
          </div>
          {data.events.length === 0 ? (
            <Empty sticker={<Deco name="nap" size={100} />} title="Nothing yet">
              Events appear when a model wakes, sleeps or fails.
            </Empty>
          ) : (
            <ul className="timeline">
              {data.events.map((event, i) => (
                <li key={`${event.t}-${i}`}>
                  <span className="t">{clock(event.t)}</span>
                  <span className={`d ${event.kind}`} />
                  <span>
                    <strong>{event.model ?? "router"}</strong> <span className="dim">{event.kind.replace("_", " ")}{event.detail ? ` · ${event.detail}` : ""}</span>
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </Reveal>
    </>
  );
}

/** One server: its GPUs on top (who holds each), then its models. */
function ServerGroup({ group }: { group: Group }) {
  const used = group.gpus.filter((g) => g.model !== null).length;
  return (
    <section className="surface server-group" aria-label={`Server ${group.name}`}>
      <div className="server-head">
        <div>
          <h2>{group.name}</h2>
          <p className="server-meta">
            {group.models.length} {group.models.length === 1 ? "model" : "models"}
            {group.gpus.length > 0 ? ` · ${used}/${group.gpus.length} GPUs in use` : ""}
          </p>
        </div>
        {group.gpus.length > 0 ? (
          <div className="gpu-strip" aria-label={`GPUs on ${group.name}`}>
            {group.gpus.map((g) => (
              <span key={g.gpu} className={`gpu-cell ${g.model ? (g.state === "awake" ? "used" : "warm") : ""}`}>
                <b>GPU {g.gpu}</b>
                {g.model ? <><span>{g.model}</span><Pill>{g.state ?? "awake"}</Pill></> : <span>free</span>}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="models in-group">
        {group.models.map(([name, model]) => <ModelCard key={name} name={name} model={model} />)}
      </div>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="surface stat">
      <span className="value">{value}</span>
      <span className="label">{label}</span>
    </div>
  );
}

function ModelCard({ name, model }: { name: string; model: ModelStatus }) {
  const awake = model.state === "awake";
  const idle = awake && model.inflight === 0 ? model.sleeps_in_s : null;
  return (
    <article className={`surface model ${awake ? "is-awake glow" : ""}`}>
      <div className="model-head">
        <div>
          <h3>{name}</h3>
          <div className="gpu-chips">
            {model.gpus.map((g) => (
              <span key={g} className="gpu-chip">GPU {g}</span>
            ))}
            {model.priority > 0 ? <span className="gpu-chip prio-chip">Priority {model.priority}</span> : null}
          </div>
        </div>
        <Pill>{model.state}</Pill>
      </div>
      {model.detail && (model.state === "down" || model.state === "starting") ? (
        <p className={`model-note ${model.state}`} role="status">{model.detail}</p>
      ) : null}
      <dl className="facts">
        <div><dt>In flight</dt><dd>{model.inflight}</dd></div>
        <div><dt>Waiting</dt><dd>{model.waiting}</dd></div>
        <div><dt>Requests</dt><dd>{model.requests}</dd></div>
        <div><dt>Errors</dt><dd>{model.errors}</dd></div>
        <div><dt>Avg wake</dt><dd>{seconds(model.avg_wake_s)}</dd></div>
        <div><dt>Sleeps in</dt><dd>{idle == null ? "–" : seconds(idle)}</dd></div>
      </dl>
    </article>
  );
}
