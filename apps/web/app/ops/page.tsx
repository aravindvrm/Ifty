import { getApiUsage, getInstitutionUniverse, getPipelineRunLatest } from "@/lib/api";
import { fmtNumber } from "@/lib/format";
import { OpsControls } from "@/components/ops-controls";

export default async function OpsPage() {
  let universe;
  let usage;
  let pipeline;
  try {
    [universe, usage, pipeline] = await Promise.all([getInstitutionUniverse(300), getApiUsage(7, 100), getPipelineRunLatest()]);
  } catch (error) {
    return (
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Ops Console</h1>
        <p className="mt-2 text-sm text-slate-400">Failed to load ops data.</p>
        <pre className="mt-3 overflow-auto rounded-xl border border-line/70 bg-black/35 p-3 text-xs text-rose-200">
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
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Ops Console</h1>
        <p className="mt-2 text-sm text-slate-400">
          Institution universe and API usage telemetry (last 7 days). This is the control plane for scoped ingestion.
        </p>
      </section>

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Automated Pipeline (CLI)</h2>
        <pre className="mt-3 overflow-auto rounded-xl border border-line/70 bg-black/30 p-3 text-xs text-slate-300">
{`python -m app.cli pipeline-run --top-n 300 --ingest-limit 20 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000`}
        </pre>
        <pre className="mt-2 overflow-auto rounded-xl border border-line/70 bg-black/30 p-3 text-xs text-slate-300">
{`python -m app.cli update-incremental --top-n 300 --ingest-limit 20 --resolve-quarters 6 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000 --log-file logs/incremental.jsonl`}
        </pre>
      </section>

      <OpsControls />

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Latest Pipeline Run</h2>
        {pipeline.run_id ? (
          <div className="mt-4 overflow-x-auto rounded-xl border border-line/70">
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

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Institution Universe</h2>
        <div className="mt-4 overflow-x-auto rounded-xl border border-line/70">
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
        <div className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">API Usage Summary</h2>
          <div className="mt-4 overflow-x-auto rounded-xl border border-line/70">
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

        <div className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">Recent API Calls</h2>
          <div className="mt-4 overflow-x-auto rounded-xl border border-line/70">
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
    </div>
  );
}
