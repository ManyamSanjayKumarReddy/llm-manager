// Shapes of the backend's JSON responses (see backend/src/llm_manager/schemas).

export type Role = "admin" | "viewer";

export interface SessionInfo {
  username: string;
  role: Role;
  csrf_token: string;
}

export interface ModelStatus {
  /** asleep | waking | awake | sleeping | failed | down */
  state: string;
  priority: number;
  gpus: number[];
  inflight: number;
  waiting: number;
  sleeps_in_s: number | null;
  requests: number;
  errors: number;
  rejected: number;
  wakes: number;
  sleeps: number;
  avg_wake_s: number | null;
  avg_wait_s: number | null;
}

export interface GpuHolder {
  model: string;
  state: string;
}

export interface RouterEvent {
  t: number;
  model: string | null;
  kind: string;
  detail: string;
}

export interface StatusData {
  uptime_s: number;
  models: Record<string, ModelStatus>;
  gpus: Record<string, GpuHolder | null>;
  events: RouterEvent[];
}

export interface ModelStats {
  model: string;
  requests: number;
  errors: number;
  p50_ms: number | null;
  p95_ms: number | null;
  avg_queue_wait_ms: number | null;
}


export interface AuditEntry {
  ts: string;
  actor: string;
  action: string;
  target: string | null;
  ip: string | null;
  detail: string | null;
}

export interface User {
  id: string;
  username: string;
  role: Role;
  is_active: boolean;
  created_at: string;
  last_login_at: string | null;
  locked: boolean;
}

export interface NewUser {
  username: string;
  password: string;
  role: Role;
}

export interface ApiKey {
  id: string;
  label: string;
  prefix: string;
  created_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
  allowed_models: string[] | null;
  rpm_limit: number | null;
  created_by: string | null;
}

export interface CreatedApiKey extends ApiKey {
  token: string;
}

export interface NewApiKey {
  label: string;
  allowed_models: string[] | null;
  rpm_limit: number | null;
}

/** What every list endpoint returns: one page plus the numbers for page controls. */
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
}

/** A machine with GPUs that models are placed on. */
export interface Server {
  name: string;
  gpu_count: number;
  /** What kind of GPUs, free text; null if not given. */
  gpu_type: string | null;
  /** Names of the models placed on it. */
  models: string[];
  created_at: string;
}

/** A model the router manages, with its live state. */
export interface ManagedModel {
  name: string;
  /** The registered server it runs on. */
  server: string;
  url: string;
  served_name: string | null;
  gpus: number[];
  idle_minutes: number;
  priority: number;
  /** Whether a key is stored. The key itself is never sent back. */
  has_api_key: boolean;
  created_at: string;
  state: string;
  inflight: number;
  waiting: number;
}

export interface NewModel {
  name: string;
  server: string;
  url: string;
  served_name: string | null;
  gpus: number[];
  idle_minutes: number;
  priority: number;
  backend_api_key: string | null;
}

export interface ModelChanges {
  server?: string;
  url?: string;
  served_name?: string;
  gpus?: number[];
  idle_minutes?: number;
  priority?: number;
  /** The container's own API key. Leave it out to keep the stored one. */
  backend_api_key?: string;
  /** Optional fields to empty out (leaving a field out of the request means "unchanged"). */
  clear?: ("served_name" | "backend_api_key")[];
}

/** What a connection test found out about a container. */
export interface ModelCheck {
  reachable: boolean;
  sleep_endpoints: boolean;
  state: string | null;
  served_models: string[];
  served_name_found: boolean | null;
  /** True if the container accepted the key, false if it refused it, null if none was sent. */
  key_accepted: boolean | null;
  problems: string[];
}

/** Requests and tokens added up over some period. */
export interface UsageTotals {
  requests: number;
  errors: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/** One UTC day (days without traffic are included, with zeros). */
export interface UsageDay extends UsageTotals {
  day: string;
}

export interface UsageModel extends UsageTotals {
  model: string;
}

/** One API key's usage; keys that were not used in the period are listed with zeros. */
export interface UsageKey extends UsageTotals {
  id: string;
  label: string;
  prefix: string;
  revoked: boolean;
  last_used_at: string | null;
}

export interface Usage {
  days: number;
  totals: UsageTotals;
  daily: UsageDay[];
  keys: UsageKey[];
  models: UsageModel[];
}

export interface KeyUsage {
  key: UsageKey;
  days: number;
  daily: UsageDay[];
  models: UsageModel[];
}
