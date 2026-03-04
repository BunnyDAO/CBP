"""
Gap Signal — Core computation module for the Gap Imbalance Indicator.

Loads processed candle break instances, computes the ratio of unfilled long targets
above price vs short targets below price, and generates trading signals based on
historically optimal thresholds.
"""

import glob
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

# Default higher timeframes to include
DEFAULT_TF_FILTER = ["1h", "2h", "4h", "6h", "8h", "12h", "1D", "2D", "3D", "1W", "2W", "1mo"]


def load_instances(
    folders: list[str],
    timeframe_filter: Optional[list[str]] = None,
    base_dir: str = "."
) -> pd.DataFrame:
    """Load all processed instance CSVs from the given folders."""
    all_dfs = []
    for folder in folders:
        path = os.path.join(base_dir, folder) if not os.path.isabs(folder) else folder
        if not os.path.isdir(path):
            continue
        files = sorted(glob.glob(os.path.join(path, "*.csv")))
        for f in files:
            try:
                df = pd.read_csv(f)
                if len(df) > 0:
                    all_dfs.append(df)
            except Exception:
                continue

    if not all_dfs:
        return pd.DataFrame()

    instances = pd.concat(all_dfs, ignore_index=True)
    instances["confirm_date"] = pd.to_datetime(instances["confirm_date"], format="mixed")
    instances["Completed Date"] = pd.to_datetime(
        instances["Completed Date"], format="mixed", errors="coerce"
    )
    instances["target"] = instances["target"].astype(float)
    instances["entry"] = instances["entry"].astype(float)

    # Parse Active Date if present
    if "Active Date" in instances.columns:
        instances["Active Date"] = pd.to_datetime(
            instances["Active Date"], format="mixed", errors="coerce"
        )

    # Filter by timeframe
    if timeframe_filter:
        instances = instances[instances["timeframe"].isin(timeframe_filter)].copy()

    return instances.reset_index(drop=True)


def get_current_price(candles_path: str, base_dir: str = ".") -> tuple[float, str]:
    """Get the latest price and date from the daily candle CSV, with Binance API fallback."""
    path = os.path.join(base_dir, candles_path) if not os.path.isabs(candles_path) else candles_path

    try:
        candles = pd.read_csv(path, parse_dates=["timestamp"])
        candles = candles.sort_values("timestamp")
        last = candles.iloc[-1]
        return float(last["close"]), str(last["timestamp"].date())
    except Exception:
        pass

    # Fallback: Binance public API
    try:
        import urllib.request
        url = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            return float(data["price"]), datetime.utcnow().strftime("%Y-%m-%d")
    except Exception:
        return 0.0, "unknown"


