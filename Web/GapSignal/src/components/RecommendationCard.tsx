import { type Recommendation } from "../lib/api";

export default function RecommendationCard({ rec }: { rec: Recommendation }) {
  const isNeutral = rec.direction === "NEUTRAL";
  const isLong = rec.direction === "LONG";

  const bg = isNeutral
    ? "bg-gray-800/50 border-gray-700"
    : isLong
      ? "bg-green-500/10 border-green-500/30"
      : "bg-red-500/10 border-red-500/30";

  return (
    <div className={`rounded-xl border p-5 ${bg}`}>
      <p className="text-sm text-gray-500 uppercase tracking-wider mb-2">Recommendation</p>
      <p className="text-lg font-semibold text-white">{rec.action}</p>
      {!isNeutral && (
        <div className="grid grid-cols-3 gap-3 mt-4 pt-3 border-t border-gray-700/50">
          <div>
            <p className="text-xs text-gray-500">Position %</p>
            <p className="text-sm font-mono text-white">{rec.position_pct}%</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">USD</p>
            <p className="text-sm font-mono text-white">${rec.position_usd.toLocaleString()}</p>
          </div>
          <div>
            <p className="text-xs text-gray-500">SOL</p>
            <p className="text-sm font-mono text-white">{rec.position_sol}</p>
          </div>
        </div>
      )}
    </div>
  );
}
