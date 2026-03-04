const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export interface SignalData {
  date: string;
  price: number;
  price_date: string;
  long_above: number;
  short_below: number;
  total_gaps: number;
  long_ratio: number;
  signal: string;
  signal_strength: number;
  recommendation: Recommendation;
  trend: TrendPoint[];
  gap_distribution: GapZone[];
}

export interface Recommendation {
  action: string;
  direction: string;
  position_pct: number;
  position_usd: number;
  position_sol: number;
}

export interface TrendPoint {
  date: string;
  long_ratio: number;
  price: number;
  long_above: number;
  short_below: number;
}

export interface GapZone {
  zone: string;
  zone_start: number;
  zone_end: number;
  longs: number;
  shorts: number;
}

export interface Target {
  confirm_date: string;
  timeframe: string;
  direction: string;
  situation: string;
  status: string;
  entry: number;
  target: number;
  distance_pct: number;
  distance_usd: number;
}

export interface TargetsResponse {
  price: number;
  price_date: string;
  count: number;
  targets: Target[];
}

export interface HistoryPoint {
  date: string;
  price: number;
  long_above: number;
  short_below: number;
  total_gaps: number;
  long_ratio: number;
  signal: number;
}

export interface HistoryResponse {
  source: string;
  count: number;
  history: HistoryPoint[];
}

export interface Config {
  portfolio_size: number;
  thresholds: {
    strong_long: number;
    lean_long: number;
    lean_short: number;
    strong_short: number;
  };
  position_sizing: {
    strong_pct: number;
    lean_pct: number;
  };
  timeframe_filter: string[];
  instance_folders: string[];
  candles_path: string;
  data_root: string;
  webhook_url: string;
  webhook_enabled: boolean;
  pipeline_schedule_hours: number;
  scheduler_enabled: boolean;
}

export interface PipelineStatus {
  running: boolean;
  progress: number;
  step: string;
  log: string[];
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface SignalChange {
  timestamp: string;
  previous_signal: string;
  previous_strength: number;
  signal: string;
  signal_strength: number;
  long_ratio: number;
  price: number;
}

export interface PriceData {
  price: number;
  source: "websocket" | "csv";
  timestamp: string;
}

export interface SchedulerStatus {
  enabled: boolean;
  interval_hours: number;
  running: boolean;
  next_run: string | null;
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${url}`, options);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

export const api = {
  getSignal: () => fetchJson<SignalData>("/api/signal"),

  getTargets: (params?: { timeframe?: string; direction?: string }) => {
    const q = new URLSearchParams();
    if (params?.timeframe) q.set("timeframe", params.timeframe);
    if (params?.direction) q.set("direction", params.direction);
    const qs = q.toString();
    return fetchJson<TargetsResponse>(`/api/targets${qs ? `?${qs}` : ""}`);
  },

  getHistory: (days?: number) =>
    fetchJson<HistoryResponse>(`/api/history${days ? `?days=${days}` : ""}`),

  getConfig: () => fetchJson<Config>("/api/config"),

  saveConfig: (config: Partial<Config>) =>
    fetchJson<{ status: string; config: Config }>("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    }),

  triggerUpdate: () =>
    fetchJson<{ status: string; started_at: string }>("/api/update", {
      method: "POST",
    }),

  getUpdateStatus: () => fetchJson<PipelineStatus>("/api/update/status"),

  getSignalChanges: (limit = 50) =>
    fetchJson<{ changes: SignalChange[] }>(`/api/signal/changes?limit=${limit}`),

  getPrice: () => fetchJson<PriceData>("/api/price"),

  getScheduler: () => fetchJson<SchedulerStatus>("/api/scheduler"),

  updateScheduler: (params: { enabled?: boolean; interval_hours?: number }) => {
    const q = new URLSearchParams();
    if (params.enabled !== undefined) q.set("enabled", String(params.enabled));
    if (params.interval_hours !== undefined) q.set("interval_hours", String(params.interval_hours));
    return fetchJson<SchedulerStatus>(`/api/scheduler?${q.toString()}`, { method: "POST" });
  },

  testWebhook: () =>
    fetchJson<{ status: string; http_status: number }>("/api/webhook/test", { method: "POST" }),
};
