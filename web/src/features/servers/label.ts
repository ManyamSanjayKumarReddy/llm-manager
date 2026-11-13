import type { Server } from "../../api/types";

/** How a server reads in a dropdown: "ops-local-2 · RTX 4060 Ti 16 GB (2 GPUs)". */
export function serverLabel(s: Server): string {
  const gpus = `${s.gpu_count} GPU${s.gpu_count === 1 ? "" : "s"}`;
  return `${s.name}${s.gpu_type ? ` · ${s.gpu_type}` : ""} (${gpus})`;
}
