import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

export default defineConfig({
  test: { include: ["engine/**/*.test.ts"] },
  resolve: {
    alias: {
      "@engine": fileURLToPath(new URL("./engine", import.meta.url)),
      "@config": fileURLToPath(new URL("./config/tuning.json", import.meta.url)),
    },
  },
});
