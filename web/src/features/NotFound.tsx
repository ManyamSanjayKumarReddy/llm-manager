import { useEffect } from "react";

import { Logo } from "../components/Logo";
import { Deco } from "../components/Stickers";
import { Link } from "../router/Link";

/** Shown for an address that is not part of the app. */
export function NotFound({ signedIn }: { signedIn: boolean }) {
  useEffect(() => {
    document.title = "Page not found";
  }, []);
  return (
    <div className="not-found">
      <Logo to="/" />
      <Deco name="thinking" size={140} />
      <h1>This page doesn’t exist</h1>
      <p className="dim">The address may have been mistyped, or the page has moved.</p>
      <div className="row">
        <Link className="btn primary" to={signedIn ? "/overview" : "/"}>{signedIn ? "Go to the dashboard" : "Back to home"}</Link>
      </div>
    </div>
  );
}
