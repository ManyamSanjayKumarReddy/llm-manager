import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { mockApi, visit } from "./helpers";

const admin = { username: "root", role: "admin", csrf_token: "c" };
const model = (server: string, state: string, gpus: number[], extra: Record<string, unknown> = {}) => ({
  server, state, gpus, priority: 0, inflight: 0, waiting: 0, idle_s: 0, sleeps_after_s: 600, sleeps_in_s: null,
  requests: 0, errors: 0, rejected: 0, wakes: 0, sleeps: 0, last_wake_s: null, avg_wake_s: null,
  waits: 0, avg_wait_s: null, max_wait_s: null, ...extra,
});

const status = {
  uptime_s: 100,
  models: {
    alpha: model("box-1", "awake", [0, 1]),
    beta: model("box-2", "starting", [0], { detail: "loading: Loading weights" }),
    gamma: model("box-2", "down", [1], { detail: "The container stopped (exit code 1). Not enough free GPU memory: 15.82 of 22.03 GiB is free." }),
  },
  gpus: { "box-1 · GPU 0": { model: "alpha", state: "awake" }, "box-1 · GPU 1": { model: "alpha", state: "awake" }, "box-2 · GPU 0": null, "box-2 · GPU 1": null },
  servers: [
    { name: "box-1", gpus: [{ gpu: 0, model: "alpha", state: "awake" }, { gpu: 1, model: "alpha", state: "awake" }] },
    { name: "box-2", gpus: [{ gpu: 0, model: null, state: null }, { gpu: 1, model: null, state: null }] },
  ],
  events: [],
};

describe("Overview grouped by server", () => {
  beforeEach(() => {
    visit("/overview");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    mockApi({ "GET /api/auth/me": () => ({ body: admin }), "GET /api/status": () => ({ body: status }) });
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  it("shows one block per server with its own models and GPUs", async () => {
    render(<App />);
    const one = await screen.findByRole("region", { name: "Server box-1" });
    const two = screen.getByRole("region", { name: "Server box-2" });
    expect(within(one).getByText("alpha", { selector: "h3" })).toBeInTheDocument();
    expect(within(one).queryByText("beta", { selector: "h3" })).not.toBeInTheDocument();
    expect(within(two).getByText("beta", { selector: "h3" })).toBeInTheDocument();
    expect(within(two).getByText("gamma", { selector: "h3" })).toBeInTheDocument();
    expect(within(one).getByText(/2\/2 GPUs in use/)).toBeInTheDocument();
    expect(within(two).getByText(/0\/2 GPUs in use/)).toBeInTheDocument();
    expect(within(two).getAllByText("free")).toHaveLength(2);
  });

  it("says a loading model is starting, and why a failed one is down", async () => {
    render(<App />);
    const two = await screen.findByRole("region", { name: "Server box-2" });
    expect(within(two).getByText("starting")).toBeInTheDocument();
    expect(within(two).getByText("loading: Loading weights")).toBeInTheDocument();
    expect(within(two).getByText("down")).toBeInTheDocument();
    expect(within(two).getByText(/Not enough free GPU memory: 15\.82 of 22\.03 GiB is free/)).toBeInTheDocument();
  });
});
