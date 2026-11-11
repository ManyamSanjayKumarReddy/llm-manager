import { useEffect, useState } from "react";

import { Pill } from "../../components/ui";

interface Frame {
  a: string;
  b: string;
  log: string;
}

// A short, looping story: a request wakes one model, then a request for the other swaps them.
const FRAMES: readonly Frame[] = [
  { a: "asleep", b: "asleep", log: "Waiting for a request" },
  { a: "waking", b: "asleep", log: "POST /v1/chat/completions  ·  gpt-oss-20b" },
  { a: "awake", b: "asleep", log: "Awake in 0.8 s  ·  answering" },
  { a: "awake", b: "asleep", log: "Streaming the reply" },
  { a: "sleeping", b: "waking", log: "POST /v1/chat/completions  ·  qwen3-vl-8b" },
  { a: "asleep", b: "awake", log: "qwen3-vl-8b took the GPU  ·  answering" },
  { a: "asleep", b: "awake", log: "No requests for a while" },
  { a: "asleep", b: "sleeping", log: "Idle, going to sleep" },
];
const STEP_MS = 1700;

/** A moving picture of what the router does. It is an illustration, not live data. */
export function HeroDemo() {
  const [i, setI] = useState(0);
  const reduced = typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  useEffect(() => {
    if (reduced) return undefined;
    const timer = setInterval(() => { setI((n) => (n + 1) % FRAMES.length); }, STEP_MS);
    return () => { clearInterval(timer); };
  }, [reduced]);

  const frame = FRAMES[reduced ? 2 : i] ?? FRAMES[0];
  if (!frame) return null;
  const gpuBusy = frame.a === "awake" || frame.b === "awake" || frame.a === "waking" || frame.b === "waking";
  return (
    <figure className="demo surface glow" aria-label="Illustration of models waking and sleeping">
      <div className="demo-bar">
        <span className="dots" aria-hidden="true"><i /><i /><i /></span>
        <figcaption className="mono">Illustration</figcaption>
      </div>
      <div className="demo-rows">
        <DemoRow name="gpt-oss-20b" gpus="GPU 0, 1" state={frame.a} />
        <DemoRow name="qwen3-vl-8b" gpus="GPU 0" state={frame.b} />
      </div>
      <div className="demo-gpu" aria-hidden="true">
        <span>GPU 0</span>
        <div className="bar"><i className={gpuBusy ? "on" : ""} /></div>
      </div>
      <p className="demo-log mono" aria-live="off"><span className="live-dot" /> {frame.log}</p>
    </figure>
  );
}

function DemoRow({ name, gpus, state }: { name: string; gpus: string; state: string }) {
  return (
    <div className={`demo-row ${state === "awake" ? "on" : ""}`}>
      <div>
        <strong>{name}</strong>
        <div className="dim mono small-text">{gpus}</div>
      </div>
      <Pill>{state}</Pill>
    </div>
  );
}
