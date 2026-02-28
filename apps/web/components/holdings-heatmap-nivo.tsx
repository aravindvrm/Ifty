"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ResponsiveTreeMap } from "@nivo/treemap";

import { fmtNumber, fmtUsdThousands } from "@/lib/format";

import type { HoldingsHeatmapProps } from "./charts";

type NivoLeaf = {
  id: string;
  name: string;
  label: string;
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
  const isFullName = Boolean(node.data?.is_full_name);
  const valueLabel = String(node.data?.valueLabel ?? "");
  const showSymbol = width >= 34 && height >= 24;
  const showValue = width >= 70 && height >= 42;
  const fontSizeSymbol = isFullName
    ? Math.max(7, Math.min(11, Math.round(Math.min(width, height) * 0.12)))
    : Math.max(8, Math.min(18, Math.round(Math.min(width, height) * 0.18)));
  const fontSizeValue = Math.max(7, Math.min(12, Math.round(fontSizeSymbol * 0.68)));
  const canWrapName = isFullName && width >= 96 && height >= 46 && label.includes(" ");
  const words = label.split(/\s+/).filter(Boolean);
  let line1 = label;
  let line2 = "";
  if (canWrapName && words.length > 1) {
    const splitAt = Math.ceil(words.length / 2);
    line1 = words.slice(0, splitAt).join(" ");
    line2 = words.slice(splitAt).join(" ");
  }

  return (
    <g transform={`translate(${node.x},${node.y})`}>
      <rect
        width={width}
        height={height}
        rx={5}
        ry={5}
        fill={String(node.color)}
        stroke="rgba(226, 232, 240, 0.24)"
        strokeWidth={1}
      />
      {showSymbol ? (
        <text
          x={width / 2}
          y={showValue ? height * 0.43 : height * 0.52}
          textAnchor="middle"
          dominantBaseline="middle"
          fill="#e2e8f0"
          fontSize={fontSizeSymbol}
          fontWeight={700}
          style={{ pointerEvents: "none" }}
        >
          {canWrapName ? (
            <>
              <tspan x={width / 2} dy={line2 ? `-${Math.round(fontSizeSymbol * 0.5)}` : "0"}>
                {line1}
              </tspan>
              {line2 ? <tspan x={width / 2} dy={Math.round(fontSizeSymbol * 1.05)}>{line2}</tspan> : null}
            </>
          ) : (
            label
          )}
        </text>
      ) : null}
      {showValue ? (
        <text
          x={width / 2}
          y={height * 0.69}
          textAnchor="middle"
          dominantBaseline="middle"
          fill="rgba(226, 232, 240, 0.96)"
          fontSize={fontSizeValue}
          fontWeight={500}
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
