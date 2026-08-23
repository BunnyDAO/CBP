"""Run one simulation without the interactive menu.

main.py is still the interactive front end.  This is the scriptable one: it takes
a config (config.py plus any overrides you pass), validates it, and runs a single
new simulation into an output folder.  sweep.py uses it to run many configs in
parallel, but it's just as usable on its own:

    python run_sim.py --output ../../Data/SOLUSDT-BINANCE/Simulations/test1
    python run_sim.py --output ...test2 --set MIN_PENDING_CANDLES=20 --set position_size_percent=50
    python run_sim.py --output ...test3 --config my_overrides.json --start 2022-01-01 --end 2023-01-01

Relative paths given on the command line are resolved against the directory you
ran from; relative paths coming from config.py resolve against this script's
folder, the same way they do when you run main.py from here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pickle
import shutil
import sys
import time
import traceback
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Files a run writes into its output folder.  The simulator appends to these, so a
# folder that already has them would produce a mix of two runs.
RUN_OUTPUT_PREFIXES = ('analysis_', 'trades_', 'closed_positions', 'open_positions', 'TERMINATED')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='Run a single BotSim simulation non-interactively.')
    parser.add_argument('-o', '--output', help='Output folder for this run (created if missing).')
    parser.add_argument('-c', '--config', help='JSON file of config overrides (see sim_config.py).')
    parser.add_argument('--set', action='append', default=[], metavar='KEY=VALUE',
                        help='Override one setting; repeatable. Values are parsed as JSON, '
                             'falling back to a plain string.')
    parser.add_argument('--candles', help='Path to the 1m candles CSV.')
    parser.add_argument('--instances', help='Folder of processed instance CSVs.')
    parser.add_argument('--start', help='Start date (YYYY-MM-DD or YYYYMMDD).')
    parser.add_argument('--end', help='End date (YYYY-MM-DD or YYYYMMDD).')
    parser.add_argument('--fresh', action='store_true',
                        help='Delete previous run output in the output folder before starting.')
    parser.add_argument('--candle-cache', metavar='DIR',
                        help='Cache parsed candles here so repeated runs skip the CSV parse. '
                             'Worth using for sweeps.')
    parser.add_argument('--dry-run', action='store_true',
                        help='Validate the config and print it, but do not run.')
    return parser.parse_args(argv)


def parse_set_value(text):
    """Parse a --set value: JSON first (so 3, true, ["1v1"] work), else a plain string."""
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return text


def collect_overrides(args):
    """Merge --config, --set, and the path/date flags into one override dict."""
    overrides = {}

    if args.config:
        with open(args.config, 'r') as f:
            overrides.update(json.load(f))

    for item in args.set:
        if '=' not in item:
            raise ValueError(f"--set expects KEY=VALUE, got {item!r}")
        key, _, value = item.partition('=')
        overrides[key.strip()] = parse_set_value(value.strip())

    # The explicit flags win over anything in --config / --set.
    if args.candles:
        overrides['candles_file_default'] = args.candles
    if args.instances:
        overrides['instances_folder_default'] = args.instances
    if args.output:
        overrides['output_folder_default'] = args.output
    if args.start:
        overrides['starting_date'] = args.start
    if args.end:
        overrides['ending_date'] = args.end

    return overrides


def absolutize_cli_paths(args):
    """Make paths from the command line absolute before we chdir to the script folder."""
    for name in ('output', 'config', 'candles', 'instances', 'candle_cache'):
        value = getattr(args, name, None)
        if value:
            setattr(args, name, os.path.abspath(value))
    return args


def existing_run_output(folder):
    """Return the names of files in `folder` that look like output from a previous run."""
    if not os.path.isdir(folder):
        return []
    return sorted(
        name for name in os.listdir(folder)
        if name.startswith(RUN_OUTPUT_PREFIXES)
    )


def clear_run_output(folder):
    """Delete previous run output (including the summary CSV) from `folder`."""
    if not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if name.startswith(RUN_OUTPUT_PREFIXES) or name.endswith('.csv') or name == 'run_meta.json':
            if os.path.isfile(path):
                os.remove(path)
            elif os.path.isdir(path):
                shutil.rmtree(path)


def candle_cache_path(cache_dir, candles_file, start_date, end_date):
    """A cache key covering the file's identity and the slice we asked for."""
    stat = os.stat(candles_file)
    key = '|'.join([
        os.path.abspath(candles_file),
        str(int(stat.st_mtime)),
        str(stat.st_size),
        start_date.isoformat(),
        end_date.isoformat(),
    ])
    digest = hashlib.md5(key.encode('utf-8')).hexdigest()[:16]
    return os.path.join(cache_dir, f'candles_{digest}.pickle')


