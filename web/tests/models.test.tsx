import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { setCsrfToken } from "../src/api/client";
import { App } from "../src/App";
import { problemsOf, DEFAULTS, type Form } from "../src/features/models/form";
import {
  buildVllmCommand,
  buildVllmLines,
  generateApiKey,
  maskSecret,
  servedNameFor,
  suggestName,
  vllmProblems,
  type VllmParams,
} from "../src/lib/vllmCommand";
import { mockApi, page, status, visit } from "./helpers";

// The command people run today, plus the lines sleep mode needs.
const base: VllmParams = {
  containerName: "gpt-oss-20b",
  model: "openai/gpt-oss-20b",
  port: 8025,
  gpus: [0],
  imageTag: "v0.10.1",
  cacheDir: "/root/.cache/huggingface",
  apiKey: "sk-abc123",
  hfToken: "",
  maxModelLen: 32768,
  maxNumSeqs: 4,
  memoryShare: 0.9,
  allowLongContext: true,
  toolCalling: true,
  toolParser: "openai",
  autoRestart: true,
  extraArgs: "",
};

describe("vLLM command", () => {
  const command = buildVllmCommand(base) ?? "";
  const lines = command.split(" \\\n  ");

  it("keeps every line of the command people already run", () => {
    for (const original of [
      "docker run -d",
      `--gpus '"device=0"'`,
      "--name gpt-oss-20b",
      "--restart unless-stopped",
      "-v /root/.cache/huggingface:/root/.cache/huggingface",
      "-e VLLM_API_KEY=sk-abc123",
      "-e VLLM_ALLOW_LONG_MAX_MODEL_LEN=1",
      '--env "HUGGING_FACE_HUB_TOKEN="',
      "-p 127.0.0.1:8025:8000",
      "--ipc=host",
      "vllm/vllm-openai:v0.10.1",
      "--model openai/gpt-oss-20b",
      "--max-model-len 32768",
      "--max-num-seqs 4",
      "--gpu-memory-utilization 0.9",
      "--tokenizer-mode auto",
      "--enable-auto-tool-choice",
      "--tool-call-parser openai",
      "--host 0.0.0.0 --port 8000",
    ]) {
      expect(lines).toContain(original);
    }
  });

  it("adds only what sleep mode needs, and marks those lines", () => {
    expect(lines).toContain("-e VLLM_SERVER_DEV_MODE=1");
    expect(lines).toContain("--enable-sleep-mode");
    const marked = (buildVllmLines(base) ?? []).filter((l) => l.router).map((l) => l.text);
    expect(marked).toEqual(["-e VLLM_SERVER_DEV_MODE=1", "--enable-sleep-mode"]);
    const two = (buildVllmLines({ ...base, gpus: [1, 0] }) ?? []).filter((l) => l.router).map((l) => l.text);
    expect(two).toEqual(["-e VLLM_SERVER_DEV_MODE=1", "--tensor-parallel-size 2", "--enable-sleep-mode"]);
  });

  it("splits a model over several GPUs with tensor parallelism, listing them in order", () => {
    const multi = buildVllmCommand({ ...base, gpus: [1, 0] }) ?? "";
    expect(multi).toContain(`--gpus '"device=0,1"'`);
    expect(multi).toContain("--tensor-parallel-size 2");
    expect(command).not.toContain("--tensor-parallel-size");
  });

  it("leaves out what was switched off", () => {
    const off = buildVllmCommand({ ...base, toolCalling: false, allowLongContext: false, autoRestart: false, apiKey: "" }) ?? "";
    for (const gone of ["--enable-auto-tool-choice", "--tool-call-parser", "VLLM_ALLOW_LONG_MAX_MODEL_LEN", "--restart", "VLLM_API_KEY"]) {
      expect(off).not.toContain(gone);
    }
  });

  it("shows keys masked on screen but copies the real ones", () => {
    const shown = (buildVllmLines({ ...base, hfToken: "hf_realtoken123" }) ?? []).map((l) => l.text).join("\n");
    expect(shown).not.toContain("sk-abc123");
    expect(shown).not.toContain("hf_realtoken123");
    expect(shown).toContain("sk-••••••••");
    expect(buildVllmCommand({ ...base, hfToken: "hf_realtoken123" })).toContain("HUGGING_FACE_HUB_TOKEN=hf_realtoken123");
    expect(maskSecret("ab")).toBe("••••");
  });

  it("quotes a key that is not shell-safe, so it can never run as a command", () => {
    const tricky = buildVllmCommand({ ...base, apiKey: "a$b`c'd" }) ?? "";
    expect(tricky).toContain(`-e VLLM_API_KEY='a$b\`c'\\''d'`);
  });

  it("quotes a token that is not shell-safe, so it can never run as a command", () => {
    const tricky = buildVllmCommand({ ...base, hfToken: 'a"b$(id)' }) ?? "";
    expect(tricky).toContain(`--env 'HUGGING_FACE_HUB_TOKEN=a"b$(id)'`);
    const plain = buildVllmCommand({ ...base, hfToken: "hf_abc123" }) ?? "";
    expect(plain).toContain('--env "HUGGING_FACE_HUB_TOKEN=hf_abc123"'); // same shape as the usual command
  });

  it("never publishes the port beyond this machine", () => {
    expect(command).toContain("-p 127.0.0.1:8025:8000");
    expect(command).not.toMatch(/-p 0\.0\.0\.0|-p \d+:8000/);
  });

  it("is a multi-line command that a shell reads as one", () => {
    const raw = command.split("\n");
    expect(raw.length).toBeGreaterThan(15);
    expect(raw.slice(0, -1).every((l) => l.endsWith(" \\"))).toBe(true);
    expect(raw.at(-1)?.endsWith("\\")).toBe(false);
  });

  it("adds extra arguments before the host line", () => {
    const extra = buildVllmCommand({ ...base, extraArgs: "--dtype  bfloat16" }) ?? "";
    expect(extra.indexOf("--dtype bfloat16")).toBeGreaterThan(extra.indexOf("--tool-call-parser"));
    expect(extra.indexOf("--dtype bfloat16")).toBeLessThan(extra.indexOf("--host 0.0.0.0"));
  });

  const unsafe: [string, Partial<VllmParams>][] = [
    ["shell injection in the model", { model: "x; rm -rf /" }],
    ["command substitution in the name", { containerName: "a$(whoami)" }],
    ["spaces in the name", { containerName: "a b" }],
    ["a quote in the tag", { imageTag: "v1' --privileged" }],
    ["a newline in the model", { model: "a/b\nrm" }],
    ["a bad cache path", { cacheDir: "/tmp/x; reboot" }],
    ["a key with a space", { apiKey: "two words" }],
    ["a key with a newline", { apiKey: "abc\nX-Evil: 1" }],
    ["a huge key", { apiKey: "k".repeat(513) }],
    ["a token with a space", { hfToken: "a b" }],
    ["a bad parser", { toolParser: "x; id" }],
    ["shell characters in extra arguments", { extraArgs: "--x $(id)" }],
    ["quotes in extra arguments", { extraArgs: "--x 'y'" }],
    ["port too low", { port: 80 }],
    ["port too high", { port: 70000 }],
    ["fractional port", { port: 8025.5 }],
    ["no GPUs", { gpus: [] }],
    ["tiny context", { maxModelLen: 10 }],
    ["zero parallel requests", { maxNumSeqs: 0 }],
    ["memory share above 1", { memoryShare: 1.2 }],
    ["memory share not a number", { memoryShare: Number.NaN }],
  ];
  it.each(unsafe)("refuses %s", (_, change) => {
    const params = { ...base, ...change };
    expect(vllmProblems(params).length).toBeGreaterThan(0);
    expect(buildVllmCommand(params)).toBeNull();
  });

  it("suggests names, reads --served-model-name, and makes strong random keys", () => {
    expect(suggestName("openai/gpt-oss-20b")).toBe("gpt-oss-20b");
    expect(suggestName("Qwen/Qwen3-VL-8B-Instruct-FP8")).toBe("qwen3-vl-8b-instruct-fp8");
    expect(suggestName("weird name!!")).toBe("weird-name");
    expect(servedNameFor("org/model", "--dtype bfloat16")).toBe("org/model");
    expect(servedNameFor("org/model", "--served-model-name my-model --dtype x")).toBe("my-model");
    const [a, b] = [generateApiKey(), generateApiKey()];
    expect(a).toMatch(/^sk-[0-9a-f]{48}$/);
    expect(a).not.toBe(b);
  });
});

