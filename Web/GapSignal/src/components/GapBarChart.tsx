import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Cell,
} from "recharts";
import { type GapZone } from "../lib/api";

interface Props {
  distribution: GapZone[];
  currentPrice: number;
}

export default function GapBarChart({ distribution, currentPrice }: Props) {
  // Transform: shorts as negative, longs as positive
  const chartData = distribution.map((z) => ({
    zone: z.zone,
    longs: z.longs,
    shorts: -z.shorts,
    zoneStart: z.zone_start,
    zoneEnd: z.zone_end,
  }));

  // Find the zone containing current price
  const currentZone = distribution.find(
    (z) => currentPrice >= z.zone_start && currentPrice < z.zone_end
  )?.zone;

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
      <h3 className="text-sm font-medium text-gray-400 mb-4">
        Gap Distribution by Price Zone
      </h3>
      <ResponsiveContainer width="100%" height={Math.max(300, chartData.length * 24)}>
        <BarChart data={chartData} layout="vertical" margin={{ left: 60, right: 20, top: 5, bottom: 5 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" horizontal={false} />
          <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 11 }} />
          <YAxis
            dataKey="zone"
            type="category"
            tick={{ fill: "#6b7280", fontSize: 11 }}
            width={70}
          />
          <Tooltip
            contentStyle={{
              backgroundColor: "#1f2937",
              border: "1px solid #374151",
              borderRadius: "8px",
              fontSize: "12px",
            }}
            formatter={(value: number, name: string) => [
              Math.abs(value),
              name === "shorts" ? "Short Targets" : "Long Targets",
            ]}
          />
          <ReferenceLine x={0} stroke="#4b5563" />
          <Bar dataKey="shorts" fill="#ef4444" radius={[4, 0, 0, 4]}>
            {chartData.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.zone === currentZone ? "#f87171" : "#ef4444"}
                opacity={entry.zone === currentZone ? 1 : 0.7}
              />
            ))}
          </Bar>
          <Bar dataKey="longs" fill="#22c55e" radius={[0, 4, 4, 0]}>
            {chartData.map((entry, i) => (
              <Cell
                key={i}
                fill={entry.zone === currentZone ? "#4ade80" : "#22c55e"}
                opacity={entry.zone === currentZone ? 1 : 0.7}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      <p className="text-xs text-gray-600 mt-2 text-center">
        Current price: ${currentPrice.toFixed(2)} — Shorts (left) | Longs (right)
      </p>
    </div>
  );
}