def load_candles_cached(load_candles, candles_file, start_date, end_date, cache_dir):
    """load_candles, but memoised on disk. Falls back to a normal load on any cache error."""
    if not cache_dir:
        return load_candles(candles_file, start_date, end_date)

    try:
        os.makedirs(cache_dir, exist_ok=True)
        path = candle_cache_path(cache_dir, candles_file, start_date, end_date)
    except OSError as exc:
        print(f"Warning: candle cache unavailable ({exc}); parsing the CSV instead.")
        return load_candles(candles_file, start_date, end_date)

    if os.path.exists(path):
        try:
            with open(path, 'rb') as f:
                candles = pickle.load(f)
            print(f"Loaded {len(candles)} candles from cache.")
            return candles
        except Exception as exc:
            print(f"Warning: could not read candle cache {path} ({exc}); reparsing.")

    candles = load_candles(candles_file, start_date, end_date)

    # Write via a temp file so parallel runs never read a half-written cache.
    try:
        temp_path = f'{path}.{os.getpid()}.tmp'
        with open(temp_path, 'wb') as f:
            pickle.dump(candles, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(temp_path, path)
    except Exception as exc:
        print(f"Warning: could not write candle cache ({exc}).")

    return candles


def build_config(args):
    """Resolve config.py + overrides into a validated SimConfig."""
    from sim_config import SimConfig

    base = SimConfig.from_config_module()
    try:
        cfg = base.with_overrides(collect_overrides(args))
    except (KeyError, ValueError, OSError) as exc:
        print(f"Could not build the config: {exc}")
        return None

    errors = cfg.validate()
    if errors:
        print("Config is not runnable:")
        for error in errors:
            print(f"  - {error}")
        return None

    for note in cfg.warnings():
        print(f"Note: {note}")

    return cfg


def run(cfg, candle_cache=None):
    """Apply the config, import the simulator, and run one new simulation.

    Returns the run_meta dict describing what happened.
    """
    # Everything below imports the simulator, which binds its settings at import
    # time - so the config has to go in first.
    cfg.apply()

    from initialization import load_candles, load_instances
    from simulation import run_simulation

    output_folder = cfg.output_folder_default
    starting_date = cfg.starting_date.replace(hour=0, minute=0, second=0, microsecond=0)
    ending_date = cfg.ending_date.replace(hour=23, minute=59, second=59, microsecond=0)

    started_at = time.time()

    print(f"Loading instances from {cfg.instances_folder_default}")
    instances_by_minute = load_instances(cfg.instances_folder_default, starting_date, ending_date)

    print(f"Loading candles from {cfg.candles_file_default}")
    candles = load_candles_cached(
        load_candles, cfg.candles_file_default, starting_date, ending_date, candle_cache)

    if not candles:
        raise RuntimeError(
            f"No candles loaded from {cfg.candles_file_default} for "
            f"{starting_date:%Y-%m-%d}..{ending_date:%Y-%m-%d}")

    run_simulation(
        instances_by_minute, candles, starting_date, ending_date,
        output_folder, cfg.fee_rate,
        [],   # trades_all
        [],   # trade_log
        [],   # open_positions
        initial_cash_on_hand=cfg.starting_bankroll,
        initial_total_long=0.0,
        initial_long_basis=0.0,
        initial_total_short=0.0,
        initial_short_basis=0.0,
    )

    elapsed = time.time() - started_at

    # run_simulation returns early (without a summary report) when an early
    # termination rule fires, and leaves a marker file behind.
    terminated = [
        name for name in os.listdir(output_folder)
        if name.startswith('TERMINATED')
    ]

    return {
        'status': 'terminated' if terminated else 'completed',
        'termination_reason': terminated[0] if terminated else None,
        'elapsed_seconds': round(elapsed, 1),
        'instances_loaded': sum(len(v) for v in instances_by_minute.values()),
        'candles_loaded': len(candles),
        'config': cfg.to_dict(),
    }


def main(argv=None):
    args = absolutize_cli_paths(parse_args(argv))

    # config.py's default paths are relative to this folder, exactly as main.py
    # assumes.  CLI paths were made absolute above, so this is safe.
    os.chdir(SCRIPT_DIR)

    cfg = build_config(args)
    if cfg is None:
        return 1

    print(f"Config: {cfg.summary_line()}")
    print(f"Output: {cfg.output_folder_default}")

    if args.dry_run:
        print(json.dumps(cfg.to_dict(), indent=2, sort_keys=True))
        return 0

    output_folder = cfg.output_folder_default
    os.makedirs(output_folder, exist_ok=True)

    stale = existing_run_output(output_folder)
    if stale:
        if args.fresh:
            clear_run_output(output_folder)
        else:
            print(f"Output folder already holds results from a previous run "
                  f"({', '.join(stale[:4])}{'...' if len(stale) > 4 else ''}).")
            print("The simulator appends to these files, so the results would be mixed together.")
            print("Pass --fresh to clear them, or point --output at a new folder.")
            return 1

    meta_path = os.path.join(output_folder, 'run_meta.json')
    try:
        meta = run(cfg, candle_cache=args.candle_cache)
    except Exception as exc:
        traceback.print_exc()
        with open(meta_path, 'w') as f:
            json.dump({
                'status': 'failed',
                'error': f'{type(exc).__name__}: {exc}',
                'config': cfg.to_dict(),
            }, f, indent=2, sort_keys=True)
        return 2

    meta['finished_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(meta_path, 'w') as f:
        json.dump(meta, f, indent=2, sort_keys=True)

    print(f"Run {meta['status']} in {meta['elapsed_seconds']}s -> {output_folder}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
