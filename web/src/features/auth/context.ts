import { createContext, useContext } from "react";

import type { SessionInfo } from "../../api/types";

export type AuthState =
  | { status: "loading" }
  | { status: "anonymous" }
  | { status: "authenticated"; user: SessionInfo };

export interface AuthContextValue {
  state: AuthState;
  signIn: (username: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}

/** The signed-in user; only call inside the authenticated part of the app. */
export function useUser(): SessionInfo {
  const { state } = useAuth();
  if (state.status !== "authenticated") throw new Error("not signed in");
  return state.user;
}
