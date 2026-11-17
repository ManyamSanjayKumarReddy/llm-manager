import type { HostStats as Stats } from "../../api/types";
import { gb } from "./hostSummary";

/** A labelled bar. ``fill`` is 0 to 1; a nearly full bar turns warning-coloured. */
function Meter({ label, fill, text }: { label: string; fill: number; text: string }) {
  const pct = Math.max(0, Math.min(1, fill)) * 100;
  return (
    <div className="host-meter">
      <span className="host-meter-label">{label}</span>
      <div className="bar" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <i className={pct > 90 ? "full" : undefined} style={{ width: `${pct}%` }} />
      </div>
      <span className="host-meter-text dim">{text}</span>
    </div>
  );
}

/** GPU, memory and disk of a server, as bars. Memory is what limits how many models fit. */
export function HostStatsView({ stats }: { stats: Stats }) {
  const ramUsed = stats.ram_total_mb - stats.ram_available_mb;
  return (
    <div className="host-stats">
      {stats.gpus.map((g) => (
        <Meter key={g.index} label={`GPU ${g.index}`} fill={g.memory_used_mb / g.memory_total_mb} text={`${gb(g.memory_used_mb)} of ${gb(g.memory_total_mb)} · ${g.utilization_pct}% busy${g.temperature_c === null ? "" : ` · ${g.temperature_c}°C`}`} />
      ))}
      {stats.gpu_error ? <p className="hint dim">No GPU figures: {stats.gpu_error}</p> : null}
      <Meter label="RAM" fill={ramUsed / stats.ram_total_mb} text={`${gb(stats.ram_available_mb)} free of ${gb(stats.ram_total_mb)}`} />
      {stats.swap_total_mb > 0 ? <Meter label="Swap" fill={stats.swap_used_mb / stats.swap_total_mb} text={`${gb(stats.swap_used_mb)} of ${gb(stats.swap_total_mb)} used`} /> : null}
      <Meter label="Disk" fill={1 - stats.disk_free_gb / stats.disk_total_gb} text={`${stats.disk_free_gb.toFixed(0)} GB free of ${stats.disk_total_gb.toFixed(0)} GB`} />
    </div>
  );
}
