// Shapes of the backend's JSON responses (see backend/src/llm_manager/schemas).

export type Role = "admin" | "viewer";

export interface SessionInfo {
  username: string;
  role: Role;
  csrf_token: string;
}

export interface ModelStatus {
  /** The server it runs on. */
  server?: string;
  /** The container (on that server's agent) that runs it, if linked. */
  container?: string | null;
  /** asleep | waking | awake | sleeping | starting | failed | down */
  state: string;
  /** Why it is starting or down, when its server's agent could tell. */
  detail?: string | null;
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

/** The GPUs of one server (those a model is registered on) and who holds each. */
export interface ServerGpus {
  name: string;
  gpus: { gpu: number; model: string | null; state: string | null }[];
}

export interface StatusData {
  uptime_s: number;
  models: Record<string, ModelStatus>;
  gpus: Record<string, GpuHolder | null>;
  servers?: ServerGpus[];
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
  /** Where its Wakeful agent listens, if it has one. */
  agent_url: string | null;
  /** An agent address and token are stored (the token itself is never sent back). */
  has_agent: boolean;
  /** Its agent connects out to Wakeful (a connection token was issued). */
  tunnel: boolean;
  /** That agent is connected right now. */
  tunnel_connected: boolean;
  /** When it was last connected (null: never). */
  tunnel_last_seen: string | null;
  tunnel_agent_version: string | null;
  /** Names of the models placed on it. */
  models: string[];
  created_at: string;
}

/** The token an agent uses to connect out. Shown once, when it is created. */
export interface TunnelEnrolled {
  token: string;
  /** The agent connects to wss://<this site><connect_path>. */
  connect_path: string;
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
  /** The container (on the server's agent) that runs it, if linked. */
  container: string | null;
  created_at: string;
  state: string;
  /** Why it is starting or down, when known. */
  detail?: string | null;
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
  clear?: ("served_name" | "backend_api_key" | "container")[];
  /** The container that runs it (on the server's agent). */
  container?: string;
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

/** The scheduler's timings, all in seconds. */
export interface SchedulerValues {
  queue_timeout_s: number;
  min_awake_s: number;
  priority_hold_s: number;
  /** null: never stop a running request. */
  preempt_after_s: number | null;
  wake_timeout_s: number;
  sleep_timeout_s: number;
  reaper_interval_s: number;
  sleep_level: number;
}

export interface SchedulerSettings {
  values: SchedulerValues;
  /** What "Reset to defaults" restores. */
  defaults: SchedulerValues;
  updated_at: string | null;
  updated_by: string | null;
}

/** A container on a server, as its agent reports it. */
export interface Container {
  name: string;
  /** running, exited, restarting, created, paused or dead. */
  state: string;
  running: boolean;
  /** What Docker prints, e.g. "Up 3 hours". */
  status: string;
  image: string;
  port: number | null;
  gpus: number[];
  /** The Hugging Face id it was started with. */
  model: string | null;
  restart_policy: string;
  exit_code: number | null;
  oom_killed: boolean;
  created_at: string;
  started_at: string | null;
  /** The registered model that uses it, and that model's wake/sleep state. */
  registered_as: string | null;
  model_state: string | null;
  /** Why that model is starting or down, when known. */
  model_detail?: string | null;
}

/** What the agent needs to create a container (sleep mode is always on). */
export interface NewContainer {
  name: string;
  model: string;
  image: string;
  port: number;
  gpus: number[];
  cache_dir: string;
  api_key?: string | null;
  hf_token?: string | null;
  max_model_len: number;
  max_num_seqs: number;
  memory_share: number;
  allow_long_context: boolean;
  tool_calling: boolean;
  tool_parser: string;
  auto_restart: boolean;
  extra_args: string;
  /** Also register it as a model. */
  register_as?: {
    name: string;
    url: string;
    served_name: string | null;
    idle_minutes: number;
    priority: number;
  };
}

export interface ContainerLogs {
  name: string;
  text: string;
  truncated: boolean;
}

export interface HostGpu {
  index: number;
  name: string;
  memory_used_mb: number;
  memory_total_mb: number;
  utilization_pct: number;
  temperature_c: number | null;
}

/** How loaded a server is right now. */
export interface HostStats {
  gpus: HostGpu[];
  /** Why GPU figures are missing, if they are. */
  gpu_error: string | null;
  ram_total_mb: number;
  ram_available_mb: number;
  swap_total_mb: number;
  swap_used_mb: number;
  disk_total_gb: number;
  disk_free_gb: number;
  disk_path: string;
  cpu_count: number;
  load_1m: number;
}
