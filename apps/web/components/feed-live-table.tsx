"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown } from "lucide-react";

import { get13DGFeed, type Feed13DGResponse } from "@/lib/api";
import { TickerIcon } from "@/components/ticker-icon";

type FeedRow = Feed13DGResponse["rows"][number];
const ALLOWED_EVENT_TYPES = ["NEW_5PCT", "EXIT_5PCT", "AMENDMENT_UP", "AMENDMENT_DOWN", "OTHER"] as const;
type AllowedEventType = (typeof ALLOWED_EVENT_TYPES)[number];

function toEventClass(eventType: string): string {
  const value = (eventType || "").toUpperCase();
  const base = "inline-flex rounded-full border px-2 py-0.5 text-[11px]";
  if (value === "NEW_5PCT" || value === "AMENDMENT_UP") {
    return `${base} border-emerald-400/40 bg-emerald-400/10 text-emerald-300`;
  }
  if (value === "EXIT_5PCT" || value === "AMENDMENT_DOWN") {
    return `${base} border-rose-400/40 bg-rose-400/10 text-rose-300`;
  }
  return `${base} border-slate-500/50 bg-slate-500/10 text-slate-300`;
}

function displaySecurity(row: FeedRow): string {
  return row.security_display || row.ticker || row.security_name || row.issuer_name_raw || row.cusip_raw || "-";
}

