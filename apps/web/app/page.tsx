import Link from "next/link";

import { Sparkline } from "@/components/charts";
import { get13DGFeed, getHomeOverview } from "@/lib/api";
import { fmtNumber, fmtPct, fmtUsd } from "@/lib/format";

type SparkPoint = { report_date: string; net_shares: number; net_holder_count: number };

function toSpark(series: Array<{ report_date: string; value: number }>): SparkPoint[] {
  return series.map((x) => ({ report_date: x.report_date, net_shares: Number(x.value ?? 0), net_holder_count: 0 }));
}

function fmtSigned(n: number, digits = 0): string {
  const base = fmtNumber(n, digits);
  if (n > 0) return `+${base}`;
  return base;
}

function fmtSignedUsd(n: number): string {
  if (n > 0) return `+${fmtUsd(n)}`;
  return fmtUsd(n);
}

const TICKER_PATTERN = /^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$/;
const DERIVATIVE_NAME_PATTERN = /\b(?:OPTION|WARRANT|RIGHT|NOTE|BOND|DEBT|PFD|PREFERRED)\b|(?:\b\d+(?:\.\d+)?\s+\d{2}\/\d{2}\/\d{2}\b)/i;

function isDisplayableMover(row: {
  ticker: string | null;
  security_name: string | null;
}) {
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
  let feedRows: Awaited<ReturnType<typeof get13DGFeed>>["rows"] = [];
  let feedError: string | null = null;
  try {
    const [homeOverview, feed] = await Promise.all([
      getHomeOverview({ quartersN: 8, topN: 10, scatterN: 0 }),
      get13DGFeed({ days: 180, limitN: 18, includeOther: false, mappedOnly: false }).catch((error: unknown) => {
        feedError = String(error);
        return null;
      })
    ]);
    overview = homeOverview;
    feedRows = feed?.rows ?? [];
  } catch (error) {
    return (
      <div className="stack">
        <div className="card">
          <h1 className="page-title">Institutional Flow Tracker</h1>
          <p className="page-subtitle">Failed to load homepage analytics.</p>
          <pre>{String(error)}</pre>
        </div>
      </div>
    );
  }

  const pulseCards = [
    {
      title: "Breadth: Net Accumulation",
      value: fmtPct(overview.pulse.breadth_accum_pct),
      subtitle: `${fmtNumber(overview.pulse.accum_count)} of ${fmtNumber(overview.pulse.universe_count)} securities`,
      spark: toSpark(overview.pulse_series.breadth_accum_pct)
    },
    {
      title: "Participation: Adders",
      value: fmtPct(overview.pulse.participation_increase_pct),
      subtitle: `${fmtNumber(overview.pulse.holders_added)} adds vs ${fmtNumber(overview.pulse.holders_trimmed)} trims`,
      spark: toSpark(overview.pulse_series.participation_increase_pct)
    },
    {
      title: "Net 13F Value Change QoQ",
      value: fmtSignedUsd(overview.pulse.net_value_change_usd),
      subtitle: `Latest quarter ${overview.latest_quarter ?? "-"}`,
      spark: toSpark(overview.pulse_series.net_value_change_usd)
    },
    {
      title: "13D/G Mix (30d)",
      value: `13D ${fmtPct(overview.pulse.bo_13d_share_30d)} / 13G ${fmtPct(overview.pulse.bo_13g_share_30d)}`,
      subtitle: `${fmtNumber(overview.pulse.form_13d_30d)} / ${fmtNumber(overview.pulse.form_13g_30d)} unique filings`,
      spark: toSpark(overview.pulse_series.bo_13d_share_pct)
    }
  ];

  const columns = [
    { key: "accumulated", title: "Top Accumulated (QoQ)", rows: overview.top_movers.accumulated.filter(isDisplayableMover) },
    { key: "distributed", title: "Top Distributed (QoQ)", rows: overview.top_movers.distributed.filter(isDisplayableMover) },
    { key: "new_holders", title: "Most New Holders (QoQ)", rows: overview.top_movers.new_holders.filter(isDisplayableMover) }
  ] as const;

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Institutional Flow Pulse</h1>
        <p className="page-subtitle">
          Market-wide institutional positioning snapshot for {overview.latest_quarter ?? "-"}.
        </p>
      </div>

      <div className="pulse-grid">
        {pulseCards.map((card) => (
          <div key={card.title} className="card pulse-card">
            <div className="pulse-kicker">{card.title}</div>
            <div className="pulse-value">{card.value}</div>
            <div className="pulse-sub">{card.subtitle}</div>
            <div className="pulse-spark">
              <Sparkline data={card.spark} />
            </div>
          </div>
        ))}
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Coverage & Freshness</h3>
          <div className="kpi-grid">
            <div>
              <div className="muted">Latest Quarter</div>
              <div>{overview.trust.latest_quarter_loaded ?? "-"}</div>
            </div>
            <div>
              <div className="muted">Institutions in Universe</div>
              <div>{fmtNumber(overview.trust.managers_in_universe)}</div>
            </div>
            <div>
              <div className="muted">Institutions with Positions</div>
              <div>{fmtNumber(overview.trust.managers_with_positions)}</div>
            </div>
            <div>
              <div className="muted">Mapped Position Rows (Latest Quarter)</div>
              <div>{fmtNumber(overview.trust.holdings_rows_latest_quarter)}</div>
            </div>
            <div>
              <div className="muted">Mapped Analytics Coverage</div>
              <div>{fmtPct(overview.trust.mapping_coverage_pct_latest_quarter)}</div>
            </div>
          </div>
        </div>

        <div className="card">
          <h3>13D/G Breadth (30d)</h3>
          <div className="kpi-grid">
            <div>
              <div className="muted">Unique Filers</div>
              <div>{fmtNumber(overview.bo_activity_30d.unique_filers)}</div>
            </div>
            <div>
              <div className="muted">Unique Securities</div>
              <div>{fmtNumber(overview.bo_activity_30d.unique_securities)}</div>
            </div>
          </div>
          <p className="page-subtitle">
            Distinct beneficial owners and distinct security keys seen in the last 30 days.
          </p>
        </div>
      </div>

      <div className="card">
        <h3>Largest New Stake (30d)</h3>
        {overview.largest_new_stake_30d ? (
          <div className="kpi-grid">
            <div>
              <div className="muted">Security</div>
              <div>
                {overview.largest_new_stake_30d.ticker ? (
                  <Link href={`/security/${encodeURIComponent(overview.largest_new_stake_30d.ticker)}`}>
                    {overview.largest_new_stake_30d.ticker}
                  </Link>
                ) : (
                  overview.largest_new_stake_30d.security_display ?? "-"
                )}
              </div>
            </div>
            <div>
              <div className="muted">Institution</div>
              <div>
                {overview.largest_new_stake_30d.manager_id ? (
                  <Link href={`/institution/${overview.largest_new_stake_30d.manager_id}`}>
                    {overview.largest_new_stake_30d.manager_name ?? `Institution ${overview.largest_new_stake_30d.manager_id}`}
                  </Link>
                ) : (
                  overview.largest_new_stake_30d.manager_name ?? "-"
                )}
              </div>
            </div>
            <div>
              <div className="muted">% Beneficial Owned</div>
              <div>{fmtPct((overview.largest_new_stake_30d.percent_beneficial_owned ?? 0) / 100)}</div>
            </div>
            <div>
              <div className="muted">Date</div>
              <div>{overview.largest_new_stake_30d.report_date ?? "-"}</div>
            </div>
            <div>
              <div className="muted">Form</div>
              <div>{overview.largest_new_stake_30d.form_type ?? "-"}</div>
            </div>
          </div>
        ) : (
          <p className="muted">No NEW_5PCT event found in the last 30 days.</p>
        )}
      </div>

      <div className="movers-grid">
        {columns.map((column) => (
          <div key={column.key} className="card">
            <h3>{column.title}</h3>
            <div className="table-wrap">
              <table className="table home-movers-table">
                <thead>
                  <tr>
                    <th>Security</th>
                    <th>Net Value (QoQ)</th>
                    <th>Net Holders</th>
                    <th>Spark</th>
                  </tr>
                </thead>
                <tbody>
                  {column.rows.length ? (
                    column.rows.map((row) => (
                      <tr key={`${column.key}-${row.security_id}`}>
                        <td>
                          {row.ticker ? (
                            <Link href={`/security/${encodeURIComponent(row.ticker)}`}>{row.ticker}</Link>
                          ) : (
                            row.security_name ?? `Security ${row.security_id}`
                          )}
                        </td>
                        <td className={row.net_value_change_usd >= 0 ? "badge-pos" : "badge-neg"}>
                          {fmtSignedUsd(row.net_value_change_usd)}
                        </td>
                        <td className={row.net_holder_count >= 0 ? "badge-pos" : "badge-neg"}>{fmtSigned(row.net_holder_count, 0)}</td>
                        <td className="spark-cell">
                          <Sparkline data={row.series as SparkPoint[]} />
                        </td>
                      </tr>
                    ))
                  ) : (
                    <tr>
                      <td colSpan={4} className="muted">No eligible securities for this view.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        ))}
      </div>

      <div className="card">
        <div className="feed-header">
          <h3>Latest 13D/G Feed</h3>
          <Link href="/feed">View full feed</Link>
        </div>
        <p className="page-subtitle">Most recent mapped beneficial ownership events (latest available window).</p>
        <div className="table-wrap">
          <table className="table feed-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Event</th>
                <th>Security</th>
                <th>Institution</th>
                <th>% Owned</th>
                <th>Form</th>
              </tr>
            </thead>
            <tbody>
              {feedRows.length ? (
                feedRows.map((row) => (
                  <tr key={`home-feed-${row.bo_event_id}`}>
                    <td>{row.report_date}</td>
                    <td>
                      <span className={`event-chip event-${(row.event_type || "").toLowerCase().replace(/_/g, "-")}`}>
                        {row.event_type}
                      </span>
                    </td>
                    <td>
                      {row.ticker ? (
                        <Link href={`/security/${encodeURIComponent(row.ticker)}`}>{row.ticker}</Link>
                      ) : (
                        row.security_name ?? row.issuer_name_raw ?? "-"
                      )}
                    </td>
                    <td>
                      {row.manager_id ? (
                        <Link href={`/institution/${row.manager_id}`}>{row.manager_name ?? `Institution ${row.manager_id}`}</Link>
                      ) : (
                        row.manager_name ?? "-"
                      )}
                    </td>
                    <td>
                      {row.percent_beneficial_owned === null || row.percent_beneficial_owned === undefined
                        ? "-"
                        : `${Number(row.percent_beneficial_owned).toFixed(2)}%`}
                    </td>
                    <td>{row.form_type}</td>
                  </tr>
                ))
              ) : (
                <tr>
                  <td colSpan={6} className="muted">
                    {feedError ? `Feed unavailable: ${feedError}` : "No 13D/G events found for this window."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Security Lens</h3>
          <p>Ownership concentration, active institutional holders, and 13D/G event timeline.</p>
          <Link href="/security">Search securities</Link>
        </div>
        <div className="card">
          <h3>Institution Lens</h3>
          <p>Current exposure heatmap, top buys/sells, turnover and concentration.</p>
          <Link href="/institution">Browse institutions</Link>
        </div>
      </div>
    </div>
  );
}
