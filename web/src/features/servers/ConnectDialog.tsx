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

  const connectUrl = enrolled ? `${window.location.origin.replace(/^http/, "ws")}${enrolled.connect_path}` : "";
  const settings = enrolled ? `AGENT_CONNECT_URL=${connectUrl}\nAGENT_CONNECT_TOKEN=${enrolled.token}` : "";

  return (
    <div>
      <h2>Connect the agent on {server.name}</h2>
      <p className="dim">
        The agent on that machine connects out to Wakeful and keeps the connection open. The machine needs no open port, no certificate and no web-server rule, so this works behind a firewall. Wakeful then controls its containers and reaches its models through that connection.
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
          <div className="alert" role="status">
            <strong>Copy these now.</strong> The token is shown only once and cannot be recovered; if you lose it, create a new one.
          </div>
          <pre className="command wrap" aria-label="Agent settings" tabIndex={0}>{settings}</pre>
          <div className="actions"><CopyButton value={settings} label="agent settings" /></div>
          <ol className="connect-steps">
            <li>On {server.name}, put these two lines in <code>/etc/wakeful-agent.env</code> (remove <code>AGENT_TOKEN</code>; it is not needed).</li>
            <li>If some containers there were not created by Wakeful, add <code>AGENT_RELAY_PORTS=8025,8026</code> with their ports.</li>
            <li>Run <code>systemctl enable --now wakeful-agent</code> (or restart it). This page shows when it connects.</li>
          </ol>
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
    </div>
  );
}
