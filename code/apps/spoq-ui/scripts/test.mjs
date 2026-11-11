import { spawnSync } from "node:child_process";
const args = process.argv
  .slice(2)
  .flatMap((arg) => (arg === "--runInBand" ? ["--maxWorkers=1"] : [arg]));
const result = spawnSync(
  process.execPath,
  ["node_modules/vitest/vitest.mjs", "run", ...args],
  { stdio: "inherit" },
);
process.exit(result.status ?? 1);
