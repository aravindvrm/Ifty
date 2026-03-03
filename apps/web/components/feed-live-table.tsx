"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { get13DGFeed, type Feed13DGResponse } from "@/lib/api";

type FeedRow = Feed13DGResponse["rows"][number];
const ALLOWED_EVENT_TYPES = ["NEW_5PCT", "EXIT_5PCT", "AMENDMENT_UP", "AMENDMENT_DOWN", "OTHER"] as const;
type AllowedEventType = (typeof ALLOWED_EVENT_TYPES)[number];

function toEventClass(eventType: string): string {
  return `event-chip event-${(eventType || "").toLowerCase().replace(/_/g, "-")}`;
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
  const [mappedOnly, setMappedOnly] = useState(true);
  const [includeOther, setIncludeOther] = useState(false);
  const [includeLowQuality, setIncludeLowQuality] = useState(false);
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
          includeOther,
          mappedOnly,
          includeLowQuality,
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
  }, [search, eventType, formType, windowDays, mappedOnly, includeOther, includeLowQuality]);

  return (
    <>
      <div className="feed-controls">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search ticker, security, institution, CUSIP..."
          className="feed-control-input feed-control-search"
        />
        <select
          value={eventType}
          onChange={(event) => setEventType(event.target.value)}
          className="feed-control-input"
        >
          <option value="ALL">All Events</option>
          {eventTypes.map((value) => (
            <option key={`event-type-${value}`} value={value}>
              {value}
            </option>
          ))}
        </select>
        <select
          value={formType}
          onChange={(event) => setFormType(event.target.value)}
          className="feed-control-input"
        >
          <option value="ALL">All Forms</option>
          {formTypes.map((value) => (
            <option key={`form-type-${value}`} value={value}>
              {value}
            </option>
          ))}
        </select>
        <select
          value={windowDays}
          onChange={(event) => setWindowDays(event.target.value)}
          className="feed-control-input"
        >
          <option value="7">Last 7D</option>
          <option value="30">Last 30D</option>
          <option value="90">Last 90D</option>
          <option value="180">Last 6M</option>
          <option value="365">Last 1Y</option>
          <option value="ALL">All Dates</option>
        </select>
        <label className="feed-control-check">
          <input type="checkbox" checked={mappedOnly} onChange={(event) => setMappedOnly(event.target.checked)} />
          Mapped only
        </label>
        <label className="feed-control-check">
          <input type="checkbox" checked={includeOther} onChange={(event) => setIncludeOther(event.target.checked)} />
          Include OTHER
        </label>
        <label className="feed-control-check">
          <input
            type="checkbox"
            checked={includeLowQuality}
            onChange={(event) => setIncludeLowQuality(event.target.checked)}
          />
          Include Low Quality
        </label>
      </div>

      <div className="feed-results-line">
        <span>
          Showing <strong>{liveRows.length.toLocaleString("en-US")}</strong> events
          {loading ? " • Updating..." : ""}
        </span>
        {(search || eventType !== "ALL" || formType !== "ALL" || windowDays !== "90" || !mappedOnly || includeOther || includeLowQuality) && (
          <button
            type="button"
            onClick={() => {
              setSearch("");
              setEventType("ALL");
              setFormType("ALL");
              setWindowDays("90");
              setMappedOnly(true);
              setIncludeOther(false);
              setIncludeLowQuality(false);
            }}
          >
            Clear Filters
          </button>
        )}
      </div>

      <div className="table-wrap">
        <table className="table feed-table">
          <thead>
            <tr>
              <th>Date</th>
              <th>Event</th>
              <th>Security</th>
              <th>Institution</th>
              <th>% Owned</th>
              <th>Shares</th>
              <th>Form</th>
            </tr>
          </thead>
          <tbody>
            {liveRows.length ? (
              liveRows.map((row) => (
                <tr key={`feed-row-${row.bo_event_id}`}>
                  <td>{row.report_date}</td>
                  <td>
                    <span className={toEventClass(row.event_type)}>{row.event_type}</span>
                  </td>
                  <td>
                    {row.ticker ? (
                      <Link href={`/security/${encodeURIComponent(row.ticker)}`}>{row.ticker}</Link>
                    ) : (
                      displaySecurity(row)
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
                  <td>
                    {row.shares_beneficial_owned === null || row.shares_beneficial_owned === undefined
                      ? "-"
                      : Number(row.shares_beneficial_owned).toLocaleString("en-US")}
                  </td>
                  <td>{row.form_type}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={7} className="muted">
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
