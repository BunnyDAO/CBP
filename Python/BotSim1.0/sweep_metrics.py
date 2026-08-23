"""Turn a simulation output folder into one row of comparable numbers.

The simulator already writes everything needed for this: minute-by-minute equity
in analysis_YYYYMM.csv, closed trades in closed_positions.csv, and fees in
trades_all.csv.  Nothing here re-runs or re-derives the simulation; it only reads
what a run left behind, so it works on old run folders too.

Used by sweep.py to build the comparison table, and usable on its own:

    python sweep_metrics.py ../../Data/SOLUSDT-BINANCE/Simulations/my_run
"""

from __future__ import annotations

import csv
import json
import math
import os
import statistics
import sys
from datetime import datetime

# Metric columns in the order they should appear in a report.
METRIC_COLUMNS = [
    'status', 'starting_bankroll', 'final_bankroll', 'net_pnl', 'return_pct',
    'annualized_return_pct', 'max_drawdown', 'max_drawdown_pct', 'max_drawdown_date',
    'sharpe_daily', 'closed_trades', 'wins', 'losses', 'win_rate',
    'profit_factor', 'expectancy', 'avg_win', 'avg_loss', 'gross_profit', 'gross_loss',
    'fees_paid', 'open_at_end', 'first_timestamp', 'last_timestamp',
    'elapsed_seconds', 'termination_reason',
]

TRADING_DAYS_PER_YEAR = 365  # crypto trades every day


def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_divide(numerator, denominator):
    return numerator / denominator if denominator else None


def read_equity_curve(folder):
    """Stream the monthly analysis files and summarise the equity curve.

    Returns a dict, or None when the run wrote no analysis files at all.
    """
    analysis_files = sorted(
        name for name in os.listdir(folder)
        if name.startswith('analysis_') and name.endswith('.csv') and name != 'analysis_all.csv'
    )
    if not analysis_files:
        return None

    first_bankroll = None
    last_bankroll = None
    first_timestamp = None
    last_timestamp = None
    peak = None
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    max_drawdown_date = ''
    daily_close = {}   # date -> last bankroll seen that day
    daily_order = []   # dates in the order first seen

    for name in analysis_files:
        with open(os.path.join(folder, name), 'r', newline='') as f:
            for row in csv.DictReader(f):
                bankroll = _to_float(row.get('total_bankroll'), None)
                if bankroll is None:
                    continue
                timestamp = (row.get('timestamp') or '').strip()

                if first_bankroll is None:
                    first_bankroll = bankroll
                    first_timestamp = timestamp
                last_bankroll = bankroll
                last_timestamp = timestamp

                if peak is None or bankroll > peak:
                    peak = bankroll
                drawdown = peak - bankroll
                if drawdown > max_drawdown:
                    max_drawdown = drawdown
                    max_drawdown_pct = (drawdown / peak * 100) if peak else 0.0
                    max_drawdown_date = timestamp[:10]

                day = timestamp[:10]
                if day:
                    if day not in daily_close:
                        daily_order.append(day)
                    daily_close[day] = bankroll

    if first_bankroll is None:
        return None

    return {
        'first_bankroll': first_bankroll,
        'last_bankroll': last_bankroll,
        'first_timestamp': first_timestamp,
        'last_timestamp': last_timestamp,
        'max_drawdown': max_drawdown,
        'max_drawdown_pct': max_drawdown_pct,
        'max_drawdown_date': max_drawdown_date,
        'daily_series': [daily_close[day] for day in daily_order],
    }


def daily_sharpe(daily_series):
    """Annualised Sharpe from a daily equity series, with a 0% risk-free rate.

    Returns None when there aren't enough days or the returns never vary.
    """
    if len(daily_series) < 3:
        return None
    returns = []
    for previous, current in zip(daily_series, daily_series[1:]):
        if previous:
            returns.append(current / previous - 1.0)
    if len(returns) < 2:
        return None
    spread = statistics.pstdev(returns)
    if not spread:
        return None
    return statistics.fmean(returns) / spread * math.sqrt(TRADING_DAYS_PER_YEAR)


def read_closed_trades(folder):
    """Summarise closed_positions.csv (one row per completed round trip)."""
    path = os.path.join(folder, 'closed_positions.csv')
    summary = {
        'closed_trades': 0, 'wins': 0, 'losses': 0,
        'gross_profit': 0.0, 'gross_loss': 0.0,
    }
    if not os.path.exists(path):
        return summary

    with open(path, 'r', newline='') as f:
        for row in csv.DictReader(f):
            raw_pnl = row.get('ind_PnL')
            if raw_pnl in (None, ''):
                continue
            pnl = _to_float(raw_pnl, None)
            if pnl is None:
                continue
            summary['closed_trades'] += 1
            if pnl > 0:
                summary['wins'] += 1
                summary['gross_profit'] += pnl
            elif pnl < 0:
                summary['losses'] += 1
                summary['gross_loss'] += pnl   # kept negative
    return summary