describe("form problems", () => {
  const form = (change: Partial<Form>): Form => ({ ...DEFAULTS, model: "openai/gpt-oss-20b", server: "this-server", ...change });
  const registered = [{ name: "taken", server: "this-server", url: "http://127.0.0.1:9000", served_name: null, gpus: [0], idle_minutes: 10, priority: 0, has_api_key: false, container: null, created_at: "", state: "asleep", inflight: 0, waiting: 0 }];

  it("files each problem under the step where it can be fixed", () => {
    expect(problemsOf(form({}), []).flat()).toEqual([]);
    expect(problemsOf(DEFAULTS, [])[0]?.[0]).toMatch(/Enter the Hugging Face model/);
    const steps = problemsOf(form({ apiKey: "a b", maxModelLen: "5", idle: "0", imageTag: "bad tag" }), []);
    expect(steps[1]?.[0]).toMatch(/API key/);
    expect(steps[2]?.[0]).toMatch(/Context length/);
    expect(steps[3]?.[0]).toMatch(/Sleep after idle/);
    expect(steps[4]?.[0]).toMatch(/vLLM version/);
  });

  it("spots a name or port that is already taken", () => {
    expect(problemsOf(form({ name: "taken", nameEdited: true }), registered)[0]?.join(" ")).toMatch(/already registered/);
    expect(problemsOf(form({ port: "9000" }), registered)[0]?.join(" ")).toMatch(/Port 9000 is already used by “taken”/);
  });
});

