import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { readFileSync } from "node:fs";
// @ts-expect-error Build helpers are plain Node modules and ship no client code.
import { sourceFingerprint, licenseNotices } from "./scripts/source-hash.mjs";
const root = fileURLToPath(new URL(".", import.meta.url));
export default defineConfig({
  base: "./",
  plugins: [
    react(),
    {
      name: "spoq-build-provenance",
      apply: "build",
      generateBundle() {
        const version = JSON.parse(
          readFileSync(new URL("./package.json", import.meta.url), "utf8"),
        ).version;
        this.emitFile({
          type: "asset",
          fileName: "build-info.json",
          source:
            JSON.stringify(
              {
                format: "spoq-ui-build-1",
                version,
                ...sourceFingerprint(root),
              },
              null,
              2,
            ) + "\n",
        });
        this.emitFile({
          type: "asset",
          fileName: "licenses.txt",
          source: licenseNotices(root),
        });
      },
    },
  ],
  build: { sourcemap: false, target: "es2022" },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    globals: true,
  },
});
