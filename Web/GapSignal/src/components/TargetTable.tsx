import { useState, useEffect } from "react";
import { api, type Target, type TargetsResponse } from "../lib/api";

const TIMEFRAMES = ["all", "1h", "2h", "4h", "6h", "8h", "12h", "1D", "2D", "3D", "1W", "2W", "1mo"];

export default function TargetTable() {
  const [data, setData] = useState<TargetsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [tfFilter, setTfFilter] = useState("all");
  const [dirFilter, setDirFilter] = useState<string>("");
  const [sortKey, setSortKey] = useState<keyof Target>("distance_pct");
  const [sortAsc, setSortAsc] = useState(true);

  useEffect(() => {
    setLoading(true);
    const params: { timeframe?: string; direction?: string } = {};
    if (tfFilter !== "all") params.timeframe = tfFilter;
    if (dirFilter) params.direction = dirFilter;
    api.getTargets(params).then(setData).finally(() => setLoading(false));
  }, [tfFilter, dirFilter]);

  const handleSort = (key: keyof Target) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
  };

  const sorted = data?.targets
    ? [...data.targets].sort((a, b) => {
        const va = a[sortKey];
        const vb = b[sortKey];
        const cmp = typeof va === "number" ? (va as number) - (vb as number) : String(va).localeCompare(String(vb));
        return sortAsc ? cmp : -cmp;
      })
    : [];

  const SortHeader = ({ label, field }: { label: string; field: keyof Target }) => (
    <th
      className="px-3 py-2 text-left text-xs font-medium text-gray-500 uppercase cursor-pointer hover:text-gray-300"
      onClick={() => handleSort(field)}
    >
      {label} {sortKey === field ? (sortAsc ? "\u2191" : "\u2193") : ""}
    </th>
  );

  return (
    <div>
      {/* Filters */}
      <div className="flex gap-3 mb-4 flex-wrap">
        <select
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300"
          value={tfFilter}
          onChange={(e) => setTfFilter(e.target.value)}
        >
          {TIMEFRAMES.map((tf) => (
            <option key={tf} value={tf}>{tf === "all" ? "All Timeframes" : tf}</option>
          ))}
        </select>
        <select
          className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-sm text-gray-300"
          value={dirFilter}
          onChange={(e) => setDirFilter(e.target.value)}
        >
          <option value="">Both Directions</option>
          <option value="long">Long Only</option>
          <option value="short">Short Only</option>
        </select>
        {data && (
          <span className="text-sm text-gray-500 self-center ml-auto">
            {sorted.length} targets | Price: ${data.price.toFixed(2)}
          </span>
        )}
      </div>

      {/* Table */}
      {loading ? (
        <div className="text-center py-12 text-gray-500">Loading targets...</div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-gray-800">
          <table className="w-full text-sm">
            <thead className="bg-gray-900">
              <tr>
                <SortHeader label="Direction" field="direction" />
                <SortHeader label="Target" field="target" />
                <SortHeader label="Distance" field="distance_pct" />
                <SortHeader label="Timeframe" field="timeframe" />
                <SortHeader label="Type" field="situation" />
                <SortHeader label="Confirmed" field="confirm_date" />
                <SortHeader label="Entry" field="entry" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {sorted.map((t, i) => (
                <tr key={i} className="hover:bg-gray-800/30">
                  <td className="px-3 py-2">
                    <span
                      className={`inline-block px-2 py-0.5 rounded text-xs font-medium ${
                        t.direction === "long"
                          ? "bg-green-500/20 text-green-400"
                          : "bg-red-500/20 text-red-400"
                      }`}
                    >
                      {t.direction.toUpperCase()}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-white">${t.target.toFixed(2)}</td>
                  <td className="px-3 py-2 font-mono">
                    <span className={t.distance_pct > 0 ? "text-green-400" : "text-red-400"}>
                      {t.distance_pct > 0 ? "+" : ""}{t.distance_pct.toFixed(1)}%
                    </span>
                    <span className="text-gray-600 ml-1">(${Math.abs(t.distance_usd).toFixed(2)})</span>
                  </td>
                  <td className="px-3 py-2 text-gray-400">{t.timeframe}</td>
                  <td className="px-3 py-2 text-gray-400">{t.situation}</td>
                  <td className="px-3 py-2 text-gray-500">{t.confirm_date}</td>
                  <td className="px-3 py-2 font-mono text-gray-500">${t.entry.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {sorted.length === 0 && (
            <div className="text-center py-8 text-gray-500">No targets found</div>
          )}
        </div>
      )}
    </div>
  );
}
