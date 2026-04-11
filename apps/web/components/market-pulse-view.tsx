import { DailyBriefingPanel } from "@/components/daily-briefing-panel";
import { FlowDistributionHistogram } from "@/components/flow-distribution-histogram";
import { Top13DGColumn } from "@/components/top-13dg-column";
import { TopMoversColumn } from "@/components/top-movers-column";
import { TickerIcon } from "@/components/ticker-icon";
import { getHomeOverview, getInsiderClusters, getInsiderFeed, getSignalScorecards } from "@/lib/api";
import { fmtNumber, fmtUsd } from "@/lib/format";
import Link from "next/link";

const TICKER_PATTERN = /^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$/;
const DERIVATIVE_NAME_PATTERN =
  /\b(?:OPTION|WARRANT|RIGHT|NOTE|BOND|DEBT|PFD|PREFERRED)\b|(?:\b\d+(?:\.\d+)?\s+\d{2}\/\d{2}\/\d{2}\b)/i;

function isDisplayableMover(row: { ticker: string | null; security_name: string | null }) {
  const ticker = (row.ticker ?? "").trim().toUpperCase();
  if (!TICKER_PATTERN.test(ticker)) {
    return false;
  }
  const securityName = (row.security_name ?? "").trim();
  if (securityName && DERIVATIVE_NAME_PATTERN.test(securityName)) {
    return false;
  }
  return true;
}

