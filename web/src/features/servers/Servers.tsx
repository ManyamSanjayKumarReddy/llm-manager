import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { Server } from "../../api/types";
import { Reveal } from "../../components/Reveal";
import { Field, PageHead } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { Link } from "../../router/Link";
import { useToast } from "../toast/context";

/** The machines with GPUs. Models are placed on one of them, so GPU numbers stay unambiguous. */
export function Servers() {
  const toast = useToast();
  const servers = useAsync(() => api.servers(), undefined, 0);

  /** Run a change, show the outcome, refresh the list. Returns whether it worked. */
  async function act(change: () => Promise<unknown>, success: string): Promise<boolean> {
    try {
      await change();
      toast.show("success", success);
      await servers.reload();
      return true;
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
      return false;
    }
  }

  const items = servers.data ?? [];
  return (
    <div className="page">
      <PageHead eyebrow="Fleet" title="Servers">
        The GPU boxes you run models on, for example a 2× RTX 4060 Ti machine. Register each one here, then choose it when you add a model. Models only compete for a GPU when they are on the same server.
      </PageHead>
      <Reveal><NewServerForm onCreate={(s) => act(() => api.addServer(s), `Server “${s.name}” added.`)} /></Reveal>
      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>Registered servers</h2><span className="count">{items.length} total</span></div>
          {servers.error ? <div className="alert error" role="alert">{servers.error}</div> : null}
          {!servers.loading && items.length === 0 ? <p className="no-match">No servers yet. Add the first one above.</p> : null}
          <div className="table-wrap" hidden={items.length === 0}>
            <table className="cards">
              <thead><tr><th>Server</th><th>GPU type</th><th>GPUs</th><th>Models</th><th /></tr></thead>
              <tbody>
                {items.map((server) => (
                  <ServerRow
                    key={`${server.name}-${server.gpu_count}-${server.gpu_type ?? ""}`}
                    server={server}
                    onChange={(changes) => act(() => api.updateServer(server.name, changes), `${server.name} updated.`)}
                    onRemove={() => act(() => api.removeServer(server.name), `${server.name} removed.`)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {items.length > 0 ? <p className="hint dim">Add models on the <Link to="/models">Models</Link> page.</p> : null}
        </section>
      </Reveal>
    </div>
  );
}

function ServerRow({ server, onChange, onRemove }: { server: Server; onChange: (changes: { gpu_count?: number; gpu_type?: string }) => Promise<boolean>; onRemove: () => Promise<boolean> }) {
  const [count, setCount] = useState(String(server.gpu_count));
  const [type, setType] = useState(server.gpu_type ?? "");
  const [confirming, setConfirming] = useState(false);
  const countChanged = Number(count) !== server.gpu_count;
  const typeChanged = type.trim() !== (server.gpu_type ?? "");
  const countOk = Number.isInteger(Number(count)) && Number(count) >= 1 && Number(count) <= 16;
  const save = () => {
    void onChange({ ...(countChanged ? { gpu_count: Number(count) } : {}), ...(typeChanged ? { gpu_type: type.trim() } : {}) });
  };
  return (
    <tr>
      <td className="primary"><strong>{server.name}</strong></td>
      <td data-label="GPU type">
        <input className="input" type="text" maxLength={100} aria-label={`GPU type of ${server.name}`} value={type} onChange={(e) => { setType(e.target.value); }} />
      </td>
      <td data-label="GPUs">
        <input className="input" type="number" min={1} max={16} inputMode="numeric" aria-label={`GPUs on ${server.name}`} style={{ width: "5rem" }} value={count} onChange={(e) => { setCount(e.target.value); }} />
      </td>
      <td data-label="Models" className="dim">{server.models.length > 0 ? server.models.join(", ") : "None yet"}</td>
      <td data-label="">
        <div className="actions-cell">
          {countChanged || typeChanged ? <button className="btn small primary" type="button" disabled={!countOk} onClick={save}>Save</button> : null}
          {confirming ? (
            <>
              <button className="btn small" type="button" onClick={() => { setConfirming(false); }}>Keep it</button>
              <button className="btn small danger" type="button" onClick={() => void onRemove().then((ok) => { if (!ok) setConfirming(false); })}>Yes, remove</button>
            </>
          ) : (
            <button className="btn small" type="button" disabled={server.models.length > 0} title={server.models.length > 0 ? "Remove or move its models first" : undefined} onClick={() => { setConfirming(true); }}>Remove</button>
          )}
        </div>
      </td>
    </tr>
  );
}

function NewServerForm({ onCreate }: { onCreate: (server: { name: string; gpu_count: number; gpu_type: string | null }) => Promise<boolean> }) {
  const [name, setName] = useState("");
  const [gpus, setGpus] = useState("");
  const [type, setType] = useState("");

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (await onCreate({ name: name.trim(), gpu_count: Number(gpus), gpu_type: type.trim() || null })) {
      setName("");
      setType("");
      setGpus("");
    }
  }

  return (
    <form className="surface stack" onSubmit={(e) => void submit(e)}>
      <h2>Add a server</h2>
      <div className="row">
        <Field label="Name">
          <input className="input" type="text" required maxLength={64} autoComplete="off" autoCapitalize="none" spellCheck={false} value={name} onChange={(e) => { setName(e.target.value); }} />
        </Field>
        <Field label="GPU type (optional)">
          <input className="input" type="text" maxLength={100} autoComplete="off" value={type} onChange={(e) => { setType(e.target.value); }} />
        </Field>
        <Field label="How many GPUs">
          <input className="input" type="number" required min={1} max={16} inputMode="numeric" value={gpus} onChange={(e) => { setGpus(e.target.value); }} />
        </Field>
      </div>
      <p className="hint dim">The name is a short label for the machine (lowercase letters, digits, dot, dash, underscore) and cannot change later. This is not the model address. GPUs are numbered from 0, as <code>nvidia-smi</code> shows them.</p>
      <div><button className="btn primary" type="submit">Add server</button></div>
    </form>
  );
}