export function FeedLiveTable({
  rows,
  loadError
}: {
  rows: FeedRow[];
  loadError?: string | null;
}) {
  const [search, setSearch] = useState("");
  const [eventType, setEventType] = useState("ALL");
  const [formType, setFormType] = useState("ALL");
  const [windowDays, setWindowDays] = useState("90");
  const [liveRows, setLiveRows] = useState<FeedRow[]>(rows);
  const [liveError, setLiveError] = useState<string | null>(loadError ?? null);
  const [loading, setLoading] = useState(false);
  const requestSeq = useRef(0);

  useEffect(() => {
    setLiveRows(rows);
    setLiveError(loadError ?? null);
  }, [rows, loadError]);

  const formTypes = useMemo(() => {
    const set = new Set<string>();
    [...rows, ...liveRows].forEach((row) => {
      if (row.form_type) set.add(row.form_type);
    });
    return Array.from(set).sort();
  }, [rows, liveRows]);

  const eventTypes = useMemo(() => {
    const set = new Set<AllowedEventType>();
    [...rows, ...liveRows].forEach((row) => {
      const value = row.event_type as AllowedEventType;
      if (ALLOWED_EVENT_TYPES.includes(value)) set.add(value);
    });
    return ALLOWED_EVENT_TYPES.filter((value) => set.has(value));
  }, [rows, liveRows]);

  useEffect(() => {
    const seq = requestSeq.current + 1;
    requestSeq.current = seq;
    const days = windowDays === "ALL" ? 3650 : Number(windowDays);
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const selectedEventType: AllowedEventType | undefined =
          eventType !== "ALL" && ALLOWED_EVENT_TYPES.includes(eventType as AllowedEventType)
            ? (eventType as AllowedEventType)
            : undefined;
        const response = await get13DGFeed({
          limitN: 2000,
          days: Number.isFinite(days) && days > 0 ? days : 3650,
          includeOther: false,
          mappedOnly: true,
          includeLowQuality: false,
          eventType: selectedEventType,
          formType: formType === "ALL" ? undefined : formType,
          q: search.trim() || undefined
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
  }, [search, eventType, formType, windowDays]);

  return (
    <>
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search ticker, security, institution, CUSIP..."
          className="rounded-xl border border-line/80 bg-card/70 px-2.5 py-1.5 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70 lg:col-span-4"
        />
        <div className="relative lg:col-span-2">
          <select
            value={eventType}
            onChange={(event) => setEventType(event.target.value)}
            className="w-full appearance-none rounded-lg border border-line/70 bg-transparent px-2 py-1 text-xs text-slate-200 outline-none transition focus:border-accentBlue/70"
          >
            <option value="ALL">All Events</option>
            {eventTypes.map((value) => (
              <option key={`event-type-${value}`} value={value}>
                {value}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        </div>
        <div className="relative lg:col-span-2">
          <select
            value={formType}
            onChange={(event) => setFormType(event.target.value)}
            className="w-full appearance-none rounded-lg border border-line/70 bg-transparent px-2 py-1 text-xs text-slate-200 outline-none transition focus:border-accentBlue/70"
          >
            <option value="ALL">All Forms</option>
            {formTypes.map((value) => (
              <option key={`form-type-${value}`} value={value}>
                {value}
              </option>
            ))}
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        </div>
        <div className="relative lg:col-span-2">
          <select
            value={windowDays}
            onChange={(event) => setWindowDays(event.target.value)}
            className="w-full appearance-none rounded-lg border border-line/70 bg-transparent px-2 py-1 text-xs text-slate-200 outline-none transition focus:border-accentBlue/70"
          >
            <option value="7">Last 7D</option>
            <option value="30">Last 30D</option>
            <option value="90">Last 90D</option>
            <option value="180">Last 6M</option>
            <option value="365">Last 1Y</option>
            <option value="ALL">All Dates</option>
          </select>
          <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
        </div>
        <div className="flex items-center justify-end lg:col-span-2">
          <span className="rounded-lg border border-line/70 bg-transparent px-2 py-1 text-[11px] text-slate-400">
            Mode: High Quality Mapped
          </span>
        </div>
      </div>

      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-400">
        <span>
          Showing <strong>{liveRows.length.toLocaleString("en-US")}</strong> events
          {loading ? " • Updating..." : ""}
        </span>
        {(search || eventType !== "ALL" || formType !== "ALL" || windowDays !== "90") && (
          <button
            type="button"
            onClick={() => {
              setSearch("");
              setEventType("ALL");
              setFormType("ALL");
              setWindowDays("90");
            }}
            className="rounded-lg border border-line/80 bg-card/70 px-2.5 py-1 text-xs text-slate-300 transition hover:border-accentBlue/70 hover:text-slate-100"
          >
            Clear Filters
          </button>
        )}
      </div>

      <div className="mt-3 overflow-x-auto rounded-xl border border-line/70">
        <table className="min-w-full divide-y divide-line/60 text-sm">
          <thead>
            <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">Date</th>
              <th className="px-3 py-2">Event</th>
              <th className="px-3 py-2">Security</th>
              <th className="px-3 py-2">Institution</th>
              <th className="px-3 py-2 text-right">% Owned</th>
              <th className="px-3 py-2 text-right">Shares</th>
              <th className="px-3 py-2">Form</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/50 text-slate-300">
            {liveRows.length ? (
              liveRows.map((row) => (
                <tr key={`feed-row-${row.bo_event_id}`}>
                  <td className="px-3 py-2 text-xs text-slate-400">{row.report_date}</td>
                  <td className="px-3 py-2">
                    <span className={toEventClass(row.event_type)}>{row.event_type}</span>
                  </td>
                  <td className="px-3 py-2">
                    {row.ticker ? (
                      <Link href={`/security/${encodeURIComponent(row.ticker)}`} className="inline-flex items-center gap-2 text-accentBlue hover:text-white">
                        <TickerIcon ticker={row.ticker} label={displaySecurity(row)} />
                        <span>{row.ticker}</span>
                      </Link>
                    ) : (
                      displaySecurity(row)
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {row.manager_id ? (
                      <Link href={`/institution/${row.manager_id}`} className="text-accentBlue hover:text-white">
                        {row.manager_name ?? `Institution ${row.manager_id}`}
                      </Link>
                    ) : (
                      row.manager_name ?? "-"
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {row.percent_beneficial_owned === null || row.percent_beneficial_owned === undefined
                      ? "-"
                      : `${Number(row.percent_beneficial_owned).toFixed(2)}%`}
                  </td>
                  <td className="px-3 py-2 text-right">
                    {row.shares_beneficial_owned === null || row.shares_beneficial_owned === undefined
                      ? "-"
                      : Number(row.shares_beneficial_owned).toLocaleString("en-US")}
                  </td>
                  <td className="px-3 py-2">{row.form_type}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-center text-sm text-slate-500">
                  {liveError ? `Feed unavailable: ${liveError}` : "No events match current filters."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
