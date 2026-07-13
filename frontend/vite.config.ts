import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// API proxy target: defaults to the compose service name `fastapi`.
// Override with VITE_API_PROXY_TARGET when running `npm run dev` on the host
// (use http://localhost:8000 in that case).
const apiTarget = process.env.VITE_API_PROXY_TARGET || "http://fastapi:8000";

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  server: {
    port: 5173,
    host: "0.0.0.0",
    proxy: { "/api": apiTarget },
  },
});
