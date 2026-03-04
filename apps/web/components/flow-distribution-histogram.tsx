"use client";

import { useMemo, useRef, useState } from "react";

import { fmtNumber, fmtPct, fmtUsd } from "@/lib/format";

type BinContributor = {
  security_id: number;
  ticker: string | null;
  security_name: string | null;
  label: string;
  net_value_usd: number;
};

type FlowBin = {
  bin_index: number;
  range_start_usd: number;
  range_end_usd: number;
  count: number;
  pct_of_universe?: number;
  top_contributors?: BinContributor[];
};

type Props = {
  bins: FlowBin[];
  totalSecurities: number;
};

function histogramTone(rangeStartUsd: number, rangeEndUsd: number): string {
  const midpoint = (rangeStartUsd + rangeEndUsd) / 2;
  if (midpoint < 0) return "bg-rose-400/80";
  if (midpoint > 0) return "bg-emerald-400/80";
  return "bg-accentBlue/80";
}

function fmtSignedUsd(value: number): string {
  if (value > 0) return `+${fmtUsd(value)}`;
  return fmtUsd(value);
}

function fmtUsdAxis(value: number): string {
  if (!Number.isFinite(value)) return "$0";
  const abs = Math.abs(value);
  if (abs >= 1000) return fmtUsd(value);
  return `$${value.toFixed(2)}`;
}

function shortLabel(raw: string): string {
  const value = (raw ?? "").trim();
  if (!value) return "Unknown";
  return value.length > 18 ? `${value.slice(0, 18)}…` : value;
}

type HoverState = {
  bin: FlowBin;
  x: number;
  y: number;
};

export function FlowDistributionHistogram({ bins, totalSecurities }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<HoverState | null>(null);
  const histogramPeak = Math.max(1, ...bins.map((bin) => bin.count ?? 0));
  const flowMin = bins.length > 0 ? Number(bins[0].range_start_usd ?? 0) : 0;
  const flowMax = bins.length > 0 ? Number(bins[bins.length - 1].range_end_usd ?? 0) : 0;
  const flowMid = (flowMin + flowMax) / 2;

  const tooltip = useMemo(() => {
    if (!hover) return null;
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return null;
    const tooltipWidth = 360;
    const left = Math.max(8, Math.min(hover.x + 12, rect.width - tooltipWidth - 8));
    const top = Math.max(8, hover.y - 12);
    const pct = Number(
      hover.bin.pct_of_universe ??
        (totalSecurities > 0 ? hover.bin.count / totalSecurities : 0)
    );
    return {
      left,
      top,
      pct,
      contributors: (hover.bin.top_contributors ?? []).slice(0, 5),
    };
  }, [hover, totalSecurities]);

  return (
    <>
      <div ref={containerRef} className="relative flex h-80 items-end gap-1 rounded-none border border-line/70 bg-black/20 p-3">
        {bins.map((bin) => {
          const normalizedHeight = Math.round((Math.log1p(bin.count) / Math.log1p(histogramPeak)) * 292);
          const heightPx = bin.count > 0 ? Math.max(14, normalizedHeight) : 2;
          return (
            <div
              key={bin.bin_index}
              className={`flex-1 transition-opacity hover:opacity-85 ${histogramTone(
                Number(bin.range_start_usd ?? 0),
                Number(bin.range_end_usd ?? 0)
              )} ${bin.count > 0 ? "" : "opacity-30"}`}
              style={{ height: `${heightPx}px` }}
              onMouseEnter={(event) => {
                const rect = containerRef.current?.getBoundingClientRect();
                if (!rect) return;
                setHover({
                  bin,
                  x: event.clientX - rect.left,
                  y: event.clientY - rect.top,
                });
              }}
              onMouseMove={(event) => {
                const rect = containerRef.current?.getBoundingClientRect();
                if (!rect) return;
                setHover((prev) =>
                  prev && prev.bin.bin_index === bin.bin_index
                    ? { ...prev, x: event.clientX - rect.left, y: event.clientY - rect.top }
                    : {
                        bin,
                        x: event.clientX - rect.left,
                        y: event.clientY - rect.top,
                      }
                );
              }}
              onMouseLeave={() => setHover((prev) => (prev?.bin.bin_index === bin.bin_index ? null : prev))}
            />
          );
        })}

        {hover && tooltip ? (
          <div
            className="pointer-events-none absolute z-20 w-[360px] rounded-none border border-line/80 bg-[#060d18]/95 p-3 text-xs text-slate-200 shadow-panel backdrop-blur-sm"
            style={{ left: `${tooltip.left}px`, top: `${tooltip.top}px` }}
          >
            <div className="font-semibold text-slate-100">
              {fmtUsd(hover.bin.range_start_usd)} to {fmtUsd(hover.bin.range_end_usd)}
            </div>
            <div className="mt-1 text-slate-300">
              {fmtNumber(hover.bin.count)} securities • {fmtPct(tooltip.pct)} of filtered universe
            </div>
            <div className="mt-2 text-slate-400">Largest moves in bin</div>
            {tooltip.contributors.length > 0 ? (
              <ul className="mt-1 space-y-0.5">
                {tooltip.contributors.map((row) => (
                  <li key={`${row.security_id}-${row.net_value_usd}`} className="flex items-center justify-between gap-2">
                    <span className="truncate text-slate-100">
                      {shortLabel(row.ticker || row.label || row.security_name || "")}
                    </span>
                    <span className={Number(row.net_value_usd) >= 0 ? "text-emerald-300" : "text-rose-300"}>
                      {fmtSignedUsd(Number(row.net_value_usd ?? 0))}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="mt-1 text-slate-500">No contributor detail.</div>
            )}
          </div>
        ) : null}
      </div>
      <div className="grid grid-cols-3 text-xs text-slate-500">
        <span>{fmtUsdAxis(flowMin)}</span>
        <span className="text-center">{fmtUsdAxis(flowMid)}</span>
        <span className="text-right">{fmtUsdAxis(flowMax)}</span>
      </div>
    </>
  );
}
