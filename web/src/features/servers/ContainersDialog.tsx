import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { Container, Server } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal, ModalHeader } from "../../components/Modal";
import { Pagination } from "../../components/Pagination";
import { Pill, type Tone } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { usePagedList } from "../../hooks/usePagedList";
import { useToast } from "../toast/context";
import { HostStatsView } from "./HostStats";
import { LogsDialog } from "./LogsDialog";

interface Props {
  server: Server;
  onClose: () => void;
  /** A container or its model changed: refresh lists elsewhere. */
  onChanged: () => void;
}

function toneOf(c: Container): Tone {
  if (c.running) return "ok";
  if (c.oom_killed || c.state === "dead") return "bad";
  if (["restarting", "created", "paused"].includes(c.state)) return "warn";
  return "idle";
}

function labelOf(c: Container): string {
  if (c.running) return "running";
  if (c.oom_killed) return "out of memory";
  if (c.state === "exited" && c.exit_code) return `exited (${c.exit_code})`;
  return c.state;
}

/** The containers on one server (through its agent), with the machine's GPU, memory and disk. */
export function ContainersDialog({ server, onClose, onChanged }: Props) {
  const toast = useToast();
  const list = usePagedList((q) => api.containers(server.name, q), {}, { initialPageSize: 10, everyMs: 5000 });
  const host = useAsync(() => api.hostStats(server.name), 10000);
  const [busy, setBusy] = useState<string>();
  const [removing, setRemoving] = useState<Container>();
  const [logsOf, setLogsOf] = useState<string>();

  async function act(verb: "start" | "stop" | "restart", c: Container) {
    setBusy(c.name);
    const call = { start: api.startContainer, stop: api.stopContainer, restart: api.restartContainer }[verb];
    try {
      await call(server.name, c.name);
      toast.show("success", `${c.name}: ${verb === "stop" ? "stopped" : verb === "start" ? "started" : "restarted"}.`);
      onChanged();
      await list.reload();
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
    }
    setBusy(undefined);
  }

  return (
    <>
      <ModalHeader title={`Containers · ${server.name}`} subtitle="Started and stopped through this server’s agent. Only containers created from Wakeful are listed." onClose={onClose} />
      <div className="modal-body">
        <section aria-label="Server load">
          {host.error ? <div className="alert error" role="alert">{host.error}</div> : host.data ? <HostStatsView stats={host.data} /> : <div className="skeleton" aria-hidden="true" />}
        </section>

        {list.error ? <div className="alert error" role="alert">{list.error}</div> : null}
        {!list.loading && list.total === 0 && !list.error ? (
          <p className="no-match">No containers yet. Add a model from the Models page and choose to start it for you.</p>
        ) : null}
        <div className={`table-wrap ${list.fetching ? "fetching" : ""}`} hidden={list.total === 0}>
          <table className="cards">
            <thead><tr><th>Container</th><th>State</th><th>Port · GPUs</th><th /></tr></thead>
            <tbody>
              {list.items.map((c) => (
                <tr key={c.name}>
                  <td className="primary">
                    <strong>{c.name}</strong>
                    <span className="dim mono small-text">{c.model ?? c.image}</span>
                    {c.registered_as ? <span className="dim small-text">model “{c.registered_as}”{c.model_state ? ` · ${c.model_state}` : ""}</span> : null}
                  </td>
                  <td data-label="State"><Pill tone={toneOf(c)}>{labelOf(c)}</Pill><span className="dim small-text">{c.status}</span></td>
                  <td data-label="Port · GPUs">{c.port === null ? <span className="dim">n/a</span> : <span className="mono">{c.port}</span>} {c.gpus.map((g) => <span key={g} className="gpu-chip">GPU {g}</span>)}</td>
                  <td data-label="">
                    <div className="actions-cell">
                      {c.running ? (
                        <button type="button" className="icon-btn" disabled={busy === c.name} onClick={() => void act("stop", c)} aria-label={`Stop ${c.name}`} title="Stop"><Icon name="stop" size={16} /></button>
                      ) : (
                        <button type="button" className="icon-btn" disabled={busy === c.name} onClick={() => void act("start", c)} aria-label={`Start ${c.name}`} title="Start"><Icon name="play" size={16} /></button>
                      )}
                      <button type="button" className="icon-btn" disabled={busy === c.name} onClick={() => void act("restart", c)} aria-label={`Restart ${c.name}`} title="Restart"><Icon name="refresh" size={16} /></button>
                      <button type="button" className="icon-btn" onClick={() => { setLogsOf(c.name); }} aria-label={`Logs of ${c.name}`} title="Logs"><Icon name="terminal" size={16} /></button>
                      <button type="button" className="icon-btn danger" disabled={busy === c.name} onClick={() => { setRemoving(c); }} aria-label={`Remove ${c.name}`} title="Remove"><Icon name="trash" size={16} /></button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pagination page={list.page} pages={list.pages} total={list.total} pageSize={list.pageSize} noun="containers" onPage={list.setPage} onPageSize={list.setPageSize} />
      </div>

      <Modal open={removing !== undefined} onClose={() => { setRemoving(undefined); }} label="Remove container">
        {removing ? (
          <RemoveContainer
            server={server.name}
            container={removing}
            onClose={() => { setRemoving(undefined); }}
            onRemoved={() => { setRemoving(undefined); onChanged(); void list.reload(); }}
          />
        ) : null}
      </Modal>

      <Modal open={logsOf !== undefined} onClose={() => { setLogsOf(undefined); }} label="Container logs" size="lg">
        {logsOf ? <LogsDialog server={server.name} name={logsOf} onClose={() => { setLogsOf(undefined); }} /> : null}
      </Modal>
    </>
  );
}

/** Deleting a container is final. When a model is registered for it, that goes too, and the admin must type the name. */
function RemoveContainer({ server, container, onClose, onRemoved }: { server: string; container: Container; onClose: () => void; onRemoved: () => void }) {
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const model = container.registered_as;
  const confirmed = model === null || typed === container.name;

  async function remove(event: SubmitEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      await api.removeContainer(server, container.name, model !== null);
      toast.show("success", model ? `${container.name} and its model “${model}” were removed.` : `${container.name} was removed.`);
      onRemoved();
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(e) => { void remove(e); }}>
      <h2>Remove “{container.name}”?</h2>
      <div className="alert error" role="alert">
        <strong>This deletes the container and cannot be undone.</strong>{" "}
        {model ? <>The model “{model}” is removed from Wakeful too, so programs can no longer call it. </> : null}
        Downloaded model files stay on the server.
      </div>
      {model ? (
        <label className="field">
          Type <strong>{container.name}</strong> to confirm
          <input className="input" type="text" autoComplete="off" spellCheck={false} autoCapitalize="none" value={typed} onChange={(e) => { setTyped(e.target.value); }} />
        </label>
      ) : null}
      <div className="actions">
        <button className="btn" type="button" onClick={onClose}>Keep it</button>
        <button className="btn danger" type="submit" disabled={busy || !confirmed}>{model ? "Remove container and model" : "Remove container"}</button>
      </div>
    </form>
  );
}
