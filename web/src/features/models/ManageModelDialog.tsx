import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { ManagedModel, ModelChanges, Server } from "../../api/types";
import { FormSection, PresetNumber } from "../../components/Controls";
import { Icon } from "../../components/Icon";
import { ModalHeader } from "../../components/Modal";
import { Field, Pill } from "../../components/ui";
import { serverLabel } from "../servers/label";
import { useToast } from "../toast/context";
import { IDLES, PRIORITIES } from "./form";
import { GpuPicker } from "./GpuPicker";

interface Props {
  model: ManagedModel;
  servers: Server[];
  onClose: () => void;
  /** Something changed on the server: refresh the list (and close if ``close``). */
  onChanged: (close: boolean) => void;
}

/** Everything about one registered model: its settings, putting it to sleep, and removing it. */
export function ManageModelDialog({ model, servers, onClose, onChanged }: Props) {
  const toast = useToast();
  const [priority, setPriority] = useState(String(model.priority));
  const [idle, setIdle] = useState(String(model.idle_minutes));
  const [url, setUrl] = useState(model.url);
  const [served, setServed] = useState(model.served_name ?? "");
  const [server, setServer] = useState(model.server);
  const [gpus, setGpus] = useState(model.gpus);
  const gpuCount = servers.find((s) => s.name === server)?.gpu_count ?? 0;
  const [newKey, setNewKey] = useState("");
  const [removeKey, setRemoveKey] = useState(false);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const [busy, setBusy] = useState(false);
  const idleNow = model.state === "asleep" || model.state === "down";

  async function run(action: () => Promise<unknown>, success: string, close: boolean) {
    setBusy(true);
    try {
      await action();
      toast.show("success", success);
      onChanged(close);
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
    }
    setBusy(false);
  }

  function save(event: SubmitEvent) {
    event.preventDefault();
    const changes: ModelChanges = {};
    if (Number(priority) !== model.priority) changes.priority = Number(priority);
    if (Number(idle) !== model.idle_minutes) changes.idle_minutes = Number(idle);
    if (url !== model.url) changes.url = url;
    if (server !== model.server) changes.server = server;
    if (gpus.join() !== model.gpus.join()) changes.gpus = gpus;
    const clear: NonNullable<ModelChanges["clear"]> = [];
    if (served !== (model.served_name ?? "")) {
      if (served) changes.served_name = served;
      else clear.push("served_name");
    }
    if (newKey) changes.backend_api_key = newKey;
    else if (removeKey) clear.push("backend_api_key");
    if (clear.length > 0) changes.clear = clear;
    if (Object.keys(changes).length === 0) { onClose(); return; }
    void run(() => api.updateModel(model.name, changes), `${model.name} updated.`, true);
  }

  return (
    <form onSubmit={save}>
      <ModalHeader title={model.name} subtitle={model.served_name ?? model.url} onClose={onClose} />
      <div className="modal-body">
        <div className="summary">
          <Pill>{model.state}</Pill>
          <span className="dim">{model.inflight} running · {model.waiting} waiting</span>
          {model.state === "awake" ? (
            <button type="button" className="btn small right" disabled={busy || model.inflight > 0} onClick={() => void run(() => api.sleepModel(model.name), `${model.name} is asleep.`, true)}>
              <Icon name="moon" size={15} /> Sleep now
            </button>
          ) : null}
        </div>

        <FormSection title="Wake and sleep" hint="These can change at any time, even while the model is awake.">
          <PresetNumber label="Priority" options={PRIORITIES} value={priority} onChange={setPriority} min={0} max={100} />
          <PresetNumber label="Sleep after idle (minutes)" options={IDLES} value={idle} onChange={setIdle} min={0.1} step="any" />
        </FormSection>

        <FormSection title="Container API key" hint={model.has_api_key ? "A key is stored. It is never shown again." : "No key is stored."}>
          <Field label={model.has_api_key ? "Replace the key" : "Add a key"}>
            <input className="input" type="password" autoComplete="off" spellCheck={false} placeholder={model.has_api_key ? "Leave empty to keep the current key" : "Leave empty for none"} value={newKey} onChange={(e) => { setNewKey(e.target.value.trim()); setRemoveKey(false); }} />
          </Field>
          {model.has_api_key ? (
            <label className="check-line"><input type="checkbox" checked={removeKey} disabled={newKey !== ""} onChange={(e) => { setRemoveKey(e.target.checked); }} /> Remove the stored key</label>
          ) : null}
        </FormSection>

        <FormSection title="Where it runs" hint={idleNow ? "Changing these is safe while the model is asleep." : `Locked while the model is ${model.state}. Put it to sleep to change them.`}>
          <fieldset className="locked" disabled={!idleNow}>
            <Field label="Container address">
              <input className="input" type="text" value={url} onChange={(e) => { setUrl(e.target.value.trim()); }} />
            </Field>
            <Field label="Name vLLM serves">
              <input className="input" type="text" value={served} onChange={(e) => { setServed(e.target.value.trim()); }} />
            </Field>
            <Field label="Server">
              <select className="input" value={server} onChange={(e) => { setServer(e.target.value); setGpus((g) => g.filter((n) => n < (servers.find((s) => s.name === e.target.value)?.gpu_count ?? 0))); }}>
                {servers.some((s) => s.name === server) ? null : <option value={server}>{server}</option>}
                {servers.map((s) => <option key={s.name} value={s.name}>{serverLabel(s)}</option>)}
              </select>
            </Field>
            <div className="field"><span>GPUs</span><GpuPicker count={gpuCount} value={gpus} onChange={setGpus} /></div>
          </fieldset>
        </FormSection>
      </div>

      <footer className="modal-foot">
        {confirmRemove ? (
          <>
            <p className="confirm-text"><strong>Remove “{model.name}”?</strong> Programs can no longer call it. The container keeps running, untouched.</p>
            <button type="button" className="btn" onClick={() => { setConfirmRemove(false); }}>Keep it</button>
            <button type="button" className="btn danger" disabled={busy} onClick={() => void run(() => api.removeModel(model.name), `${model.name} removed.`, true)}>Yes, remove</button>
          </>
        ) : (
          <>
            <button type="button" className="btn danger spacer" onClick={() => { setConfirmRemove(true); }}><Icon name="trash" size={15} /> Remove</button>
            <button type="button" className="btn" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn primary" disabled={busy || gpus.length === 0}>Save changes</button>
          </>
        )}
      </footer>
    </form>
  );
}
