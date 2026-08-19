import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// Chrome extension build: relative asset paths (no absolute "/"), no HTML
// history routing (the app uses HashRouter), single index.html entry.
export default defineConfig({
  plugins: [react()],
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
