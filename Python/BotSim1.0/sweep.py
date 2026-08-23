"""Run many simulator configs and put the results in one table.

A sweep is a JSON file: a base config, plus a grid of settings to vary and/or an
explicit list of runs.  Every combination becomes one simulation in its own output
folder, run in a separate process (several at a time), and the results are
collected into sweep_results.csv sorted by whichever metric you pick.

    python sweep.py sweeps/example_sweep.json
    python sweep.py sweeps/example_sweep.json --workers 4
    python sweep.py sweeps/example_sweep.json --dry-run     # show the plan, run nothing
    python sweep.py sweeps/example_sweep.json --resume      # skip runs that already finished
    python sweep.py sweeps/example_sweep.json --report-only # just rebuild the results table

Sweep file format (only "grid" or "runs" is required):

    {
      "name": "pending-window",
      "output_root": "../../Data/SOLUSDT-BINANCE/Simulations/sweeps/pending-window",
      "base":   {"starting_date": "2022-01-01", "ending_date": "2023-06-30"},
      "grid":   {"MIN_PENDING_CANDLES": [5, 10, 20], "position_size_percent": [30, 70]},
      "runs":   [{"USE_STATIC_TIME_CAPIT": true, "STATIC_TIME_CAPIT_DURATION": 36}],
      "sort_by": "return_pct"
    }

"base" applies to every run.  "grid" is expanded into the cartesian product of its
values.  "runs" adds explicit combinations on top of the grid (or instead of it).
Settings not mentioned anywhere keep whatever config.py says, so config.py is
still the place to set the paths and anything you're not sweeping.

Paths inside "base" are resolved the same way config.py's are (relative to this
folder).  "output_root" is resolved relative to the sweep file.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sweep_metrics import METRIC_COLUMNS, collect_run_metrics

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_SIM = os.path.join(SCRIPT_DIR, 'run_sim.py')

# Tracks live child processes so Ctrl-C can stop them.
_active_processes = set()
_active_lock = threading.Lock()


# ----------------------------------------------------------------------
# Plan building
# ----------------------------------------------------------------------
def load_sweep_file(path):
    with open(path, 'r') as f:
        sweep = json.load(f)

    unknown = sorted(set(sweep) - {'name', 'output_root', 'base', 'grid', 'runs', 'sort_by', 'sort_desc'})
    if unknown:
        raise KeyError(f"Unknown key(s) in sweep file: {', '.join(unknown)}")
    if not sweep.get('grid') and not sweep.get('runs'):
        raise ValueError("Sweep file needs a 'grid' and/or a 'runs' list")

    return sweep


def expand_grid(grid):
    """Cartesian product of {key: [values]} into a list of override dicts."""
    if not grid:
        return [{}]
    keys = list(grid)
    for key in keys:
        if not isinstance(grid[key], list):
            raise TypeError(f"grid['{key}'] must be a list of values")
    return [dict(zip(keys, combo)) for combo in itertools.product(*(grid[key] for key in keys))]


def expand_runs(sweep):
    """Every override dict this sweep asks for, de-duplicated, order preserved."""
    grid_combos = expand_grid(sweep.get('grid'))
    explicit = sweep.get('runs') or [{}]

    combos = []
    seen = set()
    for grid_part in grid_combos:
        for explicit_part in explicit:
            combined = dict(grid_part)
            combined.update(explicit_part)   # explicit runs win over the grid
            key = json.dumps(combined, sort_keys=True, default=str)
            if key not in seen:
                seen.add(key)
                combos.append(combined)
    return combos


def varying_keys(combos):
    """Keys whose value is not the same across every run - the ones worth naming."""
    if len(combos) <= 1:
        return sorted(combos[0]) if combos else []
    keys = sorted({key for combo in combos for key in combo})
    varying = []
    for key in keys:
        values = {json.dumps(combo.get(key), sort_keys=True, default=str) for combo in combos}
        if len(values) > 1:
            varying.append(key)
    return varying


def abbreviate(keys):
    """Short labels for folder names: MIN_PENDING_CANDLES -> MPC, falling back to
    the full key whenever two settings would collide."""
    short = {}
    for key in keys:
        parts = [part for part in key.replace('-', '_').split('_') if part]
        short[key] = ''.join(part[0] for part in parts).upper() if parts else key
    counts = {}
    for value in short.values():
        counts[value] = counts.get(value, 0) + 1
    return {key: (key if counts[value] > 1 else value) for key, value in short.items()}


def format_value(value):
    """Compact, filesystem-safe rendering of a setting's value."""
    if isinstance(value, bool):
        return 'T' if value else 'F'
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (list, tuple)):
        text = '-'.join(str(item) for item in value)
    else:
        text = str(value)
    return ''.join(char if char.isalnum() or char in '.-' else '_' for char in text)