def read_fees(folder):
    """Total fees paid, from trades_all.csv.

    An entry row records the opening fee; the matching exit row records opening +
    closing together.  So the total is every exit row, plus the entry rows of
    trades that were still open at the end.
    """
    path = os.path.join(folder, 'trades_all.csv')
    if not os.path.exists(path):
        return 0.0

    fees = 0.0
    opening_fees = {}
    closed_ids = set()

    with open(path, 'r', newline='') as f:
        for row in csv.DictReader(f):
            order_type = (row.get('order_type') or '').strip()
            trade_id = (row.get('trade_id') or '').strip()
            fee = _to_float(row.get('trade_fee'))
            if order_type in ('open long', 'open short'):
                opening_fees[trade_id] = fee
            elif order_type in ('close long', 'close short'):
                closed_ids.add(trade_id)
                fees += fee

    for trade_id, fee in opening_fees.items():
        if trade_id not in closed_ids:
            fees += fee

    return fees


def count_open_positions(folder):
    path = os.path.join(folder, 'open_positions.csv')
    if not os.path.exists(path):
        return 0
    with open(path, 'r', newline='') as f:
        return sum(1 for _ in csv.DictReader(f))


def read_run_meta(folder):
    path = os.path.join(folder, 'run_meta.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (ValueError, OSError):
        return {}


def find_termination(folder):
    """Return the termination reason a run left behind, if any."""
    markers = [name for name in os.listdir(folder) if name.startswith('TERMINATED')]
    if not markers:
        return None
    # Filename is "TERMINATED - <reason>.txt"
    reason = markers[0][len('TERMINATED - '):].rsplit('.txt', 1)[0]
    return reason or markers[0]


def _elapsed_days(first_timestamp, last_timestamp):
    try:
        first = datetime.strptime(first_timestamp, '%Y-%m-%d %H:%M:%S')
        last = datetime.strptime(last_timestamp, '%Y-%m-%d %H:%M:%S')
    except (TypeError, ValueError):
        return None
    days = (last - first).total_seconds() / 86400
    return days if days > 0 else None


def collect_run_metrics(folder):
    """Read one run folder and return a dict keyed by METRIC_COLUMNS."""
    metrics = {column: None for column in METRIC_COLUMNS}

    if not os.path.isdir(folder):
        metrics['status'] = 'missing'
        return metrics

    meta = read_run_meta(folder)
    termination = find_termination(folder)

    equity = read_equity_curve(folder)
    if equity is None:
        # No analysis files means the run never got going.
        metrics['status'] = meta.get('status') or 'no_output'
        metrics['termination_reason'] = meta.get('termination_reason') or termination
        metrics['elapsed_seconds'] = meta.get('elapsed_seconds')
        return metrics

    trades = read_closed_trades(folder)
    decided = trades['wins'] + trades['losses']

    starting = equity['first_bankroll']
    final = equity['last_bankroll']
    net_pnl = final - starting
    days = _elapsed_days(equity['first_timestamp'], equity['last_timestamp'])

    annualized = None
    if days and starting > 0 and final > 0:
        annualized = ((final / starting) ** (TRADING_DAYS_PER_YEAR / days) - 1) * 100

    if meta.get('status'):
        status = meta['status']
    elif termination:
        status = 'terminated'
    else:
        status = 'completed'

    metrics.update({
        'status': status,
        'starting_bankroll': round(starting, 2),
        'final_bankroll': round(final, 2),
        'net_pnl': round(net_pnl, 2),
        'return_pct': round(net_pnl / starting * 100, 2) if starting else None,
        'annualized_return_pct': round(annualized, 2) if annualized is not None else None,
        'max_drawdown': round(equity['max_drawdown'], 2),
        'max_drawdown_pct': round(equity['max_drawdown_pct'], 2),
        'max_drawdown_date': equity['max_drawdown_date'],
        'sharpe_daily': None,
        'closed_trades': trades['closed_trades'],
        'wins': trades['wins'],
        'losses': trades['losses'],
        'win_rate': round(trades['wins'] / decided, 4) if decided else None,
        'gross_profit': round(trades['gross_profit'], 2),
        'gross_loss': round(trades['gross_loss'], 2),
        'fees_paid': round(read_fees(folder), 2),
        'open_at_end': count_open_positions(folder),
        'first_timestamp': equity['first_timestamp'],
        'last_timestamp': equity['last_timestamp'],
        'elapsed_seconds': meta.get('elapsed_seconds'),
        'termination_reason': meta.get('termination_reason') or termination,
    })

    sharpe = daily_sharpe(equity['daily_series'])
    if sharpe is not None:
        metrics['sharpe_daily'] = round(sharpe, 3)

    profit_factor = _safe_divide(trades['gross_profit'], abs(trades['gross_loss']))
    if profit_factor is not None:
        metrics['profit_factor'] = round(profit_factor, 3)

    total_trade_pnl = trades['gross_profit'] + trades['gross_loss']
    expectancy = _safe_divide(total_trade_pnl, trades['closed_trades'])
    if expectancy is not None:
        metrics['expectancy'] = round(expectancy, 2)

    avg_win = _safe_divide(trades['gross_profit'], trades['wins'])
    if avg_win is not None:
        metrics['avg_win'] = round(avg_win, 2)

    avg_loss = _safe_divide(trades['gross_loss'], trades['losses'])
    if avg_loss is not None:
        metrics['avg_loss'] = round(avg_loss, 2)

    return metrics


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__.strip())
        return 1
    for folder in argv:
        print(f"\n{folder}")
        metrics = collect_run_metrics(folder)
        width = max(len(column) for column in METRIC_COLUMNS)
        for column in METRIC_COLUMNS:
            value = metrics.get(column)
            if value is not None:
                print(f"  {column:<{width}}  {value}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
