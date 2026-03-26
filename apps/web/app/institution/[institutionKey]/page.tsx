import Link from "next/link";

import { HoldingsHeatmap } from "@/components/charts";
import { TickerIcon } from "@/components/ticker-icon";
import { get13DGFeed, getInstitution, type Feed13DGResponse } from "@/lib/api";
import { fmtNumber, fmtPct, fmtUsd, fmtUsdThousands } from "@/lib/format";

type Props = { params: Promise<{ institutionKey: string }> };

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

export default async function InstitutionPage({ params }: Props) {
  const { institutionKey } = await params;

  let institution;
  try {
    institution = await getInstitution(institutionKey);
  } catch (error) {
    return (
      <section className="rounded-none p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Institution {institutionKey}</h1>
        <p className="mt-2 text-sm text-slate-400">Failed to load institution data.</p>
        <pre className="mt-3 overflow-auto rounded-none border border-line/70 bg-black/35 p-3 text-xs text-rose-200">
          {String(error)}
        </pre>
      </section>
    );
  }

  let institutionFeedRows: FeedRow[] = [];
  let institutionFeedError: string | null = null;
  try {
    const feed = await get13DGFeed({
      days: 3650,
      limitN: 200,
      includeOther: false,
      mappedOnly: true,
      universeOnly: true,
      includeLowQuality: false,
      managerKey: institutionKey,
    });
    institutionFeedRows = feed.rows ?? [];
  } catch (error) {
    institutionFeedError = String(error);
  }

  const deltaBySecurityId = new Map<number, number>();
  for (const position of institution.top_positions) {
    const delta = position.qoq_delta_value_usd_thousands;
    if (delta === null || delta === undefined) continue;
    deltaBySecurityId.set(position.security_id, Number(delta));
  }
  if (deltaBySecurityId.size === 0) {
    for (const row of institution.top_buys) {
      const prev = deltaBySecurityId.get(row.security_id) ?? 0;
      deltaBySecurityId.set(row.security_id, prev + Math.abs(Number(row.delta_val ?? 0)));
    }
    for (const row of institution.top_sells) {
      const prev = deltaBySecurityId.get(row.security_id) ?? 0;
      deltaBySecurityId.set(row.security_id, prev - Math.abs(Number(row.delta_val ?? 0)));
    }
  }
  const heatmapData = institution.top_positions.map((position) => ({
    id: position.security_id,
    name: `${position.issuer_name_raw ?? "Unknown"}`,
    symbol: position.ticker ?? null,
    size: Number(position.value_usd_thousands ?? 0),
    delta: deltaBySecurityId.has(position.security_id) ? deltaBySecurityId.get(position.security_id) : null
  }));

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6 shadow-panel">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-100">
              Institution: {institution.manager.manager_name}
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              CIK {institution.manager.cik} • Latest quarter {institution.latest_quarter ?? "-"}
            </p>
          </div>
          <div className="flex justify-start lg:justify-end">
            <Link
              href="/institution"
              className="rounded-none border border-line/80 bg-cardSoft/80 px-3 py-1.5 text-xs text-slate-300 transition hover:border-accentBlue/70 hover:text-white"
            >
              Back to institution directory
            </Link>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">Turnover</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">{fmtPct(institution.metrics.turnover_ratio)}</div>
        </div>
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">Top 10 Concentration</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">{fmtPct(institution.metrics.top10_concentration_pct)}</div>
        </div>
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">New / Exited Positions</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">
            {fmtNumber(institution.metrics.new_positions_count ?? 0)} / {fmtNumber(institution.metrics.exited_positions_count ?? 0)}
          </div>
        </div>
        <div className="rounded-none border border-line/80 bg-card/70 p-4">
          <div className="text-xs text-slate-500">Portfolio Value</div>
          <div className="mt-1 text-xl font-semibold text-slate-100">{fmtUsd(institution.metrics.total_value_current)}</div>
        </div>
      </section>

      <HoldingsHeatmap
        title="Current Position Heatmap"
        data={heatmapData}
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
                {institution.top_buys.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-3 py-4 text-center text-sm text-slate-500">
                      No buys in current comparison window.
                    </td>
                  </tr>
                ) : (
                  institution.top_buys.map((row, idx) => (
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
                {institution.top_sells.length === 0 ? (
                  <tr>
                    <td colSpan={2} className="px-3 py-4 text-center text-sm text-slate-500">
                      No sells in current comparison window.
                    </td>
                  </tr>
                ) : (
                  institution.top_sells.map((row, idx) => (
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
              {institution.top_positions.length === 0 ? (
                <tr>
                  <td colSpan={3} className="px-3 py-4 text-center text-sm text-slate-500">
                    No mapped positions available.
                  </td>
                </tr>
              ) : (
                institution.top_positions.map((row, idx) => (
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
                <th className="px-3 py-2">Security</th>
                <th className="px-3 py-2 text-right">% Owned</th>
                <th className="px-3 py-2 text-right">% Δ Owned</th>
                <th className="px-3 py-2">Form</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line/50 text-slate-300">
              {institutionFeedRows.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-sm text-slate-500">
                    {institutionFeedError ? `13D/G feed unavailable: ${institutionFeedError}` : "No 13D/G events found."}
                  </td>
                </tr>
              ) : (
                institutionFeedRows.map((row) => (
                  <tr key={`institution-13dg-${row.bo_event_id}`}>
                    <td className="px-3 py-2 text-xs text-slate-400">{row.report_date}</td>
                    <td className="px-3 py-2">
                      <span className={toEventClass(row.event_type)}>{row.event_type}</span>
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