def run_folder_name(index, combo, labels, keys):
    parts = [f"{labels[key]}{format_value(combo[key])}" for key in keys if key in combo]
    slug = '_'.join(parts)
    if len(slug) > 80:
        slug = slug[:80].rstrip('_')
    return f"{index:03d}_{slug}" if slug else f"{index:03d}"


def build_plan(sweep, sweep_path):
    """Turn a sweep file into a list of run descriptors, with invalid combos flagged."""
    from sim_config import SimConfig

    sweep_dir = os.path.dirname(os.path.abspath(sweep_path))
    output_root = sweep.get('output_root')
    if not output_root:
        raise ValueError("Sweep file needs an 'output_root'")
    output_root = os.path.abspath(os.path.join(sweep_dir, output_root))

    base_overrides = sweep.get('base') or {}
    combos = expand_runs(sweep)
    keys = varying_keys(combos)
    labels = abbreviate(keys)

    # config.py supplies everything the sweep doesn't mention.
    base_config = SimConfig.from_config_module().with_overrides(base_overrides)

    plan = []
    for index, combo in enumerate(combos, start=1):
        name = run_folder_name(index, combo, labels, keys)
        folder = os.path.join(output_root, name)

        try:
            cfg = base_config.with_overrides(combo)
            errors = cfg.validate()
        except (KeyError, ValueError) as exc:
            errors = [str(exc)]
            cfg = None

        plan.append({
            'name': name,
            'folder': folder,
            'overrides': combo,
            'errors': errors,
            'config': cfg,
        })

    return {
        'sweep_name': sweep.get('name') or os.path.splitext(os.path.basename(sweep_path))[0],
        'output_root': output_root,
        'base': base_overrides,
        'varying_keys': keys,
        'sort_by': sweep.get('sort_by', 'return_pct'),
        'sort_desc': sweep.get('sort_desc', True),
        'runs': plan,
    }


# ----------------------------------------------------------------------
# Execution
# ----------------------------------------------------------------------
def already_finished(folder):
    """True when this folder holds a finished run we don't need to redo."""
    meta_path = os.path.join(folder, 'run_meta.json')
    if not os.path.exists(meta_path):
        return False
    try:
        with open(meta_path, 'r') as f:
            return json.load(f).get('status') in ('completed', 'terminated')
    except (ValueError, OSError):
        return False


def merged_overrides(entry):
    """The overrides for one run: the sweep's base plus this combination."""
    merged = dict(entry.get('base') or {})
    merged.update(entry['overrides'])
    return merged


def write_run_config(entry, plan_dir):
    """Write the per-run override file that run_sim.py will read."""
    path = os.path.join(plan_dir, f"{entry['name']}.json")
    with open(path, 'w') as f:
        json.dump(merged_overrides(entry), f, indent=2, sort_keys=True, default=str)
    return path


