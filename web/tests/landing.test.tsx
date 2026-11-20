import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi, type MockInstance } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { mockApi, page, stats, status, visit } from "./helpers";

const notLoggedIn = () => ({ status: 401, body: { detail: "not logged in" } });
const admin = { username: "root", role: "admin", csrf_token: "c" };
const signedIn = {
  "GET /api/auth/me": () => ({ body: admin }),
  "GET /api/status": () => ({ body: status }),
  "GET /api/stats": (_: RequestInit, q: URLSearchParams) => ({ body: page(stats, q) }),
  "GET /api/events": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }),
};

let scrollSpy: MockInstance<typeof window.scrollTo>;

beforeEach(() => {
  visit("/");
  vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
  scrollSpy = vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

describe("landing page", () => {
  it("is what a signed-out visitor sees first", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: /Models that wake when you call/ })).toBeInTheDocument();
    expect(screen.queryByLabelText("Password")).not.toBeInTheDocument();
  });

  it("explains the product in sections people can jump to", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    render(<App />);
    await screen.findByRole("heading", { level: 1 });
    for (const heading of [/hostage/, /Three steps/, /One command connects a GPU server/, /Everything around the wake-up/, /important one goes first/, /Same API/, /Straight answers/, /Give your GPUs a rest/]) {
      expect(screen.getByRole("heading", { name: heading })).toBeInTheDocument();
    }
    const nav = screen.getByRole("navigation", { name: "Page sections" });
    const targets = [["How it works", "#how"], ["Connect", "#connect"], ["Features", "#features"], ["Priority", "#priority"], ["FAQ", "#faq"]] as const;
    for (const [label, target] of targets) {
      expect(within(nav).getByRole("link", { name: label })).toHaveAttribute("href", target);
      expect(document.querySelector(target)).not.toBeNull(); // the link points at a real section
    }
  });

  it("says its animation is an illustration and states what the numbers are", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    render(<App />);
    expect(await screen.findByText("Illustration")).toBeInTheDocument();
    expect(screen.getByText(/Measured in our cloud test/)).toBeInTheDocument();
  });

  it("answers the common questions", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByText("Does it create or download models?"));
    expect(screen.getByText(/The agent only manages containers it created/)).toBeVisible();
  });

  it("shows the one-line install command with the page's own address", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    render(<App />);
    expect(await screen.findByLabelText("Install command")).toHaveTextContent(`curl -fsSL ${window.location.origin}/install-agent.sh | sudo bash -s -- wkt_`);
    expect(screen.getByText("Do I have to open a port on my GPU server?")).toBeInTheDocument();
  });

  it("shows a code sample that points at the page's own address", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByLabelText("Example request")).toHaveTextContent(`${window.location.origin}/v1/chat/completions`);
    await user.click(screen.getByRole("tab", { name: "Python" }));
    expect(screen.getByLabelText("Example request")).toHaveTextContent("OpenAI(base_url=");
  });

  it("does not show the landing page's call to action to someone who is signed in", async () => {
    visit("/overview");
    mockApi(signedIn);
    render(<App />);
    expect(await screen.findByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /Models that wake when you call/ })).not.toBeInTheDocument();
  });
});

describe("signing in from the landing page", () => {
  it("leads to /signin and back", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    const user = userEvent.setup();
    render(<App />);
    const links = await screen.findAllByRole("link", { name: "Sign in" });
    expect(links.length).toBeGreaterThan(1);
    for (const link of links) expect(link).toHaveAttribute("href", "/signin");

    await user.click(links[0] as HTMLElement);
    expect(await screen.findByLabelText("Password")).toBeInTheDocument();
    expect(window.location.pathname).toBe("/signin");

    await user.click(screen.getByRole("link", { name: "Back to home" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Models that wake/ })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/");
  });
});

