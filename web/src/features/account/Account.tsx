import { useState, type SubmitEvent } from "react";

import { api } from "../../api/client";
import { Reveal } from "../../components/Reveal";
import { Alert, Field, PageHead, type Notice } from "../../components/ui";
import { useUser } from "../auth/context";

export function Account() {
  const me = useUser();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [notice, setNotice] = useState<Notice>();

  async function submit(event: SubmitEvent) {
    event.preventDefault();
    if (next !== again) {
      setNotice({ kind: "error", text: "The new passwords do not match." });
      return;
    }
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setAgain("");
      setNotice({ kind: "success", text: "Password changed. Your other sessions were signed out." });
    } catch (err) {
      setNotice({ kind: "error", text: err instanceof Error ? err.message : "Could not change the password." });
    }
  }

  return (
    <div className="page">
      <PageHead eyebrow="You" title="Account">
        Signed in as <strong>{me.username}</strong> ({me.role}).
      </PageHead>
      <Reveal>
        <form className="surface stack narrow" onSubmit={(e) => void submit(e)}>
          <h2>Change password</h2>
          <p className="dim">At least 12 characters. Your other sessions are signed out.</p>
          <Alert notice={notice} />
          <Field label="Current password">
            <input className="input" type="password" required maxLength={256} autoComplete="current-password" value={current} onChange={(e) => { setCurrent(e.target.value); }} />
          </Field>
          <Field label="New password">
            <input className="input" type="password" required maxLength={256} autoComplete="new-password" value={next} onChange={(e) => { setNext(e.target.value); }} />
          </Field>
          <Field label="Repeat new password">
            <input className="input" type="password" required maxLength={256} autoComplete="new-password" value={again} onChange={(e) => { setAgain(e.target.value); }} />
          </Field>
          <div><button className="btn primary" type="submit">Change password</button></div>
        </form>
      </Reveal>
    </div>
  );
}
