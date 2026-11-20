import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { Container, Server } from "../../api/types";
import { Icon } from "../../components/Icon";
import { Modal, ModalHeader } from "../../components/Modal";
import { Pagination } from "../../components/Pagination";
import { Pill, type Tone } from "../../components/ui";
import { useAsync } from "../../hooks/useAsync";
import { usePagedList } from "../../hooks/usePagedList";
import { Link } from "../../router/Link";
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
      <ModalHeader title={`Containers · ${server.name}`} subtitle="The vLLM containers Wakeful started on this server, and how the machine is doing." onClose={onClose} />
      <div className="modal-body">
        <section aria-label="Server load">
          {host.error ? <div className="alert error" role="alert">{host.error}</div> : host.data ? <HostStatsView stats={host.data} /> : <div className="skeleton" aria-hidden="true" />}
        </section>

        {list.error ? <div className="alert error" role="alert">{list.error}</div> : null}
        {!list.loading && list.total === 0 && !list.error ? (
          <div className="cc-empty">
            <strong>No containers yet</strong>
            <p className="dim">Add a model on the Models page and choose “Create and register”: Wakeful starts the container here and registers it.</p>
            <Link className="btn small primary" to="/models">Add a model</Link>
          </div>
        ) : null}
        <ul className={`container-list ${list.fetching ? "fetching" : ""}`} hidden={list.total === 0}>
          {list.items.map((c) => (
            <li key={c.name} className="container-card" aria-label={`Container ${c.name}`}>
              <div className="cc-top">
                <div className="cc-title">
                  <strong>{c.name}</strong>
                  <span className="dim mono">{c.model ?? c.image}</span>
                </div>
                <Pill tone={toneOf(c)}>{labelOf(c)}</Pill>
              </div>
              <div className="cc-chips">
                {c.port === null ? null : <span className="gpu-chip">port {c.port}</span>}
                {c.gpus.map((g) => <span key={g} className="gpu-chip">GPU {g}</span>)}
                <span className="dim small-text">{c.status}</span>
              </div>
              {c.registered_as ? (
                <div className="cc-model">
                  <div className="cc-model-line">
                    <span className="dim">Model</span> <strong>{c.registered_as}</strong>
                    {c.model_state ? <Pill>{c.model_state}</Pill> : null}
                  </div>
                  {c.model_detail && (c.model_state === "down" || c.model_state === "starting") ? (
                    <p className={`model-note ${c.model_state}`} role="status">{c.model_detail}</p>
                  ) : null}
                </div>
              ) : (
                <div className="cc-model dim">Not registered as a model yet.</div>
              )}
              <div className="cc-actions">
                {c.running ? (
                  <button type="button" className="btn small" disabled={busy === c.name} onClick={() => void act("stop", c)} aria-label={`Stop ${c.name}`}><Icon name="stop" size={14} /> Stop</button>
                ) : (
                  <button type="button" className="btn small primary" disabled={busy === c.name} onClick={() => void act("start", c)} aria-label={`Start ${c.name}`}><Icon name="play" size={14} /> Start</button>
                )}
                <button type="button" className="btn small" disabled={busy === c.name} onClick={() => void act("restart", c)} aria-label={`Restart ${c.name}`}><Icon name="refresh" size={14} /> Restart</button>
                <button type="button" className="btn small" onClick={() => { setLogsOf(c.name); }} aria-label={`Logs of ${c.name}`}><Icon name="terminal" size={14} /> Logs</button>
                <button type="button" className="btn small danger right" disabled={busy === c.name} onClick={() => { setRemoving(c); }} aria-label={`Remove ${c.name}`}><Icon name="trash" size={14} /> Remove</button>
              </div>
            </li>
          ))}
        </ul>
        {list.total > list.pageSize ? <Pagination page={list.page} pages={list.pages} total={list.total} pageSize={list.pageSize} noun="containers" onPage={list.setPage} onPageSize={list.setPageSize} /> : null}
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
