import type { Evaluation, ModelInfo } from "./types";

const RENDERS_IMAGES = "render_pages";

/**
 * What is worth saying before a run on the app's most expensive configuration.
 *
 * This used to predict the cost: "minutes rather than seconds", "one full page
 * image per document". Both were assumptions frozen into a sentence. The first
 * described one machine — move the app to a workstation with a discrete GPU and
 * it becomes false with nothing to catch it. The second described one setting:
 * the page limit belongs to the pipeline and changes between runs.
 *
 * So nothing here is predicted. When a comparable run exists, its measured
 * average is reported, along with the page limit it was measured at — a reader
 * who has changed that since can see the number no longer describes their next
 * run. When none exists, only the shape of the configuration is stated, and how
 * long that turns out to take is left to the run to answer.
 */
export function runWarning(
  model: ModelInfo | undefined,
  steps: string[],
  history: Evaluation[],
  pipeline: string,
): string | null {
  if (!model || model.provider === "gemini") return null;
  if (!model.requires_safe_profile) return null;
  if (!steps.includes(RENDERS_IMAGES)) return null;

  const measured = mostRecentComparable(history, model.id, pipeline);
  if (measured?.average_elapsed_ms != null) {
    const pages = measured.max_pages === 1 ? "1 page" : `${measured.max_pages} pages`;
    return (
      `The last run of "${pipeline}" with ${model.name} averaged ` +
      `${(measured.average_elapsed_ms / 1000).toFixed(1)} s per document, at a limit of ${pages}.`
    );
  }

  return (
    `${model.name} is loaded with its layers held on the processor, and this pipeline ` +
    `sends it rendered page images rather than text.`
  );
}

/** The newest finished run of the same model on the same pipeline. */
function mostRecentComparable(
  history: Evaluation[],
  modelId: string,
  pipeline: string,
): Evaluation | undefined {
  return history
    .filter(
      (evaluation) =>
        evaluation.model === modelId &&
        evaluation.pipeline === pipeline &&
        evaluation.average_elapsed_ms != null,
    )
    .sort((a, b) => b.created_at.localeCompare(a.created_at))[0];
}
