import { useState } from "react";

import { api } from "../../api/client";
import { Icon } from "../../components/Icon";
import { Reveal } from "../../components/Reveal";
import { Alert, PageHead, Pill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { Link } from "../../router/Link";
import { useUser } from "../auth/context";

const KEY = "<API_KEY>";

const SNIPPETS = {
  curl: (base: string, model: string) => `curl ${base}/chat/completions \\
  -H "Authorization: Bearer ${KEY}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "${model}",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'`,
  python: (base: string, model: string) => `from openai import OpenAI

client = OpenAI(base_url="${base}", api_key="${KEY}")
reply = client.chat.completions.create(
    model="${model}",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(reply.choices[0].message.content)`,
  javascript: (base: string, model: string) => `import OpenAI from "openai";

const client = new OpenAI({ baseURL: "${base}", apiKey: "${KEY}" });
const reply = await client.chat.completions.create({
  model: "${model}",
  messages: [{ role: "user", content: "Hello!" }],
});
console.log(reply.choices[0].message.content);`,
} as const;

type Language = keyof typeof SNIPPETS;
const LANGUAGES: readonly (readonly [Language, string])[] = [["curl", "curl"], ["python", "Python"], ["javascript", "JavaScript"]];

/** Copies text and says so for two seconds. Browsers may block the clipboard: the text stays selectable. */
function useCopy(): [boolean, (text: string) => Promise<void>] {
  const [copied, setCopied] = useState(false);
  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => { setCopied(false); }, 2000);
    } catch {
      // clipboard blocked: nothing to do
    }
  }
  return [copied, copy];
}

function CopyRow({ label, value, hint }: { label: string; value: string; hint?: string }) {
  const [copied, copy] = useCopy();
  return (
    <div className="connect-row">
      <div className="connect-label">
        <span>{label}</span>
        {hint ? <span className="dim small-text">{hint}</span> : null}
      </div>
      <code className="connect-value">{value}</code>
      <button type="button" className="btn small" onClick={() => void copy(value)} aria-label={`Copy ${label}`}>
        <Icon name="copy" size={14} /> {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** What a program needs to call Wakeful: the base URL, an API key, and a model name. */
export function Connect() {
  const me = useUser();
  const status = useAsync(() => api.status(), 10_000);
  const base = `${window.location.origin}/v1`;
  const models = Object.entries(status.data?.models ?? {});
  const [chosen, setChosen] = useState<string>();
  const model = chosen && models.some(([n]) => n === chosen) ? chosen : (models[0]?.[0] ?? "your-model-name");
  const [language, setLanguage] = useState<Language>("curl");
  const [copied, copy] = useCopy();
  const code = SNIPPETS[language](base, model);

  return (
    <div className="page">
      <PageHead eyebrow="Developers" title="Connect">
        Everything a program needs to use your models: an address, a key and a model name. It works with any tool that speaks the OpenAI API.
      </PageHead>
      <Alert notice={status.error ? { kind: "error", text: status.error } : undefined} />

      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>The three things you need</h2></div>
          <CopyRow label="Base URL" value={base} hint="Put this where a tool asks for the OpenAI base URL." />
          <div className="connect-row">
            <div className="connect-label">
              <span>API key</span>
              <span className="dim small-text">A key is shown only once, when it is created.</span>
            </div>
            <code className="connect-value">{KEY}</code>
            {me.role === "admin" ? <Link className="btn small primary" to="/api-keys">Create a key</Link> : <span className="dim small-text">Ask an admin</span>}
          </div>
          <p className="hint dim">Send it as <code>Authorization: Bearer {KEY}</code>. A key can be limited to certain models and a number of requests per minute. If a model you expect is refused with 403, the key is not allowed to use it.</p>
        </section>
      </Reveal>

      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>Model name</h2><span className="count">{models.length} available</span></div>
          {status.data && models.length === 0 ? <p className="no-match">No models are registered yet.</p> : null}
          {models.map(([name, m]) => (
            <ModelRow key={name} name={name} state={m.state} active={name === model} onPick={() => { setChosen(name); }} />
          ))}
          <p className="hint dim">Use the name exactly as shown in the <code>model</code> field. A model that is asleep is woken by your request, so the first answer takes a few seconds longer.</p>
        </section>
      </Reveal>

      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>Try it</h2><span className="count">using {model}</span></div>
          <div className="code-card">
            <div className="code-tabs" role="tablist" aria-label="Language">
              {LANGUAGES.map(([value, label]) => (
                <button key={value} type="button" role="tab" aria-selected={language === value} onClick={() => { setLanguage(value); }}>{label}</button>
              ))}
              <button type="button" className="btn small copy-code" onClick={() => void copy(code)}>{copied ? "Copied" : "Copy"}</button>
            </div>
            <pre className="command" aria-label="Example request"><code>{code}</code></pre>
          </div>
          <p className="hint dim">Replace <code>{KEY}</code> with your key. Add <code>"stream": true</code> for streamed answers.</p>
        </section>
      </Reveal>

      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>Good to know</h2></div>
          <ul className="notes">
            <li><strong>Retry on 503 and 429.</strong> 503 means the model is waking or another one is using its GPU. Wait the number of seconds in the <code>Retry-After</code> header and try again. 429 means your key reached its per-minute limit.</li>
            <li><strong>See the list from code:</strong> <code>GET {base}/models</code> returns the models your key may use, without waking anything.</li>
            <li><strong>Usage is tracked per key.</strong> Prompt and completion tokens appear on the Usage page, so give each program its own key.</li>
          </ul>
        </section>
      </Reveal>
    </div>
  );
}

function ModelRow({ name, state, active, onPick }: { name: string; state: string; active: boolean; onPick: () => void }) {
  const [copied, copy] = useCopy();
  return (
    <div className={`connect-row ${active ? "picked" : ""}`}>
      <div className="connect-label">
        <button type="button" className="row-open" onClick={onPick} aria-pressed={active} aria-label={`Use ${name} in the example`}>
          <strong>{name}</strong>
        </button>
        <Pill>{state}</Pill>
      </div>
      <code className="connect-value">{name}</code>
      <button type="button" className="btn small" onClick={() => void copy(name)} aria-label={`Copy ${name}`}>
        <Icon name="copy" size={14} /> {copied ? "Copied" : "Copy"}
      </button>
    </div>
  );
}
