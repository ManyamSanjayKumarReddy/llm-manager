import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, setCsrfToken, setUnauthorizedHandler } from "../../api/client";
import type { SessionInfo } from "../../api/types";
import { AuthContext, type AuthState } from "./context";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });

  const startSession = useCallback((user: SessionInfo) => {
    setCsrfToken(user.csrf_token);
    setState({ status: "authenticated", user });
  }, []);

  const endSession = useCallback(() => {
    setCsrfToken("");
    setState({ status: "anonymous" });
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(endSession);
    api.me().then(startSession, endSession);
  }, [startSession, endSession]);

  const signIn = useCallback(
    async (username: string, password: string) => {
      startSession(await api.login(username, password));
    },
    [startSession],
  );

  const signOut = useCallback(async () => {
    try {
      await api.logout();
    } catch {
      // the session may already be gone; either way we are signed out here
    }
    endSession();
  }, [endSession]);

  const value = useMemo(() => ({ state, signIn, signOut }), [state, signIn, signOut]);
  return <AuthContext value={value}>{children}</AuthContext>;
}
