import Link from "next/link";

import { HoldingsHeatmap, NetAccumulationBarChart } from "@/components/charts";
import { SecurityActivePositionsTable } from "@/components/security-active-positions-table";
import { TickerIcon } from "@/components/ticker-icon";
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
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Security: {ticker.toUpperCase()}</h1>
        <p className="mt-2 text-sm text-slate-400">Failed to load security data.</p>
        <pre className="mt-3 overflow-auto rounded-xl border border-line/70 bg-black/35 p-3 text-xs text-rose-200">
          {String(error)}
        </pre>
      </section>
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
    <div className="space-y-6">
      <section className="rounded-2xl border border-line/80 bg-card/80 p-6 shadow-panel">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h1 className="inline-flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-100">
              <TickerIcon ticker={security.ticker} label={security.security_name} size={22} />
              <span>{security.ticker}</span>
              {security.security_name ? <span className="text-slate-100">- {security.security_name}</span> : null}
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              Last report date: {latestQuarter ?? "-"} • MIC {security.mic || "N/A"} • Security ID {security.security_id}
            </p>
          </div>

          <div className="w-full lg:max-w-[780px]">
            <div className="flex flex-wrap justify-start gap-2 lg:justify-end">
              <Link
                href="/security"
                className="rounded-xl border border-line/80 bg-cardSoft/80 px-3 py-1.5 text-xs text-slate-300 transition hover:border-accentBlue/70 hover:text-white"
              >
                Search another security
              </Link>
              <Link
                href="/institution"
                className="rounded-xl border border-line/80 bg-cardSoft/80 px-3 py-1.5 text-xs text-slate-300 transition hover:border-accentBlue/70 hover:text-white"
              >
                Browse institutions
              </Link>
            </div>
            <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
              <div className="rounded-xl border border-line/80 bg-black/20 p-2.5">
                <div className="text-[11px] text-slate-500">Holders</div>
                <div className="mt-1 text-sm font-semibold text-slate-100">
                  {fmtNumber(security.ownership_summary.holders_count ?? 0)}
                </div>
              </div>
              <div className="rounded-xl border border-line/80 bg-black/20 p-2.5">
                <div className="text-[11px] text-slate-500">Total Shares</div>
                <div className="mt-1 text-sm font-semibold text-slate-100">
                  {fmtNumber(security.ownership_summary.total_shares ?? 0)}
                </div>
              </div>
              <div className="rounded-xl border border-line/80 bg-black/20 p-2.5">
                <div className="text-[11px] text-slate-500">Total Value</div>
                <div className="mt-1 text-sm font-semibold text-slate-100">
                  {fmtUsd(security.ownership_summary.total_value_usd ?? 0)}
                </div>
              </div>
              <div className="rounded-xl border border-line/80 bg-black/20 p-2.5">
                <div className="text-[11px] text-slate-500">QoQ Δ Shares</div>
                <div
                  className={`mt-1 text-sm font-semibold ${
                    (security.ownership_summary.qoq_net_change_shares ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"
                  }`}
                >
                  {fmtNumber(security.ownership_summary.qoq_net_change_shares ?? 0)}
                </div>
              </div>
              <div className="rounded-xl border border-line/80 bg-black/20 p-2.5">
                <div className="text-[11px] text-slate-500">Top 10 Conc.</div>
                <div className="mt-1 text-sm font-semibold text-slate-100">
                  {fmtPct(security.ownership_summary.top10_concentration_pct ?? security.concentration.top10_pct ?? 0)}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Activity Breakdown</h2>
        <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <div className="rounded-xl border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Total</div>
            <div className="mt-1 text-lg font-semibold text-slate-100">{fmtNumber(security.activity_breakdown.total ?? 0)}</div>
          </div>
          <div className="rounded-xl border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">New</div>
            <div className="mt-1 text-lg font-semibold text-emerald-300">{fmtNumber(security.activity_breakdown.new ?? 0)}</div>
          </div>
          <div className="rounded-xl border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Increased</div>
            <div className="mt-1 text-lg font-semibold text-emerald-300">{fmtNumber(security.activity_breakdown.increased ?? 0)}</div>
          </div>
          <div className="rounded-xl border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Decreased</div>
            <div className="mt-1 text-lg font-semibold text-rose-300">{fmtNumber(security.activity_breakdown.decreased ?? 0)}</div>
          </div>
          <div className="rounded-xl border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Sold Out</div>
            <div className="mt-1 text-lg font-semibold text-rose-300">{fmtNumber(security.activity_breakdown.sold_out ?? 0)}</div>
          </div>
          <div className="rounded-xl border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Activity</div>
            <div className="mt-1 text-lg font-semibold text-slate-100">{fmtNumber(security.activity_breakdown.activity ?? 0)}</div>
          </div>
        </div>
      </section>

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

      <section className="rounded-2xl border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">13D/G Events Feed</h2>
        {eventsError ? <p className="mt-2 text-sm text-rose-300">Events unavailable: {eventsError}</p> : null}
        <form className="mt-4 flex flex-wrap items-center gap-2" method="get">
          <input
            name="start_date"
            defaultValue={startDate}
            placeholder="Start (YYYY-MM-DD)"
            className="rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-accentBlue/70"
          />
          <input
            name="end_date"
            defaultValue={endDate}
            placeholder="End (YYYY-MM-DD)"
            className="rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-accentBlue/70"
          />
          <label className="inline-flex items-center gap-2 rounded-xl border border-line/80 bg-cardSoft/70 px-3 py-2 text-xs text-slate-300">
            <input type="checkbox" name="new_5pct_only" value="1" defaultChecked={new5PctOnly} className="h-4 w-4" />
            NEW_5PCT only
          </label>
          <button
            type="submit"
            className="rounded-xl border border-line/80 bg-cardSoft/80 px-3 py-2 text-sm text-slate-200 transition hover:border-accentBlue/70 hover:text-white"
          >
            Apply
          </button>
        </form>
        <div className="mt-4 overflow-x-auto rounded-xl border border-line/70">
          <table className="min-w-full divide-y divide-line/60 text-sm">
            <thead>
              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Institution</th>
                <th className="px-3 py-2">Event</th>
                <th className="px-3 py-2 text-right">Percent Owned</th>
                <th className="px-3 py-2">Form</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {events.rows.map((event, idx) => (
                <tr key={`${event.accession_no}-${idx}`}>
                  <td className="px-3 py-2">{event.report_date}</td>
                  <td className="px-3 py-2">{event.manager_name ?? "Unknown"}</td>
                  <td className="px-3 py-2">{event.event_type}</td>
                  <td className="px-3 py-2 text-right">
                    {event.percent_beneficial_owned === null ? "-" : `${event.percent_beneficial_owned.toFixed(2)}%`}
                  </td>
                  <td className="px-3 py-2">{event.form_type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
