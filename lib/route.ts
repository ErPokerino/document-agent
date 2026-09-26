/**
 * The address bar is the navigation.
 *
 * The shell used to keep its section in component state, so a refresh
 * returned to the workspace and the back button did nothing. The hash is
 * the record: a Lab run and its filters, and the dataset that was open.
 */

import type { EvaluationFilters } from "./run-filters.ts";

export const VIEWS = [
  "workspace",
  "extraction",
  "pipelines",
  "master-data",
  "datasets",
  "lab",
  "llm",
  "processors",
  "settings",
] as const;

export type AppView = (typeof VIEWS)[number];

export type AppRoute = {
  view: AppView;
  dataset: string | null;
  evaluationId: number | null;
  filters: EvaluationFilters;
};

const LIST_FILTERS = ["model", "pipeline", "dataset", "runsOn"] as const;

function blank(): AppRoute {
  return {
    view: "workspace",
    dataset: null,
    evaluationId: null,
    filters: { model: [], pipeline: [], dataset: [], runsOn: [], since: "", minAccuracy: "", minDocuments: "" },
  };
}

export function parseHash(hash: string): AppRoute {
  const route = blank();
  const bare = hash.replace(/^#/, "");
  const [path, query = ""] = bare.split("?");
  const parts = path.split("/").filter(Boolean);
  if ((VIEWS as readonly string[]).includes(parts[0] ?? "")) route.view = parts[0] as AppView;
  if (route.view === "datasets" && parts[1]) route.dataset = decodeURIComponent(parts[1]);
  if (route.view === "lab" && parts[1] && /^\d+$/.test(parts[1])) route.evaluationId = Number(parts[1]);

  const params = new URLSearchParams(query);
  for (const key of LIST_FILTERS) {
    const value = params.get(key);
    if (value) route.filters[key] = value.split("\u001f").filter(Boolean);
  }
  route.filters.since = params.get("since") ?? "";
  route.filters.minAccuracy = params.get("minAccuracy") ?? "";
  route.filters.minDocuments = params.get("minDocuments") ?? "";
  return route;
}

export function formatHash(route: AppRoute): string {
  let path = `#/${route.view}`;
  if (route.view === "datasets" && route.dataset) path += `/${encodeURIComponent(route.dataset)}`;
  if (route.view === "lab" && route.evaluationId !== null) path += `/${route.evaluationId}`;
  if (route.view !== "lab") return path;

  const params = new URLSearchParams();
  for (const key of LIST_FILTERS) {
    if (route.filters[key].length) params.set(key, route.filters[key].join("\u001f"));
  }
  if (route.filters.since) params.set("since", route.filters.since);
  if (route.filters.minAccuracy) params.set("minAccuracy", route.filters.minAccuracy);
  if (route.filters.minDocuments) params.set("minDocuments", route.filters.minDocuments);
  const query = params.toString();
  return query ? `${path}?${query}` : path;
}
