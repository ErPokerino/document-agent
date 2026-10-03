import assert from "node:assert/strict";
import test from "node:test";

import { COVERAGE_PLOT, cellWeight, linePath, placeCoverage, thresholdLabel } from "../lib/classification-view.ts";

test("coverage is drawn left to right whatever order the points arrive in", () => {
  const placed = placeCoverage([
    { threshold: 0.9, answered: 1, coverage: 0.25, accuracy: 1 },
    { threshold: 0.5, answered: 4, coverage: 1, accuracy: 0.5 },
  ]);

  assert.deepEqual(placed.map((point) => point.coverage), [0.25, 1]);
  assert.equal(placed[1].x, COVERAGE_PLOT.width - COVERAGE_PLOT.right);
});

test("accuracy is measured from zero, so a small difference is not drawn as a cliff", () => {
  const [point] = placeCoverage([{ threshold: 0.5, answered: 1, coverage: 1, accuracy: 0 }]);

  assert.equal(point.y, COVERAGE_PLOT.height - COVERAGE_PLOT.bottom);
});

test("the line visits every point in order", () => {
  assert.equal(linePath([{ x: 1, y: 2 }, { x: 3, y: 4 }]), "M1.0,2.0 L3.0,4.0");
});

test("a confusion cell is shaded against the fullest cell", () => {
  assert.equal(cellWeight(2, [[4, 2], [0, 1]]), 0.5);
  assert.equal(cellWeight(0, [[0, 0], [0, 0]]), 0);
});

test("a confidence threshold reads as a band, a score as a number", () => {
  assert.equal(thresholdLabel(2, "confidence"), "medium or higher");
  assert.equal(thresholdLabel(0.8, "score"), "≥ 0.80");
});
