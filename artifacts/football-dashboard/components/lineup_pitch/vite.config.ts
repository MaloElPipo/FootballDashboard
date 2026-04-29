import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// Build mode = single self-contained HTML+JS bundle that Streamlit
// loads in an iframe via streamlit.components.v1.declare_component(path=...).
// We DO NOT need a dev server for Streamlit consumption; the dist/ folder
// is what Python points at. `vite dev` is kept for standalone debugging.

export default defineConfig({
  plugins: [react()],
  base: "./",
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist"),
    emptyOutDir: true,
    assetsInlineLimit: 100_000_000,
    cssCodeSplit: false,
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        manualChunks: undefined,
        entryFileNames: "assets/[name].js",
        assetFileNames: "assets/[name].[ext]",
      },
    },
  },
  server: {
    port: 5180,
    host: "0.0.0.0",
  },
});
