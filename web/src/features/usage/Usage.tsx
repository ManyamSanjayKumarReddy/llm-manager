import { useState } from "react";

import { api } from "../../api/client";
import type { UsageKey, UsageModel, UsageTotals } from "../../api/types";
import { Modal, ModalHeader } from "../../components/Modal";
import { Reveal } from "../../components/Reveal";
import { Deco } from "../../components/Stickers";
import { Switch } from "../../components/Controls";
import { Alert, Empty, PageHead, Pill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { useHideRevoked } from "../../hooks/useHideRevoked";
import { ago, compact, exact } from "../../lib/format";
import { DailyChart, Legend } from "./UsageChart";

const RANGES: readonly (readonly [number, string])[] = [
  [1, "Today"],
  [7, "7 days"],
  [30, "30 days"],
  [90, "90 days"],
];

export function Usage() {
  const [days, setDays] = useState(30);
  const usage = useAsync(() => api.usage(days), 30_000, days);
  const [opened, setOpened] = useState<UsageKey>();
  const [hideRevoked, setHideRevoked] = useHideRevoked();
  const data = usage.data;
  const used = data?.keys.filter((k) => k.requests > 0).length ?? 0;
  const errorRate = data && data.totals.requests > 0 ? (data.totals.errors / data.totals.requests) * 100 : 0;
  const nothingYet = data !== undefined && data.totals.requests === 0;
  const shownKeys = data?.keys.filter((k) => !(hideRevoked && k.revoked)) ?? [];
  const hiddenCount = (data?.keys.length ?? 0) - shownKeys.length;
  const biggest = Math.max(1, ...shownKeys.map((k) => k.total_tokens));

  return (
    <div className="page">
      <PageHead eyebrow="Tokens" title="Usage">
        Which API key uses how many tokens, on which model, day by day. Days are UTC. Tokens are the counts vLLM reports for each request.
      </PageHead>

      <div className="range-row">
        <div className="segmented" role="group" aria-label="Time range">
          {RANGES.map(([value, label]) => (
            <button key={value} type="button" aria-pressed={value === days} onClick={() => { setDays(value); }}>{label}</button>
          ))}
        </div>
        <Legend />
      </div>

      <Alert notice={usage.error ? { kind: "error", text: usage.error } : undefined} />

      {data === undefined ? (
        usage.error ? null : <div className="skeleton" aria-hidden="true" />
      ) : (
        <>
          <Reveal>
            <div className="stats">
              <Stat label="Total tokens" value={compact(data.totals.total_tokens)} exactValue={data.totals.total_tokens} />
              <Stat label="Prompt tokens" value={compact(data.totals.prompt_tokens)} exactValue={data.totals.prompt_tokens} />
              <Stat label="Completion tokens" value={compact(data.totals.completion_tokens)} exactValue={data.totals.completion_tokens} />
              <Stat label={`Requests · ${used} key${used === 1 ? "" : "s"} used`} value={compact(data.totals.requests)} exactValue={data.totals.requests} note={errorRate > 0 ? `${errorRate.toFixed(1)}% failed` : undefined} />
            </div>
          </Reveal>

          {nothingYet ? (
            <Reveal>
              <section className="surface">
                <Empty sticker={<Deco name="thinking" size={110} />} title="No requests in this period">
                  Usage appears here as programs call the API with a key. Tokens are counted from the moment this page was added; earlier requests show without tokens.
                </Empty>
              </section>
            </Reveal>
          ) : (
            <Reveal>
              <section className="surface stack">
                <div className="section-title"><h2>Tokens per day</h2><span className="count">{exact(data.totals.total_tokens)} in {days === 1 ? "today" : `${days} days`}</span></div>
                <DailyChart daily={data.daily} label="Tokens per day" />
              </section>
            </Reveal>
          )}

          <Reveal>
            <section className="surface stack">
              <div className="section-title"><h2>By API key</h2><span className="count">{shownKeys.length} key{shownKeys.length === 1 ? "" : "s"}{hiddenCount > 0 ? ` · ${hiddenCount} revoked hidden` : ""}</span></div>
              <div className="toolbar"><Switch checked={hideRevoked} onChange={setHideRevoked} label="Hide revoked" /></div>
              {shownKeys.length === 0 ? <p className="no-match">{data.keys.length === 0 ? "No API keys yet. Create one on the API keys page." : "All keys are revoked. Turn off “Hide revoked” to see them."}</p> : (
                <div className="table-wrap">
                  <table className="cards usage-table">
                    <thead><tr><th>Key</th><th className="num">Requests</th><th className="num">Prompt</th><th className="num">Completion</th><th className="num">Total tokens</th><th>Share</th><th>Last used</th></tr></thead>
                    <tbody>
                      {shownKeys.map((k) => (
                        <tr key={k.id}>
                          <td className="primary">
                            <button type="button" className="row-open" onClick={() => { setOpened(k); }} aria-label={`Usage of ${k.label}`}>
                              <strong>{k.label}</strong>
                              <span className="dim mono small-text">{k.prefix}…{k.revoked ? " · revoked" : ""}</span>
                            </button>
                          </td>
                          <td data-label="Requests" className="num">{exact(k.requests)}</td>
                          <td data-label="Prompt" className="num" title={exact(k.prompt_tokens)}>{compact(k.prompt_tokens)}</td>
                          <td data-label="Completion" className="num" title={exact(k.completion_tokens)}>{compact(k.completion_tokens)}</td>
                          <td data-label="Total tokens" className="num" title={exact(k.total_tokens)}><strong>{compact(k.total_tokens)}</strong></td>
                          <td data-label="Share"><Share total={k} of={biggest} /></td>
                          <td data-label="Last used" className="dim">{ago(k.last_used_at)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </section>
          </Reveal>

          <Reveal>
            <section className="surface stack">
              <div className="section-title"><h2>By model</h2><span className="count">{data.models.length} used</span></div>
              {data.models.length === 0 ? <p className="no-match">No model was called in this period.</p> : <ModelTable models={data.models} />}
            </section>
          </Reveal>
        </>
      )}

      <Modal open={opened !== undefined} onClose={() => { setOpened(undefined); }} label="API key usage" size="lg">
        {opened ? <KeyDetail summary={opened} days={days} onClose={() => { setOpened(undefined); }} /> : null}
      </Modal>
    </div>
  );
}

function Stat({ label, value, exactValue, note }: { label: string; value: string; exactValue: number; note?: string }) {
  return (
    <div className="surface stat" title={exact(exactValue)}>
      <span className="value">{value}</span>
      <span className="label">{label}</span>
      {note ? <span className="dim small-text">{note}</span> : null}
    </div>
  );
}

/** A bar as long as the key's total compared with the biggest key, split into prompt and completion. */
function Share({ total, of }: { total: UsageTotals; of: number }) {
  const whole = (total.total_tokens / of) * 100;
  const prompt = total.total_tokens > 0 ? (total.prompt_tokens / total.total_tokens) * whole : 0;
  return (
    <div className="share" aria-hidden="true">
      <div className="track">
        <span className="seg prompt" style={{ width: `${prompt}%` }} />
        <span className="seg completion" style={{ width: `${whole - prompt}%` }} />
      </div>
    </div>
  );
}

function ModelTable({ models }: { models: UsageModel[] }) {
  return (
    <div className="table-wrap">
      <table className="cards usage-table">
        <thead><tr><th>Model</th><th className="num">Requests</th><th className="num">Failed</th><th className="num">Prompt</th><th className="num">Completion</th><th className="num">Total tokens</th></tr></thead>
        <tbody>
          {models.map((m) => (
            <tr key={m.model}>
              <td className="primary"><strong>{m.model}</strong></td>
              <td data-label="Requests" className="num">{exact(m.requests)}</td>
              <td data-label="Failed" className="num">{exact(m.errors)}</td>
              <td data-label="Prompt" className="num" title={exact(m.prompt_tokens)}>{compact(m.prompt_tokens)}</td>
              <td data-label="Completion" className="num" title={exact(m.completion_tokens)}>{compact(m.completion_tokens)}</td>
              <td data-label="Total tokens" className="num" title={exact(m.total_tokens)}><strong>{compact(m.total_tokens)}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function KeyDetail({ summary, days, onClose }: { summary: UsageKey; days: number; onClose: () => void }) {
  const detail = useAsync(() => api.keyUsage(summary.id, days), undefined, `${summary.id}-${days}`);
  const key = detail.data?.key ?? summary;
  const range = days === 1 ? "today" : `the last ${days} days`;
  return (
    <>
      <ModalHeader title={key.label} subtitle={`${key.prefix}… · ${range}`} onClose={onClose} />
      <div className="modal-body">
        {key.revoked ? <Pill tone="bad">revoked</Pill> : null}
        <div className="mini-stats">
          <div><b>{exact(key.total_tokens)}</b><span>Total tokens</span></div>
          <div><b>{exact(key.prompt_tokens)}</b><span>Prompt</span></div>
          <div><b>{exact(key.completion_tokens)}</b><span>Completion</span></div>
          <div><b>{exact(key.requests)}</b><span>Requests</span></div>
          <div><b>{exact(key.errors)}</b><span>Failed</span></div>
        </div>
        <Alert notice={detail.error ? { kind: "error", text: detail.error } : undefined} />
        {detail.data ? (
          <>
            <Legend />
            <DailyChart daily={detail.data.daily} label={`Tokens per day for ${key.label}`} />
            <h3>By model</h3>
            {detail.data.models.length === 0 ? <p className="dim">This key did not call any model in this period.</p> : <ModelTable models={detail.data.models} />}
          </>
        ) : null}
      </div>
    </>
  );
}
