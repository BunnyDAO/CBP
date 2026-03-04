import { type SignalData, type PriceData } from "../lib/api";

const signalColors: Record<string, { bg: string; text: string; border: string }> = {
  "STRONG LONG": { bg: "bg-green-500/20", text: "text-green-400", border: "border-green-500/40" },
  "LEAN LONG": { bg: "bg-green-500/10", text: "text-green-300", border: "border-green-500/20" },
  NEUTRAL: { bg: "bg-gray-500/10", text: "text-gray-400", border: "border-gray-500/20" },
  "LEAN SHORT": { bg: "bg-red-500/10", text: "text-red-300", border: "border-red-500/20" },
  "STRONG SHORT": { bg: "bg-red-500/20", text: "text-red-400", border: "border-red-500/40" },
};

interface Props {
  data: SignalData;
  livePrice?: PriceData | null;
}

export default function SignalBadge({ data, livePrice }: Props) {
  const colors = signalColors[data.signal] ?? signalColors.NEUTRAL;

  const displayPrice = livePrice?.price ?? data.price;
  const isLive = livePrice?.source === "websocket";

  return (
    <div className={`rounded-xl border ${colors.border} ${colors.bg} p-6`}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm text-gray-500 uppercase tracking-wider">Current Signal</p>
          <p className={`text-4xl font-bold mt-1 ${colors.text}`}>{data.signal}</p>
        </div>
        <div className="text-right">
          <div className="flex items-center justify-end gap-2">
            <p className="text-2xl font-mono text-white">${displayPrice.toLocaleString()}</p>
            <span
              className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${
                isLive
                  ? "bg-green-500/20 text-green-400 animate-pulse"
                  : "bg-yellow-500/20 text-yellow-400"
              }`}
            >
              {isLive ? "LIVE" : "DELAYED"}
            </span>
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {isLive ? `WS ${new Date(livePrice!.timestamp).toLocaleTimeString()}` : `as of ${data.price_date}`}
          </p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-4 mt-4 pt-4 border-t border-gray-800">
        <div>
          <p className="text-xs text-gray-500">Long Targets Above</p>
          <p className="text-xl font-semibold text-green-400">{data.long_above}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Short Targets Below</p>
          <p className="text-xl font-semibold text-red-400">{data.short_below}</p>
        </div>
        <div>
          <p className="text-xs text-gray-500">Long Ratio</p>
          <p className="text-xl font-semibold text-white">
            {(data.long_ratio * 100).toFixed(1)}%
          </p>
        </div>
      </div>
    </div>
  );
}
