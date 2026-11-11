import type { ReactNode } from "react";

/** An on/off switch with a label and an optional explanation underneath. */
export function Switch({ checked, onChange, label, hint }: { checked: boolean; onChange: (on: boolean) => void; label: string; hint?: ReactNode }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" checked={checked} onChange={(e) => { onChange(e.target.checked); }} />
      <span className="track" aria-hidden="true"><i /></span>
      <span className="switch-text">
        <strong>{label}</strong>
        {hint ? <span className="dim">{hint}</span> : null}
      </span>
    </label>
  );
}

/** Quick-pick buttons for a numeric field; the one matching the current value is highlighted. */
export function Presets({ label, options, value, onPick }: { label: string; options: readonly (readonly [string, string])[]; value: string; onPick: (value: string) => void }) {
  return (
    <div className="presets" role="group" aria-label={label}>
      {options.map(([text, v]) => (
        <button key={v} type="button" className="chip-btn" aria-pressed={value === v} onClick={() => { onPick(v); }}>{text}</button>
      ))}
    </div>
  );
}

/** Quick-pick buttons and a number box on one row: pick a common value, or type your own. */
export function PresetNumber({ label, options, value, onChange, min, max, step }: { label: string; options: readonly (readonly [string, string])[]; value: string; onChange: (value: string) => void; min: number; max?: number; step?: string }) {
  return (
    <div className="field">
      <span>{label}</span>
      <div className="preset-row">
        <Presets label={label} options={options} value={value} onPick={onChange} />
        <input className="input num-input" type="number" min={min} max={max} step={step} inputMode="decimal" value={value} onChange={(e) => { onChange(e.target.value); }} aria-label={`${label} number`} />
      </div>
    </div>
  );
}

/** A titled group of related fields inside a popup. */
export function FormSection({ title, hint, grow = false, children }: { title: string; hint?: string; /** Take the spare height of the popup (the content then scrolls inside itself). */ grow?: boolean; children: ReactNode }) {
  return (
    <section className={`group ${grow ? "grow" : ""}`}>
      <header>
        <h3>{title}</h3>
        {hint ? <p className="dim">{hint}</p> : null}
      </header>
      <div className="group-body">{children}</div>
    </section>
  );
}
