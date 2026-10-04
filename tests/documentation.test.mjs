import assert from "node:assert/strict";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Documentation moves as the code does. A page renamed or a heading reworded
// leaves links pointing at nothing, and nobody notices until a reader does;
// this fails the build instead.

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

function markdownUnder(folder) {
  return readdirSync(folder).flatMap((name) => {
    const path = join(folder, name);
    if (statSync(path).isDirectory()) return markdownUnder(path);
    return name.endsWith(".md") ? [path] : [];
  });
}

function anchorsOf(path) {
  return new Set(
    readFileSync(path, "utf8")
      .split("\n")
      .filter((line) => line.startsWith("#"))
      .map((line) => line.replace(/^#+/, "").trim().toLowerCase().replace(/[^\w\- ]/g, "").replaceAll(" ", "-")),
  );
}

const pages = [
  ...["README.md", "ROADMAP.md", "AGENTS.md", "CONTRIBUTING.md", ".github/pull_request_template.md"].map((name) => join(root, name)),
  ...markdownUnder(join(root, "docs")),
];

test("every relative link in the documentation reaches a file and a heading that exist", () => {
  const broken = [];
  for (const page of pages) {
    for (const [, target] of readFileSync(page, "utf8").matchAll(/\]\(([^)]+)\)/g)) {
      if (/^(https?:|mailto:)/.test(target)) continue;
      const [path, anchor] = target.split("#");
      const destination = path ? resolve(dirname(page), path) : page;
      if (!existsSync(destination)) broken.push(`${page}: ${target}`);
      else if (anchor && destination.endsWith(".md") && !anchorsOf(destination).has(anchor)) broken.push(`${page}: ${target}`);
    }
  }
  assert.deepEqual(broken, []);
});

test("every feature page is listed in the documentation index", () => {
  const index = readFileSync(join(root, "docs", "README.md"), "utf8");
  const features = readdirSync(join(root, "docs", "features"));

  assert.deepEqual(features.filter((name) => !index.includes(`features/${name}`)), []);
});

test("every decision record is listed in the decisions index", () => {
  const index = readFileSync(join(root, "docs", "decisions", "README.md"), "utf8");
  const records = readdirSync(join(root, "docs", "decisions")).filter((name) => /^\d{4}-/.test(name));

  assert.deepEqual(records.filter((name) => !index.includes(name)), []);
});
