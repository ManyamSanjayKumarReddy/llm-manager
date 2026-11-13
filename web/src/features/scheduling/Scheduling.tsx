import { useState, type ReactNode, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { SchedulerSettings, SchedulerValues } from "../../api/types";
import { Reveal } from "../../components/Reveal";
import { Alert, Field, PageHead } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { dateTime, seconds } from "../../lib/format";
import { useToast } from "../toast/context";

/** The form's text boxes. Numbers stay as text until they are checked and sent. */
interface Form {
  queue: string;
  turn: string;
  hold: string;
  stopRunning: boolean;
  stopAfter: string;
  wake: string;
  sleep: string;
  reaper: string;
  level: string;
}

const toForm = (v: SchedulerValues): Form => ({
  queue: String(v.queue_timeout_s),
  turn: String(v.min_awake_s),
  hold: String(v.priority_hold_s),
  stopRunning: v.preempt_after_s !== null,
  stopAfter: v.preempt_after_s === null ? "30" : String(v.preempt_after_s),
  wake: String(v.wake_timeout_s),
  sleep: String(v.sleep_timeout_s),
  reaper: String(v.reaper_interval_s),
  level: String(v.sleep_level),
});

const num = (text: string): number => (text.trim() === "" ? Number.NaN : Number(text));

/** The values to send, or the first thing wrong with the form. */
function check(f: Form): { values: SchedulerValues } | { problem: string } {
  const positive: [string, string][] = [
    ["Queue timeout", f.queue],
    ["Wake-up call limit", f.wake],
    ["Sleep call limit", f.sleep],
    ["Idle check interval", f.reaper],
  ];
  for (const [label, text] of positive) {
    if (!(num(text) > 0)) return { problem: `${label} must be more than 0.` };
  }
  for (const [label, text] of [["Turn length", f.turn], ["Priority hold", f.hold]] as const) {
    if (!(num(text) >= 0)) return { problem: `${label} must be 0 or more.` };
  }
  if (f.stopRunning) {
    if (!(num(f.stopAfter) > 0)) return { problem: "Stop after must be more than 0 seconds." };
    if (num(f.stopAfter) >= num(f.queue)) return { problem: "Stop after must be smaller than the queue timeout, or the request gives up first." };
  }
  return {
    values: {
      queue_timeout_s: num(f.queue),
      min_awake_s: num(f.turn),
      priority_hold_s: num(f.hold),
      preempt_after_s: f.stopRunning ? num(f.stopAfter) : null,
      wake_timeout_s: num(f.wake),
      sleep_timeout_s: num(f.sleep),
      reaper_interval_s: num(f.reaper),
      sleep_level: Number(f.level),
    },
  };
}

/** How the scheduler behaves when models share a GPU: waiting, turns, priority, stopping requests. */
export function Scheduling() {
  const loaded = useAsync(() => api.schedulerSettings(), undefined, 0);
  return (
    <div className="page">
      <PageHead eyebrow="Admin" title="Scheduling">
        How the router behaves when models share a GPU: how long a request may wait, how long a model keeps its turn, which priority wins, and whether a long-running request may be stopped. Changes apply at once, no restart.
      </PageHead>
      <Alert notice={loaded.error ? { kind: "error", text: loaded.error } : undefined} />
      {loaded.data ? <Editor key={loaded.data.updated_at ?? "unsaved"} settings={loaded.data} onSaved={() => void loaded.reload()} /> : null}
    </div>
  );
}

function Editor({ settings, onSaved }: { settings: SchedulerSettings; onSaved: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState(() => toForm(settings.values));
  const [saving, setSaving] = useState(false);
  const set = (change: Partial<Form>) => { setForm((f) => ({ ...f, ...change })); };

  const result = check(form);
  const saved = JSON.stringify(toForm(settings.values));
  const changed = JSON.stringify(form) !== saved;
  const isDefault = JSON.stringify(form) === JSON.stringify(toForm(settings.defaults));

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (!("values" in result)) return;
    setSaving(true);
    try {
      await api.saveSchedulerSettings(result.values);
      toast.show("success", "Scheduling saved. It is in force now.");
      onSaved();
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
    } finally {
      setSaving(false);
    }
  }

  const input = (label: string, key: keyof Form, unit = "seconds", step = "any") => (
    <Field label={label}>
      <span className="unit-input">
        <input className="input" aria-label={label} type="number" min={0} step={step} inputMode="decimal" required value={String(form[key])} onChange={(e) => { set({ [key]: e.target.value }); }} />
        <span className="dim">{unit}{num(String(form[key])) >= 60 ? ` · ${seconds(num(String(form[key])))}` : ""}</span>
      </span>
    </Field>
  );

  return (
    <Reveal>
      <form className="stack" onSubmit={(e) => void submit(e)}>
        <Section title="Waiting requests" intro="When a model is asleep or another model holds its GPU, requests for it wait in line.">
          {input("Queue timeout", "queue")}
          <p className="hint dim">After this long a waiting request gives up with a 503 and a Retry-After header, and your client can try again. Raise it if your requests are long (a 5 minute request needs more than 300 here). Applies to requests that are already waiting, too.</p>
        </Section>

        <Section title="Who goes first" intro="Applies to models that share a GPU on the same server.">
          <div className="row">
            {input("Turn length", "turn")}
            {input("Priority hold", "hold")}
          </div>
          <p className="hint dim"><strong>Turn length:</strong> with equal priorities, a model that has been awake this long stops taking new requests when another model is waiting, so the other one can swap in. Requests already running are never cut off.</p>
          <p className="hint dim"><strong>Priority hold:</strong> a lower-priority model waits this long after a higher-priority one last served before it may take the GPU.</p>
        </Section>

        <Section title="Long-running requests" intro="What happens when a high-priority request waits for a lower-priority model that is busy.">
          <label className="switch">
            <input type="checkbox" role="switch" checked={form.stopRunning} onChange={(e) => { set({ stopRunning: e.target.checked }); }} />
            <span className="track"><i /></span>
            <span className="switch-text">
              <strong>Stop a running lower-priority request</strong>
              <span className="dim">{form.stopRunning ? "A waiting higher-priority request may cancel it (the client gets a 503) and take the GPU." : "Off: running requests always finish. The higher-priority request waits, up to the queue timeout."}</span>
            </span>
          </label>
          {form.stopRunning ? (
            <>
              {input("Stop after", "stopAfter")}
              <p className="hint dim">Once a higher-priority request has waited this long, the lower-priority model's running requests are stopped. It must be smaller than the queue timeout. Equal or higher priorities are never stopped.</p>
            </>
          ) : null}
        </Section>

        <Section title="Wake and sleep" intro="Rarely needs changing.">
          <div className="row">
            {input("Wake-up call limit", "wake")}
            {input("Sleep call limit", "sleep")}
            {input("Idle check interval", "reaper")}
          </div>
          <Field label="Sleep level">
            <select className="input" value={form.level} onChange={(e) => { set({ level: e.target.value }); }}>
              <option value="1">1 · weights kept in CPU RAM (fast wake)</option>
              <option value="2">2 · weights dropped (slow wake, less RAM)</option>
            </select>
          </Field>
        </Section>

        {"problem" in result ? <div className="alert error" role="alert">{result.problem}</div> : null}
        <div className="actions-bar">
          <button className="btn primary" type="submit" disabled={saving || !changed || "problem" in result}>{saving ? "Saving…" : "Save changes"}</button>
          <button className="btn" type="button" disabled={isDefault} onClick={() => { setForm(toForm(settings.defaults)); }}>Reset to defaults</button>
          <span className="foot-hint">{settings.updated_at ? `Last saved by ${settings.updated_by ?? "an admin"}, ${dateTime(settings.updated_at)}.` : "Never saved: the built-in values are in use."}</span>
        </div>
      </form>
    </Reveal>
  );
}

function Section({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  return (
    <section className="surface stack-sm">
      <div>
        <h2>{title}</h2>
        <p className="hint dim">{intro}</p>
      </div>
      {children}
    </section>
  );
}
