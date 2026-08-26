"use client";

import { ArrowRight, GitCompare, LoaderCircle } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "../lib/api";
import { diffRuns, type FieldChange, type RunDiff } from "../lib/run-diff";
import type { Evaluation, EvaluationDetail } from "../lib/types";
import { InfoHint } from "./info-hint";

type Props = {
  evaluations: Evaluation[];
};

const DIRECTION_LABELS: Record<FieldChange["direction"], string> = {
  fixed: "fixed",
  broken: "regressed",
  changed: "still wrong",
  added: "new field",
  removed: "gone",
};

/**
 * Two runs held against each other, field by field.
 *
 * Chosen deliberately rather than computed for whatever happens to be on
 * screen: comparing two runs is a question someone asks about a specific
 * change they made, and the pair has to be theirs to pick.
 */
/** One answered comparison, remembered with the pair it answers for. */
type Comparison = {
  before: number;
  after: number;
  pair: [EvaluationDetail, EvaluationDetail] | null;
  diff: RunDiff | null;
  error: string | null;
};

export function RunDiffPanel({ evaluations }: Props) {
  const [beforeId, setBeforeId] = useState<number | "">("");
  const [afterId, setAfterId] = useState<number | "">("");
  // One piece of state, written only when an answer arrives. Everything the
  // panel shows is then read off the selection: what was loaded for another
  // pair is simply not this pair's answer, so nothing has to be cleared when
  // the selects change — and clearing state to mirror state is what made this
  // component cascade renders.
  const [answered, setAnswered] = useState<Comparison | null>(null);

  const scorable = evaluations.filter((evaluation) => evaluation.status !== "running");
  const pairChosen = beforeId !== "" && afterId !== "" && beforeId !== afterId;

  useEffect(() => {
    if (!pairChosen) return;
    let cancelled = false;
    const before = Number(beforeId);
    const after = Number(afterId);
    Promise.all([api.evaluation(before), api.evaluation(after)])
      .then(([first, second]) => {
        if (cancelled) return;
        setAnswered({
          before,
          after,
          pair: [first, second],
          diff: diffRuns(first, second),
          error: null,
        });
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setAnswered({
          before,
          after,
          pair: null,
          diff: null,
          error: requestError instanceof Error ? requestError.message : "Those runs could not be read.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [beforeId, afterId, pairChosen]);

  const current =
    pairChosen && answered !== null && answered.before === Number(beforeId) && answered.after === Number(afterId)
      ? answered
      : null;
  // A pair is chosen and its answer is not in yet.
  const busy = pairChosen && current === null;
  const shownDiff = current?.diff ?? null;
  const shownPair = current?.pair ?? null;
  const error = current?.error ?? null;

  const mismatch =
    shownPair !== null && shownPair[0].dataset !== shownPair[1].dataset
      ? `${shownPair[0].dataset} against ${shownPair[1].dataset}`
      : null;

  return (
    <div className="settings-card">
      <div className="settings-card-heading">
        <span className="settings-card-icon"><GitCompare size={18} /></span>
        <div>
          <h3>
            Compare two runs
            <InfoHint text="Field by field, over the documents both runs reached. The aggregates above answer which approach is better; this answers whether one change helped, which is a different question — a prompt edit that fixes two documents and breaks two others reads as no change at all." />
          </h3>
          <p>Pick a run and something to compare it against.</p>
        </div>
      </div>

      <div className="diff-pick">
        <label>
          <span>Before</span>
          <select value={beforeId} onChange={(event) => setBeforeId(event.target.value === "" ? "" : Number(event.target.value))}>
            <option value="">Choose a run…</option>
            {scorable.map((evaluation) => (
              <option key={evaluation.id} value={evaluation.id}>
                #{evaluation.id} · {evaluation.model} · {evaluation.pipeline}
              </option>
            ))}
          </select>
        </label>
        <ArrowRight size={14} className="diff-arrow" />
        <label>
          <span>After</span>
          <select value={afterId} onChange={(event) => setAfterId(event.target.value === "" ? "" : Number(event.target.value))}>
            <option value="">Choose a run…</option>
            {scorable.map((evaluation) => (
              <option key={evaluation.id} value={evaluation.id}>
                #{evaluation.id} · {evaluation.model} · {evaluation.pipeline}
              </option>
            ))}
          </select>
        </label>
        {busy && <LoaderCircle className="spin" size={15} />}
      </div>

      {error && <p className="field-help">{error}</p>}

      {mismatch && (
        <p className="compare-caution">
          These runs are over different datasets — {mismatch}. Only documents appearing in both are compared.
        </p>
      )}

      {shownDiff && (
        <>
          <div className="diff-totals">
            <span className="diff-total fixed"><b>{shownDiff.summary.fixed}</b> fixed</span>
            <span className="diff-total broken"><b>{shownDiff.summary.broken}</b> regressed</span>
            <span className="diff-total changed"><b>{shownDiff.summary.changed}</b> still wrong, differently</span>
            <span className="diff-total"><b>{shownDiff.summary.unchanged}</b> unchanged</span>
            <span className={`diff-net ${shownDiff.summary.net > 0 ? "good" : shownDiff.summary.net < 0 ? "poor" : ""}`}>
              {shownDiff.summary.net > 0 ? `+${shownDiff.summary.net}` : shownDiff.summary.net} net
            </span>
          </div>

          {(shownDiff.onlyInBefore.length > 0 || shownDiff.onlyInAfter.length > 0 || shownDiff.failedAfter.length > 0) && (
            <p className="field-help">
              {shownDiff.onlyInBefore.length > 0 && `${shownDiff.onlyInBefore.length} document${shownDiff.onlyInBefore.length === 1 ? "" : "s"} only in the first run. `}
              {shownDiff.onlyInAfter.length > 0 && `${shownDiff.onlyInAfter.length} only in the second. `}
              {shownDiff.failedAfter.length > 0 && `${shownDiff.failedAfter.length} failed in the second run and could not be compared.`}
            </p>
          )}

          {shownDiff.byDocument.length === 0 ? (
            <div className="models-empty">
              <GitCompare size={18} />
              <span>Every field both runs scored came out the same.</span>
            </div>
          ) : (
            <div className="runs-table-wrap">
              <table className="runs-table compare-table">
                <thead>
                  <tr>
                    <th>Document</th>
                    <th>Field</th>
                    <th>Before</th>
                    <th>After</th>
                    <th>Expected</th>
                    <th>Change</th>
                  </tr>
                </thead>
                <tbody>
                  {shownDiff.byDocument.flatMap((entry) =>
                    entry.changes.map((change, index) => (
                      <tr key={`${entry.document}-${change.entity}`}>
                        <td>{index === 0 ? entry.document : ""}</td>
                        <td className="compare-row-label"><strong>{change.entity}</strong></td>
                        <td className={change.before?.matched ? "good" : ""}>{describe(change.before?.value)}</td>
                        <td className={change.after?.matched ? "good" : ""}>{describe(change.after?.value)}</td>
                        <td className="compare-expected">{describe(change.expected)}</td>
                        <td><span className={`diff-tag ${change.direction}`}>{DIRECTION_LABELS[change.direction]}</span></td>
                      </tr>
                    )),
                  )}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function describe(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  return String(value);
}
