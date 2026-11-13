import type { ReactNode } from "react";

import { Account } from "./features/account/Account";
import { Connect } from "./features/connect/Connect";
import { Audit } from "./features/audit/Audit";
import { History } from "./features/history/History";
import { ApiKeys } from "./features/keys/ApiKeys";
import { Models } from "./features/models/Models";
import { Overview } from "./features/overview/Overview";
import { Usage } from "./features/usage/Usage";
import { Servers } from "./features/servers/Servers";
import { Users } from "./features/users/Users";

/** One screen of the dashboard (everything after signing in). */
export interface DashboardPage {
  path: string;
  title: string;
  /** Only administrators may open it; the API enforces this too. */
  admin?: boolean;
  /** Shown in the navigation. */
  nav?: boolean;
  /** Pages with the same group share one drop-down; a group with a single visible page is a plain link. */
  group?: string;
  /** For screens without a tab of their own: the tab to highlight. */
  parent?: string;
  view: ReactNode;
}

export const PAGES: readonly DashboardPage[] = [
  { path: "/overview", title: "Overview", nav: true, view: <Overview /> },
  { path: "/servers", title: "Servers", admin: true, nav: true, group: "Fleet", view: <Servers /> },
  { path: "/models", title: "Models", admin: true, nav: true, group: "Fleet", view: <Models /> },
  { path: "/usage", title: "Usage", admin: true, nav: true, group: "Activity", view: <Usage /> },
  { path: "/history", title: "History", nav: true, group: "Activity", view: <History /> },
  { path: "/api-keys", title: "API keys", admin: true, nav: true, group: "Developers", view: <ApiKeys /> },
  { path: "/connect", title: "Connect", nav: true, group: "Developers", view: <Connect /> },
  { path: "/users", title: "Users", admin: true, nav: true, group: "Admin", view: <Users /> },
  { path: "/audit", title: "Audit", admin: true, nav: true, group: "Admin", view: <Audit /> },
  { path: "/account", title: "Account", nav: true, view: <Account /> },
];

export function findPage(path: string): DashboardPage | undefined {
  return PAGES.find((page) => page.path === path);
}

/** Where to go after signing in: the page that was asked for, if it is one of ours. */
export function safeNext(next: string | null): string {
  return next !== null && findPage(next) ? next : "/overview";
}
