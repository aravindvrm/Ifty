"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { ResponsiveTreeMap } from "@nivo/treemap";

import { fmtNumber, fmtPct, fmtUsdThousands } from "@/lib/format";
import { TickerIcon } from "@/components/ticker-icon";

import type { HoldingsHeatmapProps } from "./charts";

type NivoLeaf = {
  id: string;
  name: string;
  label: string;
  symbol: string | null;
  is_full_name: boolean;
  entry_order: number;
  sharesLabel: string;
  pctOfInstitutionLabel: string;
  value: number;
  color: string;
  valueLabel: string;
  deltaLabelValue: string;
};

type HeatmapHoverState = {
  name: string;
  sharesLabel: string;
  deltaLabelValue: string;
  pctOfInstitutionLabel: string;
  clientX: number;
  clientY: number;
};

function normalizeSuffixToken(token: string): string {
  return token.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
}

function compactEntityName(name: string): string {
  const raw = name.trim().replace(/\s+/g, " ");
  if (!raw) {
    return "Unknown";
  }
  const tokens = raw.split(" ");
  const trailingNoise = new Set([
    "INC",
    "CORP",
    "CORPORATION",
    "CO",
    "COMPANY",
    "LLC",
    "LP",
    "LTD",
    "PLC",
    "HOLDINGS",
    "HOLDING",
    "GROUP",
    "TRUST",
    "ADVISORS",
    "ADVISER",
    "MANAGEMENT"
  ]);
  while (tokens.length > 1 && trailingNoise.has(normalizeSuffixToken(tokens[tokens.length - 1]))) {
    tokens.pop();
  }
  if (tokens.length > 1 && normalizeSuffixToken(tokens[0]) === "THE") {
    tokens.shift();
  }
  const compact = tokens.join(" ").trim();
  return compact || raw;
}

function tileFill(size: number, delta: number | null | undefined, maxSize: number, maxAbsDelta: number): string {
  const sizeWeight = Math.max(0.18, Math.sqrt(Math.max(0, size) / maxSize));
  if (delta === null || delta === undefined || Number.isNaN(delta)) {
    return `rgba(14, 165, 233, ${(0.2 + sizeWeight * 0.48).toFixed(3)})`;
  }
  const deltaWeight = Math.min(1, Math.abs(delta) / maxAbsDelta);
  const alpha = 0.24 + 0.56 * Math.max(sizeWeight, deltaWeight);
  if (delta > 0) {
    return `rgba(34, 197, 94, ${alpha.toFixed(3)})`;
  }
  if (delta < 0) {
    return `rgba(239, 68, 68, ${alpha.toFixed(3)})`;
  }
  return `rgba(148, 163, 184, ${(0.22 + sizeWeight * 0.35).toFixed(3)})`;
}

function deriveLabel(
  name: string,
  explicitSymbol: string | null | undefined,
  labelMode: "auto" | "name"
): { label: string; isFullName: boolean } {
  if (labelMode === "auto" && explicitSymbol && explicitSymbol.trim()) {
    return { label: explicitSymbol.trim().toUpperCase(), isFullName: false };
  }
  return { label: compactEntityName(name), isFullName: true };
}

function formatByType(value: number, kind: "usd_thousands" | "number"): string {
  return kind === "usd_thousands" ? fmtUsdThousands(value) : fmtNumber(value);
}

