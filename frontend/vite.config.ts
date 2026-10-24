import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// FastAPI server for `npm run dev`. Override with API_TARGET=http://host:port.
const apiTarget = process.env.API_TARGET ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@fixtures": fileURLToPath(new URL("../contracts/fixtures", import.meta.url)),
    },
  },
  server: {
    fs: { allow: [fileURLToPath(new URL("..", import.meta.url))] },
    proxy: {
      "/api": apiTarget,
      "/ws": { target: apiTarget.replace(/^http/, "ws"), ws: true },
    },
  },
});
