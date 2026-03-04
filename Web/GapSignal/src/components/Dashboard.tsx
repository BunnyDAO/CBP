import { useState, useEffect } from "react";
import { api, type SignalData } from "../lib/api";
import SignalBadge from "./SignalBadge";
import RecommendationCard from "./RecommendationCard";
import RatioTrendChart from "./RatioTrendChart";
import GapBarChart from "./GapBarChart";

const DEFAULT_THRESHOLDS = {
  strong_long: 0.8,
  lean_long: 0.6,
  lean_short: 0.4,
  strong_short: 0.2,
};

export default function Dashboard() {
  const [data, setData] = useState<SignalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [thresholds, setThresholds] = useState(DEFAULT_THRESHOLDS);

  useEffect(() => {
    Promise.all([api.getSignal(), api.getConfig()])
      .then(([signal, config]) => {
        setData(signal);
        setThresholds(config.thresholds);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24">
        <div className="text-gray-500">Loading signal data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-6 text-center">
        <p className="text-red-400 font-medium">Failed to load signal</p>
        <p className="text-sm text-red-400/70 mt-1">{error}</p>
        <p className="text-xs text-gray-500 mt-3">
          Make sure the API is running: <code className="text-gray-400">python api.py</code> in{" "}
          <code className="text-gray-400">CBP/Python/GapSignal/</code>
        </p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-white">Dashboard</h2>
        <p className="text-xs text-gray-500">Updated {data.date}</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <SignalBadge data={data} />
        <RecommendationCard rec={data.recommendation} />
      </div>

      <RatioTrendChart trend={data.trend} thresholds={thresholds} />

      <GapBarChart distribution={data.gap_distribution} currentPrice={data.price} />
    </div>
  );
}
