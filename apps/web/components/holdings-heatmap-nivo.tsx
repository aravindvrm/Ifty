"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ResponsiveTreeMap } from "@nivo/treemap";

import { fmtNumber, fmtUsdThousands } from "@/lib/format";
import { TickerIcon } from "@/components/ticker-icon";

import type { HoldingsHeatmapProps } from "./charts";

type NivoLeaf = {
  id: string;
  name: string;
  label: string;
  symbol: string | null;
  is_full_name: boolean;
  value: number;
  color: string;
  valueLabel: string;
  deltaLabelValue: string;
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

function NivoNode({ node }: any) {
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

  return (
    <g transform={`translate(${node.x},${node.y})`}>
      <clipPath id={clipId}>
        <rect x={1} y={1} width={Math.max(0, width - 2)} height={Math.max(0, height - 2)} rx={5} ry={5} />
      </clipPath>
      <rect
        width={width}
        height={height}
        rx={5}
        ry={5}
        fill={String(node.color)}
        stroke="rgba(226, 232, 240, 0.24)"
        strokeWidth={1}
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
  );
}

export function HoldingsHeatmapNivo({
  title,
  data,
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
  const [containerWidth, setContainerWidth] = useState(920);

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

    return ranked.map((point) => {
      const deltaValueRaw = point.delta === null || point.delta === undefined ? null : Number(point.delta);
      const deltaValue = deltaValueRaw !== null && !Number.isNaN(deltaValueRaw) ? deltaValueRaw : null;
      const deltaTextRaw = deltaValue === null ? "-" : formatByType(deltaValue, deltaFormat);
      const deltaText = signedDelta && deltaValue !== null && deltaValue > 0 ? `+${deltaTextRaw}` : deltaTextRaw;
      const { label, isFullName } = deriveLabel(point.name, point.symbol, labelMode);
      return {
        id: String(point.id),
        name: point.name,
        label,
        symbol: point.symbol ? String(point.symbol).toUpperCase() : null,
        is_full_name: isFullName,
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

  return (
    <div className="chart-box">
      <h3>{title}</h3>
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
          nodeComponent={NivoNode}
          tooltip={({ node }: any) => (
            <div className="heatmap-tooltip">
              <div className="heatmap-tooltip-title">{String(node?.data?.name ?? "")}</div>
              <div>{valueLabel}: {String(node?.data?.valueLabel ?? "-")}</div>
              <div>{deltaLabel}: {String(node?.data?.deltaLabelValue ?? "-")}</div>
            </div>
          )}
        />
      </div>
    </div>
  );
}
