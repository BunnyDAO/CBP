"""
Gap Signal API — FastAPI server for the Gap Imbalance Dashboard.

Endpoints:
  GET  /api/signal          — Full signal data (dashboard)
  GET  /api/signal/simple   — Lightweight signal for external apps
  GET  /api/signal/changes  — Signal transition change log
  GET  /api/health          — Health check
  GET  /api/targets         — Unfilled targets with optional filters
  GET  /api/history         — Signal history from CSV
  GET  /api/config          — Current config
  POST /api/config          — Update and persist config
  POST /api/update          — Trigger data pipeline (async)
  GET  /api/update/status   — Check pipeline progress
  POST /api/webhook/test    — Fire test webhook payload
  GET  /api/scheduler       — Scheduler status + next run
  POST /api/scheduler       — Update scheduler settings
  GET  /api/price           — Live price (WebSocket or CSV fallback)

Auth:
  Set API_KEY env var to require `X-API-Key` header on all requests.
  Unset = no auth (local dev).
"""

import json
import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, Query, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import gap_signal as gs

app = FastAPI(title="Gap Signal API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
HISTORY_PATH = os.path.join(BASE_DIR, "signal_history.csv")
CHANGES_PATH = os.path.join(BASE_DIR, "signal_changes.json")
PROCESSING_DIR = os.path.join(BASE_DIR, "..", "Processing")

# Auth — set API_KEY env var to enable
API_KEY = os.environ.get("API_KEY")

# Signal cache — avoid recomputing on every poll
_signal_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 300  # 5 minutes

# Live price (populated by WebSocket thread, used by _compute_signal)
_live_price: Optional[float] = None
_live_price_ts: float = 0

# Pipeline state
pipeline_state = {
    "running": False,
    "progress": 0,
    "step": "",
    "log": [],
    "error": None,
    "started_at": None,
    "finished_at": None,
}


def verify_api_key(request: Request):
    """Check X-API-Key header if API_KEY is set."""
    if not API_KEY:
        return
    key = request.headers.get("X-API-Key")
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


def save_config(config: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(config, f, indent=2)


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "1.0.0", "timestamp": datetime.now().isoformat()}


# ─── Cached Signal Computation ───────────────────────────────────────────────

def _compute_signal() -> dict:
    """Compute full signal data, with 5-minute cache."""
    global _signal_cache, _cache_ts
    now = time.time()
    if _signal_cache and (now - _cache_ts) < CACHE_TTL:
        return _signal_cache

    config = load_config()

    instances = gs.load_instances(
        folders=config["instance_folders"],
        timeframe_filter=config.get("timeframe_filter"),
        base_dir=BASE_DIR,
    )

    # Use live WebSocket price if fresh (< 60s), else CSV
    now_ts = time.time()
    if _live_price is not None and (now_ts - _live_price_ts) < 60:
        price = round(_live_price, 4)
        price_date = datetime.fromtimestamp(_live_price_ts).strftime("%Y-%m-%d")
    else:
        price, price_date = gs.get_current_price(config["candles_path"], base_dir=BASE_DIR)

    imbalance = gs.compute_gap_imbalance(instances, price)
    signal, strength = gs.generate_signal(imbalance["long_ratio"], config["thresholds"])
    recommendation = gs.recommend_position(
        signal, strength,
        config["portfolio_size"],
        config["position_sizing"],
        price,
    )

    trend = gs.get_trend_data(
        instances, config["candles_path"], days=90, base_dir=BASE_DIR
    )

    today = datetime.now().strftime("%Y-%m-%d")

    # Log to history
    gs.append_signal_history(HISTORY_PATH, {
        "date": today,
        "price": price,
        "long_above": imbalance["long_above"],
        "short_below": imbalance["short_below"],
        "total_gaps": imbalance["total_gaps"],
        "long_ratio": imbalance["long_ratio"],
        "signal": signal,
        "signal_strength": strength,
    })

    # Detect signal change
    prev_strength = _signal_cache.get("signal_strength") if _signal_cache else None
    if prev_strength is not None and prev_strength != strength:
        change_entry = {
            "timestamp": datetime.now().isoformat(),
            "previous_signal": _signal_cache["signal"],
            "previous_strength": prev_strength,
            "signal": signal,
            "signal_strength": strength,
            "long_ratio": imbalance["long_ratio"],
            "price": price,
        }
        gs.append_signal_change(CHANGES_PATH, change_entry)
        _fire_webhook(change_entry)

    _signal_cache = {
        "date": today,
        "price": price,
        "price_date": price_date,
        "long_above": imbalance["long_above"],
        "short_below": imbalance["short_below"],
        "total_gaps": imbalance["total_gaps"],
        "long_ratio": imbalance["long_ratio"],
        "signal": signal,
        "signal_strength": strength,
        "recommendation": recommendation,
        "trend": trend,
        "gap_distribution": imbalance["gap_distribution"],
    }
    _cache_ts = now
    return _signal_cache


# ─── Signal Endpoints ────────────────────────────────────────────────────────

@app.get("/api/signal", dependencies=[Depends(verify_api_key)])
def get_signal():
    """Full signal data for the dashboard."""
    return _compute_signal()


@app.get("/api/signal/simple", dependencies=[Depends(verify_api_key)])
def get_signal_simple():
    """Lightweight endpoint for external apps to poll.

    Returns:
        {
            "signal": "NEUTRAL",          # STRONG LONG / LEAN LONG / NEUTRAL / LEAN SHORT / STRONG SHORT
            "signal_strength": 0,         # -2, -1, 0, 1, 2
            "long_ratio": 0.4306,
            "price": 86.71,
            "long_above": 93,
            "short_below": 123,
            "date": "2026-03-03"
        }
    """
    full = _compute_signal()
    return {
        "signal": full["signal"],
        "signal_strength": full["signal_strength"],
        "long_ratio": full["long_ratio"],
        "price": full["price"],
        "long_above": full["long_above"],
        "short_below": full["short_below"],
        "date": full["date"],
    }


# ─── Signal Changes Endpoint ─────────────────────────────────────────────────

@app.get("/api/signal/changes", dependencies=[Depends(verify_api_key)])
def get_signal_changes(limit: int = Query(50, description="Max entries to return")):
    """Recent signal transitions."""
    return {"changes": gs.load_signal_changes(CHANGES_PATH, limit=limit)}


# ─── Webhook ────────────────────────────────────────────────────────────────

WEBHOOK_URL = os.environ.get("WEBHOOK_URL")


def _fire_webhook(change_entry: dict):
    """POST signal change to webhook URL if enabled."""
    config = load_config()
    url = WEBHOOK_URL or config.get("webhook_url", "")
    enabled = bool(WEBHOOK_URL) or config.get("webhook_enabled", False)
    if not url or not enabled:
        return
    payload = {
        "event": "signal_change",
        "previous_signal": change_entry.get("previous_signal"),
        "signal": change_entry["signal"],
        "signal_strength": change_entry["signal_strength"],
        "long_ratio": change_entry["long_ratio"],
        "price": change_entry["price"],
        "timestamp": change_entry["timestamp"],
    }
    try:
        import requests as req
        req.post(url, json=payload, timeout=10)
    except Exception:
        pass


@app.post("/api/webhook/test", dependencies=[Depends(verify_api_key)])
def test_webhook():
    """Fire a test webhook payload."""
    config = load_config()
    url = WEBHOOK_URL or config.get("webhook_url", "")
    if not url:
        raise HTTPException(status_code=400, detail="No webhook URL configured")
    payload = {
        "event": "test",
        "previous_signal": "NEUTRAL",
        "signal": "LEAN LONG",
        "signal_strength": 1,
        "long_ratio": 0.65,
        "price": 150.0,
        "timestamp": datetime.now().isoformat(),
    }
    try:
        import requests as req
        resp = req.post(url, json=payload, timeout=10)
        return {"status": "sent", "http_status": resp.status_code}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


# ─── Targets Endpoint ────────────────────────────────────────────────────────

@app.get("/api/targets", dependencies=[Depends(verify_api_key)])
def get_targets(
    timeframe: Optional[str] = Query(None, description="Comma-separated timeframes"),
    direction: Optional[str] = Query(None, description="'long' or 'short'"),
):
    config = load_config()

    instances = gs.load_instances(
        folders=config["instance_folders"],
        timeframe_filter=config.get("timeframe_filter"),
        base_dir=BASE_DIR,
    )

    price, price_date = gs.get_current_price(config["candles_path"], base_dir=BASE_DIR)

    tf_filter = timeframe.split(",") if timeframe else None
    targets = gs.get_unfilled_targets(
        instances, price,
        timeframe_filter=tf_filter,
        direction_filter=direction,
    )

    return {
        "price": price,
        "price_date": price_date,
        "count": len(targets),
        "targets": targets,
    }


# ─── History Endpoint ────────────────────────────────────────────────────────

@app.get("/api/history", dependencies=[Depends(verify_api_key)])
def get_history(days: int = Query(365, description="Number of days of history")):
    config = load_config()

    # Try loading from gap_imbalance_daily.csv first (has much more history)
    daily_path = os.path.join(
        BASE_DIR, config.get("data_root", "../../Data/SOLUSDT-BINANCE"),
        "gap_imbalance_daily.csv"
    )
    if os.path.exists(daily_path):
        import pandas as pd
        df = pd.read_csv(daily_path)
        df = df.tail(days)
        records = []
        for _, row in df.iterrows():
            records.append({
                "date": row["date"],
                "price": round(float(row["price"]), 2),
                "long_above": int(row["long_above"]),
                "short_below": int(row["short_below"]),
                "total_gaps": int(row["total_gaps"]),
                "long_ratio": round(float(row["long_ratio"]), 4),
                "signal": int(row["signal"]) if "signal" in row else 0,
            })
        return {"source": "daily", "count": len(records), "history": records}

    # Fallback: local signal_history.csv
    history = gs.load_signal_history(HISTORY_PATH)
    if days and len(history) > days:
        history = history[-days:]
    return {"source": "local", "count": len(history), "history": history}


# ─── Config Endpoints ────────────────────────────────────────────────────────

class ConfigUpdate(BaseModel):
    portfolio_size: Optional[float] = None
    thresholds: Optional[dict] = None
    position_sizing: Optional[dict] = None
    timeframe_filter: Optional[list[str]] = None
    instance_folders: Optional[list[str]] = None
    candles_path: Optional[str] = None
    data_root: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_enabled: Optional[bool] = None
    pipeline_schedule_hours: Optional[int] = None
    scheduler_enabled: Optional[bool] = None


@app.get("/api/config", dependencies=[Depends(verify_api_key)])
def get_config():
    return load_config()


@app.post("/api/config", dependencies=[Depends(verify_api_key)])
def update_config(update: ConfigUpdate):
    config = load_config()
    update_dict = update.model_dump(exclude_none=True)
    config.update(update_dict)
    save_config(config)
    return {"status": "saved", "config": config}


# ─── Pipeline Update Endpoints ───────────────────────────────────────────────

def run_pipeline():
    global pipeline_state
    config = load_config()
    candles_path = os.path.join(BASE_DIR, config["candles_path"])
    data_root = os.path.join(BASE_DIR, config.get("data_root", "../../Data/SOLUSDT-BINANCE"))

    steps = [
        {
            "name": "Download latest candle data",
            "cmd": [
                "python3", os.path.join(PROCESSING_DIR, "download_binance_historical_data.py"),
                "--some", "-d", candles_path,
            ],
        },
        {
            "name": "Convert timeframes",
            "cmd": [
                "python3", os.path.join(PROCESSING_DIR, "historical_data_TF_converter.py"),
                "--path", candles_path,
            ],
        },
        {
            "name": "Find new instances",
            "cmd": [
                "python3", os.path.join(PROCESSING_DIR, "historical_instances_finder_updater.py"),
                "--no-prompt",
                "-i", os.path.join(data_root, "Candles"),
                "-o", os.path.join(data_root, "Instances", "1v1", "Unprocessed"),
            ],
        },
        {
            "name": "Process instance status",
            "cmd": [
                "python3", os.path.join(PROCESSING_DIR, "historical_process_status_of_instances.py"),
            ],
            "stdin": "\n\n",
        },
    ]

    for i, step in enumerate(steps):
        pipeline_state["step"] = step["name"]
        pipeline_state["progress"] = int((i / len(steps)) * 100)
        pipeline_state["log"].append(f"[{datetime.now().strftime('%H:%M:%S')}] Starting: {step['name']}")

        try:
            result = subprocess.run(
                step["cmd"],
                capture_output=True,
                text=True,
                timeout=600,
                input=step.get("stdin"),
                cwd=PROCESSING_DIR,
            )
            if result.returncode != 0:
                pipeline_state["log"].append(f"  Warning: {result.stderr[:200] if result.stderr else 'non-zero exit'}")
            else:
                pipeline_state["log"].append(f"  Completed: {step['name']}")
        except FileNotFoundError:
            pipeline_state["log"].append(f"  Skipped (script not found): {step['name']}")
        except subprocess.TimeoutExpired:
            pipeline_state["log"].append(f"  Timeout: {step['name']}")
        except Exception as e:
            pipeline_state["log"].append(f"  Error: {str(e)}")

    pipeline_state["progress"] = 100
    pipeline_state["step"] = "Complete"
    pipeline_state["running"] = False
    pipeline_state["finished_at"] = datetime.now().isoformat()


@app.post("/api/update", dependencies=[Depends(verify_api_key)])
def trigger_update():
    global pipeline_state
    if pipeline_state["running"]:
        return {"status": "already_running", "started_at": pipeline_state["started_at"]}

    pipeline_state = {
        "running": True,
        "progress": 0,
        "step": "Starting...",
        "log": [],
        "error": None,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    }

    thread = threading.Thread(target=run_pipeline, daemon=True)
    thread.start()

    return {"status": "started", "started_at": pipeline_state["started_at"]}


@app.get("/api/update/status", dependencies=[Depends(verify_api_key)])
def update_status():
    return pipeline_state


# ─── Scheduled Pipeline Refresh ─────────────────────────────────────────────

_scheduler = None


def _scheduled_pipeline_run():
    """Run pipeline on schedule, then invalidate signal cache."""
    global _signal_cache, _cache_ts
    if pipeline_state["running"]:
        return
    pipeline_state.update({
        "running": True,
        "progress": 0,
        "step": "Starting (scheduled)...",
        "log": [],
        "error": None,
        "started_at": datetime.now().isoformat(),
        "finished_at": None,
    })
    run_pipeline()
    # Invalidate cache so next signal request recomputes (triggers change detection)
    _signal_cache = {}
    _cache_ts = 0


def _start_scheduler():
    """Start or restart the APScheduler BackgroundScheduler."""
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        return

    config = load_config()
    if not config.get("scheduler_enabled", True):
        return

    hours = config.get("pipeline_schedule_hours", 6)

    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass

    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _scheduled_pipeline_run,
        "interval",
        hours=hours,
        id="pipeline_refresh",
        replace_existing=True,
    )
    _scheduler.start()


