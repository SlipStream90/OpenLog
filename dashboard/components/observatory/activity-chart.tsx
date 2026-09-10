"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { ChartPoint } from "@/lib/api";

/**
 * Sessions-per-day bar chart (PRD section 14). Pure presentational client
 * component: data is fetched server-side and passed in as props.
 */
export function ActivityChart({ points }: { points: ChartPoint[] }) {
  if (points.every((p) => p.sessions === 0)) return null;
  const data = points.map((p) => ({
    ...p,
    day: p.date.slice(5),
    hours: Math.round((p.seconds / 3600) * 10) / 10,
  }));
  return (
    <div className="h-56 w-full" role="img" aria-label="Sessions per day chart">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid strokeDasharray="3 3" className="stroke-border" vertical={false} />
          <XAxis dataKey="day" tickLine={false} axisLine={false} className="font-mono text-[10px]" />
          <YAxis
            allowDecimals={false}
            tickLine={false}
            axisLine={false}
            className="font-mono text-[10px]"
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "var(--card)",
              border: "1px solid var(--border)",
              borderRadius: 8,
              fontSize: 12,
              fontFamily: "monospace",
            }}
            formatter={(value, name) => [value, name === "sessions" ? "sessions" : String(name)]}
            labelFormatter={(label, payload) => payload?.[0]?.payload?.date ?? label}
          />
          <Bar dataKey="sessions" fill="var(--primary)" radius={[4, 4, 0, 0]} maxBarSize={28} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
