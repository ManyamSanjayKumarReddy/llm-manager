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
    const row = (await screen.findByText("this-server")).closest("tr") as HTMLElement;
    expect(within(row).getByText("qwen3-vl-8b")).toBeInTheDocument();
    expect(within(row).getByRole("button", { name: "Remove" })).toBeDisabled(); // it still has a model

    await user.type(screen.getByLabelText("Name"), "ops-local-2");
    await user.type(screen.getByLabelText("GPU type (optional)"), "RTX 4060 Ti 16 GB");
    await user.type(screen.getByLabelText("How many GPUs"), "4");
    await user.click(screen.getByRole("button", { name: "Add server" }));

    await waitFor(() => { expect(calls.some((c) => c.key === "POST /api/servers")).toBe(true); });
    const post = calls.find((c) => c.key === "POST /api/servers");
    expect(JSON.parse(post?.init.body as string)).toEqual({ name: "ops-local-2", gpu_count: 4, gpu_type: "RTX 4060 Ti 16 GB" });
    expect(await screen.findByText("ops-local-2")).toBeInTheDocument();
  });
});
