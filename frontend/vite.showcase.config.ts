import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The public demo page (site/demo/): the 3D floor driven by the in-browser showcase model. No backend.
export default defineConfig({
  root: fileURLToPath(new URL("./showcase", import.meta.url)),
  base: "./",
  publicDir: false,
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@fixtures": fileURLToPath(new URL("../contracts/fixtures", import.meta.url)),
    },
  },
  server: { fs: { allow: [fileURLToPath(new URL("..", import.meta.url))] } },
  build: {
    outDir: fileURLToPath(new URL("../site/demo", import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 2500,
  },
});
