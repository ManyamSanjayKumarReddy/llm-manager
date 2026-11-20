import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { Server, StatusData } from "../../api/types";
import { Modal } from "../../components/Modal";
import { Reveal } from "../../components/Reveal";
import { Field, PageHead, Pill } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { Link } from "../../router/Link";
import { useToast } from "../toast/context";
import { AgentDialog } from "./AgentDialog";
import { ConnectDialog } from "./ConnectDialog";
import { ContainersDialog } from "./ContainersDialog";
import { HostStatsView } from "./HostStats";

/** The machines with GPUs. Models are placed on one of them, so GPU numbers stay unambiguous. */
export function Servers() {
  const toast = useToast();
  const servers = useAsync(() => api.servers(), undefined, 0);
  const status = useAsync(() => api.status(), 5000);

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
  const [editFor, setEditFor] = useState<string>();
  const agentServer = items.find((s) => s.name === agentFor);
  const connectServer = items.find((s) => s.name === connectFor);
  const containerServer = items.find((s) => s.name === containersFor);
  const editServer = items.find((s) => s.name === editFor);
  return (
    <div className="page">
      <PageHead eyebrow="Fleet" title="Servers">
        The GPU machines you run models on. Add each one here, connect its agent, then choose it when you add a model. Models only compete for a GPU when they are on the same server.
      </PageHead>
      <Reveal><NewServerForm onCreate={(s) => act(() => api.addServer(s), `Server “${s.name}” added.`)} /></Reveal>

      <div className="section-title"><h2>Your servers</h2><span className="count">{items.length} total</span></div>
      {servers.error ? <div className="alert error" role="alert">{servers.error}</div> : null}
      {!servers.loading && items.length === 0 ? <p className="no-match">No servers yet. Add the first one above.</p> : null}
      <div className="server-list">
        {items.map((server, i) => (
          <Reveal key={server.name} delay={i * 60}>
            <ServerCard
              server={server}
              status={status.data}
              onAgent={() => { setAgentFor(server.name); }}
              onConnect={() => { setConnectFor(server.name); }}
              onContainers={() => { setContainersFor(server.name); }}
              onEdit={() => { setEditFor(server.name); }}
            />
          </Reveal>
        ))}
      </div>
      {items.length > 0 ? <p className="hint dim">Add models on the <Link to="/models">Models</Link> page. An agent lets you start, stop and create containers on a server from here.</p> : null}

      <Modal open={agentServer !== undefined} onClose={() => { setAgentFor(undefined); }} label="Agent settings">
        {agentServer ? <AgentDialog server={agentServer} onClose={() => { setAgentFor(undefined); }} onChanged={() => { setAgentFor(undefined); void servers.reload(); }} /> : null}
      </Modal>
      <Modal open={connectServer !== undefined} onClose={() => { setConnectFor(undefined); }} label="Connect agent" size="md">
        {connectServer ? <ConnectDialog server={connectServer} onClose={() => { setConnectFor(undefined); }} onChanged={() => { void servers.reload(); }} /> : null}
      </Modal>
      <Modal open={containerServer !== undefined} onClose={() => { setContainersFor(undefined); }} label="Containers" size="fit">
        {containerServer ? <ContainersDialog server={containerServer} onClose={() => { setContainersFor(undefined); }} onChanged={() => { void servers.reload(); }} /> : null}
      </Modal>
      <Modal open={editServer !== undefined} onClose={() => { setEditFor(undefined); }} label="Edit server" size="md">
        {editServer ? (
          <EditServer
            server={editServer}
            onClose={() => { setEditFor(undefined); }}
            onSave={(changes) => act(() => api.updateServer(editServer.name, changes), `${editServer.name} updated.`)}
            onRemove={() => act(() => api.removeServer(editServer.name), `${editServer.name} removed.`)}
          />
        ) : null}
      </Modal>
    </div>
  );
}

/** How the agent on a server is reached, as one badge. */
function ConnectionBadge({ server }: { server: Server }) {
  if (server.tunnel) return server.tunnel_connected ? <Pill tone="ok">connected</Pill> : <Pill tone="warn">not connected</Pill>;
  if (server.has_agent) return <Pill tone="ok">agent (address)</Pill>;
  return <Pill tone="idle">no agent</Pill>;
}

/** The machine's GPU, memory and disk. Says so when the agent cannot be reached. */
function LiveLoad({ server }: { server: Server }) {
  const waiting = server.tunnel && !server.tunnel_connected;
  const host = useAsync(() => (waiting ? Promise.reject(new Error("not connected")) : api.hostStats(server.name)), 15000);
  if (waiting) return <p className="dim hint">The agent is not connected. Start it on that machine; this card updates when it connects.</p>;
  if (host.error) return <p className="dim hint">The agent could not be reached ({host.error}).</p>;
  if (!host.data) return <div className="skeleton" aria-hidden="true" />;
  return <HostStatsView stats={host.data} />;
}

