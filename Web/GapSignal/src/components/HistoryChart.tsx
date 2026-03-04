import { useState, useEffect } from "react";
import {
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { api, type HistoryPoint } from "../lib/api";

export default function HistoryChart() {
  const [history, setHistory] = useState<HistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(365);

  useEffect(() => {
    setLoading(true);
    api.getHistory(days).then((res) => {
      setHistory(res.history);
      setLoading(false);
    });
  }, [days]);

  if (loading) {
    return <div className="text-center py-12 text-gray-500">Loading history...</div>;
  }

  return (
    <div>
      <div className="flex gap-2 mb-4">
        {[90, 180, 365, 730, 1500].map((d) => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={`px-3 py-1 rounded text-xs ${
              days === d
                ? "bg-blue-600 text-white"
                : "bg-gray-800 text-gray-400 hover:text-white"
            }`}
          >
            {d < 365 ? `${d}d` : `${(d / 365).toFixed(d % 365 === 0 ? 0 : 1)}y`}
          </button>
        ))}
      </div>

      <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">
          Long Ratio & Price History ({history.length} days)
        </h3>
        <ResponsiveContainer width="100%" height={400}>
          <ComposedChart data={history} margin={{ left: 0, right: 40, top: 5, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis
              dataKey="date"
              tick={{ fill: "#6b7280", fontSize: 10 }}
              tickFormatter={(d: string) => d.slice(2, 7)}
              interval={Math.floor(history.length / 10)}
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
              formatter={(value: number, name: string) => {
                if (name === "long_ratio") return [`${(value * 100).toFixed(1)}%`, "Long Ratio"];
                if (name === "price") return [`$${value.toFixed(2)}`, "Price"];
                return [value, name];
              }}
            />

            {/* Signal zone shading thresholds */}
            <ReferenceLine yAxisId="ratio" y={0.8} stroke="#22c55e" strokeDasharray="5 5" />
            <ReferenceLine yAxisId="ratio" y={0.6} stroke="#86efac" strokeDasharray="3 3" />
            <ReferenceLine yAxisId="ratio" y={0.4} stroke="#fca5a5" strokeDasharray="3 3" />
            <ReferenceLine yAxisId="ratio" y={0.2} stroke="#ef4444" strokeDasharray="5 5" />
            <ReferenceLine yAxisId="ratio" y={0.5} stroke="#4b5563" strokeDasharray="2 2" />

            <Line
              yAxisId="ratio"
              type="monotone"
              dataKey="long_ratio"
              stroke="#3b82f6"
              strokeWidth={1.5}
              dot={false}
            />
            <Line
              yAxisId="price"
              type="monotone"
              dataKey="price"
              stroke="#9ca3af"
              strokeWidth={1}
              strokeDasharray="4 4"
              dot={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* History table */}
      <div className="mt-6 overflow-x-auto rounded-xl border border-gray-800">
        <table className="w-full text-sm">
          <thead className="bg-gray-900">
            <tr>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Date</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Price</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Long Above</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Short Below</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Total</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Long Ratio</th>
              <th className="px-3 py-2 text-left text-xs font-medium text-gray-500">Signal</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800/50">
            {[...history].reverse().slice(0, 30).map((h, i) => {
              const ratio = h.long_ratio;
              let signalLabel = "NEUTRAL";
              let signalColor = "text-gray-400";
              if (ratio >= 0.8) { signalLabel = "STRONG LONG"; signalColor = "text-green-400"; }
              else if (ratio >= 0.6) { signalLabel = "LEAN LONG"; signalColor = "text-green-300"; }
              else if (ratio <= 0.2) { signalLabel = "STRONG SHORT"; signalColor = "text-red-400"; }
              else if (ratio <= 0.4) { signalLabel = "LEAN SHORT"; signalColor = "text-red-300"; }
              return (
                <tr key={i} className="hover:bg-gray-800/30">
                  <td className="px-3 py-2 text-gray-400">{h.date}</td>
                  <td className="px-3 py-2 font-mono text-white">${h.price.toFixed(2)}</td>
                  <td className="px-3 py-2 font-mono text-green-400">{h.long_above}</td>
                  <td className="px-3 py-2 font-mono text-red-400">{h.short_below}</td>
                  <td className="px-3 py-2 font-mono text-gray-400">{h.total_gaps}</td>
                  <td className="px-3 py-2 font-mono text-white">{(ratio * 100).toFixed(1)}%</td>
                  <td className={`px-3 py-2 text-xs font-medium ${signalColor}`}>{signalLabel}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
