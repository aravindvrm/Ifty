"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { Sparkline } from "@/components/charts";
import { TickerIcon } from "@/components/ticker-icon";
import { fmtNumber, fmtUsd } from "@/lib/format";

type SparkPoint = { report_date: string; net_shares: number; net_holder_count: number };

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
  intervalMs = 5200,
  className = "",
}: {
  title: string;
  columnKey: string;
  rows: MoverRow[];
  pageSize?: number;
  intervalMs?: number;
  className?: string;
}) {
  const ANIMATION_MS = 620;
  const ROW_HEIGHT_PX = 102;
  const ROW_GAP_PX = 8;
  const VIEWPORT_BUFFER_PX = 16;
  const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
  const [page, setPage] = useState(0);
  const [incomingPage, setIncomingPage] = useState<number | null>(null);
  const [animating, setAnimating] = useState(false);
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    setPage(0);
    setIncomingPage(null);
    setAnimating(false);
  }, [rows.length, pageSize]);

  useEffect(() => {
    if (pageCount <= 1 || animating || incomingPage !== null) return;
    if (isHovered) return;
    const timer = window.setTimeout(() => {
      setIncomingPage((page + 1) % pageCount);
    }, Math.max(1800, intervalMs));
    return () => window.clearTimeout(timer);
  }, [animating, incomingPage, intervalMs, isHovered, page, pageCount]);

  useEffect(() => {
    if (incomingPage === null) return;
    const raf = window.requestAnimationFrame(() => setAnimating(true));
    return () => window.cancelAnimationFrame(raf);
  }, [incomingPage]);

  useEffect(() => {
    if (!animating || incomingPage === null) return;
    const timer = window.setTimeout(() => {
      setPage(incomingPage);
      setIncomingPage(null);
      setAnimating(false);
    }, ANIMATION_MS);
    return () => window.clearTimeout(timer);
  }, [ANIMATION_MS, animating, incomingPage]);

  const pageRows = useMemo(() => {
    const start = page * pageSize;
    return rows.slice(start, start + pageSize);
  }, [page, pageSize, rows]);
  const incomingRows = useMemo(() => {
    if (incomingPage === null) return [] as MoverRow[];
    const start = incomingPage * pageSize;
    return rows.slice(start, start + pageSize);
  }, [incomingPage, pageSize, rows]);
  const viewportHeight = Math.max(
    440,
    pageSize * ROW_HEIGHT_PX + Math.max(0, pageSize - 1) * ROW_GAP_PX + VIEWPORT_BUFFER_PX
  );

  const currentPaneStyle = {
    transform: animating && incomingPage !== null ? "translateY(-100%)" : "translateY(0%)",
    transition: incomingPage !== null ? `transform ${ANIMATION_MS}ms cubic-bezier(0.22, 0.8, 0.3, 1)` : "none",
  };
  const incomingPaneStyle = {
    transform: animating ? "translateY(0%)" : "translateY(100%)",
    transition: `transform ${ANIMATION_MS}ms cubic-bezier(0.22, 0.8, 0.3, 1)`,
  };

  const renderRows = (rowsToRender: MoverRow[], pageKey: string) => (
    <div className="space-y-2">
      {rowsToRender.map((row) => (
        <div
          key={`${columnKey}-${pageKey}-${row.security_id}`}
          className="rounded-none border border-line/60 bg-cardSoft/50 p-2.5 transition-colors hover:border-accentBlue/70 hover:bg-card/75"
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
          <div className="mt-2 h-9 rounded-none border border-line/60 bg-black/25 px-1">
            <Sparkline data={row.series as SparkPoint[]} />
          </div>
        </div>
      ))}
    </div>
  );

  return (
    <div className={className}>
      <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
      <div
        className="relative mt-3 overflow-hidden"
        style={{ height: `${viewportHeight}px` }}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
      >
        {rows.length ? (
          <div className="absolute inset-0" style={currentPaneStyle}>
            {renderRows(pageRows, `page-${page}`)}
          </div>
        ) : (
          <p className="text-xs text-slate-500">No eligible securities for this view.</p>
        )}
        {rows.length && incomingPage !== null ? (
          <div className="absolute inset-0" style={incomingPaneStyle}>
            {renderRows(incomingRows, `incoming-${incomingPage}`)}
          </div>
        ) : (
          null
        )}
      </div>
      {rows.length > pageSize ? (
        <div className="mt-2 flex items-center justify-between text-[10px] text-slate-500">
          <span>{fmtNumber(rows.length)} items</span>
          <span>
            Page {page + 1}/{pageCount}
          </span>
        </div>
      ) : null}
    </div>
  );
}
