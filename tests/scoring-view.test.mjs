import assert from "node:assert/strict";
import test from "node:test";

import { entitiesIn, scoreWithout } from "../lib/scoring-view.ts";

const metrics = (perEntity) => ({
  matched: Object.values(perEntity).reduce((sum, tally) => sum + tally.matched, 0),
  total: Object.values(perEntity).reduce((sum, tally) => sum + tally.total, 0),
  accuracy: null,
  per_entity: perEntity,
  per_confidence: {},
});

const run = metrics({
  supplier_name: { matched: 9, total: 10, accuracy: 0.9 },
  id_subject: { matched: 0, total: 10, accuracy: 0 },
  total_amount: { matched: 10, total: 10, accuracy: 1 },
});

test("excluding nothing leaves the run's own numbers", () => {
  const scored = scoreWithout(run, []);

  assert.deepEqual(scored, { matched: 19, total: 30, accuracy: 19 / 30 });
});

test("excluding a field takes it out of both halves of the fraction", () => {
  const scored = scoreWithout(run, ["id_subject"]);

  assert.deepEqual(scored, { matched: 19, total: 20, accuracy: 0.95 });
});

test("excluding several fields at once", () => {
  const scored = scoreWithout(run, ["id_subject", "supplier_name"]);

  assert.deepEqual(scored, { matched: 10, total: 10, accuracy: 1 });
});

test("excluding a field a run never scored changes nothing", () => {
  assert.deepEqual(scoreWithout(run, ["currency"]), scoreWithout(run, []));
});

test("excluding everything leaves no accuracy rather than zero", () => {
  const scored = scoreWithout(run, ["id_subject", "supplier_name", "total_amount"]);

  // Nothing was scored, which is not the same as scoring nothing right.
  assert.deepEqual(scored, { matched: 0, total: 0, accuracy: null });
});

test("a run that scored nothing has no accuracy either", () => {
  assert.equal(scoreWithout(metrics({}), []).accuracy, null);
});

test("the fields on offer are every one any run scored, in order", () => {
  const runs = [
    { metrics: metrics({ supplier_name: { matched: 1, total: 1, accuracy: 1 } }) },
    { metrics: run },
  ];

  assert.deepEqual(entitiesIn(runs), ["id_subject", "supplier_name", "total_amount"]);
});
