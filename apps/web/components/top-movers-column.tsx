"use client";

import Link from "next/link";
import { useEffect, useRef } from "react";

import { TickerIcon } from "@/components/ticker-icon";
import { fmtNumber, fmtUsd } from "@/lib/format";

type MoverRow = {
  security_id: number;
  ticker: string | null;
  security_name: string | null;
  net_value_change_usd: number;
  net_holder_count: number;
  series: Array<{ report_date: string; net_shares: number; net_holder_count: number }>;
};

function toneClass(value: number): string {
  return value >= 0 ? "text-emerald-300" : "text-rose-300";
}

function fmtSigned(value: number, digits = 0): string {
  const base = fmtNumber(value, digits);
  if (value > 0) return `+${base}`;
  return base;
}

function fmtSignedUsd(value: number): string {
  if (value > 0) return `+${fmtUsd(value)}`;
  return fmtUsd(value);
}

export function TopMoversColumn({
  title,
  columnKey,
  rows,
  pageSize = 5,
  className = "",
}: {
  title: string;
  columnKey: string;
  rows: MoverRow[];
  pageSize?: number;
  className?: string;
}) {
  const SCROLL_PX_PER_SEC = 24;
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

  const renderRows = (rowsToRender: MoverRow[], pageKey: string, isPrimary = false) => (
    <div ref={isPrimary ? primaryListRef : undefined} className="space-y-2">
      {rowsToRender.map((row) => (
        <div
          key={`${columnKey}-${pageKey}-${row.security_id}`}
          className="rounded-none border border-line/60 bg-cardSoft/50 p-2.5 transition-colors hover:border-line/70 hover:bg-cardSoft/60"
        >
          <div className="flex items-center justify-between gap-2">
            <Link
              href={`/security/${encodeURIComponent(row.ticker ?? "")}`}
              className="inline-flex min-w-0 items-center gap-2 truncate text-sm font-medium text-accentBlue hover:text-white"
            >
              <TickerIcon ticker={row.ticker} label={row.security_name} />
              <span className="truncate">{row.ticker ?? row.security_name ?? `Security ${row.security_id}`}</span>
            </Link>
            <span className={`text-xs font-medium ${toneClass(row.net_value_change_usd)}`}>
              {fmtSignedUsd(row.net_value_change_usd)}
            </span>
          </div>
          <div className="mt-1 flex items-center justify-between text-xs text-slate-500">
            <span>Net holders</span>
            <span className={toneClass(row.net_holder_count)}>{fmtSigned(row.net_holder_count, 0)}</span>
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <div className={className}>
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
        {rows.length ? (
          <div ref={trackRef} className="absolute inset-0 will-change-transform">
            {renderRows(rows, "primary", true)}
            {shouldAnimate ? renderRows(rows, "clone") : null}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No eligible securities for this view.</p>
        )}
      </div>
    </div>
  );
}
