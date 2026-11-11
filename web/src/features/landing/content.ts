// Everything the landing page says, in one place so the copy is easy to review and change.

export const TICKER = [
  "Wake on demand",
  "One endpoint",
  "Shared GPUs",
  "Sleep when idle",
  "OpenAI compatible",
  "Priority models",
  "Zero idle VRAM",
];

export const STEPS = [
  {
    no: "01",
    title: "Register your models",
    text: "Point the dashboard at the vLLM containers you already run, or copy the ready-made command to start a new one with sleep mode on.",
  },
  {
    no: "02",
    title: "Call one endpoint",
    text: "Programs use a single OpenAI-compatible address and an API key. Ask for any model by name; the right one is loaded for you.",
  },
  {
    no: "03",
    title: "Let them sleep",
    text: "When nobody is asking, models move their weights to CPU memory and free the GPU. The next request wakes them in about a second.",
  },
] as const;

export type IconName = "bolt" | "layers" | "gauge" | "plug" | "key" | "chart" | "shield" | "sliders";

export const FEATURES: readonly { icon: IconName; title: string; text: string }[] = [
  {
    icon: "bolt",
    title: "Wake on demand",
    text: "A request for a sleeping model wakes it and waits, so callers just see a slightly slower first answer.",
  },
  {
    icon: "layers",
    title: "Shared GPUs, no clashes",
    text: "Models that need the same GPU are never loaded together. The router drains one, sleeps it, then wakes the other.",
  },
  {
    icon: "gauge",
    title: "Priority models",
    text: "Mark a model as more important. When both are waiting for a GPU, it goes first and never gets interrupted mid-answer.",
  },
  {
    icon: "plug",
    title: "OpenAI compatible",
    text: "Existing clients and SDKs work by changing the base URL. Streaming responses pass straight through.",
  },
  {
    icon: "key",
    title: "Keys with limits",
    text: "Give each program its own key, restrict it to certain models, cap its requests per minute, and revoke it instantly.",
  },
  {
    icon: "chart",
    title: "History you can read",
    text: "Requests, errors, median and p95 latency, queue wait, and every wake and sleep, per model and per time window.",
  },
  {
    icon: "shield",
    title: "Secure by default",
    text: "No default account, hashed passwords, lockouts, per-request CSRF checks, a strict browser policy, and an audit trail.",
  },
  {
    icon: "sliders",
    title: "Managed from the browser",
    text: "Register, edit, sleep and remove models, and manage people and keys, without touching a config file.",
  },
];

export const FAQ = [
  {
    q: "Does it create or download models?",
    a: "No. It manages vLLM containers that you start yourself. The dashboard shows the exact docker command to start one correctly, with sleep mode enabled, and then registers it. Nothing here controls Docker.",
  },
  {
    q: "How fast is a wake-up?",
    a: "About a second for the model we measured (vLLM 0.10.1 on one RTX 4090, weights kept in CPU memory). Larger models and slower links take longer, and a model that has to swap with another one adds the time to put that one to sleep.",
  },
  {
    q: "What if two models need the same GPU?",
    a: "They never run together. A request for the sleeping one waits while the other finishes its running requests and is put to sleep. If you set priorities, the higher one goes first.",
  },
  {
    q: "What happens if nobody is using a model?",
    a: "Each model sleeps after its own idle time, whatever its priority. With no traffic, every model ends up asleep and the GPUs are free for other work.",
  },
  {
    q: "Are my prompts stored?",
    a: "No. The router records which model was called, the status, how long it took and how long it waited. Prompts and answers are never written down.",
  },
  {
    q: "Do the model containers need an API key?",
    a: "Only if you start them with one. Bind them to 127.0.0.1 and you can skip it. If you do use one, the router reads it from an environment variable on its own machine; it is never typed into the dashboard or stored in the database.",
  },
] as const;

export const PRIORITY_STEPS = [
  { who: "Summarizer", note: "priority 0", state: "awake", text: "is answering a request" },
  { who: "Support bot", note: "priority 5", state: "waiting", text: "asks for the same GPU" },
  { who: "Summarizer", note: "priority 0", state: "sleeping", text: "finishes, takes no new requests, steps aside" },
  { who: "Support bot", note: "priority 5", state: "awake", text: "wakes in about a second and answers" },
] as const;
