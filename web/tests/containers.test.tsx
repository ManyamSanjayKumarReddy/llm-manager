import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { mockApi, page, status, visit } from "./helpers";

const admin = { username: "root", role: "admin", csrf_token: "csrf-1" };
const server = (name: string, extra: Record<string, unknown> = {}) => ({
  name, gpu_count: 2, gpu_type: null, agent_url: null, has_agent: false, models: [], created_at: "2026-01-01T00:00:00Z", ...extra,
});
const container = (name: string, extra: Record<string, unknown> = {}) => ({
  name, state: "running", running: true, status: "Up 3 hours", image: "vllm/vllm-openai:v0.10.1", port: 8026, gpus: [0],
  model: "org/model", restart_policy: "unless-stopped", exit_code: null, oom_killed: false, created_at: "2026-01-01T00:00:00Z",
  started_at: "2026-01-01T00:00:01Z", registered_as: null, model_state: null, ...extra,
});
const host = {
  gpus: [{ index: 0, name: "RTX 5060 Ti", memory_used_mb: 1024, memory_total_mb: 16384, utilization_pct: 3, temperature_c: 41 }],
  gpu_error: null, ram_total_mb: 64000, ram_available_mb: 20480, swap_total_mb: 26000, swap_used_mb: 11000,
  disk_total_gb: 900, disk_free_gb: 400, disk_path: "/root/.cache", cpu_count: 16, load_1m: 0.5,
};

