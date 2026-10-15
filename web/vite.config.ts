import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";

export default defineConfig({
  root: fileURLToPath(new URL(".", import.meta.url)),
  base: "./",
  resolve: {
    alias: {
      "@engine": fileURLToPath(new URL("../engine", import.meta.url)),
      "@config": fileURLToPath(new URL("../config/tuning.json", import.meta.url)),
    },
  },
  build: { outDir: "dist", emptyOutDir: true, target: "es2022" },
  worker: { format: "es" },
  server: { port: 5173 },
});