@app.on_event("startup")
def on_startup():
    _start_scheduler()
    _start_live_price()


@app.get("/api/scheduler", dependencies=[Depends(verify_api_key)])
def get_scheduler_status():
    """Scheduler status and next run time."""
    config = load_config()
    next_run = None
    if _scheduler and _scheduler.running:
        job = _scheduler.get_job("pipeline_refresh")
        if job and job.next_run_time:
            next_run = job.next_run_time.isoformat()
    return {
        "enabled": config.get("scheduler_enabled", True),
        "interval_hours": config.get("pipeline_schedule_hours", 6),
        "running": _scheduler is not None and _scheduler.running,
        "next_run": next_run,
    }


@app.post("/api/scheduler", dependencies=[Depends(verify_api_key)])
def update_scheduler(enabled: Optional[bool] = None, interval_hours: Optional[int] = None):
    """Update scheduler settings and restart."""
    config = load_config()
    if enabled is not None:
        config["scheduler_enabled"] = enabled
    if interval_hours is not None and interval_hours >= 1:
        config["pipeline_schedule_hours"] = interval_hours
    save_config(config)

    if config.get("scheduler_enabled", True):
        _start_scheduler()
    elif _scheduler:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            pass

    return get_scheduler_status()


# ─── Live Binance Price via WebSocket ───────────────────────────────────────