export async function MarketPulseView() {
  let overview;
  try {
    overview = await getHomeOverview({ quartersN: 8, topN: 10, scatterN: 0 });
  } catch (error) {
    return (
      <section className="rounded-none p-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Institutional Flow Dashboard</h1>
        <p className="mt-2 text-sm text-slate-400">Failed to load homepage analytics.</p>
        <pre className="mt-3 overflow-auto rounded-none border border-line/70 bg-black/35 p-3 text-xs text-rose-200">
          {String(error)}
        </pre>
      </section>
    );
  }

  const columns = [
    { key: "accumulated", title: "Top Accumulated (QoQ)", rows: overview.top_movers.accumulated.filter(isDisplayableMover) },
    { key: "distributed", title: "Top Distributed (QoQ)", rows: overview.top_movers.distributed.filter(isDisplayableMover) },
    { key: "new_holders", title: "Most New Holders (QoQ)", rows: overview.top_movers.new_holders.filter(isDisplayableMover) },
  ] as const;
  const flowBins = overview.flow_distribution.bins ?? [];
  const flowFilters = overview.flow_distribution.filters ?? {};

  const [insiderBuysResult, insiderSellsResult, insiderClustersResult, scorecardsResult] = await Promise.allSettled([
    getInsiderFeed({
      days: 30,
      limitN: 6,
      signalType: "OPEN_MARKET_BUY",
    }),
    getInsiderFeed({
      days: 30,
      limitN: 6,
      signalType: "OPEN_MARKET_SELL",
    }),
    getInsiderClusters({
      days: 30,
      limitN: 6,
      minDistinctInsiders: 2,
      signalType: "OPEN_MARKET_BUY",
    }),
    getSignalScorecards({
      days: 365,
      minSamples: 5,
    }),
  ]);
  const insiderBuys = insiderBuysResult.status === "fulfilled" ? insiderBuysResult.value.rows : [];
  const insiderSells = insiderSellsResult.status === "fulfilled" ? insiderSellsResult.value.rows : [];
  const insiderClusters = insiderClustersResult.status === "fulfilled" ? insiderClustersResult.value.rows : [];
  const insiderLoadFailed =
    insiderBuysResult.status === "rejected" ||
    insiderSellsResult.status === "rejected" ||
    insiderClustersResult.status === "rejected";
  const scorecards = scorecardsResult.status === "fulfilled" ? scorecardsResult.value.rows : [];
  const scorecardsFailed = scorecardsResult.status === "rejected";

  return (
    <div className="space-y-10">
      <section>
        <article className="rounded-none p-5">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-4 xl:gap-0">
            {columns.map((column, index) => (
              <div
                key={column.key}
                className={index === 0 ? "xl:pr-3" : "xl:border-l xl:border-line/70 xl:px-3"}
              >
                <TopMoversColumn title={column.title} columnKey={column.key} rows={column.rows} />
              </div>
            ))}
            <div className="xl:border-l xl:border-line/70 xl:pl-3">
              <Top13DGColumn title="13 D/G Activity" />
            </div>
          </div>
        </article>
      </section>

      <section>
        <article className="rounded-none p-0">
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-100">Flow Distribution (QoQ Value)</h2>
            <span className="text-xs text-slate-500">
              {fmtNumber(overview.flow_distribution.total_securities)} securities
            </span>
          </div>
          {overview.flow_distribution.total_securities > 0 && flowBins.length > 0 ? (
            <div className="space-y-3">
              <FlowDistributionHistogram
                bins={flowBins}
                totalSecurities={overview.flow_distribution.total_securities}
              />
              <p className="text-xs text-slate-500">
                Net value ($) QoQ distribution for latest ({overview.latest_quarter ?? "-"}) vs previous (
                {overview.previous_quarter ?? "-"}) quarter, clipped to p01-p99.
              </p>
              <p className="text-[11px] text-slate-600">
                Filters: holders &ge; {fmtNumber(flowFilters.min_holders ?? 10)}, value &ge;{" "}
                {fmtUsd(flowFilters.min_total_value_usd ?? 50_000_000)}. Bins: Freedman-Diaconis (30-100), log-height.
              </p>
            </div>
          ) : (
            <p className="mt-3 text-sm text-slate-500">No flow distribution data available yet.</p>
          )}
        </article>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">Insider Activity</h2>
          <Link href="/activity/insiders" className="text-xs uppercase tracking-[0.12em] text-slate-400 transition hover:text-slate-100">
            View All
          </Link>
        </div>
        <article className="rounded-none p-5">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3 xl:gap-0">
            <div className="xl:pr-3">
              <h2 className="text-base font-semibold text-slate-100">Insider Open-Market Buys (30d)</h2>
              <div className="mt-3 overflow-x-auto rounded-none border border-line/70">
                <table className="min-w-full divide-y divide-line/60 text-sm">
                  <thead>
                    <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="px-3 py-2">Ticker</th>
                      <th className="px-3 py-2 text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/50 text-slate-300">
                    {insiderBuys.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="px-3 py-4 text-center text-xs text-slate-500">
                          {insiderLoadFailed ? "Insider feed unavailable." : "No buy activity in window."}
                        </td>
                      </tr>
                    ) : (
                      insiderBuys.map((row) => (
                        <tr key={`insider-buy-${row.insider_tx_id}`}>
                          <td className="px-3 py-2">
                            {row.ticker ? (
                              <Link
                                prefetch={false}
                                href={`/security/${encodeURIComponent(row.ticker)}`}
                                className="inline-flex min-w-0 items-center gap-2 text-accentBlue hover:text-white"
                              >
                                <TickerIcon ticker={row.ticker} label={row.issuer_name} />
                                <span className="font-medium">{row.ticker}</span>
                              </Link>
                            ) : (
                              row.issuer_name || "-"
                            )}
                          </td>
                          <td className="px-3 py-2 text-right text-emerald-300">
                            {row.transaction_value_usd === null ? "-" : fmtUsd(row.transaction_value_usd)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="xl:border-l xl:border-line/70 xl:px-3">
              <h2 className="text-base font-semibold text-slate-100">Insider Open-Market Sells (30d)</h2>
              <div className="mt-3 overflow-x-auto rounded-none border border-line/70">
                <table className="min-w-full divide-y divide-line/60 text-sm">
                  <thead>
                    <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="px-3 py-2">Ticker</th>
                      <th className="px-3 py-2 text-right">Value</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/50 text-slate-300">
                    {insiderSells.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="px-3 py-4 text-center text-xs text-slate-500">
                          {insiderLoadFailed ? "Insider feed unavailable." : "No sell activity in window."}
                        </td>
                      </tr>
                    ) : (
                      insiderSells.map((row) => (
                        <tr key={`insider-sell-${row.insider_tx_id}`}>
                          <td className="px-3 py-2">
                            {row.ticker ? (
                              <Link
                                prefetch={false}
                                href={`/security/${encodeURIComponent(row.ticker)}`}
                                className="inline-flex min-w-0 items-center gap-2 text-accentBlue hover:text-white"
                              >
                                <TickerIcon ticker={row.ticker} label={row.issuer_name} />
                                <span className="font-medium">{row.ticker}</span>
                              </Link>
                            ) : (
                              row.issuer_name || "-"
                            )}
                          </td>
                          <td className="px-3 py-2 text-right text-rose-300">
                            {row.transaction_value_usd === null ? "-" : fmtUsd(row.transaction_value_usd)}
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="xl:border-l xl:border-line/70 xl:pl-3">
              <h2 className="text-base font-semibold text-slate-100">Insider Cluster Buys (30d)</h2>
              <div className="mt-3 overflow-x-auto rounded-none border border-line/70">
                <table className="min-w-full divide-y divide-line/60 text-sm">
                  <thead>
                    <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                      <th className="px-3 py-2">Ticker</th>
                      <th className="px-3 py-2 text-right">Insiders</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-line/50 text-slate-300">
                    {insiderClusters.length === 0 ? (
                      <tr>
                        <td colSpan={2} className="px-3 py-4 text-center text-xs text-slate-500">
                          {insiderLoadFailed ? "Cluster screener unavailable." : "No cluster buys in window."}
                        </td>
                      </tr>
                    ) : (
                      insiderClusters.map((row, idx) => (
                        <tr key={`insider-cluster-${row.security_id ?? row.ticker ?? idx}`}>
                          <td className="px-3 py-2">
                            {row.ticker ? (
                              <Link
                                prefetch={false}
                                href={`/security/${encodeURIComponent(row.ticker)}`}
                                className="inline-flex min-w-0 items-center gap-2 text-accentBlue hover:text-white"
                              >
                                <TickerIcon ticker={row.ticker} label={row.issuer_name} />
                                <span className="font-medium">{row.ticker}</span>
                              </Link>
                            ) : (
                              row.issuer_name || "-"
                            )}
                          </td>
                          <td className="px-3 py-2 text-right text-slate-200">{fmtNumber(row.distinct_insiders)}</td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">Signal Scorecards</h2>
          <span className="text-xs text-slate-500">1 year follow-through</span>
        </div>
        <article className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <div className="overflow-x-auto border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Signal</th>
                  <th className="px-3 py-2 text-right">Samples</th>
                  <th className="px-3 py-2 text-right">Hit Rate</th>
                  <th className="px-3 py-2 text-right">Median Follow-Through</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {scorecards.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-3 py-4 text-center text-xs text-slate-500">
                      {scorecardsFailed ? "Scorecards unavailable." : "No scorecard data yet."}
                    </td>
                  </tr>
                ) : (
                  scorecards.map((row) => (
                    <tr key={row.signal_id}>
                      <td className="px-3 py-2">
                        <div className="text-slate-100">{row.label}</div>
                        <div className="mt-0.5 text-[11px] text-slate-500">{row.direction}</div>
                      </td>
                      <td className="px-3 py-2 text-right">{fmtNumber(row.sample_n)}</td>
                      <td className="px-3 py-2 text-right">
                        {row.hit_rate_pct === null || row.hit_rate_pct === undefined ? "-" : `${row.hit_rate_pct.toFixed(1)}%`}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {row.median_follow_through_value_usd === null || row.median_follow_through_value_usd === undefined
                          ? "-"
                          : fmtUsd(row.median_follow_through_value_usd)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>
      </section>

      <DailyBriefingPanel />

    </div>
  );
}
