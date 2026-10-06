import { useState } from "react";
import { api } from "../../lib/api";
import { formatUsd } from "../../lib/cost";
import type { UsageDetail } from "../../lib/types";

/** The stored charges include unsuccessful attempts and keep their original rates. */
export function UsageDetails({ evaluationId, runId }: { evaluationId?: number; runId?: number }) {
  const [detail, setDetail] = useState<UsageDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  async function load() {
    setLoading(true);
    setError("");
    try {
      setDetail(evaluationId !== undefined ? await api.evaluationUsage(evaluationId) : await api.runUsage(runId!));
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setLoading(false);
    }
  }
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(detail, null, 2)], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `usage-${evaluationId ?? runId}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }
  return <details onToggle={event => { if (event.currentTarget.open && !detail && !loading) void load(); }}>
    <summary>Usage and recorded prices</summary>
    {loading && <p>Loading usage…</p>}
    {error && <p className="alert error-alert">{error}</p>}
    {detail && <>
      <p>{detail.cost.status === "complete" ? formatUsd(detail.cost.total_usd) : `${detail.cost.status} · known charges ${formatUsd(detail.cost.known_usd)}`} · {detail.cost.calls} attempts. Estimates use the tariff stored with each request; GCP billing remains authoritative.</p>
      <button onClick={download}>Download usage and tariffs</button>
      <div className="table-scroll"><table><thead><tr><th>Document / step</th><th>Model / location</th><th>Status</th><th>Input / cache / output</th><th>Cost</th></tr></thead><tbody>
        {detail.records.map(record => <tr key={record.id}><td>{record.document}<small>{record.step}</small></td>
          <td>{record.model}<small>{record.location}</small></td><td>{record.status} {record.http_status}</td>
          <td>{record.input_tokens ?? "?"} / {record.cached_tokens} / {record.output_tokens ?? "?"}</td>
          <td>{formatUsd(record.cost.total_usd)}<small>{record.cost.status}</small></td></tr>)}
      </tbody></table></div>
    </>}
  </details>;
}
