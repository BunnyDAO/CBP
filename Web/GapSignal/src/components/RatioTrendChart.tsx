import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Area,
  ComposedChart,
} from "recharts";
import { type TrendPoint } from "../lib/api";

interface Props {
  trend: TrendPoint[];
  thresholds: {
    strong_long: number;
    lean_long: number;
    lean_short: number;
    strong_short: number;
  };
}

export default function RatioTrendChart({ trend, thresholds }: Props) {
  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
      <h3 className="text-sm font-medium text-gray-400 mb-4">
        Long Ratio — Last {trend.length} Days
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <ComposedChart data={trend} margin={{ left: 0, right: 40, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
          <XAxis
            dataKey="date"
            tick={{ fill: "#6b7280", fontSize: 10 }}
            tickFormatter={(d: string) => d.slice(5)}
            interval={Math.floor(trend.length / 8)}
          />
          <YAxis
            yAxisId="ratio"
            domain={[0, 1]}
            tick={{ fill: "#6b7280", fontSize: 11 }}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
          />
          <YAxis
            yAxisId="price"
            orientation="right"
            tick={{ fill: "#6b7280", fontSize: 11 }}
            tickFormatter={(v: number) => `$${v}`}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #374151",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            formatter={(value: number, name: string) =>
              name === "long_ratio"
                ? [`${(value * 100).toFixed(1)}%`, "Long Ratio"]
                : [`$${value.toFixed(2)}`, "Price"]
            }
          />
          {/* Threshold lines */}
          <ReferenceLine
            yAxisId="ratio"
            y={thresholds.strong_long}
            stroke="#22c55e"
            strokeDasharray="5 5"
            label={{ value: "Strong Long", fill: "#22c55e", fontSize: 10, position: "left" }}
          />
          <ReferenceLine
            yAxisId="ratio"
            y={thresholds.lean_long}
            stroke="#86efac"
            strokeDasharray="3 3"
          />
          <ReferenceLine
            yAxisId="ratio"
            y={thresholds.lean_short}
            stroke="#fca5a5"
            strokeDasharray="3 3"
          />
          <ReferenceLine
            yAxisId="ratio"
            y={thresholds.strong_short}
            stroke="#ef4444"
            strokeDasharray="5 5"
            label={{ value: "Strong Short", fill: "#ef4444", fontSize: 10, position: "left" }}
          />
          <ReferenceLine yAxisId="ratio" y={0.5} stroke="#4b5563" strokeDasharray="2 2" />

          <Line
            yAxisId="ratio"
            type="monotone"
            dataKey="long_ratio"
            stroke="#3b82f6"
            strokeWidth={2}
            dot={false}
          />
          <Line
            yAxisId="price"
            type="monotone"
            dataKey="price"
            stroke="#6b7280"
            strokeWidth={1}
            strokeDasharray="4 4"
            dot={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
