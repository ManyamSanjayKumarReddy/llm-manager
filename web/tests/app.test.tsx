import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { mockApi, page, stats, status, visit } from "./helpers";

const admin = { username: "root", role: "admin", csrf_token: "csrf-1" };
const viewer = { ...admin, role: "viewer" };
const notLoggedIn = () => ({ status: 401, body: { detail: "not logged in" } });
const base = {
  "GET /api/auth/me": () => ({ body: admin }),
  "GET /api/status": () => ({ body: status }),
  "GET /api/stats": (_: RequestInit, q: URLSearchParams) => ({ body: page(stats, q) }),
  "GET /api/events": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }),
};

beforeEach(() => {
  visit("/overview");
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  setCsrfToken("");
});

describe("sign-in", () => {
  beforeEach(() => {
    visit("/signin"); // "Sign in" on the landing page leads here
  });

  it("shows the login page when there is no session", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    render(<App />);
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  });

  it("shows the server's message for a wrong password and clears the field", async () => {
    mockApi({
      "GET /api/auth/me": notLoggedIn,
      "POST /api/auth/login": () => ({ status: 401, body: { detail: "Invalid credentials, or too many attempts." } }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Username"), "root");
    await user.type(screen.getByLabelText("Password"), "wrong-password-1");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid credentials");
    expect(screen.getByLabelText("Password")).toHaveValue("");
  });

  it("opens the overview after signing in and signs out with the CSRF token", async () => {
    const calls = mockApi({
      ...base,
      "GET /api/auth/me": notLoggedIn,
      "POST /api/auth/login": () => ({ body: admin }),
      "POST /api/auth/logout": () => ({ status: 204 }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Username"), "root");
    await user.type(screen.getByLabelText("Password"), "a-long-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("heading", { name: "gpt-oss-20b" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "qwen3-vl-8b" })).toBeInTheDocument();
    expect(screen.getByText("root")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
    const logout = calls.find((c) => c.key === "POST /api/auth/logout");
    expect((logout?.init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("csrf-1");
  });

  it("returns to the sign-in page when the session ends", async () => {
    visit("/overview");
    mockApi({ ...base, "GET /api/status": notLoggedIn });
    render(<App />);
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/signin");
  });
});

describe("overview", () => {
  it("lists the configured models with their state and GPUs", async () => {
    mockApi(base);
    render(<App />);
    const awake = (await screen.findByRole("heading", { name: "gpt-oss-20b" })).closest("article");
    expect(awake).not.toBeNull();
    expect(within(awake as HTMLElement).getByText("awake")).toBeInTheDocument();
    expect(within(awake as HTMLElement).getByText("GPU 1")).toBeInTheDocument();
    const asleep = screen.getByRole("heading", { name: "qwen3-vl-8b" }).closest("article");
    expect(within(asleep as HTMLElement).getByText("asleep")).toBeInTheDocument();
  });

  it("says so when no models are configured", async () => {
    mockApi({ ...base, "GET /api/status": () => ({ body: { ...status, models: {}, gpus: {} } }) });
    render(<App />);
    expect(await screen.findByText("No models yet")).toBeInTheDocument();
  });

  it("shows server text as text, never as markup", async () => {
    const hostile = { ...status, models: { "<img src=x onerror=alert(1)>": status.models["gpt-oss-20b"] }, gpus: {}, events: [] };
    mockApi({ ...base, "GET /api/status": () => ({ body: hostile }) });
    const { container } = render(<App />);
    expect(await screen.findByRole("heading", { name: "<img src=x onerror=alert(1)>" })).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("roles", () => {
  it("hides admin pages from viewers", async () => {
    mockApi({ ...base, "GET /api/auth/me": () => ({ body: viewer }) });
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Sections" });
    for (const shown of ["Overview", "History", "Account"]) expect(within(nav).getByRole("link", { name: shown })).toBeInTheDocument();
    for (const hidden of ["API keys", "Users", "Audit"]) expect(within(nav).queryByRole("link", { name: hidden })).not.toBeInTheDocument();
  });

  it("sends a viewer who opens an admin address to the overview", async () => {
    visit("/users");
    mockApi({ ...base, "GET /api/auth/me": () => ({ body: viewer }) });
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Overview" })).toBeInTheDocument();
  });
});

describe("history", () => {
  it("shows requests, errors and latency per model", async () => {
    mockApi(base);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("link", { name: "History" }));
    const row = (await screen.findByRole("cell", { name: "gpt-oss-20b" })).closest("tr") as HTMLElement;
    expect(within(row).getByText("1.2 s")).toBeInTheDocument();
    expect(within(row).getByText("1.5 s")).toBeInTheDocument();
    expect(within(row).getByText(/1 · 14\.3%/)).toBeInTheDocument();
  });
});

describe("api keys", () => {
  const created = {
    id: "k1", label: "ci", prefix: "lm_abcdefg", created_at: "2026-01-01T00:00:00Z", last_used_at: null,
    revoked_at: null, allowed_models: ["gpt-oss-20b"], rpm_limit: 10, created_by: "root", token: "lm_secret-token-value",
  };

  it("shows a new token once, then only its prefix", async () => {
    let keys: unknown[] = [];
    const calls = mockApi({
      ...base,
      "GET /api/keys": (_, q) => ({ body: page(keys, q) }),
      "POST /api/keys": () => {
        keys = [{ ...created, token: undefined }];
        return { status: 201, body: created };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("link", { name: "API keys" }));
    await user.type(await screen.findByLabelText("Label"), "ci");
    await user.type(screen.getByLabelText("Requests per minute"), "10");
    await user.click(await screen.findByLabelText("gpt-oss-20b"));
    await user.click(screen.getByRole("button", { name: "Create key" }));

    expect(await screen.findByText("lm_secret-token-value")).toBeInTheDocument();
    expect(screen.getByText(/shown only once/)).toBeInTheDocument();
    const post = calls.find((c) => c.key === "POST /api/keys");
    expect(JSON.parse(post?.init.body as string)).toEqual({ label: "ci", allowed_models: ["gpt-oss-20b"], rpm_limit: 10 });

    await user.click(screen.getByRole("button", { name: "I have saved it" }));
    await waitFor(() => { expect(screen.queryByText("lm_secret-token-value")).not.toBeInTheDocument(); });
    expect(screen.getByText("lm_abcdefg…")).toBeInTheDocument();
  });
});

describe("users", () => {
  it("creates an account and cannot disable yourself", async () => {
    const me = { id: "u1", username: "root", role: "admin", is_active: true, created_at: "2026-01-01T00:00:00Z", last_login_at: null, locked: false };
    const alice = { ...me, id: "u2", username: "alice", role: "viewer" };
    let users = [me];
    const calls = mockApi({
      ...base,
      "GET /api/users": (_, q) => ({ body: page(users, q) }),
      "POST /api/users": () => {
        users = [me, alice];
        return { status: 201, body: alice };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("link", { name: "Users" }));
    const rootRow = (await screen.findByRole("cell", { name: /root/ })).closest("tr") as HTMLElement;
    expect(within(rootRow).queryByRole("button", { name: "Disable" })).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Username"), "alice");
    await user.type(screen.getByLabelText("Initial password"), "a-long-passphrase");
    await user.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByRole("cell", { name: "alice" })).toBeInTheDocument();
    const post = calls.find((c) => c.key === "POST /api/users");
    expect(JSON.parse(post?.init.body as string)).toEqual({ username: "alice", password: "a-long-passphrase", role: "viewer" });
  });
});
