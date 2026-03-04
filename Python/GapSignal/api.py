"""
Gap Signal API — FastAPI server for the Gap Imbalance Dashboard.

Endpoints:
  GET  /api/signal         — Full signal data (dashboard)
  GET  /api/signal/simple  — Lightweight signal for external apps
  GET  /api/health         — Health check
  GET  /api/targets        — Unfilled targets with optional filters
  GET  /api/history        — Signal history from CSV
  GET  /api/config         — Current config
  POST /api/config         — Update and persist config
  POST /api/update         — Trigger data pipeline (async)
  GET  /api/update/status  — Check pipeline progress

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
PROCESSING_DIR = os.path.join(BASE_DIR, "..", "Processing")

# Auth — set API_KEY env var to enable
API_KEY = os.environ.get("API_KEY")

# Signal cache — avoid recomputing on every poll
_signal_cache: dict = {}
_cache_ts: float = 0
CACHE_TTL = 300  # 5 minutes

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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
