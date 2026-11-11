import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, api, setCsrfToken, setUnauthorizedHandler } from "../src/api/client";
import { mockApi } from "./helpers";

afterEach(() => {
  vi.unstubAllGlobals();
  setCsrfToken("");
});

describe("api client", () => {
  it("sends the CSRF token on changes but not on reads", async () => {
    const calls = mockApi({
      "GET /api/status": () => ({ body: { models: {} } }),
      "POST /api/auth/logout": () => ({ status: 204 }),
    });
    setCsrfToken("tok");
    await api.status();
    await api.logout();
    const headers = (i: number) => calls[i]?.init.headers as Record<string, string>;
    expect(headers(0)["X-CSRF-Token"]).toBeUndefined();
    expect(headers(1)["X-CSRF-Token"]).toBe("tok");
    expect(calls[1]?.init.credentials).toBe("same-origin");
  });

  it("turns error responses into readable messages", async () => {
    mockApi({
      "POST /api/auth/login": () => ({ status: 429, body: {} }),
      "GET /api/status": () => ({ status: 422, body: { detail: [{ msg: "too short" }, { msg: "bad role" }] } }),
    });
    await expect(api.login("a", "b")).rejects.toMatchObject({
      status: 429,
      message: expect.stringContaining("Too many") as unknown,
    });
    await expect(api.status()).rejects.toThrow("too short; bad role");
  });

  it("signals an ended session, except for a failed sign-in", async () => {
    mockApi({
      "GET /api/status": () => ({ status: 401, body: { detail: "not logged in" } }),
      "POST /api/auth/login": () => ({ status: 401, body: { detail: "Invalid credentials" } }),
    });
    const onEnd = vi.fn();
    setUnauthorizedHandler(onEnd);
    await expect(api.login("a", "b")).rejects.toBeInstanceOf(ApiError);
    expect(onEnd).not.toHaveBeenCalled();
    await expect(api.status()).rejects.toBeInstanceOf(ApiError);
    expect(onEnd).toHaveBeenCalledOnce();
  });

  it("reports an unreachable server", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("network"))));
    await expect(api.status()).rejects.toMatchObject({ status: 0, message: "Cannot reach the server." });
  });
});
