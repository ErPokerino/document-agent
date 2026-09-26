import assert from "node:assert/strict";
import test from "node:test";

import { latestOnly } from "../lib/latest.ts";

test("an older request is no longer current once a newer one starts", () => {
  const latest = latestOnly();
  const first = latest.begin();
  const second = latest.begin();

  assert.equal(first(), false);
  assert.equal(second(), true);
});

test("a slow answer to an old request cannot overwrite the newer one", async () => {
  const latest = latestOnly();
  let shown = null;
  const request = (value, delay) => {
    const isCurrent = latest.begin();
    return new Promise((resolve) => setTimeout(resolve, delay)).then(() => {
      if (isCurrent()) shown = value;
    });
  };

  await Promise.all([request("running run", 20), request("opened run", 1)]);

  assert.equal(shown, "opened run");
});

test("clearing the slot discards what is still in flight", () => {
  const latest = latestOnly();
  const pending = latest.begin();
  latest.invalidate();

  assert.equal(pending(), false);
});
