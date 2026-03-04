import { useState, useEffect } from "react";
import { api, type Config, type SchedulerStatus } from "../lib/api";

export default function ConfigForm() {
  const [config, setConfig] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [webhookTesting, setWebhookTesting] = useState(false);
  const [webhookResult, setWebhookResult] = useState<string | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerStatus | null>(null);

  useEffect(() => {
    Promise.all([api.getConfig(), api.getScheduler()])
      .then(([c, s]) => {
        setConfig(c);
        setScheduler(s);
        setLoading(false);
      })
      .catch(() => {
        api.getConfig().then((c) => {
          setConfig(c);
          setLoading(false);
        });
      });
  }, []);

  const save = async () => {
    if (!config) return;
    setSaving(true);
    setSaved(false);
    await api.saveConfig(config);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  if (loading || !config) {
    return <div className="text-center py-12 text-gray-500">Loading config...</div>;
  }

  const updateThreshold = (key: string, value: number) => {
    setConfig({ ...config, thresholds: { ...config.thresholds, [key]: value } });
  };

  const updateSizing = (key: string, value: number) => {
    setConfig({ ...config, position_sizing: { ...config.position_sizing, [key]: value } });
  };

  const allTimeframes = ["15m", "30m", "1h", "2h", "4h", "6h", "8h", "12h", "1D", "2D", "3D", "1W", "2W", "1mo"];

  const toggleTf = (tf: string) => {
    const current = config.timeframe_filter;
    if (current.includes(tf)) {
      setConfig({ ...config, timeframe_filter: current.filter((t) => t !== tf) });
    } else {
      setConfig({ ...config, timeframe_filter: [...current, tf] });
    }
  };

  return (
    <div className="space-y-8">
      {/* Portfolio Size */}
      <section className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Portfolio</h3>
        <label className="block">
          <span className="text-xs text-gray-500">Portfolio Size (USD)</span>
          <input
            type="number"
            className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white"
            value={config.portfolio_size}
            onChange={(e) => setConfig({ ...config, portfolio_size: Number(e.target.value) })}
          />
        </label>
      </section>

      {/* Signal Thresholds */}
      <section className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Signal Thresholds</h3>
        <div className="grid grid-cols-2 gap-4">
          {[
            { key: "strong_long", label: "Strong Long", color: "text-green-400" },
            { key: "lean_long", label: "Lean Long", color: "text-green-300" },
            { key: "lean_short", label: "Lean Short", color: "text-red-300" },
            { key: "strong_short", label: "Strong Short", color: "text-red-400" },
          ].map(({ key, label, color }) => (
            <div key={key}>
              <div className="flex justify-between">
                <span className={`text-xs ${color}`}>{label}</span>
                <span className="text-xs text-gray-400 font-mono">
                  {((config.thresholds as Record<string, number>)[key] * 100).toFixed(0)}%
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                className="w-full mt-1"
                value={(config.thresholds as Record<string, number>)[key] * 100}
                onChange={(e) => updateThreshold(key, Number(e.target.value) / 100)}
              />
            </div>
          ))}
        </div>
      </section>

      {/* Position Sizing */}
      <section className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Position Sizing</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="flex justify-between">
              <span className="text-xs text-gray-400">Strong Signal %</span>
              <span className="text-xs text-gray-400 font-mono">{config.position_sizing.strong_pct}%</span>
            </div>
            <input
              type="range"
              min="1"
              max="50"
              className="w-full mt-1"
              value={config.position_sizing.strong_pct}
              onChange={(e) => updateSizing("strong_pct", Number(e.target.value))}
            />
          </div>
          <div>
            <div className="flex justify-between">
              <span className="text-xs text-gray-400">Lean Signal %</span>
              <span className="text-xs text-gray-400 font-mono">{config.position_sizing.lean_pct}%</span>
            </div>
            <input
              type="range"
              min="1"
              max="50"
              className="w-full mt-1"
              value={config.position_sizing.lean_pct}
              onChange={(e) => updateSizing("lean_pct", Number(e.target.value))}
            />
          </div>
        </div>
      </section>

      {/* Timeframe Filter */}
      <section className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Timeframe Filter</h3>
        <div className="flex flex-wrap gap-2">
          {allTimeframes.map((tf) => (
            <button
              key={tf}
              onClick={() => toggleTf(tf)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                config.timeframe_filter.includes(tf)
                  ? "bg-blue-600 text-white"
                  : "bg-gray-800 text-gray-500 hover:text-gray-300"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </section>

      {/* Data Paths */}
      <section className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Data Paths</h3>
        <div className="space-y-3">
          <label className="block">
            <span className="text-xs text-gray-500">Candles Path</span>
            <input
              type="text"
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono"
              value={config.candles_path}
              onChange={(e) => setConfig({ ...config, candles_path: e.target.value })}
            />
          </label>
          <label className="block">
            <span className="text-xs text-gray-500">Data Root</span>
            <input
              type="text"
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono"
              value={config.data_root}
              onChange={(e) => setConfig({ ...config, data_root: e.target.value })}
            />
          </label>
          {config.instance_folders.map((folder, i) => (
            <label key={i} className="block">
              <span className="text-xs text-gray-500">Instance Folder {i + 1}</span>
              <input
                type="text"
                className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono"
                value={folder}
                onChange={(e) => {
                  const folders = [...config.instance_folders];
                  folders[i] = e.target.value;
                  setConfig({ ...config, instance_folders: folders });
                }}
              />
            </label>
          ))}
        </div>
      </section>

      {/* Webhook */}
      <section className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Webhook Notifications</h3>
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.webhook_enabled}
                onChange={(e) => setConfig({ ...config, webhook_enabled: e.target.checked })}
                className="w-4 h-4 rounded border-gray-600 bg-gray-800"
              />
              <span className="text-xs text-gray-400">Enable webhook</span>
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-gray-500">Webhook URL</span>
            <input
              type="url"
              placeholder="https://example.com/webhook"
              className="mt-1 block w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm font-mono"
              value={config.webhook_url}
              onChange={(e) => setConfig({ ...config, webhook_url: e.target.value })}
            />
          </label>
          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                setWebhookTesting(true);
                setWebhookResult(null);
                try {
                  const res = await api.testWebhook();
                  setWebhookResult(`Sent (HTTP ${res.http_status})`);
                } catch (e: unknown) {
                  setWebhookResult(`Failed: ${e instanceof Error ? e.message : "unknown error"}`);
                }
                setWebhookTesting(false);
              }}
              disabled={webhookTesting || !config.webhook_url}
              className="px-4 py-1.5 bg-gray-700 hover:bg-gray-600 text-white rounded-lg text-xs font-medium disabled:opacity-50 transition-colors"
            >
              {webhookTesting ? "Sending..." : "Test Webhook"}
            </button>
            {webhookResult && (
              <span className={`text-xs ${webhookResult.startsWith("Sent") ? "text-green-400" : "text-red-400"}`}>
                {webhookResult}
              </span>
            )}
          </div>
        </div>
      </section>

      {/* Scheduler */}
      <section className="rounded-xl border border-gray-800 bg-gray-900/50 p-5">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Pipeline Scheduler</h3>
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={config.scheduler_enabled}
                onChange={(e) => setConfig({ ...config, scheduler_enabled: e.target.checked })}
                className="w-4 h-4 rounded border-gray-600 bg-gray-800"
              />
              <span className="text-xs text-gray-400">Enable scheduled refresh</span>
            </label>
          </div>
          <label className="block">
            <span className="text-xs text-gray-500">Interval (hours)</span>
            <input
              type="number"
              min="1"
              max="168"
              className="mt-1 block w-32 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-white text-sm"
              value={config.pipeline_schedule_hours}
              onChange={(e) => setConfig({ ...config, pipeline_schedule_hours: Number(e.target.value) })}
            />
          </label>
          {scheduler && (
            <div className="text-xs text-gray-500 space-y-1">
              <p>Status: {scheduler.running ? "Running" : "Stopped"}</p>
              {scheduler.next_run && (
                <p>Next run: {new Date(scheduler.next_run).toLocaleString()}</p>
              )}
            </div>
          )}
        </div>
      </section>

      {/* Save Button */}
      <div className="flex items-center gap-3">
        <button
          onClick={save}
          disabled={saving}
          className="px-6 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving..." : "Save Configuration"}
        </button>
        {saved && <span className="text-sm text-green-400">Saved successfully</span>}
      </div>
    </div>
  );
}
