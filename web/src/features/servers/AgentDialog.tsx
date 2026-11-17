import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { Server } from "../../api/types";
import { Field } from "../../components/ui";
import { useToast } from "../toast/context";

interface Props {
  server: Server;
  onClose: () => void;
  onChanged: () => void;
}

/** The address and secret of the Wakeful agent running on a server. The token is write-only. */
export function AgentDialog({ server, onClose, onChanged }: Props) {
  const toast = useToast();
  const [url, setUrl] = useState(server.agent_url ?? "");
  const [token, setToken] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const hasAgent = server.has_agent;
  const needsToken = !hasAgent || url.trim() !== (server.agent_url ?? "");

  async function run(changes: { agent_url?: string; agent_token?: string }, success: string) {
    setBusy(true);
    try {
      await api.updateServer(server.name, changes);
      toast.show("success", success);
      onChanged();
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
      setBusy(false);
    }
  }

  function save(event: SubmitEvent) {
    event.preventDefault();
    const changes: { agent_url?: string; agent_token?: string } = {};
    if (url.trim() !== (server.agent_url ?? "")) changes.agent_url = url.trim();
    if (token !== "") changes.agent_token = token;
    void run(changes, `Agent of ${server.name} saved.`);
  }

  const missingToken = needsToken && token === "";
  const dirty = url.trim() !== (server.agent_url ?? "") || token !== "";

  return (
    <form onSubmit={save}>
      <h2>Agent on {server.name}</h2>
      <p className="dim">
        The agent is a small service on that machine. With it you can start, stop and create the vLLM containers from here, and see the machine&rsquo;s GPU, memory and disk.
      </p>
      <Field label="Agent address">
        <input className="input" type="url" required placeholder="https://gpu-box.example.com/agent" spellCheck={false} autoCapitalize="none" autoComplete="off" value={url} onChange={(e) => { setUrl(e.target.value); }} />
      </Field>
      <Field label={hasAgent ? "Replace the token" : "Token"}>
        <input className="input" type="password" autoComplete="off" spellCheck={false} minLength={32} placeholder={hasAgent ? "Leave empty to keep the current token" : "The AGENT_TOKEN set on that machine"} value={token} onChange={(e) => { setToken(e.target.value.trim()); }} />
      </Field>
      <p className="hint dim">The token is stored so Wakeful can call the agent, and is never shown again. Use https; plain http is only accepted for localhost.</p>
      {confirming ? (
        <div className="alert error" role="alert">
          <strong>Remove the agent?</strong> You can no longer control containers on {server.name} from here, and the stored token is deleted. The containers keep running.
        </div>
      ) : null}
      <div className="actions">
        {hasAgent && !confirming ? <button className="btn danger spacer" type="button" onClick={() => { setConfirming(true); }}>Remove agent</button> : null}
        {confirming ? (
          <>
            <button className="btn" type="button" onClick={() => { setConfirming(false); }}>Keep it</button>
            <button className="btn danger" type="button" disabled={busy} onClick={() => void run({ agent_url: "" }, `Agent of ${server.name} removed.`)}>Yes, remove</button>
          </>
        ) : (
          <>
            <button className="btn" type="button" onClick={onClose}>Cancel</button>
            <button className="btn primary" type="submit" disabled={busy || !dirty || missingToken}>Save</button>
          </>
        )}
      </div>
    </form>
  );
}
