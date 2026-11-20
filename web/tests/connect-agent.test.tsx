import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { mockApi, status, visit } from "./helpers";

const admin = { username: "root", role: "admin", csrf_token: "csrf-1" };
const server = (name: string, extra: Record<string, unknown> = {}) => ({
  name, gpu_count: 2, gpu_type: null, agent_url: null, has_agent: false, tunnel: false, tunnel_connected: false,
  tunnel_last_seen: null, tunnel_agent_version: null, models: [], created_at: "2026-01-01T00:00:00Z", ...extra,
});

describe("An agent that connects out", () => {
  beforeEach(() => {
    visit("/servers");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  const base = (get: () => unknown[], more: Record<string, (init: RequestInit) => { status?: number; body?: unknown }> = {}) =>
    mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/servers": () => ({ body: get() }),
      ...more,
    });

  it("creates a token and shows the one command to run on the server, once", async () => {
    let servers = [server("edge")];
    const calls = base(() => servers, {
      "POST /api/servers/edge/tunnel": () => {
        servers = [server("edge", { has_agent: true, tunnel: true })];
        return { status: 201, body: { token: `wkt_${"x".repeat(43)}`, connect_path: "/api/agent/connect" } };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Connect agent" }));
    const dialog = await screen.findByRole("dialog", { name: "Connect agent" });
    expect(within(dialog).getByText("No connection set up")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Create connection token" }));
    const command = await within(dialog).findByLabelText("Install command");
    expect(command.textContent).toBe(`curl -fsSL ${window.location.origin}/install-agent.sh | sudo bash -s -- wkt_${"x".repeat(43)}`);
    const settings = within(dialog).getByLabelText("Agent settings", { selector: "pre" });
    expect(settings.textContent).toBe(`AGENT_CONNECT_URL=ws://${window.location.host}/api/agent/connect\nAGENT_CONNECT_TOKEN=wkt_${"x".repeat(43)}`);
    expect(within(dialog).getByText(/shown only once/)).toBeInTheDocument();
    expect(within(dialog).getByText(/The agent has not connected yet/)).toBeInTheDocument();
    expect(calls.filter((c) => c.key === "POST /api/servers/edge/tunnel")).toHaveLength(1);
  });

  it("shows when the agent is connected, and cuts it off only after a confirmation", async () => {
    let servers = [server("edge", { has_agent: true, tunnel: true, tunnel_connected: true, tunnel_agent_version: "0.1.0" })];
    const calls = base(() => servers, {
      "GET /api/servers/edge/host": () => ({ status: 503, body: { detail: "x" } }),
      "DELETE /api/servers/edge/tunnel": () => {
        servers = [server("edge")];
        return { body: servers[0] };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Settings" }));
    const dialog = await screen.findByRole("dialog", { name: "Connect agent" });
    expect(await within(dialog).findByText("Connected (agent 0.1.0)")).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));
    expect(calls.some((c) => c.key === "DELETE /api/servers/edge/tunnel")).toBe(false); // asked first
    expect(within(dialog).getByText(/Its agent is cut off/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Yes, disconnect" }));
    await waitFor(() => { expect(calls.some((c) => c.key === "DELETE /api/servers/edge/tunnel")).toBe(true); });
  });

  it("says so in the row while the agent is not connected, and does not ask it for stats", async () => {
    const calls = base(() => [server("edge", { has_agent: true, tunnel: true, tunnel_connected: false })]);
    render(<App />);
    expect(await screen.findByText("Not connected")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Containers" })).toBeDisabled();
    expect(calls.some((c) => c.key === "GET /api/servers/edge/host")).toBe(false);
  });

  it("a server with an address still offers to switch to the outbound connection", async () => {
    base(() => [server("old", { has_agent: true, agent_url: "https://a" })], {
      "GET /api/servers/old/host": () => ({ body: { gpus: [], gpu_error: null, ram_total_mb: 1000, ram_available_mb: 500, swap_total_mb: 0, swap_used_mb: 0, disk_total_gb: 10, disk_free_gb: 5, disk_path: "/", cpu_count: 2, load_1m: 0.1 } }),
    });
    render(<App />);
    expect(await screen.findByRole("button", { name: "Settings" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Connect agent" })).not.toBeInTheDocument();
  });
});
