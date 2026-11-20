// All calls to the backend. The session lives in an HttpOnly cookie (scripts cannot read it);
// the CSRF token returned at sign-in is sent back on every change.

import type {
  ApiKey,
  AuditEntry,
  Container,
  ContainerLogs,
  CreatedApiKey,
  HostStats,
  ManagedModel,
  ModelChanges,
  ModelCheck,
  ModelStats,
  NewApiKey,
  NewContainer,
  NewModel,
  NewUser,
  Page,
  RouterEvent,
  SchedulerSettings,
  SchedulerValues,
  Server,
  TunnelEnrolled,
  SessionInfo,
  StatusData,
  Usage,
  KeyUsage,
  User,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

let csrfToken = "";
let onUnauthorized: () => void = () => undefined;

export function setCsrfToken(token: string): void {
  csrfToken = token;
}

/** Called when a request that needed a session gets 401 (the session ended). */
export function setUnauthorizedHandler(handler: () => void): void {
  onUnauthorized = handler;
}

function describe(data: unknown, status: number): string {
  if (typeof data === "object" && data !== null && "detail" in data) {
    const { detail } = data;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      const messages = (detail as unknown[]).flatMap((d) =>
        typeof d === "object" && d !== null && "msg" in d ? [String(d.msg)] : [],
      );
      if (messages.length > 0) return messages.join("; ");
    }
  }
  if (status === 429) return "Too many attempts. Wait a moment and try again.";
  return `Request failed (${status}).`;
}

async function send(method: Method, path: string, body?: unknown): Promise<void> {
  await request<unknown>(method, path, body);
}

async function request<T>(method: Method, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (method !== "GET") headers["X-CSRF-Token"] = csrfToken;

  let response: Response;
  try {
    response = await fetch(path, {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server.");
  }
  if (response.status === 204) return undefined as T;

  let data: unknown = null;
  try {
    data = await response.json();
  } catch {
    // not JSON; the status code still says what happened
  }
  if (!response.ok) {
    if (response.status === 401 && path !== "/api/auth/login") onUnauthorized();
    throw new ApiError(response.status, describe(data, response.status));
  }
  return data as T;
}

const id = encodeURIComponent;

/** Paging plus optional filters for a list call. Empty filters are left out of the URL. */
export interface ListQuery {
  page: number;
  pageSize: number;
  [filter: string]: string | number | undefined;
}

function query(params: ListQuery): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    search.set(key === "pageSize" ? "page_size" : key, String(value));
  }
  return `?${search.toString()}`;
}

export const api = {
  login: (username: string, password: string) =>
    request<SessionInfo>("POST", "/api/auth/login", { username, password }),
  logout: () => send("POST", "/api/auth/logout"),
  me: () => request<SessionInfo>("GET", "/api/auth/me"),
  changePassword: (current_password: string, new_password: string) =>
    send("POST", "/api/auth/password", { current_password, new_password }),

  status: () => request<StatusData>("GET", "/api/status"),
  stats: (q: ListQuery & { hours: number }) => request<Page<ModelStats>>("GET", `/api/stats${query(q)}`),
  events: (q: ListQuery & { model?: string; kind?: string }) => request<Page<RouterEvent>>("GET", `/api/events${query(q)}`),
  audit: (q: ListQuery & { q?: string }) => request<Page<AuditEntry>>("GET", `/api/audit${query(q)}`),

  users: (q: ListQuery & { q?: string; role?: string }) => request<Page<User>>("GET", `/api/users${query(q)}`),
  createUser: (user: NewUser) => request<User>("POST", "/api/users", user),
  updateUser: (userId: string, changes: { is_active?: boolean; role?: string }) =>
    request<User>("PATCH", `/api/users/${id(userId)}`, changes),
  resetPassword: (userId: string, new_password: string) =>
    send("POST", `/api/users/${id(userId)}/password`, { new_password }),

  usage: (days: number) => request<Usage>("GET", `/api/usage?days=${days}`),
  keyUsage: (keyId: string, days: number) =>
    request<KeyUsage>("GET", `/api/usage/keys/${id(keyId)}?days=${days}`),

  schedulerSettings: () => request<SchedulerSettings>("GET", "/api/settings/scheduler"),
  saveSchedulerSettings: (values: SchedulerValues) =>
    request<SchedulerSettings>("PUT", "/api/settings/scheduler", values),

  servers: () => request<Server[]>("GET", "/api/servers"),
  addServer: (server: { name: string; gpu_count: number; gpu_type: string | null }) => request<Server>("POST", "/api/servers", server),
  /** An empty ``agent_url`` removes the agent (and forgets its token). */
  updateServer: (name: string, changes: { gpu_count?: number; gpu_type?: string; agent_url?: string; agent_token?: string }) =>
    request<Server>("PATCH", `/api/servers/${id(name)}`, changes),
  removeServer: (name: string) => send("DELETE", `/api/servers/${id(name)}`),
  enrollTunnel: (name: string) => request<TunnelEnrolled>("POST", `/api/servers/${id(name)}/tunnel`),
  revokeTunnel: (name: string) => request<Server>("DELETE", `/api/servers/${id(name)}/tunnel`),

  hostStats: (server: string) => request<HostStats>("GET", `/api/servers/${id(server)}/host`),
  containers: (server: string, q: ListQuery) => request<Page<Container>>("GET", `/api/servers/${id(server)}/containers${query(q)}`),
  createContainer: (server: string, container: NewContainer) =>
    request<Container>("POST", `/api/servers/${id(server)}/containers`, container),
  startContainer: (server: string, name: string) => request<Container>("POST", `/api/servers/${id(server)}/containers/${id(name)}/start`),
  stopContainer: (server: string, name: string) => request<Container>("POST", `/api/servers/${id(server)}/containers/${id(name)}/stop`),
  restartContainer: (server: string, name: string) => request<Container>("POST", `/api/servers/${id(server)}/containers/${id(name)}/restart`),
  /** ``removeModel`` must be true when a model is registered for the container. */
  removeContainer: (server: string, name: string, removeModel: boolean) =>
    send("DELETE", `/api/servers/${id(server)}/containers/${id(name)}?remove_model=${removeModel}`),
  containerLogs: (server: string, name: string, tail: number) =>
    request<ContainerLogs>("GET", `/api/servers/${id(server)}/containers/${id(name)}/logs?tail=${tail}`),

  models: (q: ListQuery & { q?: string }) => request<Page<ManagedModel>>("GET", `/api/models${query(q)}`),
  registerModel: (model: NewModel) => request<ManagedModel>("POST", "/api/models", model),
  updateModel: (name: string, changes: ModelChanges) =>
    request<ManagedModel>("PATCH", `/api/models/${id(name)}`, changes),
  sleepModel: (name: string) => send("POST", `/api/models/${id(name)}/sleep`),
  removeModel: (name: string) => send("DELETE", `/api/models/${id(name)}`),
  checkModel: (check: { url: string; server?: string; served_name: string | null; backend_api_key: string | null }) =>
    request<ModelCheck>("POST", "/api/models/check", check),

  keys: (q: ListQuery & { q?: string; status?: string }) => request<Page<ApiKey>>("GET", `/api/keys${query(q)}`),
  createKey: (key: NewApiKey) => request<CreatedApiKey>("POST", "/api/keys", key),
  revokeKey: (keyId: string) => send("DELETE", `/api/keys/${id(keyId)}`),
};
