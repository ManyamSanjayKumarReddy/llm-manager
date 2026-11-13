import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import type { SchedulerValues } from "../src/api/types";
import { App } from "../src/App";
import { mockApi, status, visit } from "./helpers";

const DEFAULTS: SchedulerValues = {
  queue_timeout_s: 120, min_awake_s: 10, priority_hold_s: 10, preempt_after_s: null,
  wake_timeout_s: 90, sleep_timeout_s: 60, reaper_interval_s: 15, sleep_level: 1,
};

describe("Scheduling screen", () => {
  const admin = { username: "root", role: "admin", csrf_token: "csrf-1" };

  beforeEach(() => {
    visit("/scheduling");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  function routes(initial: SchedulerValues = DEFAULTS) {
    let values = initial;
    let saved: { updated_at: string; updated_by: string } | null = null;
    return mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/settings/scheduler": () => ({ body: { values, defaults: DEFAULTS, updated_at: saved?.updated_at ?? null, updated_by: saved?.updated_by ?? null } }),
      "PUT /api/settings/scheduler": (init) => {
        values = JSON.parse(init.body as string) as SchedulerValues;
        saved = { updated_at: "2026-11-13T10:00:00Z", updated_by: "root" };
        return { body: { values, defaults: DEFAULTS, ...saved } };
      },
    });
  }

  it("shows the values in force and saves a longer queue timeout with preemption on", async () => {
    const calls = routes();
    const user = userEvent.setup();
    render(<App />);
    const queue = await screen.findByLabelText("Queue timeout");
    expect(queue).toHaveValue(120);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled(); // nothing changed yet
    expect(screen.queryByLabelText("Stop after")).not.toBeInTheDocument(); // preemption is off

    await user.clear(queue);
    await user.type(queue, "600");
    await user.click(screen.getByRole("switch"));
    await user.clear(screen.getByLabelText("Stop after"));
    await user.type(screen.getByLabelText("Stop after"), "45");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => { expect(calls.some((c) => c.key === "PUT /api/settings/scheduler")).toBe(true); });
    const put = calls.find((c) => c.key === "PUT /api/settings/scheduler");
    expect(JSON.parse(put?.init.body as string)).toEqual({ ...DEFAULTS, queue_timeout_s: 600, preempt_after_s: 45 });
    expect(await screen.findByText(/Last saved by root/)).toBeInTheDocument();
  });

  it("refuses a stop-after that is not smaller than the queue timeout", async () => {
    routes();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByLabelText("Queue timeout");
    await user.click(screen.getByRole("switch"));
    const after = screen.getByLabelText("Stop after");
    await user.clear(after);
    await user.type(after, "120");
    expect(screen.getByRole("alert")).toHaveTextContent(/smaller than the queue timeout/);
    expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
  });

  it("resets the form to the defaults without saving", async () => {
    const calls = routes({ ...DEFAULTS, queue_timeout_s: 900, preempt_after_s: 60 });
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByLabelText("Queue timeout")).toHaveValue(900);
    await user.click(screen.getByRole("button", { name: "Reset to defaults" }));
    expect(screen.getByLabelText("Queue timeout")).toHaveValue(120);
    expect(screen.queryByLabelText("Stop after")).not.toBeInTheDocument();
    expect(calls.some((c) => c.key === "PUT /api/settings/scheduler")).toBe(false);
  });
});