describe("Models screen", () => {
  const admin = { username: "root", role: "admin", csrf_token: "csrf-1" };
  const row = (name: string, extra: Record<string, unknown> = {}) => ({
    name, server: "this-server", url: "http://127.0.0.1:8025", served_name: `org/${name}`, gpus: [0], idle_minutes: 10, priority: 0,
    has_api_key: false, container: null, created_at: "2026-01-01T00:00:00Z", state: "asleep", inflight: 0, waiting: 0, ...extra,
  });
  const servers = [{ name: "this-server", gpu_count: 2, gpu_type: null, agent_url: null, has_agent: false, models: [], created_at: "2026-01-01T00:00:00Z" }];
  const ok = { reachable: true, sleep_endpoints: true, state: "awake", served_models: ["openai/new-one"], served_name_found: true, key_accepted: null, problems: [] };
  const next = async (user: ReturnType<typeof userEvent.setup>, times = 1) => {
    for (let i = 0; i < times; i++) await user.click(screen.getByRole("button", { name: /^Next/ }));
  };

  beforeEach(() => {
    visit("/models");
    vi.stubGlobal("IntersectionObserver", class { observe() {} disconnect() {} unobserve() {} takeRecords() { return []; } });
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("reduce"), addEventListener() {}, removeEventListener() {} }));
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  });
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); setCsrfToken(""); });

  const withModels = (models: ReturnType<typeof row>[] | (() => ReturnType<typeof row>[]), more: Record<string, (init: RequestInit, q: URLSearchParams) => { status?: number; body?: unknown }> = {}) =>
    mockApi({
      "GET /api/auth/me": () => ({ body: admin }),
      "GET /api/status": () => ({ body: status }),
      "GET /api/servers": () => ({ body: servers }),
      "GET /api/models": (_, q) => ({ body: page(typeof models === "function" ? models() : models, q) }),
      ...more,
    });

  it("has exactly one Add model button, in either state", async () => {
    withModels([]);
    const { unmount } = render(<App />);
    await screen.findByText("No models yet");
    expect(screen.getAllByRole("button", { name: /Add model/ })).toHaveLength(1);
    unmount();
    withModels([row("alpha")]);
    render(<App />);
    await screen.findByText("alpha");
    expect(screen.getAllByRole("button", { name: /Add model/ })).toHaveLength(1);
    expect(screen.queryByText("No models yet")).not.toBeInTheDocument();
  });

  it("lists registered models with priority, state and a stored-key note", async () => {
    withModels([row("alpha", { priority: 5, state: "awake", has_api_key: true }), row("beta")]);
    render(<App />);
    const alpha = (await screen.findByRole("button", { name: "Manage alpha" })).closest("tr") as HTMLElement;
    expect(within(alpha).getByText("5")).toBeInTheDocument();
    expect(within(alpha).getByText("awake")).toBeInTheDocument();
    expect(within(alpha).getByText(/key stored/)).toBeInTheDocument();
    const beta = screen.getByRole("button", { name: "Manage beta" }).closest("tr") as HTMLElement;
    expect(within(beta).getByText("Normal")).toBeInTheDocument();
    expect(screen.queryByText(/models.yaml/)).not.toBeInTheDocument();
  });

  it("offers only the GPUs the chosen server has", async () => {
    withModels([]);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("GPU 0")).toBeChecked();
    expect(within(dialog).getByLabelText("GPU 1")).not.toBeChecked();
    expect(within(dialog).queryByLabelText("GPU 2")).not.toBeInTheDocument();
  });

  it("walks through the steps, builds the command, then tests and registers", async () => {
    let models = [row("alpha")];
    const calls = withModels(() => models, {
      "POST /api/models/check": () => ({ body: ok }),
      "POST /api/models": (init) => {
        models = [...models, row("new-one")];
        return { status: 201, body: JSON.parse(init.body as string) };
      },
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");

    // step 1: the model. Nothing can be done before it is filled in.
    expect(within(dialog).getByRole("button", { name: /^Next/ })).toBeDisabled();
    await user.type(within(dialog).getByLabelText("Hugging Face model"), "openai/new-one");
    expect(within(dialog).getByLabelText("Name clients use")).toHaveValue("new-one");
    await user.clear(within(dialog).getByLabelText("Port on that server")); // 8025 is taken by "alpha"
    await user.type(within(dialog).getByLabelText("Port on that server"), "9100");
    await user.click(within(dialog).getByLabelText("GPU 1"));
    await next(user);

    // step 2: access, with a generated key
    await user.click(within(dialog).getByRole("button", { name: "Generate" }));
    const key = within(dialog).getByLabelText<HTMLInputElement>("Container API key").value;
    expect(key).toMatch(/^sk-[0-9a-f]{48}$/);
    await next(user);

    // step 3: performance (defaults are the usual command), step 4: priority
    expect(within(dialog).getByLabelText("Context length (tokens) number")).toHaveValue(32768);
    await next(user);
    await user.click(within(dialog).getByRole("button", { name: "High" }));
    expect(within(dialog).getByLabelText("Priority number")).toHaveValue(5);
    await next(user, 2); // step 5 (advanced) is left alone

    // step 6: the command and registration
    const command = within(dialog).getByLabelText("Container command");
    expect(command).toHaveTextContent("--model openai/new-one");
    expect(command).toHaveTextContent("--enable-sleep-mode");
    expect(command).toHaveTextContent("--tensor-parallel-size 2");
    expect(command).toHaveTextContent("docker run -d");
    expect(command).not.toHaveTextContent(key); // masked on screen
    await user.click(within(dialog).getByRole("button", { name: "Test connection" }));
    expect(await within(dialog).findByText(/Everything looks right/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Register model" }));

    await waitFor(() => { expect(calls.some((c) => c.key === "POST /api/models")).toBe(true); });
    const post = calls.find((c) => c.key === "POST /api/models");
    expect(JSON.parse(post?.init.body as string)).toEqual({
      name: "new-one", server: "this-server", url: "http://127.0.0.1:9100", served_name: "openai/new-one", gpus: [0, 1],
      idle_minutes: 10, priority: 5, backend_api_key: key,
    });
    expect(await screen.findByText(/“new-one” registered/)).toBeInTheDocument();
    await waitFor(() => { expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); });
    expect(await screen.findByRole("button", { name: "Manage new-one" })).toBeInTheDocument(); // the list refreshed
  });

  it("the popup keeps the same steps and lets you go back", async () => {
    withModels([]);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");
    const steps = within(dialog).getByRole("list", { name: "Progress" });
    expect(within(steps).getAllByRole("listitem").map((li) => li.textContent.replace(/^\d+/, ""))).toEqual(["Model", "Access", "Performance", "Sleep", "Advanced", "Run"]);
    await user.type(within(dialog).getByLabelText("Hugging Face model"), "openai/x");
    await next(user, 2);
    expect(within(steps).getByRole("listitem", { current: "step" })).toHaveTextContent("Performance");
    await user.click(within(dialog).getByRole("button", { name: "Back to Model" }));
    expect(within(steps).getByRole("listitem", { current: "step" })).toHaveTextContent("Model");
    expect(within(dialog).getByLabelText("Hugging Face model")).toHaveValue("openai/x"); // nothing was lost
  });

  it("can skip straight to the command once everything is valid", async () => {
    withModels([]);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).queryByRole("button", { name: "Skip to command" })).not.toBeInTheDocument();
    await user.type(within(dialog).getByLabelText("Hugging Face model"), "openai/x");
    await next(user);
    await user.click(within(dialog).getByRole("button", { name: "Skip to command" }));
    expect(within(dialog).getByLabelText("Container command")).toHaveTextContent("--model openai/x");
  });

  it("will not go on with unsafe input, and says why", async () => {
    withModels([]);
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Hugging Face model"), "x; rm -rf /");
    expect(within(dialog).getByRole("alert")).toHaveTextContent(/Hugging Face id/);
    expect(within(dialog).getByRole("button", { name: /^Next/ })).toBeDisabled();
  });

  it("warns when the new model shares a GPU with a registered one", async () => {
    withModels([row("alpha", { gpus: [0] })]);
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: "Manage alpha" });
    await user.click(screen.getByRole("button", { name: /Add model/ }));
    expect((await screen.findByText(/Shared GPU/)).closest(".callout")).toHaveTextContent(/alpha already uses this GPU/);
  });

  it("shows what is wrong when the connection test fails, and still allows registering", async () => {
    withModels([], {
      "POST /api/models/check": () => ({ body: { ...ok, reachable: false, sleep_endpoints: false, state: null, served_models: [], served_name_found: null, problems: ["cannot reach the container: is it running, and is the address right?"] } }),
    });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: /Add model/ }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Hugging Face model"), "openai/x");
    await next(user);
    await user.click(within(dialog).getByRole("button", { name: "Skip to command" }));
    await user.click(within(dialog).getByRole("button", { name: "Test connection" }));
    expect(await within(dialog).findByText(/cannot reach the container/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Register model" })).toBeEnabled();
  });

  it("opens a model in a popup and sends only what changed", async () => {
    const calls = withModels([row("alpha", { has_api_key: true })], { "PATCH /api/models/alpha": () => ({ body: row("alpha", { priority: 7 }) }) });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Manage alpha" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("heading", { name: "alpha" })).toBeInTheDocument();
    expect(within(dialog).getByText(/A key is stored/)).toBeInTheDocument();
    await user.clear(within(dialog).getByLabelText("Priority number"));
    await user.type(within(dialog).getByLabelText("Priority number"), "7");
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => { expect(calls.some((c) => c.key === "PATCH /api/models/alpha")).toBe(true); });
    expect(JSON.parse(calls.find((c) => c.key === "PATCH /api/models/alpha")?.init.body as string)).toEqual({ priority: 7 });
  });

  it("replaces or removes the stored key", async () => {
    const calls = withModels([row("alpha", { has_api_key: true })], { "PATCH /api/models/alpha": () => ({ body: row("alpha") }) });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Manage alpha" }));
    let dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Replace the key"), "new-key-value");
    expect(within(dialog).getByLabelText("Remove the stored key")).toBeDisabled();
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    const patches = () => calls.filter((c) => c.key === "PATCH /api/models/alpha");
    await waitFor(() => { expect(patches()).toHaveLength(1); });
    expect(JSON.parse(patches()[0]?.init.body as string)).toEqual({ backend_api_key: "new-key-value" });

    await user.click(await screen.findByRole("button", { name: "Manage alpha" }));
    dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByLabelText("Remove the stored key"));
    await user.click(within(dialog).getByRole("button", { name: "Save changes" }));
    await waitFor(() => { expect(patches()).toHaveLength(2); });
    expect(JSON.parse(patches()[1]?.init.body as string)).toEqual({ clear: ["backend_api_key"] });
  });

  it("locks where it runs while the model is awake, and offers Sleep now", async () => {
    const calls = withModels([row("alpha", { state: "awake" })], { "POST /api/models/alpha/sleep": () => ({ status: 204 }) });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Manage alpha" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Container address")).toBeDisabled();
    expect(within(dialog).getByLabelText("Priority number")).toBeEnabled();
    await user.click(within(dialog).getByRole("button", { name: /Sleep now/ }));
    await waitFor(() => { expect(calls.some((c) => c.key === "POST /api/models/alpha/sleep")).toBe(true); });
  });

  it("asks before removing, and says the container is left alone", async () => {
    const calls = withModels([row("alpha")], { "DELETE /api/models/alpha": () => ({ status: 204 }) });
    const user = userEvent.setup();
    render(<App />);
    await user.click(await screen.findByRole("button", { name: "Manage alpha" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /Remove/ }));
    expect(within(dialog).getByText(/keeps running, untouched/)).toBeInTheDocument();
    expect(calls.some((c) => c.key === "DELETE /api/models/alpha")).toBe(false); // not yet
    await user.click(within(dialog).getByRole("button", { name: "Keep it" }));
    expect(within(dialog).getByRole("button", { name: "Save changes" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: /Remove/ }));
    await user.click(within(dialog).getByRole("button", { name: "Yes, remove" }));
    await waitFor(() => { expect(calls.some((c) => c.key === "DELETE /api/models/alpha")).toBe(true); });
  });

  it("is not offered to viewers", async () => {
    visit("/models");
    mockApi({ "GET /api/auth/me": () => ({ body: { ...admin, role: "viewer" } }), "GET /api/status": () => ({ body: status }) });
    render(<App />);
    const nav = await screen.findByRole("navigation", { name: "Sections" });
    expect(within(nav).queryByRole("link", { name: "Models" })).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Add model/ })).not.toBeInTheDocument();
  });
});