def compute_gap_imbalance(
    instances: pd.DataFrame,
    current_price: float,
    zone_size: float = 5.0
) -> dict:
    """
    Compute the gap imbalance for the current price.

    Returns dict with long_above, short_below, total_gaps, long_ratio,
    and gap_distribution by price zones.
    """
    if instances.empty:
        return {
            "long_above": 0,
            "short_below": 0,
            "total_gaps": 0,
            "long_ratio": 0.5,
            "gap_distribution": [],
        }

    # Find unfilled instances: anything not Completed
    unfilled = instances[instances["Status"] != "Completed"].copy()

    # Long targets above current price
    long_mask = (unfilled["direction"] == "long") & (unfilled["target"] > current_price)
    short_mask = (unfilled["direction"] == "short") & (unfilled["target"] < current_price)

    long_above = int(long_mask.sum())
    short_below = int(short_mask.sum())
    total_gaps = long_above + short_below
    long_ratio = long_above / total_gaps if total_gaps > 0 else 0.5

    # Gap distribution by price zones
    relevant = unfilled[long_mask | short_mask].copy()
    if not relevant.empty:
        min_target = relevant["target"].min()
        max_target = relevant["target"].max()
        zone_start = int(min_target // zone_size) * zone_size
        zone_end = (int(max_target // zone_size) + 1) * zone_size

        distribution = []
        zone = zone_start
        while zone < zone_end:
            zone_high = zone + zone_size
            in_zone = relevant[
                (relevant["target"] >= zone) & (relevant["target"] < zone_high)
            ]
            longs = int(((in_zone["direction"] == "long") & (in_zone["target"] > current_price)).sum())
            shorts = int(((in_zone["direction"] == "short") & (in_zone["target"] < current_price)).sum())
            if longs > 0 or shorts > 0:
                distribution.append({
                    "zone": f"${int(zone)}-${int(zone_high)}",
                    "zone_start": zone,
                    "zone_end": zone_high,
                    "longs": longs,
                    "shorts": shorts,
                })
            zone += zone_size
    else:
        distribution = []

    return {
        "long_above": long_above,
        "short_below": short_below,
        "total_gaps": total_gaps,
        "long_ratio": round(long_ratio, 4),
        "gap_distribution": distribution,
    }


def generate_signal(long_ratio: float, thresholds: dict) -> tuple[str, int]:
    """
    Generate a trading signal from the long_ratio and threshold config.

    Returns (signal_string, signal_strength).
    signal_strength: -2 (strong short), -1 (lean short), 0 (neutral), 1 (lean long), 2 (strong long)
    """
    strong_long = thresholds.get("strong_long", 0.80)
    lean_long = thresholds.get("lean_long", 0.60)
    lean_short = thresholds.get("lean_short", 0.40)
    strong_short = thresholds.get("strong_short", 0.20)

    if long_ratio >= strong_long:
        return "STRONG LONG", 2
    elif long_ratio >= lean_long:
        return "LEAN LONG", 1
    elif long_ratio <= strong_short:
        return "STRONG SHORT", -2
    elif long_ratio <= lean_short:
        return "LEAN SHORT", -1
    else:
        return "NEUTRAL", 0


def recommend_position(
    signal: str,
    signal_strength: int,
    portfolio_size: float,
    sizing_config: dict,
    current_price: float
) -> dict:
    """Generate a position recommendation based on the signal."""
    strong_pct = sizing_config.get("strong_pct", 15) / 100
    lean_pct = sizing_config.get("lean_pct", 5) / 100

    if signal_strength == 0:
        return {
            "action": "Stay flat",
            "direction": "NEUTRAL",
            "position_pct": 0,
            "position_usd": 0,
            "position_sol": 0,
        }

    abs_strength = abs(signal_strength)
    pct = strong_pct if abs_strength == 2 else lean_pct
    direction = "LONG" if signal_strength > 0 else "SHORT"
    usd = round(portfolio_size * pct, 2)
    sol = round(usd / current_price, 4) if current_price > 0 else 0

    return {
        "action": f"Allocate ${usd:,.0f} ({pct*100:.0f}%) to SOL {direction}",
        "direction": direction,
        "position_pct": round(pct * 100, 1),
        "position_usd": usd,
        "position_sol": sol,
    }


def get_trend_data(
    instances: pd.DataFrame,
    candles_path: str,
    days: int = 90,
    base_dir: str = "."
) -> list[dict]:
    """Compute long_ratio trend over the last N days using daily candle closes."""
    path = os.path.join(base_dir, candles_path) if not os.path.isabs(candles_path) else candles_path

    try:
        candles = pd.read_csv(path, parse_dates=["timestamp"])
        candles = candles.sort_values("timestamp").set_index("timestamp")
    except Exception:
        return []

    # Use last N days of candle data
    candles_recent = candles.tail(days)

    if instances.empty:
        return []

    # Precompute arrays for vectorized computation
    conf_dates = instances["confirm_date"].values
    comp_dates = instances["Completed Date"].values
    targets = instances["target"].values
    is_long = (instances["direction"] == "long").values
    is_short = (instances["direction"] == "short").values
    has_completion = ~pd.isna(instances["Completed Date"]).values

    trend = []
    for ts, row in candles_recent.iterrows():
        price = float(row["close"])
        dt64 = np.datetime64(ts)

        # Active = confirmed before date AND (no completion OR completed after date)
        confirmed_mask = conf_dates <= dt64
        not_completed_mask = ~has_completion | (comp_dates > dt64)
        active_mask = confirmed_mask & not_completed_mask

        long_above = int(np.sum(active_mask & is_long & (targets > price)))
        short_below = int(np.sum(active_mask & is_short & (targets < price)))
        total = long_above + short_below
        ratio = long_above / total if total > 0 else 0.5

        trend.append({
            "date": str(pd.Timestamp(ts).date()),
            "long_ratio": round(ratio, 4),
            "price": round(price, 2),
            "long_above": long_above,
            "short_below": short_below,
        })

    return trend


def get_unfilled_targets(
    instances: pd.DataFrame,
    current_price: float,
    timeframe_filter: Optional[list[str]] = None,
    direction_filter: Optional[str] = None,
) -> list[dict]:
    """Get all unfilled targets with distance from current price."""
    unfilled = instances[instances["Status"] != "Completed"].copy()

    if timeframe_filter:
        unfilled = unfilled[unfilled["timeframe"].isin(timeframe_filter)]

    if direction_filter and direction_filter in ("long", "short"):
        unfilled = unfilled[unfilled["direction"] == direction_filter]

    # Only include long targets above price and short targets below price
    mask = (
        ((unfilled["direction"] == "long") & (unfilled["target"] > current_price)) |
        ((unfilled["direction"] == "short") & (unfilled["target"] < current_price))
    )
    unfilled = unfilled[mask]

    targets = []
    for _, row in unfilled.iterrows():
        target_price = float(row["target"])
        distance_pct = round((target_price - current_price) / current_price * 100, 2)
        distance_usd = round(target_price - current_price, 2)

        targets.append({
            "confirm_date": str(row["confirm_date"].date()) if pd.notna(row["confirm_date"]) else "",
            "timeframe": row["timeframe"],
            "direction": row["direction"],
            "situation": row.get("situation", ""),
            "status": row["Status"],
            "entry": round(float(row["entry"]), 4),
            "target": round(target_price, 4),
            "distance_pct": distance_pct,
            "distance_usd": distance_usd,
        })

    # Sort by absolute distance
    targets.sort(key=lambda t: abs(t["distance_pct"]))
    return targets


def load_signal_history(history_path: str) -> list[dict]:
    """Load signal history from CSV."""
    if not os.path.exists(history_path):
        return []
    try:
        df = pd.read_csv(history_path)
        return df.to_dict("records")
    except Exception:
        return []


def append_signal_history(history_path: str, entry: dict):
    """Append a signal entry to the history CSV."""
    df_new = pd.DataFrame([entry])
    if os.path.exists(history_path):
        df_existing = pd.read_csv(history_path)
        # Don't duplicate same date
        if "date" in df_existing.columns and entry.get("date") in df_existing["date"].values:
            return
        df_combined = pd.concat([df_existing, df_new], ignore_index=True)
    else:
        df_combined = df_new
    df_combined.to_csv(history_path, index=False)


def append_signal_change(path: str, entry: dict):
    """Append a signal transition entry to signal_changes.json."""
    changes = load_signal_changes(path)
    changes.append(entry)
    with open(path, "w") as f:
        json.dump(changes, f, indent=2)


def load_signal_changes(path: str, limit: int = 0) -> list[dict]:
    """Load signal change log from JSON. Returns most recent `limit` entries (0 = all)."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r") as f:
            changes = json.load(f)
        if limit > 0:
            changes = changes[-limit:]
        return changes
    except Exception:
        return []
