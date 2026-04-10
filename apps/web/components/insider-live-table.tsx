"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { TickerIcon } from "@/components/ticker-icon";
import { getInsiderFeed, type InsiderFeedResponse } from "@/lib/api";
import { fmtNumber, fmtUsd } from "@/lib/format";

type InsiderRow = InsiderFeedResponse["rows"][number];

const ALLOWED_SIGNAL_TYPES = ["OPEN_MARKET_BUY", "OPEN_MARKET_SELL", "DERIVATIVE", "OTHER"] as const;
type AllowedSignalType = (typeof ALLOWED_SIGNAL_TYPES)[number];

const ALLOWED_ROLE_GROUPS = ["CEO", "CFO", "OFFICER", "DIRECTOR", "TEN_PCT_OWNER", "OTHER"] as const;
type AllowedRoleGroup = (typeof ALLOWED_ROLE_GROUPS)[number];

const FORM4_CODE_EXPLANATIONS: Record<string, string> = {
  P: "Open-market or private purchase.",
  S: "Open-market or private sale.",
  A: "Grant, award, or other acquisition from issuer.",
  D: "Disposition to issuer (often tax/withholding related).",
  M: "Exercise or conversion of a derivative security.",
  F: "Shares delivered to pay tax/exercise price.",
  G: "Bona fide gift transfer.",
  C: "Conversion of derivative to common stock.",
  E: "Expiration or short derivative position change.",
  H: "Expiration or cancellation of derivative security.",
  I: "Discretionary transaction (Rule 16b-3).",
  J: "Other transaction type not covered elsewhere.",
  K: "Equity swap or similar derivative transaction.",
  L: "Small acquisition under Rule 16a-6.",
  O: "Out-of-the-money option exercise.",
  U: "Disposition from tender/other issuer event.",
  V: "Voluntary early report of transaction.",
  W: "Acquisition/disposition by will or inheritance.",
  X: "In-the-money option exercise.",
  Z: "Transfer to or from voting trust.",
};

function toSignalClass(signalType: string | null | undefined): string {
  const value = String(signalType ?? "").toUpperCase();
  const base = "inline-flex rounded-none border px-2 py-0.5 text-[11px]";
  if (value === "OPEN_MARKET_BUY") {
    return `${base} border-emerald-400/40 bg-emerald-400/10 text-emerald-300`;
  }
  if (value === "OPEN_MARKET_SELL") {
    return `${base} border-rose-400/40 bg-rose-400/10 text-rose-300`;
  }
  if (value === "DERIVATIVE") {
    return `${base} border-violet-400/40 bg-violet-400/10 text-violet-300`;
  }
  return `${base} border-slate-500/50 bg-slate-500/10 text-slate-300`;
}

function toRoleLabel(roleGroup: InsiderRow["role_group"]): string {
  const value = String(roleGroup ?? "").toUpperCase();
  if (value === "TEN_PCT_OWNER") return "10% Owner";
  return value || "-";
}

function toTransactionCodeExplanation(transactionCode: string | null | undefined): string | null {
  const code = String(transactionCode ?? "").trim().toUpperCase();
  if (!code) return null;
  return FORM4_CODE_EXPLANATIONS[code] ?? "Form 4 transaction code.";
}

