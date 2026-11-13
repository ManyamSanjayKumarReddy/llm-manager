import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { findPage, PAGES, safeNext } from "../src/pages";
import { parseLocation } from "../src/router/router";
import { mockApi, page, stats, status, visit } from "./helpers";

const admin = { username: "root", role: "admin", csrf_token: "c" };
const notLoggedIn = () => ({ status: 401, body: { detail: "not logged in" } });
const routes = {
  "GET /api/auth/me": () => ({ body: admin }),
  "GET /api/status": () => ({ body: status }),
  "GET /api/stats": (_: RequestInit, q: URLSearchParams) => ({ body: page(stats, q) }),
  "GET /api/events": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }),
  "GET /api/models": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }),
  "GET /api/users": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }),
  "GET /api/keys": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }),
  "GET /api/audit": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }),
};

beforeEach(() => {
  visit("/");
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

describe("addresses", () => {
  it("are real paths, never hashes", () => {
    for (const p of PAGES) expect(p.path).toMatch(/^\/[a-z-]+(\/[a-z-]+)?$/);
    expect(PAGES.map((p) => p.path)).toEqual(["/overview", "/servers", "/models", "/history", "/api-keys", "/users", "/audit", "/account"]);
  });

  it("ignore a trailing slash", () => {
    expect(parseLocation("/models/").path).toBe("/models");
    expect(parseLocation("/").path).toBe("/");
    expect(parseLocation("/signin?next=%2Fmodels").search.get("next")).toBe("/models");
  });

  it("only send you onward to our own pages", () => {
    expect(safeNext("/models")).toBe("/models");
    expect(safeNext("/api-keys")).toBe("/api-keys");
    for (const bad of ["https://evil.example", "//evil.example", "/signin", "/nonsense", "javascript:alert(1)", "", null]) {
      expect(safeNext(bad)).toBe("/overview");
    }
    expect(findPage("/users")?.admin).toBe(true);
    expect(findPage("/overview")?.admin).toBeUndefined();
  });
});

describe("moving around", () => {
  it("navigation items are real links with real addresses, and moving does not reload the page", async () => {
    visit("/overview");
    mockApi(routes);
    const user = userEvent.setup();
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Sections" });
    const expected = { Overview: "/overview", Models: "/models", History: "/history", "API keys": "/api-keys", Users: "/users", Audit: "/audit", Account: "/account" };
    for (const [label, href] of Object.entries(expected)) {
      expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", href);
    }
    expect(document.querySelector('a[href^="#"]')).toBeNull(); // nothing inside the dashboard uses a hash

    const pushed = vi.spyOn(window.history, "pushState");
    await user.click(within(nav).getByRole("link", { name: "History" }));
    expect(await screen.findByRole("heading", { level: 1, name: "History" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/history");
    expect(window.location.hash).toBe("");
    expect(pushed).toHaveBeenCalledTimes(1);
    expect(within(nav).getByRole("link", { name: "History" })).toHaveAttribute("aria-current", "page");
    expect(within(nav).getByRole("link", { name: "Overview" })).not.toHaveAttribute("aria-current");
  });

  it("the browser's back button returns to the previous screen", async () => {
    visit("/overview");
    mockApi(routes);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("link", { name: "Users" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Users" })).toBeInTheDocument();
    act(() => { window.history.back(); });
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/overview");
  });

  it("modified clicks are left to the browser (open in a new tab)", async () => {
    visit("/overview");
    mockApi(routes);
    const user = userEvent.setup();
    render(<App />);
    const link = await screen.findByRole("link", { name: "Audit" });
    await user.keyboard("{Control>}");
    await user.click(link);
    await user.keyboard("{/Control}");
    expect(window.location.pathname).toBe("/overview"); // this tab stayed where it was
  });

  it("sets the browser tab's title for each screen", async () => {
    visit("/audit");
    mockApi(routes);
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Audit trail" });
    await waitFor(() => { expect(document.title).toBe("Audit · Wakeful"); });
  });
});

describe("guarding addresses", () => {
  it("a signed-out visitor asking for a dashboard page is sent to sign in, and then on to it", async () => {
    visit("/models");
    let signedInNow = false;
    mockApi({
      ...routes,
      "GET /api/auth/me": () => (signedInNow ? { body: admin } : notLoggedIn()),
      "POST /api/auth/login": () => { signedInNow = true; return { body: admin }; },
    });
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/signin");
    expect(window.location.search).toBe("?next=%2Fmodels");

    await user.type(screen.getByLabelText("Username"), "root");
    await user.type(screen.getByLabelText("Password"), "a-long-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Models" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/models");
    expect(window.location.search).toBe("");
  });

  it("an address cannot be used to send someone to another site after signing in", async () => {
    visit("/signin?next=https%3A%2F%2Fevil.example");
    mockApi({ ...routes, "GET /api/auth/me": notLoggedIn, "POST /api/auth/login": () => ({ body: admin }) });
    const user = userEvent.setup();
    render(<App />);
    await user.type(await screen.findByLabelText("Username"), "root");
    await user.type(screen.getByLabelText("Password"), "a-long-passphrase");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(window.location.hostname).not.toBe("evil.example");
    expect(window.location.pathname).toBe("/overview");
  });

  it("someone already signed in does not see the sign-in page", async () => {
    visit("/signin");
    mockApi(routes);
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/overview");
  });

  it("a viewer asking for an admin page lands on the overview", async () => {
    visit("/api-keys");
    mockApi({ ...routes, "GET /api/auth/me": () => ({ body: { ...admin, role: "viewer" } }) });
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/overview");
  });

  it("an unknown address gets a clear page with a way out", async () => {
    visit("/no/such/page");
    mockApi({ "GET /api/auth/me": notLoggedIn });
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByRole("heading", { name: /doesn’t exist/ })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Back to home" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Models that wake/ })).toBeInTheDocument();
  });

  it("an unknown address for a signed-in person points back to the dashboard", async () => {
    visit("/nonsense");
    mockApi(routes);
    render(<App />);
    expect(await screen.findByRole("link", { name: "Go to the dashboard" })).toHaveAttribute("href", "/overview");
  });
});
