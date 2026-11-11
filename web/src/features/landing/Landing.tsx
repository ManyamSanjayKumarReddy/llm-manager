import { useState } from "react";

import { BRAND } from "../../brand";
import { Logo } from "../../components/Logo";
import { Marquee } from "../../components/Marquee";
import { Reveal } from "../../components/Reveal";
import { Deco } from "../../components/Stickers";
import { Pill } from "../../components/ui";
import { Link } from "../../router/Link";
import { FAQ, FEATURES, PRIORITY_STEPS, STEPS, TICKER, type IconName } from "./content";
import { HeroDemo } from "./HeroDemo";

const ICONS: Record<IconName, string> = {
  bolt: "M13 2 4 14h7l-1 8 9-12h-7z",
  layers: "m12 3 9 5-9 5-9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5",
  gauge: "M4 18a8 8 0 1 1 16 0M12 18l4-6",
  plug: "M9 3v5M15 3v5M6 8h12v3a6 6 0 0 1-12 0zM12 17v4",
  key: "M14 10a5 5 0 1 1-4.6-5M13 10l8 8M18 15l3 3M16 17l2 2",
  chart: "M4 20V4M4 20h16M8 16v-4M12 16V8M16 16v-6",
  shield: "M12 3 5 6v6c0 4.4 3 7.3 7 9 4-1.7 7-4.6 7-9V6z",
  sliders: "M4 7h10M18 7h2M4 17h2M10 17h10M14 5v4M8 15v4",
};