export function InsiderLiveTable({
  rows,
  loadError,
}: {
  rows: InsiderRow[];
  loadError?: string | null;
}) {
  const [search, setSearch] = useState("");
  const [signalType, setSignalType] = useState("ALL");
  const [roleGroup, setRoleGroup] = useState("ALL");
  const [windowDays, setWindowDays] = useState("90");
  const [liveRows, setLiveRows] = useState<InsiderRow[]>(rows);
  const [liveError, setLiveError] = useState<string | null>(loadError ?? null);
  const [loading, setLoading] = useState(false);

  const requestSeq = useRef(0);

  useEffect(() => {
    setLiveRows(rows);
    setLiveError(loadError ?? null);
  }, [rows, loadError]);

  useEffect(() => {
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    const days = windowDays === "ALL" ? 3650 : Number(windowDays);
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const selectedSignalType: AllowedSignalType | undefined =
          signalType !== "ALL" && ALLOWED_SIGNAL_TYPES.includes(signalType as AllowedSignalType)
            ? (signalType as AllowedSignalType)
            : undefined;
        const selectedRoleGroup: AllowedRoleGroup | undefined =
          roleGroup !== "ALL" && ALLOWED_ROLE_GROUPS.includes(roleGroup as AllowedRoleGroup)
            ? (roleGroup as AllowedRoleGroup)
            : undefined;

        const response = await getInsiderFeed({
          limitN: 2000,
          days: Number.isFinite(days) && days > 0 ? days : 3650,
          signalType: selectedSignalType,
          roleGroup: selectedRoleGroup,
          q: search.trim() || undefined,
        });
        if (requestSeq.current !== seq) return;
        setLiveRows(response.rows);
        setLiveError(null);
      } catch (error) {
        if (requestSeq.current !== seq) return;
        setLiveRows([]);
        setLiveError(String(error));
      } finally {
        if (requestSeq.current === seq) {
          setLoading(false);
        }
      }
    }, 250);

    return () => clearTimeout(timer);
  }, [search, signalType, roleGroup, windowDays]);

  return (
    <div className="activity-controls-rounded space-y-8">
      <div className="mx-auto grid w-full max-w-[1120px] grid-cols-1 gap-3 lg:grid-cols-12">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search ticker, issuer, insider, role, transaction code..."
          className="activity-pill h-11 border border-line/80 bg-card/70 px-4 text-[15px] text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70 lg:col-span-5"
        />
        <div className="relative lg:col-span-2">
          <select
            value={signalType}
            onChange={(event) => setSignalType(event.target.value)}
            className="activity-pill h-11 w-full appearance-none border border-line/70 bg-card/60 px-4 text-sm text-slate-200 outline-none transition focus:border-accentBlue/70"
          >
            <option value="ALL">All Signals</option>
            {ALLOWED_SIGNAL_TYPES.map((value) => (
              <option key={`insider-signal-${value}`} value={value}>
                {value}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        </div>
        <div className="relative lg:col-span-2">
          <select
            value={roleGroup}
            onChange={(event) => setRoleGroup(event.target.value)}
            className="activity-pill h-11 w-full appearance-none border border-line/70 bg-card/60 px-4 text-sm text-slate-200 outline-none transition focus:border-accentBlue/70"
          >
            <option value="ALL">All Roles</option>
            {ALLOWED_ROLE_GROUPS.map((value) => (
              <option key={`insider-role-${value}`} value={value}>
                {toRoleLabel(value)}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        </div>
        <div className="relative lg:col-span-2">
          <select
            value={windowDays}
            onChange={(event) => setWindowDays(event.target.value)}
            className="activity-pill h-11 w-full appearance-none border border-line/70 bg-card/60 px-4 text-sm text-slate-200 outline-none transition focus:border-accentBlue/70"
          >
            <option value="7">Last 7D</option>
            <option value="30">Last 30D</option>
            <option value="90">Last 90D</option>
            <option value="180">Last 6M</option>
            <option value="365">Last 1Y</option>
            <option value="ALL">All Dates</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        </div>
        <div className="flex items-center justify-end lg:col-span-1">
          {(search || signalType !== "ALL" || roleGroup !== "ALL" || windowDays !== "90") ? (
            <button
              type="button"
              onClick={() => {
                setSearch("");
                setSignalType("ALL");
                setRoleGroup("ALL");
                setWindowDays("90");
              }}
              className="activity-pill border border-line/80 bg-card/70 px-3 py-1.5 text-xs text-slate-300 transition hover:border-accentBlue/70 hover:text-slate-100"
            >
              Clear
            </button>
          ) : null}
        </div>
      </div>

      <div className="w-full text-left text-xs text-slate-500">
        Showing <span className="text-slate-400">{liveRows.length.toLocaleString("en-US")}</span> transactions
        {loading ? " • Updating..." : ""}
      </div>

      <div className="overflow-x-auto rounded-none border border-line/70">
        <table className="min-w-full divide-y divide-line/60 text-sm">
          <thead>
            <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Signal</th>
              <th className="px-3 py-2">Ticker</th>
              <th className="px-3 py-2">Insider</th>
              <th className="px-3 py-2">Role</th>
              <th className="px-3 py-2">Code</th>
              <th className="px-3 py-2 text-right">Shares</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-right">Value</th>
              <th className="px-3 py-2">Form</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/50 text-slate-300">
            {liveRows.length ? (
              liveRows.map((row) => (
                <tr key={`insider-row-${row.insider_tx_id}`}>
                  <td className="px-3 py-2 text-xs text-slate-400">{row.transaction_date || "-"}</td>
                  <td className="px-3 py-2">
                    <span className={toSignalClass(row.signal_type)}>{row.signal_type || "OTHER"}</span>
                  </td>
                  <td className="px-3 py-2">
                    {row.ticker ? (
                      <Link href={`/security/${encodeURIComponent(row.ticker)}`} className="inline-flex items-center gap-2 text-accentBlue hover:text-white">
                        <TickerIcon ticker={row.ticker} label={row.issuer_name || undefined} />
                        <span>{row.ticker}</span>
                      </Link>
                    ) : (
                      <span>{row.issuer_name || "-"}</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <div className="min-w-[180px]">
                      <p className="truncate text-slate-200">{row.reporting_owner_name || "-"}</p>
                      <p className="truncate text-xs text-slate-500">{row.reporting_owner_title || row.issuer_name || "-"}</p>
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400">{toRoleLabel(row.role_group)}</td>
                  <td className="px-3 py-2 text-xs text-slate-400">
                    {row.transaction_code ? (
                      <span
                        tabIndex={0}
                        className="group relative inline-flex cursor-help items-center underline decoration-dotted decoration-slate-500/60 underline-offset-2 focus-visible:outline-none"
                      >
                        <span>{row.transaction_code}</span>
                        <span
                          role="tooltip"
                          className="pointer-events-none absolute bottom-full left-1/2 z-30 mb-2 hidden w-64 -translate-x-1/2 rounded-md border border-line/90 bg-[#0a1320]/95 px-2.5 py-1.5 text-[11px] leading-snug text-slate-200 shadow-[0_8px_26px_rgba(0,0,0,0.45)] group-hover:block group-focus-within:block"
                        >
                          {toTransactionCodeExplanation(row.transaction_code)}
                        </span>
                      </span>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">{fmtNumber(row.transaction_shares, 0)}</td>
                  <td className="px-3 py-2 text-right">{fmtUsd(row.transaction_price)}</td>
                  <td
                    className={[
                      "px-3 py-2 text-right",
                      row.signal_type === "OPEN_MARKET_BUY"
                        ? "text-emerald-300"
                        : row.signal_type === "OPEN_MARKET_SELL"
                          ? "text-rose-300"
                          : "text-slate-300",
                    ].join(" ")}
                  >
                    {fmtUsd(row.transaction_value_usd)}
                  </td>
                  <td className="px-3 py-2">
                    {row.sec_url ? (
                      <a href={row.sec_url} target="_blank" rel="noreferrer" className="text-accentBlue hover:text-white">
                        {row.form_type}
                      </a>
                    ) : (
                      row.form_type
                    )}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={10} className="px-3 py-4 text-center text-sm text-slate-500">
                  {liveError ? `Insider feed unavailable: ${liveError}` : "No transactions match current filters."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
