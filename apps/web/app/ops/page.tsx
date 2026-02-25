import { getApiUsage, getManagerUniverse } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

export default async function OpsPage() {
  const [universe, usage] = await Promise.all([getManagerUniverse(300), getApiUsage(7, 100)]);

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Ops Console</h1>
        <p className="page-subtitle">
          Manager universe and API usage telemetry (last 7 days). This is the control plane for scoped ingestion.
        </p>
      </div>

      <div className="card">
        <h3>Automated Pipeline (CLI)</h3>
        <pre>
python -m app.cli pipeline-run --top-n 300 --ingest-limit 20 --recent-quarters 4 --min-holders 3 --min-total-value-usd 250000000
        </pre>
      </div>

      <div className="card">
        <h3>Manager Universe</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Manager</th>
                <th>CIK</th>
                <th>Total Value (USD)</th>
                <th>As Of</th>
              </tr>
            </thead>
            <tbody>
              {universe.rows.map((row) => (
                <tr key={row.manager_id}>
                  <td>{row.rank}</td>
                  <td>{row.manager_name}</td>
                  <td>{row.cik ?? "-"}</td>
                  <td>{fmtNumber(row.total_value_usd ?? 0, 0)}</td>
                  <td>{row.as_of_report_date}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>API Usage Summary</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Provider</th>
                  <th>Calls</th>
                  <th>OK</th>
                  <th>Errors</th>
                  <th>Avg Latency (ms)</th>
                </tr>
              </thead>
              <tbody>
                {usage.summary.map((row) => (
                  <tr key={row.provider}>
                    <td>{row.provider}</td>
                    <td>{fmtNumber(row.calls)}</td>
                    <td>{fmtNumber(row.ok_calls)}</td>
                    <td>{fmtNumber(row.error_calls)}</td>
                    <td>{fmtNumber(row.avg_latency_ms, 1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>Recent API Calls</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Provider</th>
                  <th>Status</th>
                  <th>Latency</th>
                </tr>
              </thead>
              <tbody>
                {usage.recent.slice(0, 30).map((row, i) => (
                  <tr key={`${row.provider}-${i}-${row.request_ts}`}>
                    <td>{row.request_ts}</td>
                    <td>{row.provider}</td>
                    <td>{row.status_code ?? "-"}</td>
                    <td>{fmtNumber(row.latency_ms ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
