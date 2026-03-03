import Link from "next/link";

import { HoldingsHeatmap, NetAccumulationBarChart } from "@/components/charts";
import { SecurityActivePositionsTable } from "@/components/security-active-positions-table";
import { getSecurity, getSecurityEventsFiltered } from "@/lib/api";
import { fmtNumber, fmtPct, fmtUsd } from "@/lib/format";

type Props = {
  params: Promise<{ ticker: string }>;
  searchParams: Promise<{ start_date?: string; end_date?: string; new_5pct_only?: string }>;
};

function shiftDate(days: number): string {
  const dt = new Date();
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

export default async function SecurityPage({ params, searchParams }: Props) {
  const { ticker } = await params;
  const query = await searchParams;
  const startDate = query.start_date ?? shiftDate(-3650);
  const endDate = query.end_date ?? shiftDate(0);
  const new5PctOnly = query.new_5pct_only === "1";

  let security;
  let events = { security_id: 0, ticker: ticker.toUpperCase(), rows: [] as Array<any> };
  let eventsError = "";
  try {
    security = await getSecurity(ticker);
  } catch (error) {
    return (
      <div className="card">
        <h1 className="page-title">Security: {ticker.toUpperCase()}</h1>
        <p className="page-subtitle">Failed to load security data.</p>
        <pre>{String(error)}</pre>
      </div>
    );
  }
  try {
    events = await getSecurityEventsFiltered(ticker, {
      new5pctOnly: new5PctOnly,
      startDate: startDate,
      endDate: endDate,
      limitN: 300
    });
  } catch (error) {
    eventsError = String(error);
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
  const holdingsHeatmapData = (security.active_positions ?? []).map((row) => ({
    id: row.manager_id,
    name: row.manager_name,
    symbol: null,
    size: Number(row.value_usd_thousands ?? 0),
    delta: Number(row.qoq_delta_shares ?? 0)
  }));

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">{security.ticker} {security.security_name ? `- ${security.security_name}` : ""}</h1>
        <p className="page-subtitle">Last report date: {latestQuarter ?? "-"} • MIC {security.mic || "N/A"} • Security ID {security.security_id}</p>
        <div className="input-row">
          <Link href="/security">Search another security</Link>
          <Link href="/institution">Browse institutions</Link>
        </div>
      </div>

      <div className="metric-row">
        <div className="metric">
          <div className="label">Holders (Latest Q)</div>
          <div className="value">{fmtNumber(security.ownership_summary.holders_count ?? 0)}</div>
        </div>
        <div className="metric">
          <div className="label">Total Shares</div>
          <div className="value">{fmtNumber(security.ownership_summary.total_shares ?? 0)}</div>
        </div>
        <div className="metric">
          <div className="label">Total Value</div>
          <div className="value">{fmtUsd(security.ownership_summary.total_value_usd ?? 0)}</div>
        </div>
        <div className="metric">
          <div className="label">QoQ Net Change (Shares)</div>
          <div className={`value ${(security.ownership_summary.qoq_net_change_shares ?? 0) >= 0 ? "badge-pos" : "badge-neg"}`}>
            {fmtNumber(security.ownership_summary.qoq_net_change_shares ?? 0)}
          </div>
        </div>
        <div className="metric">
          <div className="label">Top 10 Concentration</div>
          <div className="value">{fmtPct(security.ownership_summary.top10_concentration_pct ?? security.concentration.top10_pct ?? 0)}</div>
        </div>
      </div>

      <div className="card">
        <h3>Activity Breakdown</h3>
        <div className="metric-row metric-row-6">
          <div className="metric"><div className="label">Total</div><div className="value">{fmtNumber(security.activity_breakdown.total ?? 0)}</div></div>
          <div className="metric"><div className="label">New</div><div className="value badge-pos">{fmtNumber(security.activity_breakdown.new ?? 0)}</div></div>
          <div className="metric"><div className="label">Increased</div><div className="value badge-pos">{fmtNumber(security.activity_breakdown.increased ?? 0)}</div></div>
          <div className="metric"><div className="label">Decreased</div><div className="value badge-neg">{fmtNumber(security.activity_breakdown.decreased ?? 0)}</div></div>
          <div className="metric"><div className="label">Sold Out</div><div className="value badge-neg">{fmtNumber(security.activity_breakdown.sold_out ?? 0)}</div></div>
          <div className="metric"><div className="label">Activity</div><div className="value">{fmtNumber(security.activity_breakdown.activity ?? 0)}</div></div>
        </div>
      </div>

      <HoldingsHeatmap
        title="Institutional Holdings Heatmap"
        data={holdingsHeatmapData}
        valueLabel="Value (13F)"
        deltaLabel="QoQ Δ Shares"
        labelMode="name"
        valueFormat="usd_thousands"
        deltaFormat="number"
        signedDelta
        maxTiles={56}
        minRelativeSize={0.006}
        minTiles={20}
        emptyText="No active positions available for this security."
      />

      <SecurityActivePositionsTable rows={security.active_positions ?? []} />

      <NetAccumulationBarChart data={barData} />

      <div className="card">
        <h3>13D/G Events Feed</h3>
        {eventsError ? <p className="page-subtitle">Events unavailable: {eventsError}</p> : null}
        <form className="input-row" method="get">
          <input name="start_date" defaultValue={startDate} placeholder="Start (YYYY-MM-DD)" />
          <input name="end_date" defaultValue={endDate} placeholder="End (YYYY-MM-DD)" />
          <label>
            <input type="checkbox" name="new_5pct_only" value="1" defaultChecked={new5PctOnly} /> NEW_5PCT only
          </label>
          <button type="submit">Apply</button>
        </form>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Institution</th>
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
