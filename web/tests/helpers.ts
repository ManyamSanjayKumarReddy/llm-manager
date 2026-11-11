import { vi } from "vitest";

/** Put the address bar at ``path`` (before rendering), without reloading. */
export function visit(path: string): void {
  window.history.replaceState(null, "", path);
}


type Handler = (init: RequestInit, query: URLSearchParams) => { status?: number; body?: unknown };

/** Replace ``fetch`` with a router keyed by "METHOD /path"; records every call. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; init: RequestInit; query: URLSearchParams }[] = [];
  const fetchMock = vi.fn((input: RequestInfo | URL, init: RequestInit = {}) => {
    const path = typeof input === "string" ? input : input instanceof URL ? input.pathname : input.url;
    const [pathname = path, search = ""] = path.split("?");
    const key = `${init.method ?? "GET"} ${pathname}`;
    calls.push({ key, init, query: new URLSearchParams(search) });
    const handler = routes[key];
    if (!handler) return Promise.resolve(new Response(JSON.stringify({ detail: `unmocked ${key}` }), { status: 500 }));
    const { status = 200, body } = handler(init, new URLSearchParams(search));
    return Promise.resolve(
      status === 204 ? new Response(null, { status }) : new Response(JSON.stringify(body ?? {}), { status }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

const model = (state: string, gpus: number[], extra: Record<string, unknown> = {}) => ({
  state, gpus, inflight: 0, waiting: 0, idle_s: 0, sleeps_after_s: 600, sleeps_in_s: null,
  requests: 0, errors: 0, rejected: 0, wakes: 0, sleeps: 0, last_wake_s: null, avg_wake_s: null,
  waits: 0, avg_wait_s: null, max_wait_s: null, ...extra,
});

export const status = {
  uptime_s: 125,
  models: {
    "gpt-oss-20b": model("awake", [0, 1], { requests: 7, avg_wake_s: 0.8, sleeps_in_s: 540 }),
    "qwen3-vl-8b": model("asleep", [0]),
  },
  gpus: { "0": { model: "gpt-oss-20b", state: "awake" }, "1": { model: "gpt-oss-20b", state: "awake" } },
  events: [{ t: 1_700_000_000, model: "gpt-oss-20b", kind: "woke", detail: "0.81s" }],
};

export function page<T>(items: T[], query: URLSearchParams, total = items.length) {
  const page_size = Number(query.get("page_size") ?? 25);
  const current = Number(query.get("page") ?? 1);
  return { items, total, page: current, page_size, pages: Math.max(1, Math.ceil(total / page_size)) };
}

export const stats = [{ model: "gpt-oss-20b", requests: 7, errors: 1, p50_ms: 1200, p95_ms: 1500, avg_queue_wait_ms: 900 }];