function ServerCard({ server, status, onAgent, onConnect, onContainers, onEdit }: { server: Server; status: StatusData | undefined; onAgent: () => void; onConnect: () => void; onContainers: () => void; onEdit: () => void }) {
  const gpus = `${server.gpu_count} × ${server.gpu_type ?? "GPU"}`;
  const offline = server.tunnel && !server.tunnel_connected;
  return (
    <article className="surface server-card" aria-label={`Server ${server.name}`}>
      <div className="server-card-head">
        <div>
          <h3>{server.name}</h3>
          <p className="dim">{gpus}</p>
        </div>
        <ConnectionBadge server={server} />
      </div>

      <div className="server-card-body">
        <div className="server-section">
          <h4>Load</h4>
          {server.has_agent ? <LiveLoad key={String(server.tunnel_connected)} server={server} /> : (
            <p className="dim hint">Connect an agent to see this machine’s GPU, memory and disk here, and to start, stop and create containers from the dashboard.</p>
          )}
        </div>
        <div className="server-section">
          <h4>Models</h4>
          {server.models.length === 0 ? (
            <p className="dim hint">None yet. <Link to="/models">Add a model</Link> and choose this server.</p>
          ) : (
            <ul className="server-models">
              {server.models.map((name) => {
                const live = status?.models[name];
                return (
                  <li key={name} title={live?.detail ?? undefined}>
                    {name}
                    {live ? <Pill>{live.state}</Pill> : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>

      <div className="server-card-actions">
        {server.has_agent ? (
          <>
            <button className="btn small primary" type="button" disabled={offline} onClick={onContainers}>Containers</button>
            <button className="btn small" type="button" onClick={server.tunnel ? onConnect : onAgent}>Agent settings</button>
          </>
        ) : (
          <>
            <button className="btn small primary" type="button" onClick={onConnect}>Connect agent</button>
            <button className="btn small" type="button" onClick={onAgent}>Use an address</button>
          </>
        )}
        <button className="btn small right" type="button" onClick={onEdit}>Edit server</button>
      </div>
    </article>
  );
}

/** Change the GPU type and count, or remove the server (only when no model is placed on it). */
function EditServer({ server, onClose, onSave, onRemove }: { server: Server; onClose: () => void; onSave: (changes: { gpu_count?: number; gpu_type?: string }) => Promise<boolean>; onRemove: () => Promise<boolean> }) {
  const [count, setCount] = useState(String(server.gpu_count));
  const [type, setType] = useState(server.gpu_type ?? "");
  const [confirming, setConfirming] = useState(false);
  const countChanged = Number(count) !== server.gpu_count;
  const typeChanged = type.trim() !== (server.gpu_type ?? "");
  const countOk = Number.isInteger(Number(count)) && Number(count) >= 1 && Number(count) <= 16;
  const hasModels = server.models.length > 0;

  async function save(event: SubmitEvent) {
    event.preventDefault();
    const ok = await onSave({ ...(countChanged ? { gpu_count: Number(count) } : {}), ...(typeChanged ? { gpu_type: type.trim() } : {}) });
    if (ok) onClose();
  }

  return (
    <form className="edit-server" onSubmit={(e) => void save(e)}>
      <h2>Edit {server.name}</h2>
      <Field label="GPU type">
        <input className="input" type="text" maxLength={100} aria-label={`GPU type of ${server.name}`} value={type} onChange={(e) => { setType(e.target.value); }} />
      </Field>
      <Field label="How many GPUs">
        <input className="input" type="number" min={1} max={16} inputMode="numeric" aria-label={`GPUs on ${server.name}`} value={count} onChange={(e) => { setCount(e.target.value); }} />
      </Field>
      <div className="actions">
        <button className="btn" type="button" onClick={onClose}>Close</button>
        <button className="btn primary" type="submit" disabled={!countOk || !(countChanged || typeChanged)}>Save</button>
      </div>

      <div className="danger-zone">
        <p><strong>Remove this server</strong></p>
        <p className="dim">{hasModels ? "Remove or move its models first." : "This only forgets the server in Wakeful. Nothing is deleted on the machine."}</p>
        {confirming ? (
          <div className="actions">
            <button className="btn" type="button" onClick={() => { setConfirming(false); }}>Keep it</button>
            <button className="btn danger" type="button" onClick={() => void onRemove().then((ok) => { if (ok) onClose(); else setConfirming(false); })}>Yes, remove</button>
          </div>
        ) : (
          <div><button className="btn danger" type="button" disabled={hasModels} onClick={() => { setConfirming(true); }}>Remove</button></div>
        )}
      </div>
    </form>
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
