import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { mockApi, status, visit } from "./helpers";

describe("Servers screen", () => {
  const admin = { username: "root", role: "admin", csrf_token: "csrf-1" };
  const server = (name: string, gpu_count: number, models: string[] = []) => ({ name, gpu_count, gpu_type: null, agent_url: null, has_agent: false, models, created_at: "2026-01-01T00:00:00Z" });

  beforeEach(() => {
    visit("/servers");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  it("lists servers with their models, and registers a new one", async () => {
    let servers = [server("this-server", 2, ["qwen3-vl-8b"])];
    const calls = mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/servers": () => ({ body: servers }),
      "POST /api/servers": (init) => {
        const body = JSON.parse(init.body as string) as { name: string; gpu_count: number };
        servers = [...servers, server(body.name, body.gpu_count)];
        return { status: 201, body: servers.at(-1) };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    const card = await screen.findByRole("article", { name: "Server this-server" });
    expect(within(card).getByText("qwen3-vl-8b")).toBeInTheDocument();
    expect(within(card).getByText("2 × GPU")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Edit server" }));
    const edit = await screen.findByRole("dialog", { name: "Edit server" });
    expect(within(edit).getByRole("button", { name: "Remove" })).toBeDisabled(); // it still has a model
    expect(within(edit).getByText(/Remove or move its models first/)).toBeInTheDocument();
    await user.click(within(edit).getByRole("button", { name: "Close" }));

    await user.type(screen.getByLabelText("Name"), "ops-local-2");
    await user.type(screen.getByLabelText("GPU type (optional)"), "RTX 4060 Ti 16 GB");
    await user.type(screen.getByLabelText("How many GPUs"), "4");
    await user.click(screen.getByRole("button", { name: "Add server" }));

    await waitFor(() => { expect(calls.some((c) => c.key === "POST /api/servers")).toBe(true); });
    const post = calls.find((c) => c.key === "POST /api/servers");
    expect(JSON.parse(post?.init.body as string)).toEqual({ name: "ops-local-2", gpu_count: 4, gpu_type: "RTX 4060 Ti 16 GB" });
    expect(await screen.findByRole("article", { name: "Server ops-local-2" })).toBeInTheDocument();
  });

  it("groups what a server shows: connection, its models with their live state, and what to do next", async () => {
    mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: { ...status, models: { ...status.models, "qwen3-vl-8b": { ...status.models["qwen3-vl-8b"], state: "starting", detail: "loading: Loading weights" } } } }),
      "GET /api/servers": () => ({ body: [server("this-server", 2, ["qwen3-vl-8b"]), server("empty-box", 1)] }),
    });
    render(<App />);
    const card = await screen.findByRole("article", { name: "Server this-server" });
    expect(within(card).getByText("no agent")).toBeInTheDocument();
    expect(await within(card).findByText("starting")).toBeInTheDocument(); // the live state of its model
    expect(within(card).getByRole("button", { name: "Connect agent" })).toBeInTheDocument();
    const empty = screen.getByRole("article", { name: "Server empty-box" });
    expect(within(empty).getByText(/None yet/)).toBeInTheDocument();
  });

  it("removes a server from its edit dialog, after a confirmation", async () => {
    let servers = [server("old-box", 1)];
    const calls = mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/servers": () => ({ body: servers }),
      "DELETE /api/servers/old-box": () => { servers = []; return { status: 204 }; },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Edit server" }));
    const edit = await screen.findByRole("dialog", { name: "Edit server" });
    await user.click(within(edit).getByRole("button", { name: "Remove" }));
    expect(calls.some((c) => c.key === "DELETE /api/servers/old-box")).toBe(false); // asked first
    await user.click(within(edit).getByRole("button", { name: "Yes, remove" }));
    await waitFor(() => { expect(calls.some((c) => c.key === "DELETE /api/servers/old-box")).toBe(true); });
  });
});
