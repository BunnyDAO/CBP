import { useState, useEffect, useRef } from "react";
import { api, type PipelineStatus } from "../lib/api";

export default function UpdateButton() {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [polling, setPolling] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const startPolling = () => {
    setPolling(true);
    intervalRef.current = setInterval(async () => {
      const s = await api.getUpdateStatus();
      setStatus(s);
      if (!s.running) {
        if (intervalRef.current) clearInterval(intervalRef.current);
        setPolling(false);
      }
    }, 1000);
  };

  useEffect(() => {
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, []);

  const trigger = async () => {
    await api.triggerUpdate();
    startPolling();
  };

  return (
    <div className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-sm font-medium text-gray-400">Data Pipeline</h3>
          <p className="text-xs text-gray-600 mt-1">
            Download latest data, find new instances, process outcomes
          </p>
        </div>
        <button
          onClick={trigger}
          disabled={polling}
          className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
        >
          {polling ? "Running..." : "Update Data"}
        </button>
      </div>

      {status && (status.running || status.log.length > 0) && (
        <div className="mt-4">
          {/* Progress bar */}
          <div className="flex items-center gap-3 mb-2">
            <div className="flex-1 h-2 bg-gray-800 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 transition-all duration-500 rounded-full"
                style={{ width: `${status.progress}%` }}
              />
            </div>
            <span className="text-xs text-gray-500 w-12 text-right">{status.progress}%</span>
          </div>

          {/* Current step */}
          {status.running && (
            <p className="text-xs text-blue-400 mb-2">
              <span className="inline-block animate-spin mr-1">&#8635;</span>
              {status.step}
            </p>
          )}

          {/* Log */}
          <div className="bg-gray-950 rounded-lg p-3 max-h-48 overflow-y-auto font-mono text-xs text-gray-500">
            {status.log.map((line, i) => (
              <div key={i}>{line}</div>
            ))}
          </div>

          {!status.running && status.finished_at && (
            <p className="text-xs text-green-400 mt-2">
              Completed at {new Date(status.finished_at).toLocaleTimeString()}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
