"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis
} from "recharts";

type QuarterBarPoint = { report_date: string; net_change_shares: number };
type SparkPoint = { report_date: string; net_shares: number; net_holder_count: number };
type TreemapPoint = { name: string; size: number };

export function NetAccumulationBarChart({ data }: { data: QuarterBarPoint[] }) {
  return (
    <div className="chart-box">
      <h3>Net Accumulation By Quarter</h3>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="4 4" stroke="var(--grid)" />
          <XAxis dataKey="report_date" stroke="var(--muted)" />
          <YAxis stroke="var(--muted)" />
          <Tooltip />
          <Bar dataKey="net_change_shares">
            {data.map((row) => (
              <Cell key={row.report_date} fill={row.net_change_shares >= 0 ? "#22c55e" : "#ef4444"} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export function Sparkline({ data }: { data: SparkPoint[] }) {
  return (
    <ResponsiveContainer width="100%" height={44}>
      <LineChart data={data}>
        <Line type="monotone" dataKey="net_shares" stroke="#0ea5e9" dot={false} strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function PositionTreemap({ data }: { data: TreemapPoint[] }) {
  if (data.length === 0) {
    return <div className="empty-box">No mapped positions available.</div>;
  }

  return (
    <div className="chart-box">
      <h3>Current Position Treemap</h3>
      <ResponsiveContainer width="100%" height={340}>
        <Treemap
          data={data}
          dataKey="size"
          stroke="#0f172a"
          fill="#0891b2"
        />
      </ResponsiveContainer>
    </div>
  );
}