describe("logo and in-page links", () => {
  it("takes a signed-in person to the landing page, which offers the dashboard", async () => {
    visit("/models");
    mockApi({ ...signedIn, "GET /api/models": (_: RequestInit, q: URLSearchParams) => ({ body: page([], q) }) });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Models" });
    const logo = screen.getByRole("link", { name: "Wakeful home" });
    expect(logo).toHaveAttribute("href", "/");
    await user.click(logo);

    expect(await screen.findByRole("heading", { level: 1, name: /Models that wake when you call/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Sign in" })).not.toBeInTheDocument();
    const open = screen.getAllByRole("link", { name: "Open dashboard" });
    expect(open.length).toBeGreaterThan(1);
    for (const link of open) expect(link).toHaveAttribute("href", "/overview");

    await user.click(open[0] as HTMLElement);
    expect(await screen.findByRole("navigation", { name: "Sections" })).toBeInTheDocument();
    expect(window.location.pathname).toBe("/overview");
  });

  it("the logo leads home from the sign-in page too", async () => {
    visit("/signin");
    mockApi({ "GET /api/auth/me": notLoggedIn });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByLabelText("Password");
    expect(screen.getByRole("link", { name: "Wakeful home" })).toHaveAttribute("href", "/");
    await user.click(screen.getByRole("link", { name: "Wakeful home" }));
    expect(await screen.findByRole("heading", { level: 1, name: /Models that wake/ })).toBeInTheDocument();
  });

  it("jumping to a section does not throw you back to the top, but changing page does", async () => {
    mockApi({ "GET /api/auth/me": notLoggedIn });
    const scrollTo = scrollSpy;
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: /Models that wake/ });
    scrollTo.mockClear();
    await user.click(within(screen.getByRole("navigation", { name: "Page sections" })).getByRole("link", { name: "FAQ" }));
    expect(scrollTo).not.toHaveBeenCalled();
    await user.click(screen.getAllByRole("link", { name: "Sign in" })[0] as HTMLElement);
    expect(scrollTo).toHaveBeenCalledWith({ top: 0 });
  });
});

describe("pinned page title", () => {
  const routes = {
    ...signedIn,
    "GET /api/stats": (_: RequestInit, q: URLSearchParams) => ({ body: page(stats, q) }),
  };

  /** Pretend the page is scrolled: the big title sits at ``headBottom``, the navigation ends at 64. */
  function scrollTo(headBottom: number) {
    vi.spyOn(Element.prototype, "getBoundingClientRect").mockImplementation(function (this: Element) {
      const bottom = this.classList.contains("shell-bar") ? 64 : this.classList.contains("page-head") ? headBottom : 0;
      return { bottom, top: bottom - 50, left: 0, right: 0, width: 0, height: 50, x: 0, y: 0, toJSON() { return {}; } };
    });
    window.dispatchEvent(new Event("scroll"));
  }

  it("stays out of the way at the top, and pins a slim copy once the big title has scrolled off", async () => {
    mockApi(routes);
    visit("/history");
    scrollTo(300); // title fully visible
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "History" });
    const pin = document.querySelector(".page-pin") as HTMLElement;
    expect(pin).not.toBeNull();
    await vi.waitFor(() => { expect(pin).not.toHaveClass("on"); });

    scrollTo(-120); // scrolled far past it
    await vi.waitFor(() => { expect(pin).toHaveClass("on"); });
    expect(within(pin).getByText("History")).toBeInTheDocument();
    expect(within(pin).getByText(/How many requests each model served/)).toBeInTheDocument();

    scrollTo(300); // back to the top
    await vi.waitFor(() => { expect(pin).not.toHaveClass("on"); });
  });

  it("is a decoration: hidden from assistive technology so the title is not read twice", async () => {
    mockApi(routes);
    visit("/overview");
    render(<App />);
    await screen.findByRole("heading", { level: 1, name: "Overview" });
    expect(document.querySelector(".page-pin")).toHaveAttribute("aria-hidden", "true");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });
});