function clamp(min: number, value: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function wrapWords(text: string, maxCharsPerLine: number, maxLines: number): string[] {
  const words = text.trim().split(/\s+/).filter(Boolean);
  if (words.length === 0) {
    return [];
  }
  const lines: string[] = [];
  let current = "";
  for (const word of words) {
    if (!current) {
      current = word;
      continue;
    }
    if ((`${current} ${word}`).length <= maxCharsPerLine) {
      current = `${current} ${word}`;
      continue;
    }
    lines.push(current);
    current = word;
    if (lines.length >= maxLines) {
      break;
    }
  }
  if (lines.length < maxLines && current) {
    lines.push(current);
  }
  if (lines.length > maxLines) {
    return lines.slice(0, maxLines);
  }
  const original = words.join(" ");
  const rendered = lines.join(" ");
  if (rendered.length < original.length && lines.length > 0) {
    const last = lines[lines.length - 1];
    const trimmed = last.length > 2 ? `${last.slice(0, last.length - 1)}…` : `${last}…`;
    lines[lines.length - 1] = trimmed;
  }
  return lines;
}

function NivoNode({
  node,
  onHover,
  onHoverEnd,
}: {
  node: any;
  onHover?: (event: React.MouseEvent<SVGRectElement>, node: any) => void;
  onHoverEnd?: () => void;
}) {
  if (!node?.isLeaf) {
    return null;
  }
  const width = Number(node.width ?? 0);
  const height = Number(node.height ?? 0);
  if (width < 14 || height < 14) {
    return null;
  }
  const label = String(node.data?.label ?? "");
  const symbol = String(node.data?.symbol ?? "").trim().toUpperCase();
  const isFullName = Boolean(node.data?.is_full_name);
  const valueLabel = String(node.data?.valueLabel ?? "");
  const showLabel = width >= 28 && height >= 22;
  const showValue = width >= 96 && height >= 56;
  const showIcon = Boolean(symbol) && width >= 92 && height >= 56;
  const iconSize = clamp(14, Math.round(Math.min(width, height) * 0.22), 22);
  const iconY = Math.max(4, Math.round(height * 0.08));
  const base = Math.min(width, height);
  let fontSizeLabel = isFullName
    ? clamp(8, Math.round(base * 0.18), 16)
    : clamp(10, Math.round(base * 0.28), 28);
  const maxLabelWidth = Math.max(18, width - 10);
  if (!isFullName && label) {
    const maxByWidth = maxLabelWidth / (Math.max(2, label.length) * 0.62);
    const maxByHeight = (showValue ? height * 0.38 : height * 0.62);
    fontSizeLabel = Math.floor(Math.min(fontSizeLabel, maxByWidth, maxByHeight));
  }
  fontSizeLabel = clamp(8, fontSizeLabel, 28);
  const maxCharsPerLine = Math.max(4, Math.floor(maxLabelWidth / Math.max(6, fontSizeLabel * 0.58)));
  const labelLines = isFullName
    ? wrapWords(label, maxCharsPerLine, showValue ? 2 : 3)
    : [label];
  const finalLabelLines = labelLines.filter(Boolean);
  const showLabelLines = showLabel && finalLabelLines.length > 0;
  const fontSizeValue = clamp(8, Math.round(fontSizeLabel * 0.62), 13);
  const lineHeight = Math.round(fontSizeLabel * 1.04);
  const labelCenterYBase = showValue ? height * 0.38 : height * 0.5;
  const labelCenterY = showIcon ? labelCenterYBase + iconSize * 0.44 + 4 : labelCenterYBase;
  const labelStartY = labelCenterY - ((finalLabelLines.length - 1) * lineHeight) / 2;
  const clipId = `tile-clip-${String(node.id).replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const entryOrderRaw = Number(node.data?.entry_order ?? 0);
  const entryOrder = Number.isFinite(entryOrderRaw) ? Math.max(0, entryOrderRaw) : 0;
  const enterStyle: CSSProperties = {
    animationDelay: `${Math.min(entryOrder, 42) * 30}ms`
  };

  return (
    <g transform={`translate(${node.x},${node.y})`}>
      <g className="heatmap-tile heatmap-tile-enter" style={enterStyle}>
        <clipPath id={clipId}>
          <rect x={1} y={1} width={Math.max(0, width - 2)} height={Math.max(0, height - 2)} rx={0} ry={0} />
        </clipPath>
        <rect
          className="heatmap-tile-rect"
          width={width}
          height={height}
          rx={0}
          ry={0}
          fill={String(node.color)}
          stroke="rgba(226, 232, 240, 0.24)"
          strokeWidth={1}
          onMouseEnter={(event) => {
            node.onMouseEnter?.(event);
            onHover?.(event, node);
          }}
          onMouseMove={(event) => {
            node.onMouseMove?.(event);
            onHover?.(event, node);
          }}
          onMouseLeave={(event) => {
            node.onMouseLeave?.(event);
            onHoverEnd?.();
          }}
          onClick={node.onClick}
        />
        {showIcon ? (
          <foreignObject
            x={width / 2 - iconSize / 2}
            y={iconY}
            width={iconSize}
            height={iconSize}
            clipPath={`url(#${clipId})`}
            style={{ pointerEvents: "none" }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
              <TickerIcon ticker={symbol} label={String(node.data?.name ?? label)} size={iconSize} />
            </div>
          </foreignObject>
        ) : null}
        {showLabelLines ? (
          <text
            x={width / 2}
            y={labelStartY}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="#e2e8f0"
            fontSize={fontSizeLabel}
            fontWeight={700}
            clipPath={`url(#${clipId})`}
            style={{ pointerEvents: "none", textTransform: isFullName ? "none" : "uppercase" }}
          >
            {finalLabelLines.map((line, idx) => (
              <tspan key={`${line}-${idx}`} x={width / 2} dy={idx === 0 ? 0 : lineHeight}>
                {line}
              </tspan>
            ))}
          </text>
        ) : null}
        {showValue ? (
          <text
            x={width / 2}
            y={height * 0.77}
            textAnchor="middle"
            dominantBaseline="middle"
            fill="rgba(226, 232, 240, 0.96)"
            fontSize={fontSizeValue}
            fontWeight={500}
            clipPath={`url(#${clipId})`}
            style={{ pointerEvents: "none" }}
          >
            {valueLabel}
          </text>
        ) : null}
      </g>
    </g>
  );
}

