/**
 * The runs table as CSV: one row per run, not per document.
 *
 * The per-document export already exists on each run and answers "what did it
 * get wrong". This one answers the other question — how do these runs compare
 * — so it carries the whole configuration a comparison needs: pipeline, model,
 * page limit, timing, tokens, pages and cost.
 *
 * Built from the filtered rows the browser is already showing, so what you
 * export is what you are looking at.
 */

import { totalCost } from "./cost.ts";
import { scoreWithout } from "./scoring-view.ts";
import type { AppSettings, Evaluation } from "./types";

const COLUMNS = [
  "run_id",
  "created_at",
  "dataset",
  "pipeline",
  "model",
  "runs_on",
  "execution_profile",
  "parameters",
  "quantization",
  "model_size_bytes",
  "context_length",
  "parallel",
  "seed",
  "thinking_level",
  "status",
  "max_pages",
  "documents",
  "succeeded",
  "failed",
  "matched",
  "scored_fields",
  "accuracy",
  "total_seconds",
  "average_seconds",
  "prompt_tokens",
  "completion_tokens",
  "ocr_pages",
  "layout_pages",
  "cost_usd",
] as const;

type Rates = Pick<AppSettings, "gemini" | "gcp"> | { pricing: AppSettings["gemini"]["pricing"]; gcp: AppSettings["gcp"] } | null;

function pricingFor(rates: Rates, model: string) {
  if (!rates) return undefined;
  const pricing = "gemini" in rates ? rates.gemini.pricing : rates.pricing;
  return pricing?.[model];
}

function cell(value: string | number | null | undefined): string {
  if (value === null || value === undefined) return "";
  const text = String(value);
  // Quote only when it matters, so the common case stays readable by eye.
  return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function seconds(ms: number | null): string {
  return ms === null || ms === undefined ? "" : (ms / 1000).toFixed(1);
}

export function runsToCsv(
  evaluations: Evaluation[],
  rates: Rates,
  // The fields left out of the accuracy on screen are left out here too:
  // what you export is what you are looking at.
  excluded: string[] = [],
): string {
  const lines = [COLUMNS.join(",")];

  for (const run of evaluations) {
    const cost = totalCost(
      {
        promptTokens: run.prompt_tokens,
        completionTokens: run.completion_tokens,
        ocrPages: run.ocr_pages,
        layoutPages: run.layout_pages,
      },
      pricingFor(rates, run.model),
      rates ? ("gemini" in rates ? rates.gcp : rates.gcp) : null,
    );

    const score = scoreWithout(run.metrics, excluded);

    lines.push(
      [
        run.id,
        run.created_at,
        run.dataset,
        run.pipeline,
        run.model,
        run.provider ?? "lm_studio",
        run.execution_profile?.profile,
        run.execution_profile?.parameters,
        run.execution_profile?.quantization,
        run.execution_profile?.model_size_bytes,
        run.execution_profile?.context_length,
        run.execution_profile?.parallel,
        run.execution_profile?.seed,
        run.execution_profile?.thinking_level,
        run.status,
        run.max_pages,
        run.total_documents,
        run.succeeded_documents,
        run.failed_documents,
        score.matched,
        score.total,
        // A run that scored nothing has no accuracy; zero would be a claim.
        score.accuracy === null ? null : score.accuracy.toFixed(4).replace(/0+$/, "").replace(/\.$/, ""),
        seconds(run.total_elapsed_ms),
        seconds(run.average_elapsed_ms),
        run.prompt_tokens,
        run.completion_tokens,
        run.ocr_pages,
        run.layout_pages,
        cost === null ? null : cost.toFixed(4),
      ]
        .map(cell)
        .join(","),
    );
  }

  return `${lines.join("\n")}\n`;
}
