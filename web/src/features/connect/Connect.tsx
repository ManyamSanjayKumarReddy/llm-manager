import { useState } from "react";

import { api } from "../../api/client";
import { CopyButton } from "../../components/CopyButton";
import { Alert, PageHead, Pill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { useCopy } from "../../hooks/useCopy";
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

/** What a program needs to call Wakeful: the base URL, an API key, and a model name. */
export function Connect() {
  const me = useUser();
  const status = useAsync(() => api.status(), 10_000);
  const base = `${window.location.origin}/v1`;
  const models = Object.entries(status.data?.models ?? {});
  const model = models[0]?.[0] ?? "your-model-name";
  const [language, setLanguage] = useState<Language>("curl");
  const [copied, copy] = useCopy();
  const code = SNIPPETS[language](base, model);

  return (
    <div className="page">
      <PageHead eyebrow="Developers" title="Connect">
        What a program needs to use your models. It works with any tool that speaks the OpenAI API.
      </PageHead>
      <Alert notice={status.error ? { kind: "error", text: status.error } : undefined} />

      <section className="surface stack">
        <div className="section-title"><h2>Connection</h2></div>
        <div className="table-wrap">
          <table className="cards">
            <thead><tr><th>Setting</th><th>Value</th><th /></tr></thead>
            <tbody>
              <tr>
                <td className="primary"><strong>Base URL</strong></td>
                <td data-label="Value"><code>{base}</code></td>
                <td data-label=""><CopyButton value={base} label="Base URL" /></td>
              </tr>
              <tr>
                <td className="primary"><strong>API key</strong></td>
                <td data-label="Value"><code>Authorization: Bearer {KEY}</code></td>
                <td data-label="">
                  {me.role === "admin" ? <Link className="btn small" to="/api-keys">Create a key</Link> : <span className="dim small-text">Ask an admin</span>}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section className="surface stack">
        <div className="section-title"><h2>Models</h2><span className="count">{models.length} available</span></div>
        {status.data && models.length === 0 ? <p className="no-match">No models are registered yet.</p> : null}
        <div className="table-wrap" hidden={models.length === 0}>
          <table className="cards">
            <thead><tr><th>Model name</th><th>State</th><th /></tr></thead>
            <tbody>
              {models.map(([name, m]) => (
                <tr key={name}>
                  <td className="primary"><code>{name}</code></td>
                  <td data-label="State"><Pill>{m.state}</Pill></td>
                  <td data-label=""><CopyButton value={name} label={name} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="hint dim">Use the name as the <code>model</code> value. A sleeping model wakes on your request, so the first answer is a few seconds slower.</p>
      </section>

      <section className="surface stack">
        <div className="section-title"><h2>Example</h2></div>
        <div className="code-tabs" role="tablist" aria-label="Language">
          {LANGUAGES.map(([value, label]) => (
            <button key={value} type="button" role="tab" aria-selected={language === value} onClick={() => { setLanguage(value); }}>{label}</button>
          ))}
          <button type="button" className="btn small copy-code" onClick={() => void copy(code)}>{copied ? "Copied" : "Copy"}</button>
        </div>
        <pre className="command" aria-label="Example request"><code>{code}</code></pre>
      </section>

      <section className="surface stack">
        <div className="section-title"><h2>Good to know</h2></div>
        <ul className="notes">
          <li>On <code>503</code> or <code>429</code>, wait the <code>Retry-After</code> seconds and try again.</li>
          <li><code>403</code> means your key is not allowed to use that model.</li>
          <li><code>GET {base}/models</code> lists the models your key may use.</li>
        </ul>
      </section>
    </div>
  );
}