def execute_run(entry, candle_cache):
    """Run one simulation in its own process. Returns (name, returncode, seconds)."""
    os.makedirs(entry['folder'], exist_ok=True)
    log_path = os.path.join(entry['folder'], 'run.log')

    command = [
        sys.executable, RUN_SIM,
        '--config', entry['config_path'],
        '--output', entry['folder'],
        '--fresh',
    ]
    if candle_cache:
        command += ['--candle-cache', candle_cache]

    started = time.time()
    with open(log_path, 'w') as log_file:
        process = subprocess.Popen(
            command, cwd=SCRIPT_DIR,
            stdout=log_file, stderr=subprocess.STDOUT,
        )
        with _active_lock:
            _active_processes.add(process)
        try:
            returncode = process.wait()
        finally:
            with _active_lock:
                _active_processes.discard(process)

    return entry['name'], returncode, time.time() - started


def stop_active_processes():
    with _active_lock:
        processes = list(_active_processes)
    for process in processes:
        try:
            process.terminate()
        except OSError:
            pass


def warm_candle_cache(plan, cache_dir):
    """Parse each distinct candle slice once, up front.

    Without this every worker parses the same 1m CSV at the same time, which for a
    multi-year file is the slowest part of a sweep.
    """
    from run_sim import load_candles_cached

    combinations = {}
    for entry in plan['runs']:
        cfg = entry['config']
        if cfg is None or entry['errors']:
            continue
        key = (
            cfg.candles_file_default,
            cfg.starting_date.replace(hour=0, minute=0, second=0, microsecond=0),
            cfg.ending_date.replace(hour=23, minute=59, second=59, microsecond=0),
        )
        combinations[key] = True

    if not combinations:
        return

    from initialization import load_candles

    print(f"Warming the candle cache ({len(combinations)} distinct date range(s))...")
    for candles_file, start, end in combinations:
        candles = load_candles_cached(load_candles, candles_file, start, end, cache_dir)
        del candles


# ----------------------------------------------------------------------
# Reporting
# ----------------------------------------------------------------------
def sort_key_for(metric, descending):
    """Sort runs by `metric`, always pushing missing values to the bottom."""
    def key(row):
        value = row.get(metric)
        if value is None or value == '':
            return (1, 0)
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return (1, 0)
        return (0, -numeric if descending else numeric)
    return key


def build_report(plan):
    """Collect every run folder into rows, sorted by the sweep's chosen metric."""
    rows = []
    for entry in plan['runs']:
        row = {'run': entry['name'], 'folder': entry['folder']}
        for key in plan['varying_keys']:
            row[key] = entry['overrides'].get(key)
        if entry['errors']:
            row.update({column: None for column in METRIC_COLUMNS})
            row['status'] = 'invalid'
            row['termination_reason'] = '; '.join(entry['errors'])
        else:
            row.update(collect_run_metrics(entry['folder']))
        rows.append(row)

    rows.sort(key=sort_key_for(plan['sort_by'], plan['sort_desc']))
    return rows


def write_report(plan, rows):
    columns = ['run'] + list(plan['varying_keys']) + METRIC_COLUMNS + ['folder']
    path = os.path.join(plan['output_root'], 'sweep_results.csv')
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)
    return path


def print_report(plan, rows, limit=15):
    """Print the top of the table so you don't have to open the CSV."""
    metric = plan['sort_by']
    columns = ['run'] + list(plan['varying_keys']) + [
        metric, 'max_drawdown_pct', 'closed_trades', 'win_rate', 'profit_factor', 'status']
    columns = list(dict.fromkeys(columns))   # metric may already be in the list

    def cell(value):
        return '' if value is None else str(value)

    widths = {column: len(column) for column in columns}
    for row in rows[:limit]:
        for column in columns:
            widths[column] = max(widths[column], len(cell(row.get(column))))

    header = '  '.join(column.ljust(widths[column]) for column in columns)
    print()
    print(header)
    print('-' * len(header))
    for row in rows[:limit]:
        print('  '.join(cell(row.get(column)).ljust(widths[column]) for column in columns))
    if len(rows) > limit:
        print(f"... {len(rows) - limit} more in sweep_results.csv")


