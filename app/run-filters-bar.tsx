"use client";

import { FilterX } from "lucide-react";
import type { ReactNode } from "react";

import {
  distinctDatasets,
  distinctModels,
  distinctPipelines,
  emptyFilters,
  hasActiveFilters,
  type EvaluationFilters,
} from "../lib/run-filters";
import type { Evaluation } from "../lib/types";

type Props = {
  evaluations: Evaluation[];
  filters: EvaluationFilters;
  setFilters: (filters: EvaluationFilters) => void;
  /** Anything belonging to one view only, such as its own export button. */
  children?: ReactNode;
};

/**
 * One filter bar, shown by both halves of Lab.
 *
 * The table and the charts read the same selection, so they get the same
 * control over it. Two copies of this drifting apart is how one view ends up
 * able to narrow by something the other cannot.
 */
export function RunFiltersBar({ evaluations, filters, setFilters, children }: Props) {
  return (
    <div className="run-filters">
      <label><span>Dataset</span>
        <select value={filters.dataset} onChange={(event) => setFilters({ ...filters, dataset: event.target.value })}>
          <option value="">Any</option>
          {distinctDatasets(evaluations).map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <label><span>Model</span>
        <select value={filters.model} onChange={(event) => setFilters({ ...filters, model: event.target.value })}>
          <option value="">Any</option>
          {distinctModels(evaluations).map((model) => <option key={model} value={model}>{model}</option>)}
        </select>
      </label>
      <label><span>Pipeline</span>
        <select value={filters.pipeline} onChange={(event) => setFilters({ ...filters, pipeline: event.target.value })}>
          <option value="">Any</option>
          {distinctPipelines(evaluations).map((name) => <option key={name} value={name}>{name}</option>)}
        </select>
      </label>
      <label><span>Runs on</span>
        <select value={filters.runsOn} onChange={(event) => setFilters({ ...filters, runsOn: event.target.value as EvaluationFilters["runsOn"] })}>
          <option value="">Anywhere</option>
          <option value="lm_studio">On this machine</option>
          <option value="gemini">Through an API</option>
        </select>
      </label>
      <label><span>From</span>
        <input type="date" value={filters.since} onChange={(event) => setFilters({ ...filters, since: event.target.value })} />
      </label>
      <label><span>Min accuracy %</span>
        <input type="number" min="0" max="100" placeholder="Any" value={filters.minAccuracy} onChange={(event) => setFilters({ ...filters, minAccuracy: event.target.value })} />
      </label>
      <label><span>Min documents</span>
        <input type="number" min="0" placeholder="Any" value={filters.minDocuments} onChange={(event) => setFilters({ ...filters, minDocuments: event.target.value })} />
      </label>
      {children}
      <button type="button" className="secondary-button small" disabled={!hasActiveFilters(filters)} onClick={() => setFilters(emptyFilters)}>
        <FilterX size={13} /> Clear
      </button>
    </div>
  );
}
