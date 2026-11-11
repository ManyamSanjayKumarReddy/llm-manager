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

function Content({ data }: { data: StatusData }) {
  const models = Object.entries(data.models);
  const awake = models.filter(([, m]) => m.state === "awake").length;
  const requests = models.reduce((sum, [, m]) => sum + m.requests, 0);
  const gpuIds = Object.keys(data.gpus);
  const gpusBusy = gpuIds.filter((id) => data.gpus[id]).length;
  const wakes = models.filter(([, m]) => m.avg_wake_s != null);
  const avgWake = wakes.length ? wakes.reduce((s, [, m]) => s + (m.avg_wake_s ?? 0), 0) / wakes.length : null;

  return (
    <>
      <Reveal>
        <div className="stats">
          <Stat label="Models awake" value={<><CountUp value={awake} />/{models.length}</>} />
          <Stat label="GPUs in use" value={<><CountUp value={gpusBusy} />/{gpuIds.length}</>} />
          <Stat label="Requests since start" value={<CountUp value={requests} />} />
          <Stat label="Average wake" value={avgWake == null ? "–" : seconds(avgWake)} />
        </div>
      </Reveal>

      <div className="section-title">
        <h2>Your models</h2>
        <span className="count">{models.length} configured · router up {seconds(data.uptime_s)}</span>
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
        <div className="models">
          {models.map(([name, model], i) => (
            <Reveal key={name} delay={i * 70}>
              <ModelCard name={name} model={model} />
            </Reveal>
          ))}
        </div>
      )}

      {gpuIds.length > 0 ? (
        <Reveal>
          <section className="surface stack">
            <div className="section-title">
              <h2>GPUs</h2>
              <span className="count">who holds each one</span>
            </div>
            <div className="gpus">
              {Object.entries(data.gpus).map(([id, holder]) => (
                <div key={id} className={`gpu ${holder ? "used" : ""}`}>
                  <b>GPU {id}</b>
                  <span>{holder ? holder.model : "Free"}</span>
                  {holder ? <Pill>{holder.state}</Pill> : null}
                </div>
              ))}
            </div>
          </section>
        </Reveal>
      ) : null}

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
