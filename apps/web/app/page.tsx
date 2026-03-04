import { Sparkline } from "@/components/charts";
import { FlowDistributionHistogram } from "@/components/flow-distribution-histogram";
import { TopMoversColumn } from "@/components/top-movers-column";
import { getHomeOverview } from "@/lib/api";
import { fmtNumber, fmtPct, fmtUsd } from "@/lib/format";

type SparkPoint = { report_date: string; net_shares: number; net_holder_count: number };

function toSpark(series: Array<{ report_date: string; value: number }>): SparkPoint[] {
  return series.map((point) => ({
    report_date: point.report_date,
    net_shares: Number(point.value ?? 0),
    net_holder_count: 0,
  }));
}

function fmtSignedUsd(value: number): string {
  if (value > 0) return `+${fmtUsd(value)}`;
  return fmtUsd(value);
}

function toneClass(value: number): string {
  return value >= 0 ? "text-emerald-300" : "text-rose-300";
}

function histogramTone(rangeStartUsd: number, rangeEndUsd: number): string {
  const midpoint = (rangeStartUsd + rangeEndUsd) / 2;
  if (midpoint < 0) {
    return "bg-rose-400/80";
  }
  if (midpoint > 0) {
    return "bg-emerald-400/80";
  }
  return "bg-accentBlue/80";
}

function fmtUsdAxis(value: number): string {
  if (!Number.isFinite(value)) return "$0";
  const abs = Math.abs(value);
  if (abs >= 1000) {
    return fmtUsd(value);
  }
  return `$${value.toFixed(2)}`;
}

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

export default async function HomePage() {
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

  const pulseCards = [
    {
      title: "Breadth: Net Accumulation",
      value: fmtPct(overview.pulse.breadth_accum_pct),
      subtitle: `${fmtNumber(overview.pulse.accum_count)} of ${fmtNumber(overview.pulse.universe_count)} securities`,
      spark: toSpark(overview.pulse_series.breadth_accum_pct),
    },
    {
      title: "Participation: Adders",
      value: fmtPct(overview.pulse.participation_increase_pct),
      subtitle: `${fmtNumber(overview.pulse.holders_added)} adds vs ${fmtNumber(overview.pulse.holders_trimmed)} trims`,
      spark: toSpark(overview.pulse_series.participation_increase_pct),
    },
    {
      title: "Net 13F Value Change QoQ",
      value: fmtSignedUsd(overview.pulse.net_value_change_usd),
      subtitle: `Latest quarter ${overview.latest_quarter ?? "-"}`,
      spark: toSpark(overview.pulse_series.net_value_change_usd),
      valueClass: toneClass(overview.pulse.net_value_change_usd),
    },
  ];

  const columns = [
    { key: "accumulated", title: "Top Accumulated (QoQ)", rows: overview.top_movers.accumulated.filter(isDisplayableMover) },
    { key: "distributed", title: "Top Distributed (QoQ)", rows: overview.top_movers.distributed.filter(isDisplayableMover) },
    { key: "new_holders", title: "Most New Holders (QoQ)", rows: overview.top_movers.new_holders.filter(isDisplayableMover) },
  ] as const;
  const flowBins = overview.flow_distribution.bins ?? [];
  const flowFilters = overview.flow_distribution.filters ?? {};

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6 shadow-panel">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="text-3xl font-semibold tracking-tight text-slate-100">Market Pulse</h1>
            <p className="mt-2 text-sm text-slate-400">
              Normalized institutional breadth, participation, value-weighted flow, and 13D/G activity.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
            <div className="rounded-none border border-line/80 bg-black/25 px-3 py-2 text-slate-300">
              <div className="text-slate-500">Latest Quarter</div>
              <div className="mt-1 text-sm font-semibold text-slate-100">{overview.latest_quarter ?? "-"}</div>
            </div>
            <div className="rounded-none border border-line/80 bg-black/25 px-3 py-2 text-slate-300">
              <div className="text-slate-500">Previous Quarter</div>
              <div className="mt-1 text-sm font-semibold text-slate-100">{overview.previous_quarter ?? "-"}</div>
            </div>
            <div className="rounded-none border border-line/80 bg-black/25 px-3 py-2 text-slate-300">
              <div className="text-slate-500">Active Universe</div>
              <div className="mt-1 text-sm font-semibold text-slate-100">
                {fmtNumber(overview.pulse.universe_count)}
              </div>
            </div>
            <div className="rounded-none border border-line/80 bg-black/25 px-3 py-2 text-slate-300">
              <div className="text-slate-500">Mapped Coverage</div>
              <div className="mt-1 text-sm font-semibold text-slate-100">
                {fmtPct(overview.trust.mapping_coverage_pct_latest_quarter)}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {pulseCards.map((card) => (
          <article key={card.title} className="rounded-none border border-line/80 bg-card/80 p-4 shadow-panel">
            <div className="text-xs uppercase tracking-wide text-slate-500">{card.title}</div>
            <div className={`mt-2 text-2xl font-semibold ${card.valueClass ?? "text-slate-100"}`}>{card.value}</div>
            <div className="mt-1 text-xs text-slate-500">{card.subtitle}</div>
            <div className="mt-3 h-12 rounded-none border border-line/70 bg-black/20 p-1">
              <Sparkline data={card.spark} />
            </div>
          </article>
        ))}
      </section>

      <section>
        <article className="rounded-none p-5 shadow-panel">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-lg font-semibold text-slate-100">Top Movers</h2>
            <span className="text-xs text-slate-500">Ranked by latest QoQ aggregate movement</span>
          </div>
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
        <article className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
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

      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-slate-100">Coverage & Trust</h2>
          <span className="text-xs text-slate-500">Latest data integrity and universe coverage snapshot</span>
        </div>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <div className="rounded-none border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Institutions in Universe</div>
            <div className="mt-1 text-xl font-semibold text-slate-100">
              {fmtNumber(overview.trust.managers_in_universe)}
            </div>
          </div>
          <div className="rounded-none border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Institutions with Positions</div>
            <div className="mt-1 text-xl font-semibold text-slate-100">
              {fmtNumber(overview.trust.managers_with_positions)}
            </div>
          </div>
          <div className="rounded-none border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Mapped Rows (Latest Quarter)</div>
            <div className="mt-1 text-xl font-semibold text-slate-100">
              {fmtNumber(overview.trust.holdings_rows_latest_quarter)}
            </div>
          </div>
          <div className="rounded-none border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">Mapping Coverage</div>
            <div className="mt-1 text-xl font-semibold text-slate-100">
              {fmtPct(overview.trust.mapping_coverage_pct_latest_quarter)}
            </div>
          </div>
          <div className="rounded-none border border-line/70 bg-black/20 p-3">
            <div className="text-xs text-slate-500">13D/G Breadth (30d)</div>
            <div className="mt-1 text-sm text-slate-300">
              {fmtNumber(overview.bo_activity_30d.unique_filers)} filers /{" "}
              {fmtNumber(overview.bo_activity_30d.unique_securities)} securities
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
