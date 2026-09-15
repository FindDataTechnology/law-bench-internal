import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Library-style single-file IIFE build: the Jinja template drops
// <script src="/static/assistant/assistant.js"> and
// <link rel="stylesheet" href="/static/assistant/assistant.css"> into admin
// pages; the bundle self-mounts onto #lawbench-assistant-root.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/web/static/assistant",
    emptyOutDir: true,
    cssCodeSplit: false,
    // lib-mode builds do not inherit the default minifier — set it explicitly.
    minify: "esbuild",
    lib: {
      entry: "src/main.tsx",
      name: "LawbenchAssistant",
      formats: ["iife"],
      fileName: () => "assistant.js",
    },
    chunkSizeWarningLimit: 4000,
  },
});
