import { describe, expect, it } from "vitest";

import config from "../vite.config";

describe("dev server proxy", () => {
  const rules = Object.keys(config.server?.proxy ?? {}).map((key) => new RegExp(key));
  const proxied = (path: string) => rules.some((rule) => rule.test(path));

  it("sends API traffic to the backend", () => {
    for (const path of ["/api/status", "/api/auth/login", "/v1/chat/completions", "/healthz"]) expect(proxied(path)).toBe(true);
  });

  it("leaves every dashboard page to the app, including ones that start with 'api'", () => {
    for (const path of ["/", "/signin", "/overview", "/models", "/history", "/api-keys", "/users", "/audit", "/account"]) {
      expect(proxied(path), path).toBe(false);
    }
  });
});