export function HoldingsHeatmapNivo({
  title,
  data,
  containerClassName,
  emptyText = "No mapped positions available.",
  valueLabel = "Value",
  deltaLabel = "QoQ",
  labelMode = "auto",
  maxTiles = 70,
  valueFormat = "usd_thousands",
  deltaFormat = "number",
  signedDelta = true,
  minRelativeSize = 0.0125,
  minTiles = 18
}: HoldingsHeatmapProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const tooltipRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(920);
  const [hover, setHover] = useState<HeatmapHoverState | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ left: number; top: number }>({ left: 8, top: 8 });

  useEffect(() => {
    const measure = () => {
      const nextWidth = Math.floor(containerRef.current?.getBoundingClientRect().width ?? 0);
      if (nextWidth > 0) {
        setContainerWidth(nextWidth);
      }
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, []);

  const prepared = useMemo(() => {
    const rankedBase = data
      .filter((point) => Number(point.size) > 0)
      .slice()
      .sort((a, b) => b.size - a.size)
      .slice(0, maxTiles);
    if (rankedBase.length === 0) {
      return [] as NivoLeaf[];
    }

    const maxSize = Math.max(1, ...rankedBase.map((point) => Math.abs(Number(point.size) || 0)));
    const ranked = rankedBase.filter((point, index) => {
      if (index < minTiles) {
        return true;
      }
      return Number(point.size) / maxSize >= minRelativeSize;
    });
    const maxAbsDelta = Math.max(1, ...ranked.map((point) => Math.abs(Number(point.delta ?? 0) || 0)));

    return ranked.map((point, index) => {
      const deltaValueRaw = point.delta === null || point.delta === undefined ? null : Number(point.delta);
      const deltaValue = deltaValueRaw !== null && !Number.isNaN(deltaValueRaw) ? deltaValueRaw : null;
      const deltaTextRaw = deltaValue === null ? "-" : formatByType(deltaValue, deltaFormat);
      const deltaText = signedDelta && deltaValue !== null && deltaValue > 0 ? `+${deltaTextRaw}` : deltaTextRaw;
      const sharesValueRaw = point.shares === null || point.shares === undefined ? null : Number(point.shares);
      const sharesValue = sharesValueRaw !== null && !Number.isNaN(sharesValueRaw) ? sharesValueRaw : null;
      const pctOfInstitutionRaw =
        point.pctOfInstitution === null || point.pctOfInstitution === undefined
          ? null
          : Number(point.pctOfInstitution);
      const pctOfInstitution =
        pctOfInstitutionRaw !== null && !Number.isNaN(pctOfInstitutionRaw) ? pctOfInstitutionRaw : null;
      const { label, isFullName } = deriveLabel(point.name, point.symbol, labelMode);
      return {
        id: String(point.id),
        name: point.name,
        label,
        symbol: point.symbol ? String(point.symbol).toUpperCase() : null,
        is_full_name: isFullName,
        entry_order: index,
        sharesLabel: sharesValue === null ? "-" : fmtNumber(sharesValue),
        pctOfInstitutionLabel: pctOfInstitution === null ? "-" : fmtPct(pctOfInstitution),
        value: Number(point.size),
        color: tileFill(Number(point.size), deltaValue, maxSize, maxAbsDelta),
        valueLabel: formatByType(Number(point.size), valueFormat),
        deltaLabelValue: deltaText
      };
    });
  }, [data, deltaFormat, maxTiles, minRelativeSize, minTiles, signedDelta, valueFormat]);

  if (prepared.length === 0) {
    return <div className="empty-box">{emptyText}</div>;
  }

  const height = Math.max(300, Math.min(620, Math.round(Math.max(360, containerWidth) * 0.58)));
  const treeData = { name: "root", children: prepared };
  const rootClassName = containerClassName ? `chart-box ${containerClassName}` : "chart-box";

  const handleNodeHover = useCallback((event: React.MouseEvent<SVGRectElement>, node: any) => {
    setHover({
      name: String(node?.data?.name ?? ""),
      sharesLabel: String(node?.data?.sharesLabel ?? "-"),
      deltaLabelValue: String(node?.data?.deltaLabelValue ?? "-"),
      pctOfInstitutionLabel: String(node?.data?.pctOfInstitutionLabel ?? "-"),
      clientX: event.clientX,
      clientY: event.clientY,
    });
  }, []);

  const handleNodeHoverEnd = useCallback(() => {
    setHover(null);
  }, []);

  const nodeRenderer = useCallback(
    (nodeProps: any) => (
      <NivoNode node={nodeProps.node} onHover={handleNodeHover} onHoverEnd={handleNodeHoverEnd} />
    ),
    [handleNodeHover, handleNodeHoverEnd]
  );

  useLayoutEffect(() => {
    if (!hover) return;
    const tip = tooltipRef.current;
    if (!tip) return;
    const tipRect = tip.getBoundingClientRect();
    const gap = 12;
    const pad = 8;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    let leftClient = hover.clientX + gap;
    if (leftClient + tipRect.width > viewportWidth - pad) {
      leftClient = hover.clientX - tipRect.width - gap;
    }
    leftClient = Math.max(pad, Math.min(leftClient, viewportWidth - tipRect.width - pad));

    let topClient = hover.clientY + gap;
    if (topClient + tipRect.height > viewportHeight - pad) {
      topClient = hover.clientY - tipRect.height - gap;
    }
    topClient = Math.max(pad, Math.min(topClient, viewportHeight - tipRect.height - pad));
    const nextLeft = leftClient;
    const nextTop = topClient;
    setTooltipPos((prev) =>
      Math.abs(prev.left - nextLeft) < 0.5 && Math.abs(prev.top - nextTop) < 0.5
        ? prev
        : { left: nextLeft, top: nextTop }
    );
  }, [hover]);

  return (
    <div className={rootClassName}>
      <h3 className="text-lg font-semibold text-slate-100">{title}</h3>
      <div className="heatmap-legend">
        <span><em className="heatmap-swatch heatmap-swatch-pos" /> Increased</span>
        <span><em className="heatmap-swatch heatmap-swatch-neg" /> Decreased</span>
        <span><em className="heatmap-swatch heatmap-swatch-neutral" /> Unchanged / N/A</span>
      </div>
      <div className="treemap-wrap" ref={containerRef} style={{ height }}>
        <ResponsiveTreeMap
          data={treeData as any}
          identity="id"
          value="value"
          leavesOnly
          tile="squarify"
          innerPadding={1}
          outerPadding={0}
          enableParentLabel={false}
          enableLabel={false}
          colors={(node: any) => String(node.data?.color ?? "#0ea5e9")}
          colorBy="id"
          borderWidth={1}
          borderColor={{ from: "color", modifiers: [["darker", 0.55]] }}
          isInteractive
          animate
          motionConfig="gentle"
          nodeComponent={nodeRenderer}
          tooltip={() => null}
        />
        {hover ? (
          <div
            ref={tooltipRef}
            className="pointer-events-none fixed z-[80] heatmap-tooltip"
            style={{ left: `${tooltipPos.left}px`, top: `${tooltipPos.top}px` }}
          >
            <div className="heatmap-tooltip-title">{hover.name}</div>
            <div className="heatmap-tooltip-row">
              <span className="heatmap-tooltip-label">Shares</span>
              <span className="heatmap-tooltip-value">{hover.sharesLabel}</span>
            </div>
            <div className="heatmap-tooltip-row">
              <span className="heatmap-tooltip-label">{deltaLabel}</span>
              <span className="heatmap-tooltip-value">{hover.deltaLabelValue}</span>
            </div>
            <div className="heatmap-tooltip-row">
              <span className="heatmap-tooltip-label">% of Institution</span>
              <span className="heatmap-tooltip-value">{hover.pctOfInstitutionLabel}</span>
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