_ws_thread: Optional[threading.Thread] = None


def _binance_ws_loop():
    """Connect to Binance WebSocket for live SOL/USDT price with auto-reconnect."""
    global _live_price, _live_price_ts
    import importlib
    backoff = 1

    while True:
        try:
            ws_mod = importlib.import_module("websockets.sync.client")
            with ws_mod.connect("wss://stream.binance.com:9443/ws/solusdt@trade") as ws:
                backoff = 1  # reset on successful connect
                while True:
                    msg = ws.recv()
                    data = json.loads(msg)
                    _live_price = float(data["p"])
                    _live_price_ts = time.time()
        except Exception:
            time.sleep(min(backoff, 60))
            backoff *= 2


def _start_live_price():
    """Start live price WebSocket thread."""
    global _ws_thread
    try:
        import websockets  # noqa: F401
    except ImportError:
        return
    if _ws_thread is not None and _ws_thread.is_alive():
        return
    _ws_thread = threading.Thread(target=_binance_ws_loop, daemon=True)
    _ws_thread.start()


@app.get("/api/price", dependencies=[Depends(verify_api_key)])
def get_price():
    """Live price — WebSocket if fresh (< 60s), else CSV fallback."""
    now = time.time()
    if _live_price is not None and (now - _live_price_ts) < 60:
        return {
            "price": round(_live_price, 4),
            "source": "websocket",
            "timestamp": datetime.fromtimestamp(_live_price_ts).isoformat(),
        }
    # CSV fallback
    config = load_config()
    price, price_date = gs.get_current_price(config["candles_path"], base_dir=BASE_DIR)
    return {
        "price": price,
        "source": "csv",
        "timestamp": price_date,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
