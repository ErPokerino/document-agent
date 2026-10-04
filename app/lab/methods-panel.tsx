"use client";

import { FlaskConical, LoaderCircle } from "lucide-react";
import { useState } from "react";

import { api } from "../../lib/api";
import { percent } from "../../lib/format";
import { defaultResolution } from "../../lib/resolution";
import { InfoHint } from "../components/info-hint";
import { RuleEditor } from "../pipelines/resolve-settings";
import type { FieldMethods, Metrics, ResolutionConfig, ResolutionTrial } from "../../lib/types";

/**
 * Which method was right, field by field, and what another rule would have scored.
 *
 * The oracle column is the share of documents on which at least one method
 * proposed the right value: the most any rule choosing among these methods
 * could reach.
 */
export function MethodsPanel({ evaluationId, methods, metrics }: { evaluationId: number; methods: FieldMethods[]; metrics: Metrics }) {
  const [rule, setRule] = useState<ResolutionConfig>(defaultResolution());
  const [trial, setTrial] = useState<ResolutionTrial | null>(null);
  const [trying, setTrying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const names = [...new Set(methods.flatMap((field) => field.methods.map((method) => method.method)))];

  async function tryRule() {
    setTrying(true);
    setError(null);
    try {
      setTrial(await api.tryResolution(evaluationId, rule));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setTrying(false);
    }
  }

  return (
    <div className="methods-panel">
      <h4>
        Methods
        <InfoHint text="Every step that wrote a field left a candidate. Each method is scored on its own answer; Oracle is the share of documents where at least one method was right — the most a rule choosing among them could reach." />
      </h4>
      <div className="confusion-scroll">
        <table className="classification-table">
          <thead>
            <tr>
              <th>Field</th>
              {names.map((name) => <th key={name}><code>{name}</code></th>)}
              <th>Chosen</th>
              <th>Oracle</th>
              {trial && <th>With the rule below</th>}
            </tr>
          </thead>
          <tbody>
            {methods.map((field) => {
              const tried = trial?.per_entity[field.entity];
              return (
                <tr key={field.entity}>
                  <td><code>{field.entity}</code></td>
                  {names.map((name) => {
                    const scored = field.methods.find((method) => method.method === name);
                    return <td key={name} title={scored ? `${scored.correct} of ${scored.documents} right, ${scored.answered} answered` : "Not proposed for this field"}>{scored ? percent(scored.accuracy) : "—"}</td>;
                  })}
                  <td><strong>{percent(field.resolved_accuracy)}</strong></td>
                  <td>{percent(field.oracle_accuracy)}</td>
                  {trial && <td className={tried && field.resolved_accuracy !== null && tried.accuracy !== null && tried.accuracy !== field.resolved_accuracy ? (tried.accuracy > field.resolved_accuracy ? "better" : "worse") : ""}>{percent(tried?.accuracy)}</td>}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="methods-trial">
        <RuleEditor label="Try a rule on this run" rule={rule.default} methods={names} onChange={(next) => { setRule({ ...rule, default: next }); setTrial(null); }} />
        <button className="secondary-button small" disabled={trying} onClick={() => void tryRule()}>
          {trying ? <LoaderCircle className="spin" size={13} /> : <FlaskConical size={13} />} Score it
        </button>
        {trial && (
          <p className="field-help">
            Over every scored field: <strong>{percent(trial.accuracy)}</strong> with this rule, {percent(metrics.accuracy)} as run.
            Nothing was read or called again; the run itself is unchanged.
          </p>
        )}
        {error && <p className="field-warning">{error}</p>}
      </div>
    </div>
  );
}
