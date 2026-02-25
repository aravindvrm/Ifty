import Link from "next/link";

import { NetAccumulationBarChart } from "@/components/charts";
import { getSecurity, getSecurityEvents } from "@/lib/api";
import { fmtNumber, fmtPct, fmtUsdThousands } from "@/lib/format";

type Props = { params: Promise<{ ticker: string }> };

export default async function SecurityPage({ params }: Props) {
  const { ticker } = await params;

  let security;
  let events;
  try {
    [security, events] = await Promise.all([getSecurity(ticker), getSecurityEvents(ticker)]);
  } catch (error) {
    return (
      <div className="card">
        <h1 className="page-title">Security: {ticker.toUpperCase()}</h1>
        <p className="page-subtitle">Failed to load security data.</p>
        <pre>{String(error)}</pre>
      </div>
    );
  }

  const barData = Object.values(
    security.net_change_last_4q.reduce<Record<string, { report_date: string; net_change_shares: number }>>(
      (acc, row) => {
        const key = row.report_date;
        const existing = acc[key] ?? { report_date: key, net_change_shares: 0 };
        existing.net_change_shares += Number(row.net_change_shares ?? 0);
        acc[key] = existing;
        return acc;
      },
      {}
    )
  ).sort((a, b) => a.report_date.localeCompare(b.report_date));

  const latestQuarter = security.latest_quarter;
  const qoqByManager = new Map<number, number>();
  for (const row of security.net_change_last_4q) {
    if (row.report_date === latestQuarter) {
      qoqByManager.set(row.manager_id, Number(row.net_change_shares ?? 0));
    }
  }

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Security: {security.ticker}</h1>
        <p className="page-subtitle">MIC {security.mic || "N/A"} • Security ID {security.security_id}</p>
        <div className="input-row">
          <input readOnly value="Open another ticker via URL (example: /security/MSFT)" />
          <Link href="/screeners">Back to Screeners</Link>
        </div>
      </div>

      <div className="metric-row">
        <div className="metric">
          <div className="label">Latest Quarter</div>
          <div className="value">{security.latest_quarter ?? "-"}</div>
        </div>
        <div className="metric">
          <div className="label">Top 10 Concentration</div>
          <div className="value">{fmtPct(security.concentration.top10_pct ?? 0)}</div>
        </div>
        <div className="metric">
          <div className="label">Top 10 Shares</div>
          <div className="value">{fmtNumber(security.concentration.top10_shares ?? 0)}</div>
        </div>
        <div className="metric">
          <div className="label">Total Shares</div>
          <div className="value">{fmtNumber(security.concentration.total_shares ?? 0)}</div>
        </div>
      </div>

      <NetAccumulationBarChart data={barData} />

      <div className="card">
        <h3>Top Holders With QoQ Delta</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Manager</th>
                <th>Shares</th>
                <th>Value</th>
                <th>QoQ Delta (Shares)</th>
              </tr>
            </thead>
            <tbody>
              {security.top_holders.map((row) => {
                const delta = qoqByManager.get(row.manager_id) ?? 0;
                return (
                  <tr key={row.manager_id}>
                    <td>{row.manager_name}</td>
                    <td>{fmtNumber(row.shares)}</td>
                    <td>{fmtUsdThousands(row.value_usd_thousands)}</td>
                    <td className={delta >= 0 ? "badge-pos" : "badge-neg"}>{fmtNumber(delta)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>13D/G Events Feed</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Manager</th>
                <th>Event</th>
                <th>Percent Owned</th>
                <th>Form</th>
              </tr>
            </thead>
            <tbody>
              {events.rows.map((event, idx) => (
                <tr key={`${event.accession_no}-${idx}`}>
                  <td>{event.report_date}</td>
                  <td>{event.manager_name ?? "Unknown"}</td>
                  <td>{event.event_type}</td>
                  <td>{event.percent_beneficial_owned === null ? "-" : `${event.percent_beneficial_owned.toFixed(2)}%`}</td>
                  <td>{event.form_type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
