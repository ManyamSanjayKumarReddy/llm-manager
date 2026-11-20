// Builds the `docker run` command that starts a vLLM container the router can manage.
//
// It starts from the command people already run by hand (GPU, name, restart policy, cache, key,
// token, port, tool calling, ...) and adds only what wake-on-demand needs, marked as such:
//   -e VLLM_SERVER_DEV_MODE=1   exposes /sleep, /wake_up and /is_sleeping
//   --enable-sleep-mode         lets the model release its GPU memory
//   --tensor-parallel-size N    when the model is spread over several GPUs
//
// Every value is checked first: the text is meant to be pasted into a shell.

export interface VllmParams {
  containerName: string;
  model: string;
  port: number;
  gpus: number[];
  imageTag: string;
  cacheDir: string;
  apiKey: string;
  hfToken: string;
  maxModelLen: number;
  maxNumSeqs: number;
  memoryShare: number;
  allowLongContext: boolean;
  toolCalling: boolean;
  toolParser: string;
  autoRestart: boolean;
  extraArgs: string;
}

/** One line of the command, plus how to present it. */
export interface CommandLine {
  text: string;
  /** Added for wake-on-demand (not part of an ordinary vLLM command). */
  router?: boolean;
  /** Contains a secret; shown masked unless the reader asks to see it. */
  secret?: boolean;
  /** A short reason shown next to the line (never copied). */
  note?: string;
}

const NAME = /^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$/;
const HF_MODEL = /^[A-Za-z0-9][A-Za-z0-9._-]*(\/[A-Za-z0-9][A-Za-z0-9._-]*)?$/;
/** The vLLM build whose /sleep aborts running requests (backend setting VLLM_IMAGE has the same default). */
export const DEFAULT_VLLM_IMAGE = "mockdigilabs/vllm-openai-abortsleep-0.10.1:latest";

const TAG = /^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
// A full image reference such as vllm-openai:v0.10.1-abortsleep (a locally built image).
const IMAGE_REF = /^[a-z0-9][a-z0-9._/-]*:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/;
const PATH = /^[~/][A-Za-z0-9_./~-]*$/;
const PARSER = /^[a-z0-9_]{1,40}$/;
const EXTRA = /^[A-Za-z0-9_.:/=, @+-]{0,300}$/;
const SAFE_WORD = /^[A-Za-z0-9._~+/=:-]+$/;
const MAX_SECRET = 512;

/** What is wrong with the inputs, one message per problem; empty when the command is safe to show. */
export function vllmProblems(p: VllmParams): string[] {
  const problems: string[] = [];
  if (!HF_MODEL.test(p.model)) problems.push("Model: a Hugging Face id such as openai/gpt-oss-20b.");
  if (!NAME.test(p.containerName)) problems.push("Name: letters, digits, dot, dash or underscore.");
  if (!Number.isInteger(p.port) || p.port < 1024 || p.port > 65535) problems.push("Port: a number from 1024 to 65535.");
  if (p.gpus.length === 0) problems.push("Choose at least one GPU.");
  if (!TAG.test(p.imageTag) && !IMAGE_REF.test(p.imageTag)) problems.push("vLLM image: a full image such as mockdigilabs/vllm-openai-abortsleep-0.10.1:latest, or just a tag such as v0.10.1.");
  if (!PATH.test(p.cacheDir)) problems.push("Model cache folder: a path such as ~/.cache/huggingface (no spaces).");
  if (p.apiKey !== "" && !isSecretText(p.apiKey)) problems.push("API key: one line, no spaces, up to 512 characters.");
  if (p.hfToken !== "" && !isSecretText(p.hfToken)) problems.push("Hugging Face token: one line, no spaces.");
  if (!Number.isInteger(p.maxModelLen) || p.maxModelLen < 256) problems.push("Context length: a whole number, at least 256.");
  if (!Number.isInteger(p.maxNumSeqs) || p.maxNumSeqs < 1) problems.push("Parallel requests: a whole number, at least 1.");
  if (!(p.memoryShare >= 0.1 && p.memoryShare <= 0.98)) problems.push("GPU memory share: between 10% and 98%.");
  if (p.toolCalling && !PARSER.test(p.toolParser)) problems.push("Tool-call parser: lowercase letters, digits or underscore, such as openai.");
  if (!EXTRA.test(p.extraArgs)) problems.push("Extra arguments: letters, digits and . : / = , @ + - only. Quotes and shell characters are not allowed here.");
  return problems;
}

/** The image to run: a bare tag means the official vLLM image, anything with a colon is used as given. */
export function imageRef(imageTag: string): string {
  return imageTag.includes(":") ? imageTag : `vllm/vllm-openai:${imageTag}`;
}

