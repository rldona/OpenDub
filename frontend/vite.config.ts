import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build goes inside the Python package, which FastAPI serves (web/app.py): using the
// web frontend needs no Node, only changing it does. `npm run dev` proxies the API to a
// running `opendub web`.
const api = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  base: "/static/",
  build: { outDir: "../src/opendub/web/static", emptyOutDir: true },
  server: {
    proxy: Object.fromEntries(["/jobs", "/videos", "/engines", "/status", "^/style$"].map((p) => [p, api])),
  },
});
