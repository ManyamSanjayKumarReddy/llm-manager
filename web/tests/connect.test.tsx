import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { mockApi, status, visit } from "./helpers";

describe("Connect screen", () => {
  const base = `${window.location.origin}/v1`;

  beforeEach(() => {
    visit("/connect");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  const routes = (role: string) => ({
    "GET /api/auth/me": () => ({ body: { username: "u", role, csrf_token: "c" } }),
    "GET /api/status": () => ({ body: status }),
  });

  it("shows the base URL, the key placeholder and every model name", async () => {
    mockApi(routes("admin"));
    render(<App />);
    expect(await screen.findByText(base)).toBeInTheDocument();
    expect(screen.getAllByText("<API_KEY>").length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Create a key" })).toHaveAttribute("href", "/api-keys");
    expect(await screen.findByRole("button", { name: "Copy gpt-oss-20b" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Copy qwen3-vl-8b" })).toBeInTheDocument();
  });

  it("puts the chosen model and language into the example", async () => {
    mockApi(routes("admin"));
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: "Use gpt-oss-20b in the example" }); // models loaded
    const example = screen.getByLabelText("Example request");
    expect(example).toHaveTextContent(`curl ${base}/chat/completions`);
    expect(example).toHaveTextContent('"model": "gpt-oss-20b"');
    await user.click(screen.getByRole("button", { name: "Use qwen3-vl-8b in the example" }));
    expect(example).toHaveTextContent('"model": "qwen3-vl-8b"');
    await user.click(screen.getByRole("tab", { name: "Python" }));
    expect(example).toHaveTextContent(`OpenAI(base_url="${base}", api_key="<API_KEY>")`);
    await user.click(screen.getByRole("tab", { name: "JavaScript" }));
    expect(example).toHaveTextContent('model: "qwen3-vl-8b"');
  });

  it("is open to viewers, who are told to ask an admin for a key", async () => {
    mockApi(routes("viewer"));
    render(<App />);
    expect(await screen.findByText(base)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Create a key" })).not.toBeInTheDocument();
    expect(within(screen.getByRole("navigation", { name: "Sections" })).getByRole("link", { name: "Connect" })).toBeInTheDocument();
  });
});
