"use client";

import { ArrowDown, ArrowUp } from "lucide-react";

import { STRATEGY_HELP, STRATEGY_LABELS, moveInList, priorityWithAll } from "../lib/resolution";
import { InfoHint } from "./info-hint";
import type { FieldRule, ResolutionConfig } from "../lib/types";

const STRATEGIES = Object.keys(STRATEGY_LABELS) as FieldRule["strategy"][];

/** One rule: a strategy, and for priority the order of trust and a score floor. */
export function RuleEditor({ rule, methods, onChange, label }: {
  rule: FieldRule;
  methods: string[];
  onChange: (rule: FieldRule) => void;
  label: string;
}) {
  const order = priorityWithAll(rule.priority, methods);
  return (
    <div className="resolve-rule">
      <label className="flow-field">
        <span>{label}<InfoHint text={STRATEGY_HELP[rule.strategy]} /></span>
        <select aria-label={label} value={rule.strategy} onChange={(event) => onChange({ ...rule, strategy: event.target.value as FieldRule["strategy"], priority: order })}>
          {STRATEGIES.map((strategy) => <option key={strategy} value={strategy}>{STRATEGY_LABELS[strategy]}</option>)}
        </select>
      </label>
      {rule.strategy === "priority" && (
        <ol className="priority-list">
          {order.map((method, position) => {
            const listed = rule.priority.includes(method);
            return (
              <li key={method} className={listed ? "" : "excluded"}>
                <label>
                  <input
                    type="checkbox"
                    checked={listed}
                    onChange={() => onChange({ ...rule, priority: listed ? rule.priority.filter((entry) => entry !== method) : order.filter((entry) => entry === method || rule.priority.includes(entry)) })}
                  />
                  <code>{method}</code>
                </label>
                <button type="button" className="icon-button" aria-label={`Trust ${method} more`} disabled={position === 0} onClick={() => onChange({ ...rule, priority: moveInList(order, position, -1).filter((entry) => rule.priority.includes(entry)) })}><ArrowUp size={12} /></button>
                <button type="button" className="icon-button" aria-label={`Trust ${method} less`} disabled={position === order.length - 1} onClick={() => onChange({ ...rule, priority: moveInList(order, position, 1).filter((entry) => rule.priority.includes(entry)) })}><ArrowDown size={12} /></button>
              </li>
            );
          })}
          {order.length === 0 && <li className="excluded">No step before this one writes fields.</li>}
        </ol>
      )}
      {rule.strategy !== "last" && (
        <label className="flow-field">
          <span>Ignore scores below<InfoHint text="A candidate that carries a score — a similarity — below this is passed over. One without a score, such as a model's answer, is not judged by it. Empty means no floor." /></span>
          <input
            type="number" min={0} max={1} step={0.05} aria-label={`${label}: minimum score`}
            value={rule.minimum_score ?? ""}
            placeholder="No floor"
            onChange={(event) => onChange({ ...rule, minimum_score: event.target.value === "" ? null : Number(event.target.value) })}
          />
        </label>
      )}
    </div>
  );
}

/** The Resolve step: a default rule, and a different one for any field that needs it. */
export function ResolveSettings({ config, methods, fields, onChange }: {
  config: ResolutionConfig;
  methods: string[];
  fields: string[];
  onChange: (config: ResolutionConfig) => void;
}) {
  return (
    <div className="flow-step-body">
      <RuleEditor label="Every field" rule={config.default} methods={methods} onChange={(rule) => onChange({ ...config, default: rule })} />
      <details className="resolve-fields">
        <summary>A different rule for a field</summary>
        {fields.map((name) => {
          const own = config.fields[name];
          return (
            <div key={name} className="resolve-field">
              <label className="training-checkbox">
                <input
                  type="checkbox"
                  checked={Boolean(own)}
                  onChange={() => {
                    const next = { ...config.fields };
                    if (own) delete next[name];
                    else next[name] = { ...config.default };
                    onChange({ ...config, fields: next });
                  }}
                />
                <code>{name}</code>
              </label>
              {own && <RuleEditor label={name} rule={own} methods={methods} onChange={(rule) => onChange({ ...config, fields: { ...config.fields, [name]: rule } })} />}
            </div>
          );
        })}
      </details>
      <p className="field-help">
        Every step that writes a field leaves a candidate; this step chooses among those written before it.
        The Lab scores each method separately, and can try another rule on a finished run without running it again.
      </p>
    </div>
  );
}
