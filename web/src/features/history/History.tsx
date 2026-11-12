import { useState } from "react";

import { api } from "../../api/client";
import type { ModelStats } from "../../api/types";
import { Reveal } from "../../components/Reveal";
import { Deco } from "../../components/Stickers";
import { Alert, Empty, PageHead } from "../../components/ui";
import { Pagination } from "../../components/Pagination";
import { useAsync } from "../../hooks/useAsync";
import { usePagedList } from "../../hooks/usePagedList";
import { dateTime, millis } from "../../lib/format";

const WINDOWS: readonly (readonly [number, string])[] = [
  [1, "1 hour"],
  [24, "24 hours"],
  [168, "7 days"],
  [720, "30 days"],
];

const KINDS = ["woke", "sleep", "wake_failed", "sleep_failed", "rejected", "preempt", "back_online", "startup"] as const;

export function History() {
  const [hours, setHours] = useState(24);
  const models = usePagedList((q) => api.stats({ ...q, hours }), { hours }, { initialPageSize: 10, everyMs: 30_000 });
  const slowest = Math.max(1, ...models.items.map((r) => r.p95_ms ?? 0));
  const busiest = Math.max(1, ...models.items.map((r) => r.requests));
  const windowLabel = WINDOWS.find(([v]) => v === hours)?.[1];

  return (
    <div className="page">
      <PageHead eyebrow="Usage" title="History">
        How many requests each model served, how often they failed, and how long people waited.
      </PageHead>
      <div className="section-title">
        <div className="segmented" role="group" aria-label="Time window">
          {WINDOWS.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={value === hours} onClick={() => { setHours(value); }}>
              {label}
            </button>
          ))}
        </div>
        <span className="count">last {windowLabel}</span>
      </div>
      {models.error ? <Alert notice={{ kind: "error", text: models.error }} /> : null}
      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>Per model</h2><span className="count">{models.total} with traffic</span></div>
          {!models.loading && models.total === 0 ? (
            <Empty sticker={<Deco name="sparkles" size={110} />} title="No requests in this window">
              Requests appear here as soon as a program calls the API.
            </Empty>
          ) : (
            <div className={`table-wrap ${models.fetching ? "fetching" : ""}`}>
              <table className="cards">
                <thead>
                  <tr>
                    <th>Model</th><th>Requests</th><th>Errors</th><th>Median</th><th>p95</th><th className="r">Avg queue wait</th>
                  </tr>
                </thead>
                <tbody>
                  {models.items.map((row) => <Row key={row.model} row={row} slowest={slowest} busiest={busiest} />)}
                </tbody>
              </table>
            </div>
          )}
          <Pagination page={models.page} pages={models.pages} total={models.total} pageSize={models.pageSize} noun="models" onPage={models.setPage} onPageSize={models.setPageSize} />
        </section>
      </Reveal>
      <Events />
    </div>
  );
}

function Events() {
  const [model, setModel] = useState("");
  const [kind, setKind] = useState("");
  const names = useAsync(async () => Object.keys((await api.status()).models));
  const events = usePagedList((q) => api.events({ ...q, model, kind }), { model, kind }, { initialPageSize: 10, everyMs: 15_000 });
  const filtered = model !== "" || kind !== "";
  return (
    <Reveal>
      <section className="surface stack">
        <div className="section-title"><h2>Wake &amp; sleep events</h2><span className="count">{events.total} {filtered ? "match" : "recorded"}</span></div>
        <div className="toolbar">
          <select className="input" aria-label="Filter by model" value={model} onChange={(e) => { setModel(e.target.value); }}>
            <option value="">All models</option>
            {(names.data ?? []).map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
          <select className="input" aria-label="Filter by event" value={kind} onChange={(e) => { setKind(e.target.value); }}>
            <option value="">All events</option>
            {KINDS.map((k) => <option key={k} value={k}>{k.replace("_", " ")}</option>)}
          </select>
        </div>
        {events.error ? <Alert notice={{ kind: "error", text: events.error }} /> : null}
        {!events.loading && events.total === 0 ? (
          <p className="no-match">{filtered ? "No events match these filters." : "No events recorded yet."}</p>
        ) : (
          <div className={`table-wrap ${events.fetching ? "fetching" : ""}`}>
            <table className="cards">
              <thead><tr><th>When</th><th>Model</th><th>Event</th><th>Detail</th></tr></thead>
              <tbody>
                {events.items.map((e, i) => (
                  <tr key={`${e.t}-${i}`}>
                    <td className="primary dim">{dateTime(new Date(e.t * 1000).toISOString())}</td>
                    <td data-label="Model">{e.model ?? "router"}</td>
                    <td data-label="Event"><span className="action-chip">{e.kind.replace("_", " ")}</span></td>
                    <td data-label="Detail" className="dim">{e.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pagination page={events.page} pages={events.pages} total={events.total} pageSize={events.pageSize} noun="events" onPage={events.setPage} onPageSize={events.setPageSize} />
      </section>
    </Reveal>
  );
}

function Row({ row, slowest, busiest }: { row: ModelStats; slowest: number; busiest: number }) {
  const errorRate = row.requests ? (row.errors / row.requests) * 100 : 0;
  return (
    <tr>
      <td className="primary"><strong>{row.model}</strong></td>
      <td data-label="Requests">
        <div className="meter">
          <span>{row.requests}</span>
          <div className="bar"><i style={{ width: `${(row.requests / busiest) * 100}%` }} /></div>
        </div>
      </td>
      <td data-label="Errors">
        <span className={errorRate > 5 ? "pill bad" : "dim"}>{row.errors}{row.errors ? ` · ${errorRate.toFixed(1)}%` : ""}</span>
      </td>
      <td data-label="Median" className="num">{millis(row.p50_ms)}</td>
      <td data-label="p95">
        <div className="meter">
          <span>{millis(row.p95_ms)}</span>
          <div className="bar"><i style={{ width: `${((row.p95_ms ?? 0) / slowest) * 100}%` }} /></div>
        </div>
      </td>
      <td data-label="Avg queue wait" className="r num">{millis(row.avg_queue_wait_ms)}</td>
    </tr>
  );
}
