"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { HoldingsHeatmap, NetAccumulationBarChart } from "@/components/charts";
import { LottieLoader } from "@/components/lottie-loader";
import { SecurityActivePositionsTable } from "@/components/security-active-positions-table";
import { TickerIcon } from "@/components/ticker-icon";
import {
  get13DGFeed,
  getInstitution,
  getSecurity,
  getSecurityInsiders,
  getSecurityEventsFiltered,
  type Feed13DGResponse,
  type InstitutionPageResponse,
  type SecurityEventResponse,
  type SecurityInsiderFeedResponse,
  type SecurityPageResponse,
} from "@/lib/api";
import { fmtNumber, fmtPct, fmtUsd, fmtUsdThousands } from "@/lib/format";

export type ExploreSelection = {
  type: "security" | "institution";
  key: string;
};

function shiftDate(days: number): string {
  const dt = new Date();
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

function defaultEvents(): SecurityEventResponse {
  return {
    security_id: 0,
    ticker: "",
    rows: [],
  };
}

function defaultSecurityInsiders(): SecurityInsiderFeedResponse {
  return {
    security_id: 0,
    ticker: "",
    filters: {
      signal_type: null,
      start_date: "",
      end_date: "",
    },
    rows: [],
  };
}

type FeedRow = Feed13DGResponse["rows"][number];

function toEventClass(eventType: string): string {
  const value = (eventType || "").toUpperCase();
  const base = "inline-flex rounded-none border px-2 py-0.5 text-[11px]";
  if (value === "NEW_5PCT" || value === "AMENDMENT_UP") {
    return `${base} border-emerald-400/40 bg-emerald-400/10 text-emerald-300`;
  }
  if (value === "EXIT_5PCT" || value === "AMENDMENT_DOWN") {
    return `${base} border-rose-400/40 bg-rose-400/10 text-rose-300`;
  }
  return `${base} border-slate-500/50 bg-slate-500/10 text-slate-300`;
}

function toIntentClass(intentClass: string | null | undefined): string {
  const value = (intentClass || "").toUpperCase();
  const base = "inline-flex rounded-none border px-2 py-0.5 text-[11px]";
  if (value === "13D") {
    return `${base} border-amber-400/40 bg-amber-400/10 text-amber-300`;
  }
  if (value === "13G") {
    return `${base} border-sky-400/40 bg-sky-400/10 text-sky-300`;
  }
  return `${base} border-slate-500/50 bg-slate-500/10 text-slate-400`;
}

function toMaterialityClass(bucket: string | null | undefined): string {
  const value = (bucket || "").toUpperCase();
  const base = "inline-flex rounded-none border px-2 py-0.5 text-[11px]";
  if (value === "MAJOR") {
    return `${base} border-fuchsia-400/40 bg-fuchsia-400/10 text-fuchsia-300`;
  }
  if (value === "MODERATE") {
    return `${base} border-violet-400/40 bg-violet-400/10 text-violet-300`;
  }
  if (value === "MINOR") {
    return `${base} border-indigo-400/40 bg-indigo-400/10 text-indigo-300`;
  }
  return `${base} border-slate-500/50 bg-slate-500/10 text-slate-400`;
}

function toInsiderSignalClass(signalType: string | null | undefined): string {
  const value = (signalType || "").toUpperCase();
  const base = "inline-flex rounded-none border px-2 py-0.5 text-[11px]";
  if (value === "OPEN_MARKET_BUY") {
    return `${base} border-emerald-400/40 bg-emerald-400/10 text-emerald-300`;
  }
  if (value === "OPEN_MARKET_SELL") {
    return `${base} border-rose-400/40 bg-rose-400/10 text-rose-300`;
  }
  if (value === "DERIVATIVE") {
    return `${base} border-sky-400/40 bg-sky-400/10 text-sky-300`;
  }
  return `${base} border-slate-500/50 bg-slate-500/10 text-slate-400`;
}

function displayFeedSecurity(row: FeedRow): string {
  return row.security_display || row.ticker || row.security_name || row.issuer_name_raw || row.cusip_raw || "-";
}

function formatPercentChange(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "-";
  }
  const n = Number(value);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(2)}%`;
}

export function ExploreEntityView({ selection }: { selection: ExploreSelection | null }) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [security, setSecurity] = useState<SecurityPageResponse | null>(null);
  const [institution, setInstitution] = useState<InstitutionPageResponse | null>(null);
  const [events, setEvents] = useState<SecurityEventResponse>(defaultEvents());
  const [securityInsiders, setSecurityInsiders] = useState<SecurityInsiderFeedResponse>(defaultSecurityInsiders());
  const [institutionFeedRows, setInstitutionFeedRows] = useState<FeedRow[]>([]);
  const [institutionFeedError, setInstitutionFeedError] = useState("");

  const selectionToken = selection ? `${selection.type}:${selection.key}` : "";

  useEffect(() => {
    let cancelled = false;

    async function run() {
      if (!selection || !selection.key.trim()) {
        setLoading(false);
        setError("");
        setSecurity(null);
        setInstitution(null);
        setEvents(defaultEvents());
        setSecurityInsiders(defaultSecurityInsiders());
        setInstitutionFeedRows([]);
        setInstitutionFeedError("");
        return;
      }

      setLoading(true);
      setError("");
      setSecurity(null);
      setInstitution(null);
      setEvents(defaultEvents());
      setSecurityInsiders(defaultSecurityInsiders());
      setInstitutionFeedRows([]);
      setInstitutionFeedError("");

      try {
        if (selection.type === "security") {
          const [securityResponse, eventsResponse, insidersResponse] = await Promise.all([
            getSecurity(selection.key),
            getSecurityEventsFiltered(selection.key, {
              new5pctOnly: false,
              startDate: shiftDate(-3650),
              endDate: shiftDate(0),
              limitN: 300,
            }),
            getSecurityInsiders(selection.key, {
              days: 3650,
              limitN: 200,
            }),
          ]);
          if (cancelled) return;
          setSecurity(securityResponse);
          setEvents(eventsResponse);
          setSecurityInsiders(insidersResponse);
        } else {
          const [institutionResult, feedResult] = await Promise.allSettled([
            getInstitution(selection.key),
            get13DGFeed({
              days: 3650,
              limitN: 200,
              includeOther: false,
              mappedOnly: true,
              universeOnly: true,
              includeLowQuality: false,
              managerKey: selection.key,
            }),
          ]);
          if (cancelled) return;
          if (institutionResult.status !== "fulfilled") {
            throw institutionResult.reason;
          }
          const institutionResponse = institutionResult.value;
          setInstitution(institutionResponse);
          if (feedResult.status === "fulfilled") {
            setInstitutionFeedRows(feedResult.value.rows ?? []);
            setInstitutionFeedError("");
          } else {
            setInstitutionFeedRows([]);
            setInstitutionFeedError(String(feedResult.reason ?? "Feed unavailable"));
          }
        }
      } catch (err) {
        if (cancelled) return;
        setError(String(err));
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void run();

    return () => {
      cancelled = true;
    };
  }, [selectionToken]);

  const barData = useMemo(() => {
    if (!security) return [];
    return Object.values(
      security.net_change_last_4q.reduce<Record<string, { report_date: string; net_change_shares: number }>>(
        (acc, row) => {
          const k = row.report_date;
          const existing = acc[k] ?? { report_date: k, net_change_shares: 0 };
          existing.net_change_shares += Number(row.net_change_shares ?? 0);
          acc[k] = existing;
          return acc;
        },
        {}
      )
    ).sort((a, b) => a.report_date.localeCompare(b.report_date));
  }, [security]);

  const securityHeatmapData = useMemo(() => {
    if (!security) return [];
    return (security.active_positions ?? []).map((row) => ({
      id: row.manager_id,
      name: row.manager_name,
      symbol: null,
      size: Number(row.value_usd_thousands ?? 0),
      delta: Number(row.qoq_delta_shares ?? 0),
      shares: Number(row.shares ?? 0),
      pctOfInstitution:
        row.pct_manager_portfolio === null || row.pct_manager_portfolio === undefined
          ? null
          : Number(row.pct_manager_portfolio),
    }));
  }, [security]);

  const institutionTopPositions = institution?.top_positions ?? [];
  const institutionTopBuys = institution?.top_buys ?? [];
  const institutionTopSells = institution?.top_sells ?? [];

  const institutionHeatmapData = useMemo(() => {
    if (!institution) return [];
    const totalPortfolioUsd = Number(institution.metrics.total_value_current ?? 0);
    const deltaBySecurityId = new Map<number, number>();
    for (const position of institutionTopPositions) {
      const delta = position.qoq_delta_value_usd_thousands;
      if (delta === null || delta === undefined) continue;
      deltaBySecurityId.set(position.security_id, Number(delta));
    }
    if (deltaBySecurityId.size === 0) {
      for (const row of institutionTopBuys) {
        const prev = deltaBySecurityId.get(row.security_id) ?? 0;
        deltaBySecurityId.set(row.security_id, prev + Math.abs(Number(row.delta_val ?? 0)));
      }
      for (const row of institutionTopSells) {
        const prev = deltaBySecurityId.get(row.security_id) ?? 0;
        deltaBySecurityId.set(row.security_id, prev - Math.abs(Number(row.delta_val ?? 0)));
      }
    }
    return institutionTopPositions.map((position) => ({
      id: position.security_id,
      name: `${position.issuer_name_raw ?? "Unknown"}`,
      symbol: position.ticker ?? null,
      size: Number(position.value_usd_thousands ?? 0),
      delta: deltaBySecurityId.has(position.security_id) ? deltaBySecurityId.get(position.security_id) : null,
      shares: Number(position.shares ?? 0),
      pctOfInstitution:
        totalPortfolioUsd > 0
          ? ((Number(position.value_usd_thousands ?? 0) * 1000.0) / totalPortfolioUsd)
          : null,
    }));
  }, [institution, institutionTopBuys, institutionTopPositions, institutionTopSells]);

  if (!selection) return null;

  if (loading) {
    return (
      <div className="explore-entity-loading">
        <LottieLoader size={170} className="explore-loading-lottie" />
      </div>
    );
  }

  if (error) {
    return (
      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <p className="text-sm text-rose-300">Failed to load {selection.type}: {error}</p>
      </section>
    );
  }

  if (selection.type === "security") {
    if (!security) {
      return (
        <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <p className="text-sm text-rose-300">Security data unavailable.</p>
        </section>
      );
    }

    return (
      <div className="space-y-6">
        <section className="rounded-none p-6 shadow-panel">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h1 className="inline-flex items-center gap-2 text-2xl font-semibold tracking-tight text-slate-100">
                <TickerIcon ticker={security.ticker} label={security.security_name} size={22} />
                <span>{security.ticker}</span>
                {security.security_name ? <span className="text-slate-100">- {security.security_name}</span> : null}
              </h1>
              <p className="mt-2 text-sm text-slate-400">
                Last report date: {security.latest_quarter ?? "-"} • MIC {security.mic || "N/A"} • Security ID{" "}
                {security.security_id}
              </p>
            </div>

            <div className="w-full lg:max-w-[780px]">
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-5">
                <div className="rounded-none border border-line/80 bg-black/20 p-2.5">
                  <div className="text-[11px] text-slate-500">Holders</div>
                  <div className="mt-1 text-sm font-semibold text-slate-100">
                    {fmtNumber(security.ownership_summary.holders_count ?? 0)}
                  </div>
                </div>
                <div className="rounded-none border border-line/80 bg-black/20 p-2.5">
                  <div className="text-[11px] text-slate-500">Total Shares</div>
                  <div className="mt-1 text-sm font-semibold text-slate-100">
                    {fmtNumber(security.ownership_summary.total_shares ?? 0)}
                  </div>
                </div>
                <div className="rounded-none border border-line/80 bg-black/20 p-2.5">
                  <div className="text-[11px] text-slate-500">Total Value</div>
                  <div className="mt-1 text-sm font-semibold text-slate-100">
                    {fmtUsd(security.ownership_summary.total_value_usd ?? 0)}
                  </div>
                </div>
                <div className="rounded-none border border-line/80 bg-black/20 p-2.5">
                  <div className="text-[11px] text-slate-500">QoQ Δ Shares</div>
                  <div
                    className={`mt-1 text-sm font-semibold ${(security.ownership_summary.qoq_net_change_shares ?? 0) >= 0 ? "text-emerald-300" : "text-rose-300"}`}
                  >
                    {fmtNumber(security.ownership_summary.qoq_net_change_shares ?? 0)}
                  </div>
                </div>
                <div className="rounded-none border border-line/80 bg-black/20 p-2.5">
                  <div className="text-[11px] text-slate-500">Top 10 Conc.</div>
                  <div className="mt-1 text-sm font-semibold text-slate-100">
                    {fmtPct(
                      security.ownership_summary.top10_concentration_pct ?? security.concentration.top10_pct ?? 0
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">Activity Breakdown</h2>
          <div className="mt-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
            <div className="rounded-none border border-line/70 bg-black/20 p-3">
              <div className="text-xs text-slate-500">Total</div>
              <div className="mt-1 text-lg font-semibold text-slate-100">
                {fmtNumber(security.activity_breakdown.total ?? 0)}
              </div>
            </div>
            <div className="rounded-none border border-line/70 bg-black/20 p-3">
              <div className="text-xs text-slate-500">New</div>
              <div className="mt-1 text-lg font-semibold text-emerald-300">
                {fmtNumber(security.activity_breakdown.new ?? 0)}
              </div>
            </div>
            <div className="rounded-none border border-line/70 bg-black/20 p-3">
              <div className="text-xs text-slate-500">Increased</div>
              <div className="mt-1 text-lg font-semibold text-emerald-300">
                {fmtNumber(security.activity_breakdown.increased ?? 0)}
              </div>
            </div>
            <div className="rounded-none border border-line/70 bg-black/20 p-3">
              <div className="text-xs text-slate-500">Decreased</div>
              <div className="mt-1 text-lg font-semibold text-rose-300">
                {fmtNumber(security.activity_breakdown.decreased ?? 0)}
              </div>
            </div>
            <div className="rounded-none border border-line/70 bg-black/20 p-3">
              <div className="text-xs text-slate-500">Sold Out</div>
              <div className="mt-1 text-lg font-semibold text-rose-300">
                {fmtNumber(security.activity_breakdown.sold_out ?? 0)}
              </div>
            </div>
            <div className="rounded-none border border-line/70 bg-black/20 p-3">
              <div className="text-xs text-slate-500">Activity</div>
              <div className="mt-1 text-lg font-semibold text-slate-100">
                {fmtNumber(security.activity_breakdown.activity ?? 0)}
              </div>
            </div>
          </div>
        </section>

        <HoldingsHeatmap
          title="Institutional Holdings Heatmap"
          data={securityHeatmapData}
          containerClassName="chart-box-plain"
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

        <NetAccumulationBarChart data={barData} containerClassName="chart-box-plain" />

        <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">13D/G Events Feed</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Institution</th>
                  <th className="px-3 py-2">Event</th>
                  <th className="px-3 py-2">Intent</th>
                  <th className="px-3 py-2">Materiality</th>
                  <th className="px-3 py-2 text-right">Percent Owned</th>
                  <th className="px-3 py-2 text-right">% Δ Owned</th>
                  <th className="px-3 py-2">Form</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {(events.rows ?? []).map((event, idx) => (
                  <tr key={`${event.accession_no}-${idx}`}>
                    <td className="px-3 py-2">{event.report_date}</td>
                    <td className="px-3 py-2">
                      {event.manager_id ? (
                        <Link
                          prefetch={false}
                          href={`/explore?type=institution&key=${encodeURIComponent(String(event.manager_id))}`}
                          className="text-accentBlue hover:text-white"
                        >
                          {event.manager_name ?? `Institution ${event.manager_id}`}
                        </Link>
                      ) : (
                        event.manager_name ?? "Unknown"
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <span className={toEventClass(event.event_type)}>{event.event_label || event.event_type}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={toIntentClass(event.intent_class)}>{event.intent_class || "-"}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={toMaterialityClass(event.materiality_bucket)}>
                        {event.materiality_bucket || "-"}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right">
                      {event.percent_beneficial_owned === null ? "-" : `${event.percent_beneficial_owned.toFixed(2)}%`}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {formatPercentChange(event.percent_beneficial_change)}
                    </td>
                    <td className="px-3 py-2">{event.form_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">Insider Activity (Form 4)</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Date</th>
                  <th className="px-3 py-2">Insider</th>
                  <th className="px-3 py-2">Role</th>
                  <th className="px-3 py-2">Signal</th>
                  <th className="px-3 py-2 text-right">Shares</th>
                  <th className="px-3 py-2 text-right">Price</th>
                  <th className="px-3 py-2 text-right">Value</th>
                  <th className="px-3 py-2">Code</th>
                  <th className="px-3 py-2">Form</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {securityInsiders.rows.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-4 text-center text-sm text-slate-500">
                      No insider transactions available.
                    </td>
                  </tr>
                ) : (
                  securityInsiders.rows.map((row) => (
                    <tr key={`security-insider-${row.insider_tx_id}`}>
                      <td className="px-3 py-2 text-xs text-slate-400">{row.transaction_date}</td>
                      <td className="px-3 py-2">{row.reporting_owner_name || "-"}</td>
                      <td className="px-3 py-2">{row.role_group || "-"}</td>
                      <td className="px-3 py-2">
                        <span className={toInsiderSignalClass(row.signal_type)}>{row.signal_type || "-"}</span>
                      </td>
                      <td className="px-3 py-2 text-right">{fmtNumber(row.transaction_shares || 0)}</td>
                      <td className="px-3 py-2 text-right">
                        {row.transaction_price === null || row.transaction_price === undefined
                          ? "-"
                          : fmtUsd(row.transaction_price)}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {row.transaction_value_usd === null || row.transaction_value_usd === undefined
                          ? "-"
                          : fmtUsd(row.transaction_value_usd)}
                      </td>
                      <td className="px-3 py-2">{row.transaction_code || "-"}</td>
                      <td className="px-3 py-2">{row.form_type || "-"}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    );
  }

  if (!institution) {
    return (
      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <p className="text-sm text-rose-300">Institution data unavailable.</p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
          Institution: {institution.manager.manager_name}
        </h1>
        <p className="mt-2 text-sm text-slate-400">
          CIK {institution.manager.cik} • Latest quarter {institution.latest_quarter ?? "-"}
        </p>
      </section>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">Turnover</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">{fmtPct(institution.metrics.turnover_ratio)}</div>
        </div>
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">Top 10 Concentration</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">
            {fmtPct(institution.metrics.top10_concentration_pct)}
          </div>
        </div>
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">New / Exited Positions</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">
            {fmtNumber(institution.metrics.new_positions_count ?? 0)} /{" "}
            {fmtNumber(institution.metrics.exited_positions_count ?? 0)}
          </div>
        </div>
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">Portfolio Value</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">{fmtUsd(institution.metrics.total_value_current)}</div>
        </div>
      </section>

      <HoldingsHeatmap
        title="Current Position Heatmap"
        data={institutionHeatmapData}
        valueLabel="Value (13F)"
        deltaLabel="QoQ Δ Value"
        valueFormat="usd_thousands"
        deltaFormat="usd_thousands"
        signedDelta
        maxTiles={42}
        minRelativeSize={0.01}
        minTiles={16}
      />

      <section className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <div className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">Top Buys QoQ</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Security</th>
                  <th className="px-3 py-2 text-right">Delta Value (13F k$)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {institutionTopBuys.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-3 py-4 text-center text-sm text-slate-500">
                      No buys in current comparison window.
                    </td>
                  </tr>
                ) : (
                  institutionTopBuys.map((row, idx) => (
                    <tr key={`${row.security_id}-${idx}`}>
                      <td className="px-3 py-2">
                        {row.ticker ? (
                          <Link
                            prefetch={false}
                            href={`/security/${encodeURIComponent(row.ticker)}`}
                            className="inline-flex min-w-0 items-center gap-2 text-accentBlue hover:text-white"
                          >
                            <TickerIcon ticker={row.ticker} label={row.issuer_name_raw} />
                            <span className="font-medium">{row.ticker}</span>
                            <span className="truncate text-slate-400">- {row.issuer_name_raw ?? "Unknown"}</span>
                          </Link>
                        ) : (
                          row.issuer_name_raw ?? "Unknown"
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-emerald-300">{fmtUsdThousands(row.delta_val)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        <div className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
          <h2 className="text-lg font-semibold text-slate-100">Top Sells QoQ</h2>
          <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
            <table className="min-w-full divide-y divide-line/60 text-sm">
              <thead>
                <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-3 py-2">Security</th>
                  <th className="px-3 py-2 text-right">Delta Value (13F k$)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line/50 text-slate-300">
                {institutionTopSells.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-3 py-4 text-center text-sm text-slate-500">
                      No sells in current comparison window.
                    </td>
                  </tr>
                ) : (
                  institutionTopSells.map((row, idx) => (
                    <tr key={`${row.security_id}-${idx}`}>
                      <td className="px-3 py-2">
                        {row.ticker ? (
                          <Link
                            prefetch={false}
                            href={`/security/${encodeURIComponent(row.ticker)}`}
                            className="inline-flex min-w-0 items-center gap-2 text-accentBlue hover:text-white"
                          >
                            <TickerIcon ticker={row.ticker} label={row.issuer_name_raw} />
                            <span className="font-medium">{row.ticker}</span>
                            <span className="truncate text-slate-400">- {row.issuer_name_raw ?? "Unknown"}</span>
                          </Link>
                        ) : (
                          row.issuer_name_raw ?? "Unknown"
                        )}
                      </td>
                      <td className="px-3 py-2 text-right text-rose-300">{fmtUsdThousands(row.delta_val)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">Current Top Positions</h2>
        <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
          <table className="min-w-full divide-y divide-line/60 text-sm">
            <thead>
              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Security</th>
                <th className="px-3 py-2 text-right">Shares</th>
                <th className="px-3 py-2 text-right">Value</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {institutionTopPositions.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-3 py-4 text-center text-sm text-slate-500">
                    No mapped positions available.
                  </td>
                </tr>
              ) : (
                institutionTopPositions.map((row, idx) => (
                  <tr key={`${row.security_id}-${idx}`}>
                    <td className="px-3 py-2">
                      {row.ticker ? (
                        <Link
                          prefetch={false}
                          href={`/security/${encodeURIComponent(row.ticker)}`}
                          className="inline-flex min-w-0 items-center gap-2 text-accentBlue hover:text-white"
                        >
                          <TickerIcon ticker={row.ticker} label={row.issuer_name_raw} />
                          <span className="font-medium">{row.ticker}</span>
                          <span className="truncate text-slate-400">- {row.issuer_name_raw ?? "Unknown"}</span>
                        </Link>
                      ) : (
                        row.issuer_name_raw ?? "Unknown"
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">{fmtNumber(row.shares)}</td>
                    <td className="px-3 py-2 text-right">{fmtUsdThousands(row.value_usd_thousands)}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        <h2 className="text-lg font-semibold text-slate-100">13D/G Activity</h2>
        <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
          <table className="min-w-full divide-y divide-line/60 text-sm">
            <thead>
              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2">Date</th>
                <th className="px-3 py-2">Event</th>
                <th className="px-3 py-2">Intent</th>
                <th className="px-3 py-2">Materiality</th>
                <th className="px-3 py-2">Security</th>
                <th className="px-3 py-2 text-right">% Owned</th>
                <th className="px-3 py-2 text-right">% Δ Owned</th>
                <th className="px-3 py-2">Form</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {institutionFeedRows.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-3 py-4 text-center text-sm text-slate-500">
                    {institutionFeedError ? `13D/G feed unavailable: ${institutionFeedError}` : "No 13D/G events found."}
                  </td>
                </tr>
              ) : (
                institutionFeedRows.map((row) => (
                  <tr key={`institution-13dg-${row.bo_event_id}`}>
                    <td className="px-3 py-2 text-xs text-slate-400">{row.report_date}</td>
                    <td className="px-3 py-2">
                      <span className={toEventClass(row.event_type)}>{row.event_label || row.event_type}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={toIntentClass(row.intent_class)}>{row.intent_class || "-"}</span>
                    </td>
                    <td className="px-3 py-2">
                      <span className={toMaterialityClass(row.materiality_bucket)}>
                        {row.materiality_bucket || "-"}
                      </span>
                    </td>
                    <td className="px-3 py-2">
                      {row.ticker ? (
                        <Link
                          prefetch={false}
                          href={`/security/${encodeURIComponent(row.ticker)}`}
                          className="inline-flex min-w-0 items-center gap-2 text-accentBlue hover:text-white"
                        >
                          <TickerIcon ticker={row.ticker} label={displayFeedSecurity(row)} />
                          <span className="font-medium">{row.ticker}</span>
                          <span className="truncate text-slate-400">- {displayFeedSecurity(row)}</span>
                        </Link>
                      ) : (
                        displayFeedSecurity(row)
                      )}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {row.percent_beneficial_owned === null || row.percent_beneficial_owned === undefined
                        ? "-"
                        : `${Number(row.percent_beneficial_owned).toFixed(2)}%`}
                    </td>
                    <td
                      className={[
                        "px-3 py-2 text-right",
                        row.percent_beneficial_change === null || row.percent_beneficial_change === undefined
                          ? "text-slate-500"
                          : row.percent_beneficial_change > 0
                            ? "text-emerald-300"
                            : row.percent_beneficial_change < 0
                              ? "text-rose-300"
                              : "text-slate-300",
                      ].join(" ")}
                    >
                      {formatPercentChange(row.percent_beneficial_change)}
                    </td>
                    <td className="px-3 py-2">{row.form_type}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
