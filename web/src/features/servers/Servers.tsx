import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { Server } from "../../api/types";
import { Modal } from "../../components/Modal";
import { Reveal } from "../../components/Reveal";
import { Field, PageHead } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { Link } from "../../router/Link";
import { useToast } from "../toast/context";
import { AgentDialog } from "./AgentDialog";
import { ConnectDialog } from "./ConnectDialog";
import { ContainersDialog } from "./ContainersDialog";
import { hostSummary } from "./hostSummary";

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
  const [agentFor, setAgentFor] = useState<string>();
  const [connectFor, setConnectFor] = useState<string>();
  const [containersFor, setContainersFor] = useState<string>();
  const agentServer = items.find((s) => s.name === agentFor);
  const connectServer = items.find((s) => s.name === connectFor);
  const containerServer = items.find((s) => s.name === containersFor);
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
              <thead><tr><th>Server</th><th>GPU type</th><th>GPUs</th><th>Models</th><th>Agent</th><th /></tr></thead>
              <tbody>
                {items.map((server) => (
                  <ServerRow
                    key={`${server.name}-${server.gpu_count}-${server.gpu_type ?? ""}`}
                    server={server}
                    onAgent={() => { setAgentFor(server.name); }}
                    onConnect={() => { setConnectFor(server.name); }}
                    onContainers={() => { setContainersFor(server.name); }}
                    onChange={(changes) => act(() => api.updateServer(server.name, changes), `${server.name} updated.`)}
                    onRemove={() => act(() => api.removeServer(server.name), `${server.name} removed.`)}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {items.length > 0 ? <p className="hint dim">Add models on the <Link to="/models">Models</Link> page. An agent lets you start, stop and create containers on a server from here.</p> : null}
        </section>
      </Reveal>

      <Modal open={agentServer !== undefined} onClose={() => { setAgentFor(undefined); }} label="Agent settings">
        {agentServer ? <AgentDialog server={agentServer} onClose={() => { setAgentFor(undefined); }} onChanged={() => { setAgentFor(undefined); void servers.reload(); }} /> : null}
      </Modal>
      <Modal open={connectServer !== undefined} onClose={() => { setConnectFor(undefined); }} label="Connect agent" size="md">
        {connectServer ? <ConnectDialog server={connectServer} onClose={() => { setConnectFor(undefined); }} onChanged={() => { void servers.reload(); }} /> : null}
      </Modal>
      <Modal open={containerServer !== undefined} onClose={() => { setContainersFor(undefined); }} label="Containers" size="lg">
        {containerServer ? <ContainersDialog server={containerServer} onClose={() => { setContainersFor(undefined); }} onChanged={() => { void servers.reload(); }} /> : null}
      </Modal>
    </div>
  );
}

/** One line about the machine's load, refreshed now and then. Says so when the agent cannot be reached. */
function AgentStatus({ server, waiting }: { server: string; waiting: boolean }) {
  const host = useAsync(() => (waiting ? Promise.reject(new Error("not connected")) : api.hostStats(server)), 15000);
  if (waiting) return <span className="dim small-text">Not connected</span>;
  if (host.error) return <span className="dim small-text">Agent not reachable</span>;
  if (!host.data) return <span className="dim small-text">Checking…</span>;
  return <span className="dim small-text">{hostSummary(host.data)}</span>;
}

function ServerRow({ server, onChange, onRemove, onAgent, onConnect, onContainers }: { server: Server; onChange: (changes: { gpu_count?: number; gpu_type?: string }) => Promise<boolean>; onRemove: () => Promise<boolean>; onAgent: () => void; onConnect: () => void; onContainers: () => void }) {
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
      <td data-label="Agent">
        {server.has_agent ? (
          <div className="agent-cell">
            <AgentStatus key={String(server.tunnel_connected)} server={server.name} waiting={server.tunnel && !server.tunnel_connected} />
            <div className="actions-cell">
              <button className="btn small" type="button" disabled={server.tunnel && !server.tunnel_connected} onClick={onContainers}>Containers</button>
              <button className="btn small" type="button" onClick={server.tunnel ? onConnect : onAgent}>Settings</button>
            </div>
          </div>
        ) : (
          <div className="actions-cell">
            <button className="btn small" type="button" onClick={onConnect}>Connect agent</button>
            <button className="btn small" type="button" onClick={onAgent}>Use an address</button>
          </div>
        )}
      </td>
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
