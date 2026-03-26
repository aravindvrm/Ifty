import { FlowDistributionHistogram } from "@/components/flow-distribution-histogram";
import { TopMoversColumn } from "@/components/top-movers-column";
import { getHomeOverview } from "@/lib/api";
import { fmtNumber, fmtUsd } from "@/lib/format";

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
      <section className="rounded-none p-6 shadow-panel">
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

  return (
    <div className="space-y-10">
      <section>
        <article className="rounded-none p-5 shadow-panel">
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3 xl:gap-0">
            {columns.map((column, index) => (
              <div
                key={column.key}
                className={index === 0 ? "xl:pr-3" : "xl:border-l xl:border-line/70 xl:px-3"}
              >
                <TopMoversColumn title={column.title} columnKey={column.key} rows={column.rows} />
              </div>
            ))}
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

    </div>
  );
}
