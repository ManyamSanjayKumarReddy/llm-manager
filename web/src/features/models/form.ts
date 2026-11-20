import type { ManagedModel } from "../../api/types";
import { DEFAULT_VLLM_IMAGE, suggestName, vllmProblems, type VllmParams } from "../../lib/vllmCommand";

/** Everything typed into the Add model popup. Numbers stay as text until they are used. */
export interface Form {
  model: string;
  name: string;
  nameEdited: boolean;
  port: string;
  /** The registered server the container runs on. */
  server: string;
  gpus: number[];
  apiKey: string;
  hfToken: string;
  maxModelLen: string;
  maxNumSeqs: string;
  memoryShare: string;
  allowLongContext: boolean;
  toolCalling: boolean;
  toolParser: string;
  parserEdited: boolean;
  priority: string;
  idle: string;
  imageTag: string;
  cacheDir: string;
  autoRestart: boolean;
  extraArgs: string;
  url: string;
  urlEdited: boolean;
}

// The defaults are the command people already run by hand.
export const DEFAULTS: Form = {
  model: "",
  name: "",
  nameEdited: false,
  port: "8025",
  server: "",
  gpus: [0],
  apiKey: "",
  hfToken: "",
  maxModelLen: "32768",
  maxNumSeqs: "4",
  memoryShare: "0.9",
  allowLongContext: true,
  toolCalling: true,
  toolParser: "openai",
  parserEdited: false,
  priority: "0",
  idle: "10",
  imageTag: DEFAULT_VLLM_IMAGE,
  cacheDir: "~/.cache/huggingface",
  autoRestart: true,
  extraArgs: "",
  url: "",
  urlEdited: false,
};

export const EXAMPLES = ["openai/gpt-oss-20b", "Qwen/Qwen3-VL-8B-Instruct-FP8"] as const;
export const CONTEXTS = [["8k", "8192"], ["16k", "16384"], ["32k", "32768"], ["64k", "65536"], ["128k", "131072"]] as const;
export const PRIORITIES = [["Normal", "0"], ["High", "5"], ["Highest", "10"]] as const;
export const IDLES = [["5 min", "5"], ["10 min", "10"], ["30 min", "30"], ["1 hour", "60"]] as const;

/** The tool-call parser that usually goes with a model family. */
export function suggestParser(model: string): string | undefined {
  if (/gpt-oss/i.test(model)) return "openai";
  if (/qwen/i.test(model)) return "hermes";
  if (/llama/i.test(model)) return "llama3_json";
  if (/mistral/i.test(model)) return "mistral";
  return undefined;
}

export const nameOf = (f: Form): string => (f.nameEdited ? f.name : suggestName(f.model));
export const urlOf = (f: Form): string => (f.urlEdited ? f.url : `http://127.0.0.1:${f.port}`);

export function paramsOf(f: Form): VllmParams {
  return {
    containerName: nameOf(f),
    model: f.model,
    port: Number(f.port),
    gpus: f.gpus,
    imageTag: f.imageTag,
    cacheDir: f.cacheDir,
    apiKey: f.apiKey,
    hfToken: f.hfToken,
    maxModelLen: Number(f.maxModelLen),
    maxNumSeqs: Number(f.maxNumSeqs),
    memoryShare: Number(f.memoryShare),
    allowLongContext: f.allowLongContext,
    toolCalling: f.toolCalling,
    toolParser: f.toolParser,
    autoRestart: f.autoRestart,
    extraArgs: f.extraArgs,
  };
}

/** The steps of the Add model popup, in order. */
export const STEP_NAMES = ["Model", "Access", "Performance", "Sleep", "Advanced", "Run"] as const;
export const LAST_STEP = STEP_NAMES.length - 1;

// Which step a problem message belongs to (by how it starts); anything else belongs to Advanced.
const STEP_OF: readonly RegExp[] = [
  /^(Model|Name|Port|Choose|A model named|Enter the)/,
  /^(API key|Hugging Face token)/,
  /^(Context|Parallel|GPU memory|Tool-call)/,
  /^(Sleep after|Priority)/,
];

/** What is wrong with the form, as one list of messages per step. */
export function problemsOf(f: Form, registered: ManagedModel[]): string[][] {
  const perStep: string[][] = STEP_NAMES.map(() => []);
  if (f.model === "") {
    perStep[0]?.push("Enter the Hugging Face model to continue.");
    return perStep;
  }
  const all = vllmProblems(paramsOf(f));
  const name = nameOf(f);
  if (registered.some((m) => m.name === name)) all.push(`A model named “${name}” is already registered. Choose another name.`);
  if (f.server === "") all.push("Choose the server this model runs on.");
  const taken = registered.find((m) => m.server === f.server && new URL(m.url).port === f.port);
  if (taken) all.push(`Port ${f.port} is already used by “${taken.name}” on ${taken.server}.`);
  if (!/^https?:\/\/\S+$/.test(urlOf(f))) all.push("Container address: it must start with http:// or https://.");
  if (!(Number(f.idle) > 0)) all.push("Sleep after idle: a number of minutes above 0.");
  const priority = Number(f.priority);
  if (!Number.isInteger(priority) || priority < 0 || priority > 100) all.push("Priority: a whole number from 0 to 100.");
  for (const message of all) {
    const index = STEP_OF.findIndex((re) => re.test(message));
    perStep[index === -1 ? 4 : index]?.push(message);
  }
  return perStep;
}
