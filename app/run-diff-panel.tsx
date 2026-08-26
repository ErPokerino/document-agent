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
export function RunDiffPanel({ evaluations }: Props) {
  const [beforeId, setBeforeId] = useState<number | "">("");
  const [afterId, setAfterId] = useState<number | "">("");
  const [diff, setDiff] = useState<RunDiff | null>(null);
  const [pair, setPair] = useState<[EvaluationDetail, EvaluationDetail] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const scorable = evaluations.filter((evaluation) => evaluation.status !== "running");

  useEffect(() => {
    if (beforeId === "" || afterId === "" || beforeId === afterId) {
      setDiff(null);
      setPair(null);
      return;
    }
    let cancelled = false;
    setBusy(true);
    setError(null);
    Promise.all([api.evaluation(Number(beforeId)), api.evaluation(Number(afterId))])
      .then(([before, after]) => {
        if (cancelled) return;
        setPair([before, after]);
        setDiff(diffRuns(before, after));
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setError(requestError instanceof Error ? requestError.message : "Those runs could not be read.");
        setDiff(null);
      })
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
  }, [beforeId, afterId]);

  const mismatch =
    pair !== null && pair[0].dataset !== pair[1].dataset ? `${pair[0].dataset} against ${pair[1].dataset}` : null;

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

      {diff && (
        <>
          <div className="diff-totals">
            <span className="diff-total fixed"><b>{diff.summary.fixed}</b> fixed</span>
            <span className="diff-total broken"><b>{diff.summary.broken}</b> regressed</span>
            <span className="diff-total changed"><b>{diff.summary.changed}</b> still wrong, differently</span>
            <span className="diff-total"><b>{diff.summary.unchanged}</b> unchanged</span>
            <span className={`diff-net ${diff.summary.net > 0 ? "good" : diff.summary.net < 0 ? "poor" : ""}`}>
              {diff.summary.net > 0 ? `+${diff.summary.net}` : diff.summary.net} net
            </span>
          </div>

          {(diff.onlyInBefore.length > 0 || diff.onlyInAfter.length > 0 || diff.failedAfter.length > 0) && (
            <p className="field-help">
              {diff.onlyInBefore.length > 0 && `${diff.onlyInBefore.length} document${diff.onlyInBefore.length === 1 ? "" : "s"} only in the first run. `}
              {diff.onlyInAfter.length > 0 && `${diff.onlyInAfter.length} only in the second. `}
              {diff.failedAfter.length > 0 && `${diff.failedAfter.length} failed in the second run and could not be compared.`}
            </p>
          )}

          {diff.byDocument.length === 0 ? (
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
                  {diff.byDocument.flatMap((entry) =>
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