function Icon({ name }: { name: IconName }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

export function Landing({ signedIn }: { signedIn: boolean }) {
  return (
    <div className="landing">
      <div className="landing-glow" aria-hidden="true" />
      <Nav signedIn={signedIn} />
      <main>
        <Hero signedIn={signedIn} />
        <Marquee items={TICKER} />
        <Problem />
        <HowItWorks />
        <Features />
        <Priority />
        <Snippet />
        <Faq />
        <Closing signedIn={signedIn} />
      </main>
      <Footer signedIn={signedIn} />
    </div>
  );
}

/** The main call to action: sign in, or straight to the dashboard when already signed in. */
function Cta({ signedIn, big = false }: { signedIn: boolean; big?: boolean }) {
  return (
    <Link className={`btn primary ${big ? "big" : ""}`} to={signedIn ? "/overview" : "/signin"}>
      {signedIn ? "Open dashboard" : "Sign in"}
    </Link>
  );
}

function Nav({ signedIn }: { signedIn: boolean }) {
  return (
    <header className="landing-nav">
      <Logo to="/" />
      <nav aria-label="Page sections" className="landing-links">
        <a href="#how">How it works</a>
        <a href="#features">Features</a>
        <a href="#priority">Priority</a>
        <a href="#faq">FAQ</a>
      </nav>
      <Cta signedIn={signedIn} />
    </header>
  );
}

function Hero({ signedIn }: { signedIn: boolean }) {
  return (
    <section className="hero" aria-labelledby="hero-title">
      <div className="hero-copy">
        <span className="eyebrow"><span className="live-dot" /> vLLM sleep mode, managed</span>
        <h1 id="hero-title">
          Models that <em>wake</em> when you call.
        </h1>
        <p className="dim lead">{BRAND.description}</p>
        <div className="row hero-cta">
          <Cta signedIn={signedIn} big />
          <a className="btn big" href="#how">See how it works</a>
        </div>
        <ul className="facts-row">
          <li><strong>≈ 1 s</strong><span>to wake a sleeping model</span></li>
          <li><strong>≈ 1 GB</strong><span>of GPU memory while asleep</span></li>
          <li><strong>1</strong><span>endpoint for every model</span></li>
        </ul>
        <p className="fine dim">Measured in our cloud test: vLLM 0.10.1, one RTX 4090. Yours depends on the model and the GPU.</p>
      </div>
      <div className="hero-visual">
        <HeroDemo />
        <div className="hero-stickers" aria-hidden="true">
          <Deco name="metal" size={92} rotate={-10} className="s1" />
          <Deco name="star" size={84} delay={1.4} rotate={8} className="s2" />
          <Deco name="pill" size={96} delay={0.7} rotate={-4} className="s3" />
        </div>
      </div>
    </section>
  );
}

function Problem() {
  return (
    <section className="section split" aria-labelledby="problem-title">
      <Reveal>
        <span className="eyebrow">The problem</span>
        <h2 id="problem-title" className="display">One busy client shouldn’t hold your <em>GPUs</em> hostage.</h2>
        <p className="dim lead">A model that stays loaded all day keeps its GPU memory even when nobody is asking. Other projects on the same machine are left with whatever is left over.</p>
      </Reveal>
      <Reveal delay={120}>
        <div className="compare">
          <div className="surface compare-card">
            <Pill tone="bad">before</Pill>
            <h3>Always loaded</h3>
            <p className="dim">Two models, two GPUs, both full around the clock. Everything else waits for a free card.</p>
            <div className="meter-row"><span>GPU 0</span><div className="bar"><i className="full" /></div></div>
            <div className="meter-row"><span>GPU 1</span><div className="bar"><i className="full" /></div></div>
          </div>
          <div className="surface compare-card glow">
            <Pill tone="ok">{`with ${BRAND.name}`}</Pill>
            <h3>Loaded when asked</h3>
            <p className="dim">Models sleep when idle and wake on the next request. The GPUs are free the rest of the time.</p>
            <div className="meter-row"><span>GPU 0</span><div className="bar"><i className="low" /></div></div>
            <div className="meter-row"><span>GPU 1</span><div className="bar"><i className="low" /></div></div>
          </div>
        </div>
      </Reveal>
    </section>
  );
}

function HowItWorks() {
  return (
    <section className="section" id="how" aria-labelledby="how-title">
      <Reveal>
        <span className="eyebrow">How it works</span>
        <h2 id="how-title" className="display">Three steps, then <em>forget</em> about it.</h2>
      </Reveal>
      <div className="steps">
        {STEPS.map((step, i) => (
          <Reveal key={step.no} delay={i * 100}>
            <article className="surface step-card">
              <span className="big-no mono">{step.no}</span>
              <h3>{step.title}</h3>
              <p className="dim">{step.text}</p>
            </article>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

function Features() {
  return (
    <section className="section" id="features" aria-labelledby="features-title">
      <Reveal>
        <span className="eyebrow">What you get</span>
        <h2 id="features-title" className="display">Everything around the <em>wake-up</em>, too.</h2>
      </Reveal>
      <div className="feature-grid">
        {FEATURES.map((f, i) => (
          <Reveal key={f.title} delay={(i % 4) * 70}>
            <article className="surface feature">
              <span className="icon-tile"><Icon name={f.icon} /></span>
              <h3>{f.title}</h3>
              <p className="dim">{f.text}</p>
            </article>
          </Reveal>
        ))}
      </div>
    </section>
  );
}

function Priority() {
  return (
    <section className="section split" id="priority" aria-labelledby="priority-title">
      <Reveal>
        <span className="eyebrow">Priority</span>
        <h2 id="priority-title" className="display">When two models want one GPU, the <em>important</em> one goes first.</h2>
        <p className="dim lead">Give each model a number. If both have requests waiting, the higher one is next. The other finishes what it is already answering, never mid-sentence, and steps aside.</p>
        <p className="dim">A lower-priority model never interrupts a busy higher one, and models with equal priority simply take turns.</p>
      </Reveal>
      <Reveal delay={120}>
        <ol className="timeline-demo surface">
          {PRIORITY_STEPS.map((s, i) => (
            <li key={i}>
              <span className="tl-no mono">{i + 1}</span>
              <div>
                <strong>{s.who}</strong> <span className="dim mono small-text">{s.note}</span>
                <div className="dim">{s.text}</div>
              </div>
              <Pill>{s.state}</Pill>
            </li>
          ))}
        </ol>
      </Reveal>
    </section>
  );
}

const CURL = (origin: string) => `curl ${origin}/v1/chat/completions \\
  -H "Authorization: Bearer $YOUR_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "gpt-oss-20b",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`;

const PYTHON = (origin: string) => `from openai import OpenAI

client = OpenAI(base_url="${origin}/v1", api_key="YOUR_API_KEY")
reply = client.chat.completions.create(
    model="gpt-oss-20b",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(reply.choices[0].message.content)`;

function Snippet() {
  const [tab, setTab] = useState<"curl" | "python">("curl");
  const [copied, setCopied] = useState(false);
  const origin = window.location.origin;
  const code = tab === "curl" ? CURL(origin) : PYTHON(origin);

  async function copy() {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch {
      // clipboard blocked: the text stays selectable
    }
  }
  return (
    <section className="section split" aria-labelledby="snippet-title">
      <Reveal>
        <span className="eyebrow">Drop-in</span>
        <h2 id="snippet-title" className="display">Same API. Different <em>base URL</em>.</h2>
        <p className="dim lead">Any tool that speaks the OpenAI API works. If the model you ask for is asleep, the request waits for it to wake, then streams the answer as usual.</p>
      </Reveal>
      <Reveal delay={120}>
        <div className="code-card surface">
          <div className="code-tabs" role="tablist" aria-label="Language">
            {(["curl", "python"] as const).map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => { setTab(t); }}>{t === "curl" ? "curl" : "Python"}</button>
            ))}
            <button type="button" className="btn small copy-code" onClick={() => void copy()}>{copied ? "Copied" : "Copy"}</button>
          </div>
          <pre className="command" aria-label="Example request"><code>{code}</code></pre>
        </div>
      </Reveal>
    </section>
  );
}

function Faq() {
  return (
    <section className="section" id="faq" aria-labelledby="faq-title">
      <Reveal>
        <span className="eyebrow">FAQ</span>
        <h2 id="faq-title" className="display">Straight <em>answers</em>.</h2>
      </Reveal>
      <Reveal delay={80}>
        <div className="faq">
          {FAQ.map((item) => (
            <details key={item.q}>
              <summary>{item.q}</summary>
              <p className="dim">{item.a}</p>
            </details>
          ))}
        </div>
      </Reveal>
    </section>
  );
}

function Closing({ signedIn }: { signedIn: boolean }) {
  return (
    <section className="closing" aria-labelledby="closing-title">
      <Reveal>
        <div className="closing-card surface glow">
          <div className="closing-stickers" aria-hidden="true">
            <Deco name="rocket" size={110} rotate={-6} />
            <Deco name="sparkles" size={90} delay={1.2} rotate={8} />
          </div>
          <h2 id="closing-title" className="display">Give your GPUs a <em>rest</em>.</h2>
          <p className="dim lead">{signedIn ? "Register your models and watch them wake and sleep." : "Sign in to register your models and watch them wake and sleep."}</p>
          <Cta signedIn={signedIn} big />
        </div>
      </Reveal>
    </section>
  );
}

function Footer({ signedIn }: { signedIn: boolean }) {
  return (
    <footer className="landing-footer">
      <Logo size={22} to="/" />
      <nav aria-label="Footer">
        <a href="#how">How it works</a>
        <a href="#features">Features</a>
        <a href="#faq">FAQ</a>
        <Link to={signedIn ? "/overview" : "/signin"}>{signedIn ? "Dashboard" : "Sign in"}</Link>
      </nav>
      <span className="mono dim small-text">© {new Date().getFullYear()} {BRAND.name}</span>
    </footer>
  );
}
