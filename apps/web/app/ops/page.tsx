import { getAiObservability, getApiUsage, getInstitutionUniverse, getPipelineRunLatest } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import { OpsControls } from "@/components/ops-controls";

export default async function OpsPage() {
  let universe;
  let usage;
  let pipeline;
  let aiObs;
  try {
    [universe, usage, pipeline, aiObs] = await Promise.all([
      getInstitutionUniverse(300),
      getApiUsage(7, 100),
      getPipelineRunLatest(),
      getAiObservability(7, 100),
    ]);
  } catch (error) {
    return (
      <section className="rounded-none p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Ops Console</h1>
        <p className="mt-2 text-sm text-slate-400">Failed to load ops data.</p>
        <pre className="mt-3 overflow-auto rounded-none border border-line/70 bg-black/35 p-3 text-xs text-rose-200">
          {String(error)}
        </pre>
      </section>
    );
  }

  const current = pipeline.current;
  const latestCountsEvent =
    [...pipeline.events].reverse().find((event) => {
      const m = (event.metrics ?? {}) as Record<string, unknown>;
      return !!m["final_counts"] || !!m["counts"];
    }) ?? current;
  const latestCountsMetrics = ((latestCountsEvent?.metrics ?? {}) as Record<string, unknown>) ?? {};
  const finalCounts =
    (latestCountsMetrics["final_counts"] as Record<string, unknown> | undefined) ??
    (latestCountsMetrics["counts"] as Record<string, unknown> | undefined) ??
    {};

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Ops Console</h1>
        <p className="mt-2 text-sm text-slate-400">
          Institution universe and API usage telemetry (last 7 days). This is the control plane for scoped ingestion.
        </p>
      </section>

      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Automated Pipeline (CLI)</h2>
        <pre className="mt-3 overflow-auto rounded-none border border-line/70 bg-black/30 p-3 text-xs text-slate-300">
{`python -m app.cli pipeline-run --top-n 300 --ingest-limit 20 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000`}
        </pre>
        <pre className="mt-2 overflow-auto rounded-none border border-line/70 bg-black/30 p-3 text-xs text-slate-300">
{`python -m app.cli update-incremental --top-n 300 --ingest-limit 20 --resolve-quarters 6 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --log-file logs/incremental.jsonl`}
        </pre>
      </section>

      <OpsControls />

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">LLM Runtime Guardrails</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <tbody>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Enabled</th>
                  <td className="px-3 py-2 text-slate-300">{aiObs.runtime.enabled ? "Yes" : "No"}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Model</th>
                  <td className="px-3 py-2 text-slate-300">{aiObs.runtime.model}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Endpoint</th>
                  <td className="px-3 py-2 text-slate-300">{aiObs.runtime.base_origin || "-"}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">API Key</th>
                  <td className="px-3 py-2 text-slate-300">{aiObs.runtime.api_key_configured ? "Configured" : "Missing"}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Max Steps</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(aiObs.runtime.max_steps)}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Max Output Tokens</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(aiObs.runtime.max_output_tokens)}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">History Messages</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(aiObs.runtime.max_history_messages)}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Message Chars</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(aiObs.runtime.max_message_chars)}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Tool Result Chars</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(aiObs.runtime.max_tool_result_chars)}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">SQL Fallback</th>
                  <td className="px-3 py-2 text-slate-300">{aiObs.runtime.sql_fallback_enabled ? "Enabled" : "Disabled"}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">LLM Request Health</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Window</th>
                  <th className="px-3 py-2 text-right">Calls</th>
                  <th className="px-3 py-2 text-right">Errors</th>
                  <th className="px-3 py-2 text-right">Avg (ms)</th>
                  <th className="px-3 py-2 text-right">P95 (ms)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {aiObs.usage_windows.map((row) => (
                  <tr key={row.window}>
                    <td className="px-3 py-2">{row.window}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.calls)}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.error_calls)}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.avg_latency_ms, 1)}</td>
                    <td className="px-3 py-2 text-right">{row.p95_latency_ms == null ? "-" : fmtNumber(row.p95_latency_ms, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="overflow-x-auto rounded-none border border-line/70">
              <table className="min-w-full divide-y divide-line/60 text-sm">
                <thead>
                  <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2 text-right">Calls</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/50 text-slate-300">
                  {aiObs.status_breakdown.map((row, i) => (
                    <tr key={`${row.status_code ?? "null"}-${i}`}>
                      <td className="px-3 py-2">{row.status_code ?? "-"}</td>
                      <td className="px-3 py-2 text-right">{fmtNumber(row.calls)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="overflow-x-auto rounded-none border border-line/70">
              <table className="min-w-full divide-y divide-line/60 text-sm">
                <thead>
                  <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">Model</th>
                    <th className="px-3 py-2 text-right">Calls (7d)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/50 text-slate-300">
                  {aiObs.model_calls.map((row) => (
                    <tr key={row.model}>
                      <td className="px-3 py-2">{row.model}</td>
                      <td className="px-3 py-2 text-right">{fmtNumber(row.calls)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Latest Pipeline Run</h2>
        {pipeline.run_id ? (
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <tbody>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Run ID</th>
                  <td className="px-3 py-2 text-slate-300">{pipeline.run_id}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Current Stage</th>
                  <td className="px-3 py-2 text-slate-300">{current?.stage ?? "-"}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Status</th>
                  <td className="px-3 py-2 text-slate-300">{current?.status ?? "-"}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Message</th>
                  <td className="px-3 py-2 text-slate-300">{current?.message ?? "-"}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Mapped 13F</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(Number(finalCounts["mapped_13f"] ?? 0))}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Unmapped 13F</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(Number(finalCounts["unmapped_13f"] ?? 0))}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Mapped BO</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(Number(finalCounts["mapped_bo"] ?? 0))}</td>
                </tr>
                <tr>
                  <th className="bg-black/20 px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-500">Unmapped BO</th>
                  <td className="px-3 py-2 text-slate-300">{fmtNumber(Number(finalCounts["unmapped_bo"] ?? 0))}</td>
                </tr>
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-3 text-sm text-slate-400">No pipeline runs logged yet.</p>
        )}
      </section>

      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Institution Universe</h2>
        <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
          <table className="min-w-full divide-y divide-line/60 text-sm">
            <thead>
              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Rank</th>
                <th className="px-3 py-2">Institution</th>
                <th className="px-3 py-2">CIK</th>
                <th className="px-3 py-2 text-right">Total Value (USD)</th>
                <th className="px-3 py-2">As Of</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {universe.rows.map((row) => (
                <tr key={row.manager_id}>
                  <td className="px-3 py-2">{row.rank}</td>
                  <td className="px-3 py-2">{row.manager_name}</td>
                  <td className="px-3 py-2">{row.cik ?? "-"}</td>
                  <td className="px-3 py-2 text-right">{fmtNumber(row.total_value_usd ?? 0, 0)}</td>
                  <td className="px-3 py-2">{row.as_of_report_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">API Usage Summary</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Provider</th>
                  <th className="px-3 py-2 text-right">Calls</th>
                  <th className="px-3 py-2 text-right">OK</th>
                  <th className="px-3 py-2 text-right">Errors</th>
                  <th className="px-3 py-2 text-right">Avg Latency (ms)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {usage.summary.map((row) => (
                  <tr key={row.provider}>
                    <td className="px-3 py-2">{row.provider}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.calls)}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.ok_calls)}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.error_calls)}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.avg_latency_ms, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">Recent API Calls</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Time</th>
                  <th className="px-3 py-2">Provider</th>
                  <th className="px-3 py-2 text-right">Status</th>
                  <th className="px-3 py-2 text-right">Latency</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {usage.recent.slice(0, 30).map((row, i) => (
                  <tr key={`${row.provider}-${i}-${row.request_ts}`}>
                    <td className="px-3 py-2">{row.request_ts}</td>
                    <td className="px-3 py-2">{row.provider}</td>
                    <td className="px-3 py-2 text-right">{row.status_code ?? "-"}</td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.latency_ms ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Recent LLM Calls</h2>
        <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
          <table className="min-w-full divide-y divide-line/60 text-sm">
            <thead>
              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Endpoint</th>
                <th className="px-3 py-2 text-right">Status</th>
                <th className="px-3 py-2 text-right">Latency (ms)</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {aiObs.recent.slice(0, 40).map((row, i) => (
                <tr key={`${row.request_ts}-${i}`}>
                  <td className="px-3 py-2">{row.request_ts}</td>
                  <td className="px-3 py-2">{row.endpoint}</td>
                  <td className="px-3 py-2 text-right">{row.status_code ?? "-"}</td>
                  <td className="px-3 py-2 text-right">{fmtNumber(row.latency_ms ?? 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
