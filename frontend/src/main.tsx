import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { JobProvider } from "./job";
import { PrefsProvider } from "./prefs";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <PrefsProvider>
      <JobProvider>
        <App />
      </JobProvider>
    </PrefsProvider>
  </StrictMode>,
);
