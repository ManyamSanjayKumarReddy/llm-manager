export function seconds(value: number | null | undefined): string {
  if (value == null) return "–";
  if (value < 60) return `${value.toFixed(value < 10 ? 1 : 0)}s`;
  const minutes = Math.floor(value / 60);
  if (minutes < 60) return `${minutes}m ${Math.floor(value % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function millis(value: number | null | undefined): string {
  if (value == null) return "–";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}

export function dateTime(iso: string | null | undefined): string {
  if (!iso) return "never";
  return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return `${Math.floor(diff / 86400)} d ago`;
}

export function clock(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleTimeString([], { hour12: false });
}
