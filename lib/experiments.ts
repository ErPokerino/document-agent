/**
 * The experiment grid, as the Lab previews and shows it.
 *
 * `planGrid` mirrors `plan_cells` in the backend so the preview a person
 * checks before starting is the plan that runs: a pipeline that calls no
 * model is one cell, and a pipeline that sends page images is not paired with
 * a model known not to read them.
 */

import { usesModel } from "./pipeline-steps.ts";
import type { Experiment, ExperimentCell, ExperimentCellScore, ModelInfo, PipelineStep } from "./types";

export type ModelPick = Pick<ModelInfo, "id" | "name" | "provider" | "vision" | "capabilities_known">;
export type PipelinePick = { name: string; steps: Pick<PipelineStep, "kind">[] };

export type PlannedCell = {
  pipeline: string;
  model: string | null;
  state: "runs" | "once" | "skipped";
  reason?: string;
};

/** Whether a model in this pipeline is handed page images, as `requires_vision` decides. */
export function sendsImages(steps: Pick<PipelineStep, "kind">[]): boolean {
  let images = false;
  for (const step of steps) {
    if (step.kind === "llm_extract" && images) return true;
    if (step.kind === "render_pages") images = true;
  }
  return false;
}

export function planGrid(pipelines: PipelinePick[], models: ModelPick[]): PlannedCell[] {
  const cells: PlannedCell[] = [];
  for (const pipeline of pipelines) {
    if (!usesModel(pipeline.steps.map((step) => step.kind))) {
      cells.push({ pipeline: pipeline.name, model: null, state: "once" });
      continue;
    }
    for (const model of models) {
      const blind = model.vision === false && model.capabilities_known !== false;
      cells.push(
        sendsImages(pipeline.steps) && blind
          ? { pipeline: pipeline.name, model: model.id, state: "skipped", reason: "Sends page images; this model does not read images." }
          : { pipeline: pipeline.name, model: model.id, state: "runs" },
      );
    }
  }
  return cells;
}

export function runCount(cells: PlannedCell[]): number {
  return cells.filter((cell) => cell.state !== "skipped").length;
}

/** What starting the plan would do, in one line, before anything runs. */
export function planSummary(cells: PlannedCell[], documents: number): string {
  const runs = runCount(cells);
  const skipped = cells.length - runs;
  const parts = [`${runs} run${runs === 1 ? "" : "s"}`];
  if (documents) parts.push(`${runs * documents} document extractions (${documents} labelled documents each)`);
  if (skipped) parts.push(`${skipped} cell${skipped === 1 ? "" : "s"} skipped`);
  return parts.join(" · ");
}

/** The columns of the result grid: models in the order chosen, then "no model" when a pipeline needs none. */
export function gridColumns(experiment: Pick<Experiment, "cells">): { key: string; label: string; provider: string }[] {
  const columns: { key: string; label: string; provider: string }[] = [];
  for (const cell of experiment.cells) {
    const key = `${cell.provider}\u0000${cell.model}`;
    if (!columns.some((column) => column.key === key)) {
      columns.push({ key, label: cell.provider === "none" ? "No model called" : cell.model, provider: cell.provider });
    }
  }
  return columns.sort((a, b) => Number(a.provider === "none") - Number(b.provider === "none"));
}

export function gridRows(experiment: Pick<Experiment, "cells">): string[] {
  return [...new Set(experiment.cells.map((cell) => cell.pipeline))];
}

export function cellAt(experiment: Pick<Experiment, "cells">, pipeline: string, columnKey: string): ExperimentCell | undefined {
  return experiment.cells.find((cell) => cell.pipeline === pipeline && `${cell.provider}\u0000${cell.model}` === columnKey);
}

export function cellName(cell: Pick<ExperimentCell, "pipeline" | "provider" | "model">): string {
  return cell.provider === "none" ? cell.pipeline : `${cell.pipeline} · ${cell.model}`;
}

export function interval(score: Pick<ExperimentCellScore, "low" | "high">): string {
  return `${Math.round(score.low * 100)}–${Math.round(score.high * 100)}%`;
}

export function signedPoints(value: number): string {
  const points = Math.round(value * 1000) / 10;
  return `${points > 0 ? "+" : points < 0 ? "−" : "±"}${Math.abs(points).toFixed(1)} pt`;
}

export const VERDICT_LABELS: Record<ExperimentCellScore["verdict"], string> = {
  best: "Best",
  indistinguishable: "Not distinguishable from the best",
  worse: "Worse than the best",
};

export function finishedCells(experiment: Pick<Experiment, "cells">): number {
  return experiment.cells.filter((cell) => !["pending", "loading", "running"].includes(cell.status) && cell.status !== "skipped").length;
}

export function runnableCells(experiment: Pick<Experiment, "cells">): number {
  return experiment.cells.filter((cell) => cell.status !== "skipped").length;
}
