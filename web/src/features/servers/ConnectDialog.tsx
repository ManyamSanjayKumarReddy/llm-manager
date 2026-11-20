import { useState } from "react";

import { api } from "../../api/client";
import type { Server, TunnelEnrolled } from "../../api/types";
import { CopyButton } from "../../components/CopyButton";
import { useAsync } from "../../hooks/useAsync";
import { useToast } from "../toast/context";

interface Props {
  server: Server;
  onClose: () => void;
  onChanged: () => void;
}

type Confirming = "renew" | "revoke" | undefined;

/** Lets a server's agent connect out to Wakeful: no open port, no web-server rule on that machine. */
export function ConnectDialog({ server, onClose, onChanged }: Props) {
  const toast = useToast();
  const live = useAsync(() => api.servers(), 3000);
  const current = live.data?.find((s) => s.name === server.name) ?? server;
  const [enrolled, setEnrolled] = useState<TunnelEnrolled>();
  const [confirming, setConfirming] = useState<Confirming>();
  const [busy, setBusy] = useState(false);

  async function run(change: () => Promise<unknown>, success: string) {
    setBusy(true);
    try {
      await change();
      toast.show("success", success);
      onChanged();
      await live.reload(); // show the new state now, not at the next poll
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
    }
    setBusy(false);
    setConfirming(undefined);
  }

  const issue = () =>
    void run(async () => { setEnrolled(await api.enrollTunnel(server.name)); }, `Connection token for ${server.name} created.`);
  const revoke = () =>
    void run(async () => { await api.revokeTunnel(server.name); setEnrolled(undefined); }, `${server.name} no longer accepts its agent.`);

  const origin = window.location.origin;
  const connectUrl = `${origin.replace(/^http/, "ws")}${enrolled?.connect_path ?? "/api/agent/connect"}`;
  const command = enrolled ? `curl -fsSL ${origin}/install-agent.sh | sudo bash -s -- ${enrolled.token}` : "";
  const settings = enrolled ? `AGENT_CONNECT_URL=${connectUrl}\nAGENT_CONNECT_TOKEN=${enrolled.token}` : "";

  return (
    // A form, like the other small popups, so it gets their padding and spacing.
    <form className="connect-dialog" onSubmit={(e) => { e.preventDefault(); }}>
      <h2>Connect the agent on {server.name}</h2>
      <p className="dim">
        The agent on that machine connects out to Wakeful, so the machine needs no open port or certificate and works behind a firewall.
      </p>

      <p>
        <strong>Status: </strong>
        {current.tunnel_connected ? (
          <span>Connected{current.tunnel_agent_version ? ` (agent ${current.tunnel_agent_version})` : ""}</span>
        ) : current.tunnel ? (
          <span>Not connected{current.tunnel_last_seen ? `. Last seen ${new Date(current.tunnel_last_seen).toLocaleString()}` : ". The agent has not connected yet"}</span>
        ) : (
          <span>No connection set up</span>
        )}
      </p>

      {enrolled ? (
        <>
          <div className="alert success" role="status">
            <strong>Copy it now.</strong> The token is shown only once; if you lose it, create a new one.
          </div>
          <p>On {server.name}, run this command:</p>
          <pre className="command wrap connect-cmd" aria-label="Install command" tabIndex={0}>{command}</pre>
          <div className="actions"><CopyButton value={command} label="install command" /></div>
          <p className="dim">
            It needs Docker and the NVIDIA container toolkit, which a vLLM server already has. This page shows "Connected" within a few seconds. Run the same command again to update the agent later. Containers there that Wakeful did not create need <code>--relay-ports 8025,8026</code> (their ports) added to it.
          </p>
          <details className="connect-manual">
            <summary>Set it up by hand instead</summary>
            <p>Put these two lines in the agent's settings (<code>/etc/wakeful-agent.env</code> when it runs as a service) and restart it:</p>
            <pre className="command wrap connect-cmd" aria-label="Agent settings" tabIndex={0}>{settings}</pre>
            <div className="actions"><CopyButton value={settings} label="agent settings" /></div>
          </details>
        </>
      ) : null}

      {confirming === "renew" ? (
        <div className="alert error" role="alert">
          <strong>Create a new token?</strong> The agent using the current one is disconnected now, and stays disconnected until you give it the new token.
        </div>
      ) : null}
      {confirming === "revoke" ? (
        <div className="alert error" role="alert">
          <strong>Disconnect {server.name}?</strong> Its agent is cut off, and models placed on it become unreachable until you connect an agent again (or give the server an address).
        </div>
      ) : null}

      <div className="actions">
        {confirming ? (
          <>
            <button className="btn" type="button" onClick={() => { setConfirming(undefined); }}>Keep it</button>
            {confirming === "renew" ? (
              <button className="btn danger" type="button" disabled={busy} onClick={issue}>Yes, new token</button>
            ) : (
              <button className="btn danger" type="button" disabled={busy} onClick={revoke}>Yes, disconnect</button>
            )}
          </>
        ) : (
          <>
            {current.tunnel ? <button className="btn danger spacer" type="button" onClick={() => { setConfirming("revoke"); }}>Disconnect</button> : null}
            <button className="btn" type="button" onClick={onClose}>Close</button>
            {current.tunnel ? (
              <button className="btn" type="button" onClick={() => { setConfirming("renew"); }}>New token</button>
            ) : (
              <button className="btn primary" type="button" disabled={busy} onClick={issue}>Create connection token</button>
            )}
          </>
        )}
      </div>
    </form>
  );
}
