// Everything the landing page says, in one place so the copy is easy to review and change.

export const TICKER = [
  "Wake on demand",
  "One endpoint",
  "One-command install",
  "No open ports",
  "Shared GPUs",
  "Sleep when idle",
  "Containers from the browser",
  "OpenAI compatible",
  "Priority models",
  "Zero idle VRAM",
];

export const STEPS = [
  {
    no: "01",
    title: "Connect a GPU server",
    text: "Run one command on the machine. Its agent connects out to Wakeful, so there is no open port, certificate or firewall rule to set up.",
  },
  {
    no: "02",
    title: "Add your models",
    text: "Create a vLLM container from the dashboard (the image downloads itself, sleep mode is already on), or register one you already run.",
  },
  {
    no: "03",
    title: "Call one endpoint",
    text: "Programs use a single OpenAI-compatible address and an API key. A sleeping model wakes in about a second, and idle ones go back to sleep on their own.",
  },
] as const;

export type IconName = "bolt" | "layers" | "gauge" | "plug" | "key" | "chart" | "shield" | "sliders" | "server" | "box" | "pulse";

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
    icon: "server",
    title: "Any server, nothing exposed",
    text: "Add as many GPU servers as you like. Each one is connected with a single command and dials out, so it can sit behind any firewall.",
  },
  {
    icon: "box",
    title: "Containers from the browser",
    text: "Start, stop, restart, read the logs of and create vLLM containers on every server, and see its GPU, memory and disk, without logging in to it.",
  },
  {
    icon: "pulse",
    title: "Know why it is not ready",
    text: "A model that is still loading says “starting”. One that failed says why in plain words, for example not enough free GPU memory, read from its log.",
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
];

export const CONNECT_STEPS = [
  { title: "Add the server", text: "Give it a name and say how many GPUs it has. Press “Connect agent” and a one-time token is created." },
  { title: "Paste one command", text: "Run it on the GPU machine. It needs Docker and the NVIDIA container toolkit, and nothing else." },
  { title: "Watch it connect", text: "The dashboard shows the server as connected within seconds, with its GPUs, memory and disk." },
] as const;

export const FAQ = [
  {
    q: "Does it create or download models?",
    a: "On a server with the Wakeful agent, yes: choose “Create and register” and Wakeful starts a vLLM container there (the vLLM image and the model files download on first use) and registers it. Without an agent it shows the exact docker command to start one yourself, with sleep mode enabled. The agent only manages containers it created.",
  },
  {
    q: "Do I have to open a port on my GPU server?",
    a: "No. The agent connects out to Wakeful over an encrypted WebSocket and keeps it open, so the server needs no open port, certificate or web-server rule. Wakeful sends its commands, and your programs' requests, back down that connection.",
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
