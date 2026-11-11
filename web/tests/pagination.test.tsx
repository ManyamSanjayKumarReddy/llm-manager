import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { Pagination } from "../src/components/Pagination";
import { pageSlots } from "../src/lib/pageSlots";
import { mockApi, page, status, visit } from "./helpers";

describe("pageSlots", () => {
  it("shows every page when there are few", () => {
    expect(pageSlots(1, 1)).toEqual([1]);
    expect(pageSlots(3, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });
  it("collapses the middle of a long list", () => {
    expect(pageSlots(1, 20)).toEqual([1, 2, "gap-end", 20]);
    expect(pageSlots(10, 20)).toEqual([1, "gap-start", 9, 10, 11, "gap-end", 20]);
    expect(pageSlots(20, 20)).toEqual([1, "gap-start", 19, 20]);
    expect(pageSlots(4, 20)).toEqual([1, 2, 3, 4, 5, "gap-end", 20]);
    expect(pageSlots(5, 20)).toEqual([1, "gap-start", 4, 5, 6, "gap-end", 20]);
    expect(pageSlots(17, 20)).toEqual([1, "gap-start", 16, 17, 18, 19, 20]);
  });
  it("never hides just one page behind a gap", () => {
    for (let pages = 8; pages <= 30; pages++) {
      for (let page = 1; page <= pages; page++) {
        const slots = pageSlots(page, pages);
        const numbers = slots.filter((s): s is number => typeof s === "number");
        slots.forEach((slot, i) => {
          if (typeof slot === "number") return;
          const before = numbers.filter((n) => slots.indexOf(n) < i).at(-1) ?? 0;
          const after = numbers.find((n) => slots.indexOf(n) > i) ?? pages + 1;
          expect(after - before - 1).toBeGreaterThanOrEqual(2);
        });
        expect(new Set(numbers).size).toBe(numbers.length);
        expect(numbers).toContain(page);
      }
    }
  });
});

describe("<Pagination>", () => {
  const props = { noun: "keys", onPage: vi.fn(), onPageSize: vi.fn() };
  afterEach(() => { cleanup(); vi.clearAllMocks(); });

  it("says which rows are shown", () => {
    render(<Pagination {...props} page={2} pages={6} total={132} pageSize={25} />);
    expect(screen.getByText("26–50")).toBeInTheDocument();
    expect(screen.getByText("132")).toBeInTheDocument();
  });
  it("shows the last page's partial range", () => {
    render(<Pagination {...props} page={6} pages={6} total={132} pageSize={25} />);
    expect(screen.getByText("126–132")).toBeInTheDocument();
  });
  it("disables first/previous on the first page and next/last on the last", () => {
    const { rerender } = render(<Pagination {...props} page={1} pages={3} total={60} pageSize={25} />);
    expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "First page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next page" })).toBeEnabled();
    rerender(<Pagination {...props} page={3} pages={3} total={60} pageSize={25} />);
    expect(screen.getByRole("button", { name: "Next page" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Last page" })).toBeDisabled();
  });
  it("reports clicks and marks the current page", async () => {
    const user = userEvent.setup();
    render(<Pagination {...props} page={2} pages={4} total={100} pageSize={25} />);
    expect(screen.getByRole("button", { name: "Page 2" })).toHaveAttribute("aria-current", "page");
    await user.click(screen.getByRole("button", { name: "Page 4" }));
    expect(props.onPage).toHaveBeenLastCalledWith(4);
    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(props.onPage).toHaveBeenLastCalledWith(3);
    await user.click(screen.getByRole("button", { name: "First page" }));
    expect(props.onPage).toHaveBeenLastCalledWith(1);
    await user.selectOptions(screen.getByLabelText("Rows per page"), "50");
    expect(props.onPageSize).toHaveBeenCalledWith(50);
  });
  it("has no page buttons for a single page, and renders nothing when empty", () => {
    const { container, rerender } = render(<Pagination {...props} page={1} pages={1} total={3} pageSize={25} />);
    expect(screen.queryByRole("navigation", { name: "Pagination" })).not.toBeInTheDocument();
    expect(screen.getByText("1–3")).toBeInTheDocument();
    rerender(<Pagination {...props} page={1} pages={1} total={0} pageSize={25} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("a paginated list (users page)", () => {
  const admin = { username: "root", role: "admin", csrf_token: "c" };
  const make = (n: number) => Array.from({ length: n }, (_, i) => ({
    id: `id-${i}`, username: `user${String(i).padStart(3, "0")}`, role: i % 3 === 0 ? "admin" : "viewer",
    is_active: true, created_at: "2026-01-01T00:00:00Z", last_login_at: null, locked: false,
  }));
  const everyone = make(60);

  /** A tiny server: filters, slices and records what was asked. */
  function server() {
    return mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/users": (_, q) => {
        const term = q.get("q") ?? "";
        const role = q.get("role") ?? "";
        const rows = everyone.filter((u) => u.username.includes(term) && (!role || u.role === role));
        const size = Number(q.get("page_size"));
        const start = (Number(q.get("page")) - 1) * size;
        return { body: page(rows.slice(start, start + size), q, rows.length) };
      },
    });
  }
  const usersQueries = (calls: ReturnType<typeof server>) => calls.filter((c) => c.key === "GET /api/users").map((c) => c.query);

  beforeEach(() => {
    visit("/users");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); setCsrfToken(""); });

  it("asks the server for one page at a time and moves between pages", async () => {
    const calls = server();
    const user = userEvent.setup();
    render(<App />);
    expect(await screen.findByText("user000")).toBeInTheDocument();
    expect(screen.queryByText("user025")).not.toBeInTheDocument(); // only 25 per page
    expect(screen.getByText("1–25")).toBeInTheDocument();
    expect(usersQueries(calls)[0]?.get("page_size")).toBe("25");

    await user.click(screen.getByRole("button", { name: "Next page" }));
    expect(await screen.findByText("user025")).toBeInTheDocument();
    expect(screen.queryByText("user000")).not.toBeInTheDocument();
    expect(screen.getByText("26–50")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Last page" }));
    expect(await screen.findByText("user059")).toBeInTheDocument();
    expect(screen.getByText("51–60")).toBeInTheDocument();
  });

  it("changes the page size and goes back to page 1", async () => {
    const calls = server();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("user000");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("user025");
    await user.selectOptions(screen.getByLabelText("Rows per page"), "10");
    expect(await screen.findByText("1–10")).toBeInTheDocument();
    expect(screen.queryByText("user010")).not.toBeInTheDocument();
    const last = usersQueries(calls).at(-1);
    expect([last?.get("page"), last?.get("page_size")]).toEqual(["1", "10"]);
  });

  it("searches on the server after a pause, and a new search starts at page 1", async () => {
    const calls = server();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("user000");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    await screen.findByText("user025");
    const before = usersQueries(calls).length;

    await user.type(screen.getByLabelText("Search users"), "user04");
    expect(usersQueries(calls).length).toBe(before); // nothing sent while typing
    await waitFor(() => { expect(usersQueries(calls).at(-1)?.get("q")).toBe("user04"); });
    expect(usersQueries(calls).at(-1)?.get("page")).toBe("1");
    expect(usersQueries(calls).length - before).toBe(1); // one request, not one per key
    expect(await screen.findByText("user045")).toBeInTheDocument();
    expect(screen.queryByText("user000")).not.toBeInTheDocument();
  });

  it("filters by role and says so when nothing matches", async () => {
    server();
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("user000");
    await user.selectOptions(screen.getByLabelText("Filter by role"), "admin");
    await waitFor(() => { expect(screen.getByText("20")).toBeInTheDocument(); }); // every third of 60
    await user.type(screen.getByLabelText("Search users"), "zzz");
    expect(await screen.findByText("No accounts match your search.")).toBeInTheDocument();
  });

  it("steps back when the current page no longer exists", async () => {
    let rows = make(26); // two pages: 25 + 1
    const calls = mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/users": (_, q) => {
        const size = Number(q.get("page_size"));
        const start = (Number(q.get("page")) - 1) * size;
        return { body: page(rows.slice(start, start + size), q, rows.length) };
      },
      "PATCH /api/users/id-25": () => { rows = rows.slice(0, 25); return { body: rows[0] }; },
    });
    const user = userEvent.setup();
    render(<App />);
    await screen.findByText("user000");
    await user.click(screen.getByRole("button", { name: "Next page" }));
    const lone = (await screen.findByText("user025")).closest("tr") as HTMLElement;
    await user.click(within(lone).getByRole("button", { name: "Disable" }));
    expect(await screen.findByText("user000")).toBeInTheDocument(); // fell back to page 1
    expect(calls.at(-1)?.query.get("page")).toBe("1");
  });
});
