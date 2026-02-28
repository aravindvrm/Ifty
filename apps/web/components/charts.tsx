"use client";

import dynamic from "next/dynamic";

type QuarterBarPoint = { report_date: string; net_change_shares: number };
type SparkPoint = { report_date: string; net_shares: number; net_holder_count: number };
type HeatmapPoint = {
  id: number | string;
  name: string;
  symbol?: string | null;
  size: number;
  delta?: number | null;
};

export type HoldingsHeatmapProps = {
  title: string;
  data: HeatmapPoint[];
  emptyText?: string;
  valueLabel?: string;
  deltaLabel?: string;
  labelMode?: "auto" | "name";
  maxTiles?: number;
  valueFormat?: "usd_thousands" | "number";
  deltaFormat?: "usd_thousands" | "number";
  signedDelta?: boolean;
  minRelativeSize?: number;
  minTiles?: number;
};

const HoldingsHeatmapRenderer = dynamic<HoldingsHeatmapProps>(
  () => import("./holdings-heatmap-nivo").then((m) => m.HoldingsHeatmapNivo),
  {
    ssr: false,
    loading: () => (
      <div className="chart-box">
        <h3>Loading heatmap...</h3>
      </div>
    )
  }
);

export function NetAccumulationBarChart({ data }: { data: QuarterBarPoint[] }) {
  const maxAbs = Math.max(1, ...data.map((x) => Math.abs(x.net_change_shares || 0)));

  return (
    <div className="chart-box">
      <h3>Holding Activity (Net Accumulation by Quarter)</h3>
      <div style={{ minHeight: 280, display: "flex", alignItems: "flex-end", gap: 8, overflowX: "auto", paddingTop: 16 }}>
        {data.map((row) => {
          const h = Math.max(4, Math.round((Math.abs(row.net_change_shares || 0) / maxAbs) * 180));
          const isPos = (row.net_change_shares || 0) >= 0;
          return (
            <div key={row.report_date} style={{ minWidth: 72, textAlign: "center" }}>
              <div
                title={`${row.report_date}: ${row.net_change_shares.toLocaleString()}`}
                style={{
                  margin: "0 auto",
                  width: 30,
                  height: h,
                  borderRadius: 6,
                  background: isPos ? "#22c55e" : "#ef4444"
                }}
              />
              <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>{row.report_date}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function Sparkline({ data }: { data: SparkPoint[] }) {
  if (!data.length) {
    return <div style={{ height: 44 }} />;
  }

  const width = 180;
  const height = 44;
  const values = data.map((d) => d.net_shares || 0);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Math.max(1, max - min);
  const points = values
    .map((v, i) => {
      const x = (i / Math.max(1, values.length - 1)) * width;
      const y = height - ((v - min) / range) * (height - 4) - 2;
      return `${x},${y}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={44} preserveAspectRatio="none">
      <polyline fill="none" stroke="#0ea5e9" strokeWidth="2" points={points} />
    </svg>
  );
}

export function HoldingsHeatmap(props: HoldingsHeatmapProps) {
  return <HoldingsHeatmapRenderer {...props} />;
}

export function PositionTreemap({ data }: { data: Array<{ name: string; size: number }> }) {
  return (
    <HoldingsHeatmap
      title="Current Position Heatmap"
      data={data.map((row, idx) => ({ id: `${row.name}-${idx}`, name: row.name, size: row.size, symbol: null }))}
      valueLabel="Value"
      deltaLabel="QoQ"
      valueFormat="usd_thousands"
      deltaFormat="number"
    />
  );
}