function isSecretText(value: string): boolean {
  return value.length <= MAX_SECRET && /^[\x21-\x7e]+$/.test(value);
}

/** A value for a shell command: left plain when harmless, otherwise single-quoted. */
function word(value: string): string {
  return SAFE_WORD.test(value) ? value : `'${value.replaceAll("'", `'\\''`)}'`;
}

/** NAME=value as one shell word: in double quotes like the usual command when harmless, else single-quoted. */
function envArg(name: string, value: string): string {
  return SAFE_WORD.test(value) || value === "" ? `"${name}=${value}"` : word(`${name}=${value}`);
}

export function maskSecret(value: string): string {
  return value.length <= 4 ? "••••" : `${value.slice(0, 3)}••••••••`;
}

/** The command as lines, with secrets masked unless ``reveal`` is set. Null while the inputs are not valid. */
export function buildVllmLines(p: VllmParams, reveal = false): CommandLine[] | null {
  if (vllmProblems(p).length > 0) return null;
  const gpus = [...p.gpus].sort((a, b) => a - b);
  const show = (secret: string) => (reveal ? word(secret) : maskSecret(secret));
  const lines: CommandLine[] = [
    { text: "docker run -d" },
    { text: `--gpus '"device=${gpus.join(",")}"'` },
    { text: `--name ${p.containerName}` },
    ...(p.autoRestart ? [{ text: "--restart unless-stopped" }] : []),
    { text: `-v ${p.cacheDir}:/root/.cache/huggingface`, note: "downloaded models are kept here" },
    ...(p.apiKey ? [{ text: `-e VLLM_API_KEY=${show(p.apiKey)}`, secret: true, note: "the same key you store in Wakeful" }] : []),
    ...(p.allowLongContext ? [{ text: "-e VLLM_ALLOW_LONG_MAX_MODEL_LEN=1" }] : []),
    { text: "-e VLLM_SERVER_DEV_MODE=1", router: true, note: "exposes /sleep, /wake_up and /is_sleeping" },
    { text: `--env ${reveal || !p.hfToken ? envArg("HUGGING_FACE_HUB_TOKEN", p.hfToken) : `"HUGGING_FACE_HUB_TOKEN=${maskSecret(p.hfToken)}"`}`, secret: p.hfToken !== "", note: p.hfToken ? undefined : "paste your token here if the model is gated" },
    { text: `-p 127.0.0.1:${p.port}:8000`, note: "reachable from this machine only" },
    { text: "--ipc=host" },
    { text: imageRef(p.imageTag) },
    { text: `--model ${p.model}` },
    ...(gpus.length > 1 ? [{ text: `--tensor-parallel-size ${gpus.length}`, router: true, note: `one model split over ${gpus.length} GPUs` }] : []),
    { text: "--enable-sleep-mode", router: true, note: "lets the model give its GPU memory back" },
    { text: `--max-model-len ${p.maxModelLen}` },
    { text: `--max-num-seqs ${p.maxNumSeqs}` },
    { text: `--gpu-memory-utilization ${p.memoryShare}` },
    { text: "--tokenizer-mode auto" },
    ...(p.toolCalling ? [{ text: "--enable-auto-tool-choice" }, { text: `--tool-call-parser ${p.toolParser}` }] : []),
    ...(p.extraArgs.trim() ? [{ text: p.extraArgs.trim().replace(/\s+/g, " ") }] : []),
    { text: "--host 0.0.0.0 --port 8000", note: "inside the container" },
  ];
  return lines;
}

/** The command to copy, with the real secrets in it. */
export function buildVllmCommand(p: VllmParams): string | null {
  const lines = buildVllmLines(p, true);
  return lines ? lines.map((l) => l.text).join(" \\\n  ") : null;
}

/** A router name from a Hugging Face id: "openai/gpt-oss-20b" becomes "gpt-oss-20b". */
export function suggestName(model: string): string {
  const last = model.split("/").pop() ?? "";
  return last
    .toLowerCase()
    .replace(/[^a-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

/** The name vLLM will serve: `--served-model-name` if given in the extra arguments, else the model id. */
export function servedNameFor(model: string, extraArgs: string): string {
  const match = /--served-model-name[ =]([^\s]+)/.exec(extraArgs);
  return match?.[1] ?? model;
}

/** A random API key in the usual `sk-` shape (192 bits). */
export function generateApiKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return `sk-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
}

export const TOOL_PARSERS = ["openai", "hermes", "llama3_json", "mistral", "pythonic", "granite", "internlm"] as const;
