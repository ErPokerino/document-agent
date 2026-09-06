"use client";

import { MultiFilter } from "./multi-filter";
import { engineKey, engineOptionLabel } from "../lib/extraction-engine";
import { FilterX } from "lucide-react";
import type { ReactNode } from "react";

import {
  distinctDatasets,
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
  const engineOptions = [...new Map(evaluations.map(run => [engineKey(run), {
    value: engineKey(run), label: engineOptionLabel(run),
  }])).values()].sort((a, b) => a.label.localeCompare(b.label));
  const locations: Record<string, string> = { lm_studio: "On this machine", gemini: "Through an API", none: "No LLM" };
  const selections = (["dataset", "model", "pipeline", "runsOn"] as const).flatMap(facet => filters[facet].map(value => ({
    facet, value, label: facet === "model" ? engineOptions.find(option => option.value === value)?.label || "Unavailable engine" : facet === "runsOn" ? locations[value] || value : value,
  })));
  return (
    <div className="run-filters">
      <MultiFilter label="Dataset" options={distinctDatasets(evaluations).map(value => ({ value, label: value }))} value={filters.dataset} onChange={dataset => setFilters({ ...filters, dataset })} />
      <MultiFilter label="Extraction engine" options={engineOptions} value={filters.model} onChange={model => setFilters({ ...filters, model })} />
      <MultiFilter label="Pipeline" options={distinctPipelines(evaluations).map(value => ({ value, label: value }))} value={filters.pipeline} onChange={pipeline => setFilters({ ...filters, pipeline })} />
      <MultiFilter label="LLM runs on" options={[{ value: "lm_studio", label: "On this machine" }, { value: "gemini", label: "Through an API" }, { value: "none", label: "No LLM" }]} value={filters.runsOn} onChange={runsOn => setFilters({ ...filters, runsOn })} />
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
      {selections.length > 0 && <div className="filter-selections" aria-label="Active filters">{selections.map(({ facet, value, label }) => <button key={facet + value} type="button" title={label} aria-label={`Remove ${facet}: ${label}`} onClick={() => setFilters({ ...filters, [facet]: filters[facet].filter(item => item !== value) })}>{label}<span aria-hidden="true"> ×</span></button>)}</div>}
    </div>
  );
}
