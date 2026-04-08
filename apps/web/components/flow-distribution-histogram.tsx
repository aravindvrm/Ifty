"use client";

import { useLayoutEffect, useMemo, useRef, useState } from "react";

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
  clientX: number;
  clientY: number;
};

export function FlowDistributionHistogram({ bins, totalSecurities }: Props) {
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<HoverState | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ left: number; top: number }>({ left: 8, top: 8 });
  const histogramPeak = Math.max(1, ...bins.map((bin) => bin.count ?? 0));
  const flowMin = bins.length > 0 ? Number(bins[0].range_start_usd ?? 0) : 0;
  const flowMax = bins.length > 0 ? Number(bins[bins.length - 1].range_end_usd ?? 0) : 0;
  const flowMid = (flowMin + flowMax) / 2;

  const tooltip = useMemo(() => {
    if (!hover) return null;
    const pct = Number(
      hover.bin.pct_of_universe ??
        (totalSecurities > 0 ? hover.bin.count / totalSecurities : 0)
    );
    return {
      pct,
      contributors: (hover.bin.top_contributors ?? []).slice(0, 5),
    };
  }, [hover, totalSecurities]);

  useLayoutEffect(() => {
    if (!hover) return;
    const tip = tooltipRef.current;
    if (!tip) return;
    const tipRect = tip.getBoundingClientRect();
    const gap = 12;
    const pad = 8;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let left = hover.clientX + gap;
    if (left + tipRect.width > viewportWidth - pad) {
      left = hover.clientX - tipRect.width - gap;
    }
    left = Math.max(pad, Math.min(left, viewportWidth - tipRect.width - pad));

    let top = hover.clientY + gap;
    if (top + tipRect.height > viewportHeight - pad) {
      top = hover.clientY - tipRect.height - gap;
    }
    top = Math.max(pad, Math.min(top, viewportHeight - tipRect.height - pad));

    setTooltipPos((prev) =>
      Math.abs(prev.left - left) < 0.5 && Math.abs(prev.top - top) < 0.5
        ? prev
        : { left, top }
    );
  }, [hover]);

  return (
    <>
      <div className="relative h-80 overflow-x-auto overflow-y-hidden rounded-none border border-line/70 bg-black/20 p-3">
        <div className="flex h-full min-w-max items-end gap-1 md:min-w-0 md:w-full">
          {bins.map((bin) => {
            const normalizedHeight = Math.round((Math.log1p(bin.count) / Math.log1p(histogramPeak)) * 292);
            const heightPx = bin.count > 0 ? Math.max(14, normalizedHeight) : 2;
            return (
              <div
                key={bin.bin_index}
                className={`w-[6px] shrink-0 transition-opacity hover:opacity-85 md:flex-1 md:w-auto ${histogramTone(
                  Number(bin.range_start_usd ?? 0),
                  Number(bin.range_end_usd ?? 0)
                )} ${bin.count > 0 ? "" : "opacity-30"}`}
                style={{ height: `${heightPx}px` }}
                onMouseEnter={(event) => {
                  setHover({
                    bin,
                    clientX: event.clientX,
                    clientY: event.clientY,
                  });
                }}
                onMouseMove={(event) => {
                  setHover((prev) =>
                    prev && prev.bin.bin_index === bin.bin_index
                      ? { ...prev, clientX: event.clientX, clientY: event.clientY }
                      : {
                          bin,
                          clientX: event.clientX,
                          clientY: event.clientY,
                        }
                  );
                }}
                onMouseLeave={() => setHover((prev) => (prev?.bin.bin_index === bin.bin_index ? null : prev))}
              />
            );
          })}
        </div>

        {hover && tooltip ? (
          <div
            ref={tooltipRef}
            className="pointer-events-none fixed z-[80] heatmap-tooltip flow-tooltip"
            style={{ left: `${tooltipPos.left}px`, top: `${tooltipPos.top}px` }}
          >
            <div className="heatmap-tooltip-title">
              {fmtUsd(hover.bin.range_start_usd)} to {fmtUsd(hover.bin.range_end_usd)}
            </div>
            <div className="heatmap-tooltip-row">
              <span className="heatmap-tooltip-label">Universe</span>
              <span className="heatmap-tooltip-value">
                {fmtNumber(hover.bin.count)} securities ({fmtPct(tooltip.pct)})
              </span>
            </div>
            <div className="mt-2 text-slate-400">Largest moves in bin</div>
            {tooltip.contributors.length > 0 ? (
              <ul className="mt-1 space-y-1">
                {tooltip.contributors.map((row) => (
                  <li key={`${row.security_id}-${row.net_value_usd}`} className="heatmap-tooltip-row">
                    <span className="heatmap-tooltip-label truncate">
                      {shortLabel(row.ticker || row.label || row.security_name || "")}
                    </span>
                    <span
                      className={[
                        "heatmap-tooltip-value",
                        Number(row.net_value_usd) >= 0 ? "text-emerald-300" : "text-rose-300",
                      ].join(" ")}
                    >
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
