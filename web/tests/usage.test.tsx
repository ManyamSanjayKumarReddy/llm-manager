import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { compact, dayLabel } from "../src/lib/format";
import { mockApi, status, visit } from "./helpers";

const totals = (requests: number, prompt: number, completion: number, errors = 0) => ({
  requests, errors, prompt_tokens: prompt, completion_tokens: completion, total_tokens: prompt + completion,
});
const day = (d: string, t: ReturnType<typeof totals>) => ({ day: d, ...t });
const key = (id: string, label: string, t: ReturnType<typeof totals>, extra: Record<string, unknown> = {}) => ({
  id, label, prefix: `lm_${label.slice(0, 4)}`, revoked: false, last_used_at: "2026-11-13T09:00:00Z", ...t, ...extra,
});

describe("number formats", () => {
  it("shortens big numbers and keeps small ones whole", () => {
    expect([0, 999, 1000, 1234, 15_200, 999_999, 3_400_000, 2_500_000_000].map(compact))
      .toEqual(["0", "999", "1K", "1.2K", "15.2K", "1000K", "3.4M", "2.5B"]);
    expect(dayLabel("2026-11-13")).toBe("Nov 13");
  });
});

describe("Usage screen", () => {
  const admin = { username: "root", role: "admin", csrf_token: "csrf-1" };
  const usage = {
    days: 30,
    totals: totals(14, 9000, 3000, 1),
    daily: [day("2026-11-12", totals(4, 1000, 500)), day("2026-11-13", totals(10, 8000, 2500, 1))],
    keys: [
      key("k1", "alpha", totals(10, 8000, 2500, 1)),
      key("k2", "beta", totals(4, 1000, 500), { revoked: true }),
      key("k3", "quiet", totals(0, 0, 0), { last_used_at: null }),
    ],
    models: [
      { model: "gpt-oss-20b", ...totals(12, 8500, 2800, 1) },
      { model: "qwen3-vl-8b", ...totals(2, 500, 200) },
    ],
  };

  beforeEach(() => {
    visit("/usage");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    HTMLDialogElement.prototype.showModal = function showModal() { this.setAttribute("open", ""); };
    HTMLDialogElement.prototype.close = function close() { this.removeAttribute("open"); };
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  it("shows totals, the biggest key first, and each model", async () => {
    const calls = mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/usage": () => ({ body: usage }),
    });
    render(<App />);
    const keys = (await screen.findByText("By API key")).closest("section") as HTMLElement;
    expect(calls.find((c) => c.key === "GET /api/usage")?.query.get("days")).toBe("30");
    expect(screen.getByText("Total tokens", { selector: ".label" }).closest(".stat")).toHaveTextContent("12K");
    expect(screen.getByText("Prompt tokens").closest(".stat")).toHaveTextContent("9K");
    expect(screen.getByText(/Requests · 2 keys used/).closest(".stat")).toHaveTextContent("7.1% failed");
    const rows = within(keys).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getByRole("button").textContent)).toEqual(["alphalm_alph…", "betalm_beta… · revoked", "quietlm_quie…"]);
    expect(within(rows[2] as HTMLElement).getByText("never")).toBeInTheDocument();
    const models = (screen.getByText("By model").closest("section")) as HTMLElement;
    expect(within(models).getByText("gpt-oss-20b")).toBeInTheDocument();
    // the chart is readable without a mouse
    expect(screen.getByRole("button", { name: "Nov 13: 10,500 tokens, 10 requests" })).toBeInTheDocument();
    expect(screen.getByText("Show as a table")).toBeInTheDocument();
  });

  it("changes the range and opens one key's usage", async () => {
    const calls = mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/usage": () => ({ body: usage }),
      "GET /api/usage/keys/k1": () => ({ body: { key: usage.keys[0], days: 30, daily: usage.daily, models: [usage.models[0]] } }),
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("By API key");
    await user.click(screen.getByRole("button", { name: "7 days" }));
    await waitFor(() => { expect(calls.some((c) => c.key === "GET /api/usage" && c.query.get("days") === "7")).toBe(true); });
    await user.click(await screen.findByRole("button", { name: "Usage of alpha" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("By model")).toBeInTheDocument();
    expect(within(dialog).getByText("10,500", { selector: "b" })).toBeInTheDocument(); // exact total tokens of the key
    expect(calls.some((c) => c.key === "GET /api/usage/keys/k1" && c.query.get("days") === "7")).toBe(true);
  });

  it("says so when nothing was called yet", async () => {
    mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/usage": () => ({ body: { days: 30, totals: totals(0, 0, 0), daily: [day("2026-11-13", totals(0, 0, 0))], keys: [], models: [] } }),
    });
    render(<App />);
    expect(await screen.findByText("No requests in this period")).toBeInTheDocument();
    expect(screen.getByText(/No API keys yet/)).toBeInTheDocument();
  });
});
