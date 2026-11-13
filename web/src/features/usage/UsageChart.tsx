import { useState } from "react";

import type { UsageDay } from "../../api/types";
import { compact, dayLabel, exact } from "../../lib/format";

export function Legend() {
  return (
    <div className="legend" aria-label="Legend">
      <span className="key"><span className="swatch prompt" /> Prompt tokens (input)</span>
      <span className="key"><span className="swatch completion" /> Completion tokens (output)</span>
    </div>
  );
}

/** Tokens per day, prompt and completion stacked. Hover or Tab over a day to read its numbers. */
export function DailyChart({ daily, label }: { daily: UsageDay[]; label: string }) {
  const [active, setActive] = useState<UsageDay>();
  const peak = Math.max(1, ...daily.map((d) => d.total_tokens));
  const shown = active ?? daily.at(-1);
  const everyNth = Math.max(1, Math.ceil(daily.length / 6));
  const ticks = daily.filter((_, i) => i % everyNth === 0 || i === daily.length - 1);

  return (
    <div className="stack">
      <div className="readout" aria-live="polite">
        {shown ? (
          <>
            <strong>{dayLabel(shown.day)}</strong> · {exact(shown.total_tokens)} tokens
            (prompt {exact(shown.prompt_tokens)} · completion {exact(shown.completion_tokens)}) · {exact(shown.requests)} request{shown.requests === 1 ? "" : "s"}
            {shown.errors > 0 ? ` · ${exact(shown.errors)} failed` : ""}
          </>
        ) : null}
      </div>
      <div className="daily" role="group" aria-label={label}>
        <div className="y" aria-hidden="true"><span>{compact(peak)}</span><span>{compact(Math.round(peak / 2))}</span><span>0</span></div>
        <div className="plot" onMouseLeave={() => { setActive(undefined); }}>
          {daily.map((d) => (
            <button
              key={d.day}
              type="button"
              className="col"
              aria-label={`${dayLabel(d.day)}: ${exact(d.total_tokens)} tokens, ${exact(d.requests)} requests`}
              onMouseEnter={() => { setActive(d); }}
              onFocus={() => { setActive(d); }}
              onBlur={() => { setActive(undefined); }}
            >
              <span className="seg prompt" style={{ height: `${(d.prompt_tokens / peak) * 100}%` }} />
              <span className="seg completion" style={{ height: `${(d.completion_tokens / peak) * 100}%` }} />
            </button>
          ))}
        </div>
        <div className="x" aria-hidden="true">{ticks.map((d) => <span key={d.day}>{dayLabel(d.day)}</span>)}</div>
      </div>
      <details className="as-table">
        <summary>Show as a table</summary>
        <div className="table-wrap">
          <table className="usage-table">
            <thead><tr><th>Day</th><th className="num">Requests</th><th className="num">Prompt</th><th className="num">Completion</th><th className="num">Total</th></tr></thead>
            <tbody>
              {[...daily].reverse().map((d) => (
                <tr key={d.day}>
                  <td>{dayLabel(d.day)}</td>
                  <td className="num">{exact(d.requests)}</td>
                  <td className="num">{exact(d.prompt_tokens)}</td>
                  <td className="num">{exact(d.completion_tokens)}</td>
                  <td className="num">{exact(d.total_tokens)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}
