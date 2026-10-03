/**
 * Geometry for the classification panel, kept apart from React so it can be
 * tested: where a coverage point sits, and how dark a confusion cell is.
 */

import type { CoveragePointResult } from "./types";

export type Plot = { width: number; height: number; left: number; right: number; top: number; bottom: number };

export const COVERAGE_PLOT: Plot = { width: 340, height: 190, left: 40, right: 12, top: 10, bottom: 30 };

export type PlacedPoint = CoveragePointResult & { x: number; y: number };

/**
 * Coverage along x and accuracy along y, both on 0–100%.
 *
 * Both axes start at zero: a curve drawn from 80% would make a two-point
 * difference look like a cliff.
 */
export function placeCoverage(points: CoveragePointResult[], plot: Plot = COVERAGE_PLOT): PlacedPoint[] {
  const innerWidth = plot.width - plot.left - plot.right;
  const innerHeight = plot.height - plot.top - plot.bottom;
  return [...points]
    .sort((a, b) => a.coverage - b.coverage)
    .map((point) => ({
      ...point,
      x: plot.left + point.coverage * innerWidth,
      y: plot.top + (1 - point.accuracy) * innerHeight,
    }));
}

export function linePath(points: Pick<PlacedPoint, "x" | "y">[]): string {
  return points.map((point, index) => `${index ? "L" : "M"}${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ");
}

/** 0 for an empty cell, up to 1 for the fullest one in the matrix. */
export function cellWeight(count: number, matrix: number[][]): number {
  const largest = Math.max(0, ...matrix.flat());
  return largest ? count / largest : 0;
}

/** How a threshold reads: a similarity to two places, a band by its name. */
export function thresholdLabel(threshold: number, rankedBy: string): string {
  if (rankedBy === "confidence") return ({ 3: "high", 2: "medium or higher", 1: "any" } as Record<number, string>)[threshold] ?? String(threshold);
  return `≥ ${threshold.toFixed(2)}`;
}
