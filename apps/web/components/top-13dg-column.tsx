"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { get13DGFeed, type Feed13DGResponse } from "@/lib/api";
import { LottieLoader } from "@/components/lottie-loader";
import { TickerIcon } from "@/components/ticker-icon";

type FeedRow = Feed13DGResponse["rows"][number];

function displaySecurity(row: FeedRow): string {
  return row.security_display || row.ticker || row.security_name || row.issuer_name_raw || row.cusip_raw || "-";
}

function isUniverseInstitution(row: FeedRow): boolean {
  return Boolean(row.manager_id && row.manager_in_universe === 1);
}

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

function toEventLabel(eventType: string): string {
  const value = (eventType || "").toUpperCase();
  if (value === "NEW_5PCT") return "5% New";
  if (value === "AMENDMENT_UP") return "Amendment";
  if (value === "AMENDMENT_DOWN") return "Reduction";
  if (value === "EXIT_5PCT") return "Exit";
  return "Other";
}

export function Top13DGColumn({
  title = "13 D/G Activity",
  pageSize = 5,
}: {
  title?: string;
  pageSize?: number;
}) {
  const [rows, setRows] = useState<FeedRow[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const seq = useRef(0);

  const SCROLL_PX_PER_SEC = 26;
  const ROW_HEIGHT_PX = 74;
  const ROW_GAP_PX = 8;
  const VIEWPORT_BUFFER_PX = 12;
  const shouldAnimate = rows.length > pageSize;
  const trackRef = useRef<HTMLDivElement | null>(null);
  const primaryListRef = useRef<HTMLDivElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const lastTsRef = useRef<number | null>(null);
  const offsetRef = useRef(0);
  const cycleHeightRef = useRef(0);
  const pausedRef = useRef(false);

  const viewportHeight = Math.max(
    320,
    pageSize * ROW_HEIGHT_PX + Math.max(0, pageSize - 1) * ROW_GAP_PX + VIEWPORT_BUFFER_PX
  );

  useEffect(() => {
    let disposed = false;

    async function load() {
      const token = seq.current + 1;
      seq.current = token;
      try {
        const response = await get13DGFeed({
          days: 45,
          limitN: 24,
          includeOther: false,
          mappedOnly: true,
          universeOnly: true,
          includeLowQuality: false,
        });
        if (disposed || seq.current !== token) return;
        setRows(response.rows ?? []);
        setError(false);
      } catch {
        if (disposed || seq.current !== token) return;
        setRows([]);
        setError(true);
      } finally {
        if (!disposed && seq.current === token) {
          setReady(true);
        }
      }
    }

    void load();
    const interval = window.setInterval(load, 5 * 60 * 1000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, []);

  useEffect(() => {
    const trackEl = trackRef.current;
    const primaryEl = primaryListRef.current;
    if (!trackEl || !primaryEl) return;

    if (!shouldAnimate) {
      trackEl.style.transform = "translateY(0px)";
      return;
    }

    pausedRef.current = false;
    offsetRef.current = 0;
    lastTsRef.current = null;
    cycleHeightRef.current = Math.max(0, primaryEl.offsetHeight);
    trackEl.style.transform = "translateY(0px)";

    const resizeObserver =
      typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(() => {
            cycleHeightRef.current = Math.max(0, primaryEl.offsetHeight);
            if (cycleHeightRef.current > 0) {
              offsetRef.current %= cycleHeightRef.current;
              trackEl.style.transform = `translateY(-${offsetRef.current}px)`;
            }
          })
        : null;
    if (resizeObserver) resizeObserver.observe(primaryEl);

    const step = (timestamp: number) => {
      const cycleHeight = cycleHeightRef.current;
      if (lastTsRef.current === null) lastTsRef.current = timestamp;
      const deltaMs = timestamp - lastTsRef.current;
      lastTsRef.current = timestamp;

      if (!pausedRef.current && cycleHeight > 0) {
        offsetRef.current += (SCROLL_PX_PER_SEC * deltaMs) / 1000;
        if (offsetRef.current >= cycleHeight) {
          offsetRef.current %= cycleHeight;
        }
        trackEl.style.transform = `translateY(-${offsetRef.current}px)`;
      }

      rafRef.current = window.requestAnimationFrame(step);
    };

    rafRef.current = window.requestAnimationFrame(step);
    return () => {
      if (rafRef.current !== null) {
        window.cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      if (resizeObserver) resizeObserver.disconnect();
    };
  }, [SCROLL_PX_PER_SEC, shouldAnimate, rows.length, pageSize]);

  const items = useMemo(() => {
    if (!rows.length) return [];
    return shouldAnimate ? [...rows, ...rows] : rows;
  }, [rows, shouldAnimate]);

  const renderRows = (list: FeedRow[], keyPrefix: string, isPrimary = false) => (
    <div ref={isPrimary ? primaryListRef : undefined} className="space-y-2">
      {list.map((row, idx) => {
        return (
          <div
            key={`${keyPrefix}-${row.bo_event_id}-${idx}`}
            className="rounded-none border border-line/60 bg-cardSoft/50 p-2.5 transition-colors hover:border-line/70 hover:bg-cardSoft/60"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs text-slate-500">{row.report_date}</span>
              <span className="text-[11px] text-slate-400">{row.form_type || "-"}</span>
            </div>
            <div className="mt-1">
              {row.ticker ? (
                <Link
                  prefetch={false}
                  href={`/security/${encodeURIComponent(row.ticker)}`}
                  className="inline-flex min-w-0 items-center gap-2 text-sm font-medium text-accentBlue hover:text-white"
                >
                  <TickerIcon ticker={row.ticker} label={displaySecurity(row)} />
                  <span className="truncate">{row.ticker}</span>
                  <span className="truncate text-slate-400">- {displaySecurity(row)}</span>
                </Link>
              ) : (
                <span className="text-sm text-slate-300">{displaySecurity(row)}</span>
              )}
            </div>
            <div className="mt-1 flex items-center justify-between gap-2 text-xs">
              <span className="truncate text-slate-500">
                {isUniverseInstitution(row) ? (
                  <Link
                    prefetch={false}
                    href={`/explore?type=institution&key=${encodeURIComponent(String(row.manager_id))}`}
                    className="text-slate-300 hover:text-white"
                  >
                    {row.manager_name ?? `Institution ${row.manager_id}`}
                  </Link>
                ) : (
                  row.manager_name ?? "-"
                )}
              </span>
              <span className={toEventClass(row.event_type)}>{row.event_label || toEventLabel(row.event_type)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );

  return (
    <div>
      <h3 className="text-base font-semibold text-slate-100">{title}</h3>
      <div
        className="relative mt-3 overflow-hidden"
        style={{ height: `${viewportHeight}px` }}
        onMouseEnter={() => {
          pausedRef.current = true;
        }}
        onMouseLeave={() => {
          pausedRef.current = false;
        }}
      >
        {!ready ? (
          <div className="absolute inset-0 grid place-items-center">
            <LottieLoader size={84} />
          </div>
        ) : error || rows.length === 0 ? (
          <p className="text-xs text-slate-500">13D/G feed unavailable.</p>
        ) : (
          <div ref={trackRef} className="absolute inset-0 will-change-transform">
            {renderRows(rows, "primary", true)}
            {shouldAnimate ? renderRows(items.slice(rows.length), "clone") : null}
          </div>
        )}
      </div>
    </div>
  );
}