describe("Containers on a server", () => {
  beforeEach(() => {
    visit("/servers");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  const base = (servers: unknown[], more: Record<string, (init: RequestInit, q: URLSearchParams) => { status?: number; body?: unknown }> = {}) =>
    mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/servers": () => ({ body: servers }),
      ...more,
    });

  it("offers to set up an agent, and sends the address and token", async () => {
    let servers = [server("ops-local-2")];
    const calls = base([], {
      "GET /api/servers": () => ({ body: servers }),
      "PATCH /api/servers/ops-local-2": (init) => {
        const body = JSON.parse(init.body as string) as { agent_url: string };
        servers = [server("ops-local-2", { agent_url: body.agent_url, has_agent: true })];
        return { body: servers[0] };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Use an address" }));
    const dialog = await screen.findByRole("dialog", { name: "Agent settings" });
    const save = within(dialog).getByRole("button", { name: "Save" });
    expect(save).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Agent address"), "https://gpu.example.com/agent");
    expect(save).toBeDisabled(); // an address alone is not enough: the token is needed
    await user.type(within(dialog).getByLabelText("Token"), "t".repeat(40));
    await user.click(save);
    await waitFor(() => { expect(calls.some((c) => c.key === "PATCH /api/servers/ops-local-2")).toBe(true); });
    const patch = calls.find((c) => c.key === "PATCH /api/servers/ops-local-2");
    expect(JSON.parse(patch?.init.body as string)).toEqual({ agent_url: "https://gpu.example.com/agent", agent_token: "t".repeat(40) });
    expect(await screen.findByRole("button", { name: "Containers" })).toBeInTheDocument();
  });

  it("shows a server's load on its card, and says when the agent cannot be reached", async () => {
    base([server("good", { has_agent: true, agent_url: "https://a" }), server("bad", { has_agent: true, agent_url: "https://b" })], {
      "GET /api/servers/good/host": () => ({ body: host }),
      "GET /api/servers/bad/host": () => ({ status: 503, body: { detail: "cannot reach the agent" } }),
    });
    render(<App />);
    const good = await screen.findByRole("article", { name: "Server good" });
    expect(await within(good).findByRole("meter", { name: "RAM" })).toBeInTheDocument();
    expect(within(good).getByRole("meter", { name: "GPU 0" })).toBeInTheDocument();
    const bad = screen.getByRole("article", { name: "Server bad" });
    expect(await within(bad).findByText(/The agent could not be reached/)).toBeInTheDocument();
  });

  it("lists containers with their models and load, and stops one", async () => {
    let running = true;
    const calls = base([server("box", { has_agent: true, agent_url: "https://a" })], {
      "GET /api/servers/box/host": () => ({ body: host }),
      "GET /api/servers/box/containers": (_, q) => ({
        body: page([container("vllm-a", { registered_as: "alpha", model_state: "asleep", running, state: running ? "running" : "exited" }), container("vllm-b", { port: 8027 })], q),
      }),
      "POST /api/servers/box/containers/vllm-a/stop": () => { running = false; return { body: container("vllm-a", { running: false, state: "exited" }) }; },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Containers" }));
    const dialog = await screen.findByRole("dialog", { name: "Containers" });

    const card = await within(dialog).findByRole("listitem", { name: "Container vllm-a" });
    expect(within(card).getByText("alpha")).toBeInTheDocument();
    expect(within(card).getByText("asleep")).toBeInTheDocument();
    expect(within(dialog).getByRole("listitem", { name: "Container vllm-b" })).toHaveTextContent("Not registered as a model yet");
    expect(within(dialog).getByRole("meter", { name: "RAM" })).toBeInTheDocument();
    expect(within(dialog).getByRole("meter", { name: "GPU 0" })).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Stop vllm-a" }));
    await waitFor(() => { expect(calls.some((c) => c.key === "POST /api/servers/box/containers/vllm-a/stop")).toBe(true); });
    expect(await within(dialog).findByRole("button", { name: "Start vllm-a" })).toBeInTheDocument();
  });

  it("says why a model is down or still starting, right on its container", async () => {
    base([server("box", { has_agent: true, agent_url: "https://a" })], {
      "GET /api/servers/box/host": () => ({ body: host }),
      "GET /api/servers/box/containers": (_, q) => ({
        body: page([
          container("vllm-a", { registered_as: "alpha", model_state: "starting", model_detail: "loading: Loading weights" }),
          container("vllm-b", { running: false, state: "exited", exit_code: 1, registered_as: "beta", model_state: "down", model_detail: "The container stopped (exit code 1). Not enough free GPU memory: 15.82 of 22.03 GiB is free." }),
        ], q),
      }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Containers" }));
    const dialog = await screen.findByRole("dialog", { name: "Containers" });
    expect(await within(dialog).findByText("loading: Loading weights")).toBeInTheDocument();
    expect(within(dialog).getByText(/Not enough free GPU memory: 15\.82 of 22\.03 GiB is free/)).toBeInTheDocument();
  });

  it("shows the reason when a container cannot be stopped", async () => {
    base([server("box", { has_agent: true, agent_url: "https://a" })], {
      "GET /api/servers/box/host": () => ({ body: host }),
      "GET /api/servers/box/containers": (_, q) => ({ body: page([container("vllm-a", { registered_as: "alpha", model_state: "awake" })], q) }),
      "POST /api/servers/box/containers/vllm-a/stop": () => ({ status: 422, body: { detail: "alpha is awake with 2 running and 0 waiting request(s): wait until it is idle to stop" } }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Containers" }));
    const dialog = await screen.findByRole("dialog", { name: "Containers" });
    await user.click(await within(dialog).findByRole("button", { name: "Stop vllm-a" }));
    expect(await screen.findByText(/wait until it is idle to stop/)).toBeInTheDocument();
  });

  it("removing a container with a model is a danger confirm that needs the name typed", async () => {
    const calls = base([server("box", { has_agent: true, agent_url: "https://a" })], {
      "GET /api/servers/box/host": () => ({ body: host }),
      "GET /api/servers/box/containers": (_, q) => ({ body: page([container("vllm-a", { registered_as: "alpha", model_state: "asleep" })], q) }),
      "DELETE /api/servers/box/containers/vllm-a": () => ({ status: 204 }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Containers" }));
    const list = await screen.findByRole("dialog", { name: "Containers" });
    await user.click(await within(list).findByRole("button", { name: "Remove vllm-a" }));

    const confirm = await screen.findByRole("dialog", { name: "Remove container" });
    expect(within(confirm).getByRole("alert")).toHaveTextContent(/cannot be undone/);
    expect(within(confirm).getByRole("alert")).toHaveTextContent(/model “alpha” is removed from Wakeful too/);
    const go = within(confirm).getByRole("button", { name: "Remove container and model" });
    expect(go).toBeDisabled();
    await user.type(within(confirm).getByLabelText(/Type vllm-a to confirm/), "vllm-");
    expect(go).toBeDisabled();
    await user.type(within(confirm).getByLabelText(/Type vllm-a to confirm/), "a");
    expect(go).toBeEnabled();
    await user.click(go);

    await waitFor(() => { expect(calls.some((c) => c.key === "DELETE /api/servers/box/containers/vllm-a")).toBe(true); });
    const call = calls.find((c) => c.key === "DELETE /api/servers/box/containers/vllm-a");
    expect(call?.init.method).toBe("DELETE");
  });

  it("sends remove_model=true only when a model is registered", async () => {
    const calls = base([server("box", { has_agent: true, agent_url: "https://a" })], {
      "GET /api/servers/box/host": () => ({ body: host }),
      "GET /api/servers/box/containers": (_, q) => ({ body: page([container("vllm-b")], q) }),
      "DELETE /api/servers/box/containers/vllm-b": () => ({ status: 204 }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Containers" }));
    const list = await screen.findByRole("dialog", { name: "Containers" });
    await user.click(await within(list).findByRole("button", { name: "Remove vllm-b" }));
    const confirm = await screen.findByRole("dialog", { name: "Remove container" });
    // no model: no typing needed, and no model is removed
    expect(within(confirm).queryByLabelText(/to confirm/)).not.toBeInTheDocument();
    await user.click(within(confirm).getByRole("button", { name: "Remove container" }));
    await waitFor(() => { expect(calls.some((c) => c.key === "DELETE /api/servers/box/containers/vllm-b")).toBe(true); });
    const urls = (fetch as unknown as { mock: { calls: [string][] } }).mock.calls.map((c) => c[0]);
    expect(urls).toContain("/api/servers/box/containers/vllm-b?remove_model=false");
  });

  it("shows a container's logs", async () => {
    base([server("box", { has_agent: true, agent_url: "https://a" })], {
      "GET /api/servers/box/host": () => ({ body: host }),
      "GET /api/servers/box/containers": (_, q) => ({ body: page([container("vllm-a")], q) }),
      "GET /api/servers/box/containers/vllm-a/logs": () => ({ body: { name: "vllm-a", text: "INFO engine started\n", truncated: false } }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Containers" }));
    const list = await screen.findByRole("dialog", { name: "Containers" });
    await user.click(await within(list).findByRole("button", { name: "Logs of vllm-a" }));
    expect(await screen.findByLabelText("Log output")).toHaveTextContent("INFO engine started");
  });

  it("creates the container and registers the model in one step on a server with an agent", async () => {
    visit("/models");
    const calls = base([server("box", { has_agent: true, agent_url: "https://a", gpu_count: 2 })], {
      "GET /api/models": (_, q) => ({ body: page([], q) }),
      "POST /api/servers/box/containers": (init) => ({ status: 201, body: { ...container("new-one"), ...(JSON.parse(init.body as string) as object) } }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Hugging Face model"), "openai/new-one");
    for (let i = 0; i < 5; i++) await user.click(within(dialog).getByRole("button", { name: /^Next/ }));

    expect(within(dialog).getByText(/box has an agent/)).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Container command")).toHaveTextContent("docker run -d"); // the manual way stays
    await user.click(within(dialog).getByRole("button", { name: "Create and register" }));

    await waitFor(() => { expect(calls.some((c) => c.key === "POST /api/servers/box/containers")).toBe(true); });
    const body = JSON.parse(calls.find((c) => c.key === "POST /api/servers/box/containers")?.init.body as string) as Record<string, unknown>;
    expect(body).toMatchObject({
      name: "new-one", model: "openai/new-one", image: "mockdigilabs/vllm-openai-abortsleep-0.10.1:latest", port: 8025, gpus: [0],
      auto_restart: true, tool_calling: true, register_as: { name: "new-one", url: "http://127.0.0.1:8025", priority: 0, idle_minutes: 10 },
    });
    expect(calls.some((c) => c.key === "POST /api/models")).toBe(false); // the backend registers it, not the browser
  });

  it("without an agent the dialog offers only the command and registration", async () => {
    visit("/models");
    base([server("plain")], { "GET /api/models": (_, q) => ({ body: page([], q) }) });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Hugging Face model"), "openai/new-one");
    for (let i = 0; i < 5; i++) await user.click(within(dialog).getByRole("button", { name: /^Next/ }));
    expect(within(dialog).getByRole("button", { name: "Register model" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Create and register" })).not.toBeInTheDocument();
  });
});
