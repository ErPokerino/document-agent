#!/usr/bin/env node
/**
 * Run the project's virtualenv Python with the given arguments, on any OS.
 *
 * npm scripts used to name `.venv\Scripts\python.exe`, which exists only on
 * Windows. A virtualenv puts its interpreter in `Scripts` on Windows and in
 * `bin` elsewhere; this picks whichever is there, so `npm test` runs the same
 * on every contributor's machine and in CI.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const candidates = [
  join(root, ".venv", "Scripts", "python.exe"),
  join(root, ".venv", "bin", "python"),
];
const python = candidates.find((candidate) => existsSync(candidate));
if (!python) {
  console.error(`No virtualenv interpreter at ${candidates.join(" or ")}.`);
  process.exit(1);
}
const result = spawnSync(python, process.argv.slice(2), { stdio: "inherit", cwd: root });
process.exit(result.status ?? 1);
