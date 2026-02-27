import Link from "next/link";

import { PositionTreemap } from "@/components/charts";
import { getManager } from "@/lib/api";
import { fmtNumber, fmtPct, fmtUsdThousands } from "@/lib/format";

type Props = { params: Promise<{ managerKey: string }> };

export default async function ManagerPage({ params }: Props) {
  const { managerKey } = await params;

  let manager;
  try {
    manager = await getManager(managerKey);
  } catch (error) {
    return (
      <div className="card">
        <h1 className="page-title">Manager {managerKey}</h1>
        <p className="page-subtitle">Failed to load manager data.</p>
        <pre>{String(error)}</pre>
      </div>
    );
  }

  const treemapData = manager.top_positions.map((p) => ({
    name: `${p.issuer_name_raw ?? "Unknown"}`,
    size: Number(p.value_usd_thousands ?? 0)
  }));

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Manager: {manager.manager.manager_name}</h1>
        <p className="page-subtitle">CIK {manager.manager.cik} • Latest quarter {manager.latest_quarter ?? "-"}</p>
        <div className="input-row">
          <Link href="/manager">Back to manager directory</Link>
        </div>
      </div>

      <div className="metric-row">
        <div className="metric">
          <div className="label">Turnover</div>
          <div className="value">{fmtPct(manager.metrics.turnover_ratio ?? 0)}</div>
        </div>
        <div className="metric">
          <div className="label">Top 10 Concentration</div>
          <div className="value">{fmtPct(manager.metrics.top10_concentration_pct ?? 0)}</div>
        </div>
        <div className="metric">
          <div className="label">New / Exited Positions</div>
          <div className="value">
            {fmtNumber(manager.metrics.new_positions_count ?? 0)} / {fmtNumber(manager.metrics.exited_positions_count ?? 0)}
          </div>
        </div>
        <div className="metric">
          <div className="label">Portfolio Value</div>
          <div className="value">{fmtUsdThousands((manager.metrics.total_value_current ?? 0) / 1000)}</div>
        </div>
      </div>

      <PositionTreemap data={treemapData} />

      <div className="grid-2">
        <div className="card">
          <h3>Top Buys QoQ</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Security</th>
                  <th>Delta Value (13F k$)</th>
                </tr>
              </thead>
              <tbody>
                {manager.top_buys.length === 0 ? (
                  <tr>
                    <td colSpan={2}>No buys in current comparison window.</td>
                  </tr>
                ) : (
                  manager.top_buys.map((row, idx) => (
                    <tr key={`${row.security_id}-${idx}`}>
                      <td>{row.issuer_name_raw ?? "Unknown"}</td>
                      <td className="badge-pos">{fmtNumber(row.delta_val, 2)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="card">
          <h3>Top Sells QoQ</h3>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Security</th>
                  <th>Delta Value (13F k$)</th>
                </tr>
              </thead>
              <tbody>
                {manager.top_sells.length === 0 ? (
                  <tr>
                    <td colSpan={2}>No sells in current comparison window.</td>
                  </tr>
                ) : (
                  manager.top_sells.map((row, idx) => (
                    <tr key={`${row.security_id}-${idx}`}>
                      <td>{row.issuer_name_raw ?? "Unknown"}</td>
                      <td className="badge-neg">{fmtNumber(row.delta_val, 2)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="card">
        <h3>Current Top Positions</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Security</th>
                <th>Shares</th>
                <th>Value</th>
              </tr>
            </thead>
              <tbody>
                {manager.top_positions.length === 0 ? (
                  <tr>
                    <td colSpan={3}>No mapped positions available.</td>
                  </tr>
                ) : (
                  manager.top_positions.map((row, idx) => (
                    <tr key={`${row.security_id}-${idx}`}>
                      <td>{row.issuer_name_raw ?? "Unknown"}</td>
                      <td>{fmtNumber(row.shares)}</td>
                      <td>{fmtUsdThousands(row.value_usd_thousands)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
        </div>
      </div>
    </div>
  );
}
