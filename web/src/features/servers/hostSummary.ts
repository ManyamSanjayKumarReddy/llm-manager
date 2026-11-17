import type { HostStats } from "../../api/types";

/** Megabytes as "19.5 GB". */
export const gb = (mb: number): string => `${(mb / 1024).toFixed(1)} GB`;

/** One line for a table row: "RAM 19.5 GB free · GPU 1.0 GB of 16.0 GB". */
export function hostSummary(stats: HostStats): string {
  const used = stats.gpus.reduce((sum, g) => sum + g.memory_used_mb, 0);
  const total = stats.gpus.reduce((sum, g) => sum + g.memory_total_mb, 0);
  const gpu = stats.gpus.length > 0 ? ` · GPU ${gb(used)} of ${gb(total)}` : "";
  return `RAM ${gb(stats.ram_available_mb)} free${gpu}`;
}
