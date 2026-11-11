import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import type { Role, User } from "../../api/types";
import { Modal } from "../../components/Modal";
import { Reveal } from "../../components/Reveal";
import { Field, PageHead, Pill } from "../../components/ui";
import { Pagination } from "../../components/Pagination";
import { SearchBox } from "../../components/SearchBox";
import { usePagedList } from "../../hooks/usePagedList";
import { ago } from "../../lib/format";
import { useUser } from "../auth/context";
import { useToast } from "../toast/context";

export function Users() {
  const me = useUser();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [role, setRole] = useState("");
  const users = usePagedList((q) => api.users({ ...q, q: search, role }), { q: search, role });
  const filtered = search !== "" || role !== "";
  const [resetting, setResetting] = useState<User>();
  const [newPassword, setNewPassword] = useState("");

  /** Run a change, show the outcome, refresh the list. Returns whether it worked. */
  async function act(change: () => Promise<unknown>, success: string): Promise<boolean> {
    try {
      await change();
      toast.show("success", success);
      await users.reload();
      return true;
    } catch (err) {
      toast.show("error", err instanceof Error ? err.message : "That did not work.");
      return false;
    }
  }

  async function submitReset(event: SubmitEvent) {
    event.preventDefault();
    if (!resetting) return;
    if (await act(() => api.resetPassword(resetting.id, newPassword), `Password for ${resetting.username} changed.`)) {
      setResetting(undefined);
      setNewPassword("");
    }
  }

  return (
    <div className="page">
      <PageHead eyebrow="People" title="Users">
        Admins manage everything. Viewers can only look at models and history.
      </PageHead>
      <Reveal><NewUserForm onCreate={(u) => act(() => api.createUser(u), `Account “${u.username}” created.`)} /></Reveal>
      <Reveal>
        <section className="surface stack">
          <div className="section-title"><h2>Accounts</h2><span className="count">{users.total} {filtered ? "match" : "total"}</span></div>
          <div className="toolbar">
            <SearchBox label="Search users" placeholder="Search by username" value={search} onChange={setSearch} />
            <select className="input" aria-label="Filter by role" value={role} onChange={(e) => { setRole(e.target.value); }}>
              <option value="">All roles</option>
              <option value="admin">Admins</option>
              <option value="viewer">Viewers</option>
            </select>
          </div>
          {users.error ? <div className="alert error" role="alert">{users.error}</div> : null}
          {!users.loading && users.total === 0 ? (
            <p className="no-match">{filtered ? "No accounts match your search." : "No accounts yet."}</p>
          ) : null}
          <div className={`table-wrap ${users.fetching ? "fetching" : ""}`} hidden={users.total === 0}>
            <table className="cards">
              <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th /></tr></thead>
              <tbody>
                {users.items.map((user) => {
                  const self = user.username === me.username;
                  return (
                    <tr key={user.id}>
                      <td className="primary"><strong>{user.username}</strong>{self ? <span className="dim"> · you</span> : null}</td>
                      <td data-label="Role">{user.role}</td>
                      <td data-label="Status">
                        {user.is_active ? <Pill tone="ok">active</Pill> : <Pill tone="bad">disabled</Pill>}{" "}
                        {user.locked ? <Pill tone="warn">locked</Pill> : null}
                      </td>
                      <td data-label="Last sign-in" className="dim">{ago(user.last_login_at)}</td>
                      <td data-label="">
                        <div className="actions-cell">
                          {self ? null : (
                            <>
                              <button className="btn small" type="button" onClick={() => void act(() => api.updateUser(user.id, { is_active: !user.is_active }), `${user.username} ${user.is_active ? "disabled" : "enabled"}.`)}>
                                {user.is_active ? "Disable" : "Enable"}
                              </button>
                              <button className="btn small" type="button" onClick={() => void act(() => api.updateUser(user.id, { role: user.role === "admin" ? "viewer" : "admin" }), `${user.username} is now ${user.role === "admin" ? "a viewer" : "an admin"}.`)}>
                                {user.role === "admin" ? "Make viewer" : "Make admin"}
                              </button>
                            </>
                          )}
                          <button className="btn small" type="button" onClick={() => { setResetting(user); }}>Reset password</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <Pagination page={users.page} pages={users.pages} total={users.total} pageSize={users.pageSize} noun="accounts" onPage={users.setPage} onPageSize={users.setPageSize} />
        </section>
      </Reveal>

      <Modal open={resetting !== undefined} onClose={() => { setResetting(undefined); setNewPassword(""); }} label="Reset password">
        <form onSubmit={(e) => void submitReset(e)}>
          <h2>New password for {resetting?.username}</h2>
          <p className="dim">At least 12 characters. They are signed out everywhere and must use the new one.</p>
          <Field label="New password">
            <input className="input" type="password" required maxLength={256} autoComplete="new-password" value={newPassword} onChange={(e) => { setNewPassword(e.target.value); }} />
          </Field>
          <div className="actions">
            <button className="btn" type="button" onClick={() => { setResetting(undefined); setNewPassword(""); }}>Cancel</button>
            <button className="btn primary" type="submit">Change password</button>
          </div>
        </form>
      </Modal>
    </div>
  );
}

function NewUserForm({ onCreate }: { onCreate: (user: { username: string; password: string; role: Role }) => Promise<boolean> }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("viewer");

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (await onCreate({ username: username.trim(), password, role })) {
      setUsername("");
      setPassword("");
      setRole("viewer");
    }
  }

  return (
    <form className="surface stack" onSubmit={(e) => void submit(e)}>
      <h2>New account</h2>
      <div className="row">
        <Field label="Username">
          <input className="input" type="text" required minLength={3} maxLength={64} autoComplete="off" autoCapitalize="none" spellCheck={false} value={username} onChange={(e) => { setUsername(e.target.value); }} />
        </Field>
        <Field label="Initial password">
          <input className="input" type="password" required maxLength={256} autoComplete="new-password" value={password} onChange={(e) => { setPassword(e.target.value); }} />
        </Field>
        <Field label="Role">
          <select className="input" value={role} onChange={(e) => { setRole(e.target.value as Role); }}>
            <option value="viewer">Viewer (read-only)</option>
            <option value="admin">Admin</option>
          </select>
        </Field>
      </div>
      <div><button className="btn primary" type="submit">Create account</button></div>
    </form>
  );
}
