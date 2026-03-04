import { useState, useEffect } from "react";
import { api, type SignalChange } from "../lib/api";

const strengthLabel: Record<number, string> = {
  "-2": "STRONG SHORT",
  "-1": "LEAN SHORT",
  "0": "NEUTRAL",
  "1": "LEAN LONG",
  "2": "STRONG LONG",
};

const strengthColor: Record<number, string> = {
  "-2": "text-red-400",
  "-1": "text-red-300",
  "0": "text-gray-400",
  "1": "text-green-300",
  "2": "text-green-400",
};

export default function SignalChangeLog() {
  const [changes, setChanges] = useState<SignalChange[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getSignalChanges(20)
      .then((res) => {
        setChanges(res.changes.reverse());
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Signal Changes</h3>
        <p className="text-xs text-gray-500">Loading...</p>
      </div>
    );
  }

  if (changes.length === 0) {
    return (
      <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-3">Signal Changes</h3>
        <p className="text-xs text-gray-500">No signal transitions recorded yet.</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
      <h3 className="text-sm font-medium text-gray-400 mb-3">Signal Changes</h3>
      <div className="space-y-2 max-h-64 overflow-y-auto">
        {changes.map((c, i) => {
          const date = new Date(c.timestamp);
          const timeStr = date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            hour: "2-digit",
            minute: "2-digit",
          });
          return (
            <div
              key={i}
              className="flex items-center gap-3 text-xs py-1.5 border-b border-gray-800 last:border-0"
            >
              <span className="text-gray-500 w-28 shrink-0">{timeStr}</span>
              <span className={strengthColor[c.previous_strength] ?? "text-gray-400"}>
                {c.previous_signal}
              </span>
              <span className="text-gray-600">&rarr;</span>
              <span className={strengthColor[c.signal_strength] ?? "text-gray-400"}>
                {c.signal}
              </span>
              <span className="ml-auto text-gray-500 font-mono">${c.price.toLocaleString()}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