# ----------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Run a grid of BotSim configs and compare the results.')
    parser.add_argument('sweep_file', help='JSON sweep definition.')
    parser.add_argument('-w', '--workers', type=int, default=None,
                        help='Simulations to run at once (default: CPU count - 1).')
    parser.add_argument('--dry-run', action='store_true', help='Print the plan and stop.')
    parser.add_argument('--resume', action='store_true',
                        help='Skip runs whose output folder already holds a finished run.')
    parser.add_argument('--report-only', action='store_true',
                        help='Rebuild sweep_results.csv from existing run folders.')
    parser.add_argument('--no-candle-cache', action='store_true',
                        help='Parse the candle CSV in every run instead of caching it.')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    sweep_path = os.path.abspath(args.sweep_file)

    os.chdir(SCRIPT_DIR)   # so relative paths in config.py resolve as usual

    try:
        sweep = load_sweep_file(sweep_path)
        plan = build_plan(sweep, sweep_path)
    except (KeyError, TypeError, ValueError, OSError) as exc:
        print(f"Could not read the sweep file {sweep_path}: {exc}")
        return 1

    runnable = [entry for entry in plan['runs'] if not entry['errors']]
    invalid = [entry for entry in plan['runs'] if entry['errors']]

    print(f"Sweep '{plan['sweep_name']}': {len(plan['runs'])} combination(s) "
          f"-> {len(runnable)} runnable, {len(invalid)} skipped as invalid")
    print(f"Output root: {plan['output_root']}")
    if plan['varying_keys']:
        print(f"Varying: {', '.join(plan['varying_keys'])}")

    for entry in invalid:
        print(f"  skip {entry['name']}: {'; '.join(entry['errors'])}")

    if runnable:
        for note in runnable[0]['config'].warnings():
            print(f"Note: {note}")

    if args.dry_run:
        for entry in plan['runs']:
            marker = 'SKIP' if entry['errors'] else '    '
            print(f"  {marker} {entry['name']}  {json.dumps(entry['overrides'], sort_keys=True, default=str)}")
        return 0

    os.makedirs(plan['output_root'], exist_ok=True)
    plan_dir = os.path.join(plan['output_root'], '_plan')
    os.makedirs(plan_dir, exist_ok=True)

    with open(os.path.join(plan_dir, 'sweep.json'), 'w') as f:
        json.dump({
            'sweep_name': plan['sweep_name'],
            'source': sweep_path,
            'base': plan['base'],
            'varying_keys': plan['varying_keys'],
            'runs': [{'name': e['name'], 'overrides': e['overrides'], 'errors': e['errors']}
                     for e in plan['runs']],
        }, f, indent=2, sort_keys=True, default=str)

    if not args.report_only:
        pending = []
        for entry in runnable:
            if args.resume and already_finished(entry['folder']):
                print(f"  resume: {entry['name']} already finished, skipping")
                continue
            entry['base'] = plan['base']
            entry['config_path'] = write_run_config(entry, plan_dir)
            pending.append(entry)

        if pending:
            candle_cache = None
            if not args.no_candle_cache:
                candle_cache = os.path.join(plan['output_root'], '_candle_cache')
                warm_candle_cache(plan, candle_cache)

            workers = args.workers or max(1, (os.cpu_count() or 2) - 1)
            workers = max(1, min(workers, len(pending)))
            print(f"\nRunning {len(pending)} simulation(s), {workers} at a time...")

            completed = 0
            started = time.time()
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(execute_run, entry, candle_cache): entry for entry in pending}
                try:
                    for future in as_completed(futures):
                        name, returncode, seconds = future.result()
                        completed += 1
                        state = 'ok' if returncode == 0 else f'FAILED (exit {returncode})'
                        print(f"  [{completed}/{len(pending)}] {name}: {state} in {seconds:.0f}s")
                except KeyboardInterrupt:
                    print("\nInterrupted - stopping running simulations...")
                    stop_active_processes()
                    raise
            print(f"All runs finished in {time.time() - started:.0f}s")
        else:
            print("Nothing to run.")

    rows = build_report(plan)
    report_path = write_report(plan, rows)
    print_report(plan, rows)
    print(f"\nFull results: {report_path}")
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        stop_active_processes()
        sys.exit(130)
