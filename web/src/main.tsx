import "@fontsource-variable/inter";
import "@fontsource-variable/bricolage-grotesque";
import "@fontsource/space-mono/400.css";
import "@fontsource/space-mono/700.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/components.css";
import "./styles/layout.css";
import "./styles/landing.css";
import "./styles/addmodel.css";
import "./styles/containers.css";
import "./styles/usage.css";
import "./styles/connect.css";
import "./styles/gradients.css";
import "./styles/responsive.css";

const root = document.getElementById("root");
if (!root) throw new Error("#root is missing from index.html");
createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
