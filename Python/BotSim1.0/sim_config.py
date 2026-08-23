"""Typed, injectable configuration for BotSim.

The simulator modules read their settings as module-level globals pulled in with
`from config import *`.  That form binds a *copy* of every name at import time, so
a SimConfig has to be pushed into the `config` module before any simulator module
is imported.  `SimConfig.apply()` enforces that ordering rather than letting a run
silently use stale values.

config.py stays the human-editable source of defaults.  The normal flow is:

    cfg = SimConfig.from_config_module()      # start from config.py
    cfg = cfg.with_overrides({'MIN_PENDING_CANDLES': 20})
    errors = cfg.validate()
    cfg.apply()                               # before importing simulation, etc.

The dataclass field defaults below mirror config.py so a SimConfig can also be
built standalone.  Run `python sim_config.py --check` to confirm the two haven't
drifted apart.
"""

from __future__ import annotations

import json
import os
import sys
import types
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime

# Simulator modules that do `from config import *`.  See the note above.
SIM_MODULES = (
    'simulation', 'sim_entries', 'sim_exits',
    'initialization', 'position_size', 'reporting',
)

DATE_FIELDS = ('starting_date', 'ending_date')
PATH_FIELDS = ('candles_file_default', 'instances_folder_default', 'output_folder_default')

# Env var used to hand a config to a fresh interpreter (see config.py's tail and run_sim.py).
OVERRIDE_ENV_VAR = 'BOTSIM_CONFIG_JSON'


def _parse_date(value):
    """Accept a datetime, 'YYYY-MM-DD', or 'YYYY-MM-DD HH:MM:SS'."""
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Could not parse date: {value!r}")


@dataclass
class SimConfig:
    """Every setting the simulator reads, in one injectable object."""

    # --- Bankroll and early termination ---
    starting_bankroll: float = 10000.0
    USE_LOW_BANKROLL_TERMINATION: bool = True
    LOW_BANKROLL_THRESHOLD: float = 0.6
    USE_LOW_VOLUME_TERMINATION: bool = True
    LOW_VOLUME_THRESHOLD: int = 4

    # --- Position sizing ---
    position_size_method: int = 3       # 1 = fixed qty, 2 = fixed dollars, 3 = % of bankroll
    position_size_qty: float = 0.2
    position_size_amount: float = 50
    position_size_percent: float = 70
    MAX_LEVERAGE: float = 3.0
    USE_POSITION_DESCALING: bool = False
    POSITION_DESCALING_FACTOR: float = 0.5

    # --- Date range and fees ---
    starting_date: datetime = datetime(2022, 1, 1)
    ending_date: datetime = datetime(2024, 6, 30)
    fee_rate: float = 0.0003

    # --- Entries ---
    ALLOWED_SITUATIONS: list = field(default_factory=lambda: ['1v1'])
    tt_stf_any_inside_activation: bool = False
    tt_stf_same_minute: bool = False
    tt_stf_within_x_candles: bool = False
    tt_stf_within_x: int = 1
    tt_stf_within_x_minutes: bool = False
    tt_stf_within_minutes: int = 60
    FULL_INSTANCE_SET_FLAGS: list = field(default_factory=lambda: [
        'tt_stf_any_inside_activation',
        'tt_stf_within_x_candles',
        'tt_stf_within_x_minutes',
    ])
    USE_MIN_PENDING_AGE: bool = False
    MIN_PENDING_AGE: float = 12
    USE_MAX_PENDING_AGE: bool = False
    MAX_PENDING_AGE: float = 72
    USE_MIN_PENDING_CANDLES: bool = True
    MIN_PENDING_CANDLES: float = 10
    USE_MAX_PENDING_CANDLES: bool = True
    MAX_PENDING_CANDLES: float = 48
    DD_on_fib0_5: bool = False
    DD_on_fib0_0: bool = False
    DD_on_fib_0_5: bool = False
    DD_on_fib_1_0: bool = False
    AVOID_GROUPS: bool = False

    # --- Exits ---
    USE_STATIC_TIME_CAPIT: bool = False
    STATIC_TIME_CAPIT_DURATION: float = 60      # hours
    SL_on_fib0_5: bool = False
    SL_on_fib0_0: bool = False
    SL_on_fib_0_5: bool = False
    SL_on_fib_1_0: bool = False
    use_mpd_percent: bool = False
    mpd_percent: float = 3.6
    use_ampd_percent: bool = False
    ampd_percent_base: float = 3
    ampd_percent_max: float = 8
    ampd_use_pending_time: bool = True
    ampd_use_trigger_time: bool = True
    ampd_pending_weight: float = 50             # 1-100; trigger gets the remainder
    ampd_pending_time_high: float = 100         # days
    ampd_trigger_time_high: float = 60          # minutes

    # --- Debug / logging ---
    debug_show_mpd_output: bool = False
    debug_show_ampd_output: bool = False
    CREATE_TRADES_BY_MONTH: bool = False
    CREATE_ANALYSIS_ALL: bool = False

    # --- Paths ---
    prompt_for_paths: bool = False
    candles_file_default: str = os.path.join(
        '..', '..', 'Data', 'SOLUSDT-BINANCE', 'Candles', 'SOLUSDT_binance_1m.csv')
    instances_folder_default: str = os.path.join(
        '..', '..', 'Data', 'SOLUSDT-BINANCE', 'Instances', '1v1', 'Processed', 'SubSet')
    output_folder_default: str = os.path.join(
        '..', '..', 'Data', 'SOLUSDT-BINANCE', 'Simulations', 'NewFolderHere')

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------
    @classmethod
    def field_names(cls):
        return tuple(f.name for f in fields(cls))

    @classmethod
    def from_config_module(cls):
        """Build a config from the current values in config.py."""
        import config
        values = {}
        for name in cls.field_names():
            if hasattr(config, name):
                values[name] = getattr(config, name)
        return cls(**values)

    @classmethod
    def from_dict(cls, data):
        """Build a config from a plain dict (e.g. parsed JSON). Unknown keys raise."""
        known = set(cls.field_names())
        unknown = sorted(set(data) - known)
        if unknown:
            raise KeyError(f"Unknown config setting(s): {', '.join(unknown)}")
        values = dict(data)
        for name in DATE_FIELDS:
            if name in values:
                values[name] = _parse_date(values[name])
        return cls(**values)

    @classmethod
    def from_json_file(cls, path):
        with open(path, 'r') as f:
            return cls.from_dict(json.load(f))

    def with_overrides(self, overrides):
        """Return a copy with `overrides` applied. Unknown keys raise."""
        if not overrides:
            return replace(self)
        known = set(self.field_names())
        unknown = sorted(set(overrides) - known)
        if unknown:
            raise KeyError(f"Unknown config setting(s): {', '.join(unknown)}")
        clean = dict(overrides)
        for name in DATE_FIELDS:
            if name in clean:
                clean[name] = _parse_date(clean[name])
        return replace(self, **clean)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    def to_dict(self):
        """JSON-safe dict: datetimes become 'YYYY-MM-DD HH:MM:SS' strings."""
        data = asdict(self)
        for name in DATE_FIELDS:
            value = data.get(name)
            if isinstance(value, datetime):
                data[name] = value.strftime('%Y-%m-%d %H:%M:%S')
        return data

    def to_json_file(self, path):
        with open(path, 'w') as f:
            json.dump(self.to_dict(), f, indent=2, sort_keys=True)

    # ------------------------------------------------------------------
    # Applying to the config module
    # ------------------------------------------------------------------
    def apply(self, strict=True):
        """Push these settings into the `config` module.

        Must happen before any simulator module is imported, since those bind
        their globals with `from config import *` at import time.  With
        strict=True (the default) this raises instead of applying too late.
        """
        already = [name for name in SIM_MODULES if name in sys.modules]
        if already and strict:
            raise RuntimeError(
                "SimConfig.apply() was called after these simulator modules were "
                f"already imported: {', '.join(already)}. They bound their settings "
                "with `from config import *` at import time, so the overrides would "
                "be ignored. Apply the config first, then import."
            )
        import config
        for name in self.field_names():
            setattr(config, name, getattr(self, name))
        return self

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self):
        """Return a list of errors that make this config unrunnable (empty if fine)."""
        errors = []

        if self.position_size_method not in (1, 2, 3):
            errors.append(f"position_size_method must be 1, 2 or 3 (got {self.position_size_method})")

        if self.position_size_method == 3:
            if self.position_size_percent <= 0:
                errors.append("position_size_percent must be > 0 when position_size_method = 3")
            elif self.MAX_LEVERAGE is not None and self.MAX_LEVERAGE > 0:
                # simulation.py derives the position cap from these two; if it floors to
                # zero the run can never open a trade.
                max_positions = int((self.MAX_LEVERAGE * 100) / self.position_size_percent)
                if max_positions < 1:
                    errors.append(
                        f"MAX_LEVERAGE={self.MAX_LEVERAGE} with position_size_percent="
                        f"{self.position_size_percent} allows 0 open positions")
        elif self.position_size_method == 1 and self.position_size_qty <= 0:
            errors.append("position_size_qty must be > 0 when position_size_method = 1")
        elif self.position_size_method == 2 and self.position_size_amount <= 0:
            errors.append("position_size_amount must be > 0 when position_size_method = 2")

        if self.starting_bankroll <= 0:
            errors.append("starting_bankroll must be > 0")
        if self.fee_rate < 0:
            errors.append("fee_rate must be >= 0")
        if not 0 < self.LOW_BANKROLL_THRESHOLD <= 1:
            errors.append("LOW_BANKROLL_THRESHOLD must be in (0, 1]")
        if not 0 <= self.POSITION_DESCALING_FACTOR <= 1:
            errors.append("POSITION_DESCALING_FACTOR must be in [0, 1]")

        start = _parse_date(self.starting_date)
        end = _parse_date(self.ending_date)
        if start is None or end is None:
            errors.append("starting_date and ending_date are both required")
        elif start >= end:
            errors.append(f"starting_date ({start:%Y-%m-%d}) must be before ending_date ({end:%Y-%m-%d})")

        if not self.ALLOWED_SITUATIONS:
            errors.append("ALLOWED_SITUATIONS is empty, so no trade can ever be entered")

        # Windows that can never be satisfied would burn a full run for zero trades.
        if self.USE_MIN_PENDING_AGE and self.USE_MAX_PENDING_AGE and self.MIN_PENDING_AGE > self.MAX_PENDING_AGE:
            errors.append(
                f"MIN_PENDING_AGE ({self.MIN_PENDING_AGE}) > MAX_PENDING_AGE ({self.MAX_PENDING_AGE})")
        if (self.USE_MIN_PENDING_CANDLES and self.USE_MAX_PENDING_CANDLES
                and self.MIN_PENDING_CANDLES > self.MAX_PENDING_CANDLES):
            errors.append(
                f"MIN_PENDING_CANDLES ({self.MIN_PENDING_CANDLES}) > "
                f"MAX_PENDING_CANDLES ({self.MAX_PENDING_CANDLES})")

        if self.use_ampd_percent:
            if self.ampd_percent_base > self.ampd_percent_max:
                errors.append(
                    f"ampd_percent_base ({self.ampd_percent_base}) > "
                    f"ampd_percent_max ({self.ampd_percent_max})")
            if not 0 <= self.ampd_pending_weight <= 100:
                errors.append("ampd_pending_weight must be in [0, 100]")
            if self.ampd_use_pending_time and self.ampd_pending_time_high <= 0:
                errors.append("ampd_pending_time_high must be > 0 when ampd_use_pending_time is on")
            if self.ampd_use_trigger_time and self.ampd_trigger_time_high <= 0:
                errors.append("ampd_trigger_time_high must be > 0 when ampd_use_trigger_time is on")

        if self.USE_STATIC_TIME_CAPIT and self.STATIC_TIME_CAPIT_DURATION <= 0:
            errors.append("STATIC_TIME_CAPIT_DURATION must be > 0 when USE_STATIC_TIME_CAPIT is on")

        return errors

    def warnings(self):
        """Return a list of settings that are legal but won't do what they look like."""
        notes = []

        # sim_exits.py returns early from both drawdown checks unless method 3 is in use.
        if self.position_size_method != 3:
            if self.use_mpd_percent:
                notes.append("use_mpd_percent has no effect unless position_size_method = 3")
            if self.use_ampd_percent:
                notes.append("use_ampd_percent has no effect unless position_size_method = 3")
            if self.USE_POSITION_DESCALING:
                notes.append("USE_POSITION_DESCALING has no effect unless position_size_method = 3")

        if self.use_ampd_percent and self.use_mpd_percent:
            # sim_exits checks AMPD first and only falls through to MPD if it didn't fire.
            notes.append("use_ampd_percent and use_mpd_percent are both on; AMPD is checked first")

        if self.use_ampd_percent and not (self.ampd_use_pending_time or self.ampd_use_trigger_time):
            notes.append("AMPD is on but neither pending nor trigger time is used, so it "
                         "always uses ampd_percent_base")

        if self.tt_stf_any_inside_activation or self.tt_stf_within_x_candles or self.tt_stf_within_x_minutes:
            notes.append("A trigger-trade flag requiring the full instance set is on; "
                         "instance loading ignores the date range and will be slower")

        return notes

    # ------------------------------------------------------------------
    def summary_line(self):
        """One-line description of the date range and the headline settings."""
        start = _parse_date(self.starting_date)
        end = _parse_date(self.ending_date)
        return (f"{start:%Y-%m-%d}..{end:%Y-%m-%d} | situations={','.join(self.ALLOWED_SITUATIONS)} | "
                f"size_method={self.position_size_method} | bankroll={self.starting_bankroll:,.0f}")


def check_drift():
    """Compare the dataclass defaults against config.py; return a list of differences."""
    import config
    differences = []
    defaults = SimConfig()
    for name in SimConfig.field_names():
        if not hasattr(config, name):
            differences.append(f"{name}: missing from config.py")
            continue
        mine = getattr(defaults, name)
        theirs = getattr(config, name)
        if mine != theirs:
            differences.append(f"{name}: SimConfig default {mine!r} != config.py {theirs!r}")
    known = set(SimConfig.field_names())
    extra = [
        name for name, value in vars(config).items()
        if not name.startswith('_')
        and name not in known
        and not isinstance(value, types.ModuleType)
        and not callable(value)
    ]
    for name in sorted(extra):
        differences.append(f"{name}: present in config.py but not in SimConfig")
    return differences


if __name__ == '__main__':
    if '--check' in sys.argv:
        drift = check_drift()
        if drift:
            print("SimConfig and config.py have drifted apart:")
            for line in drift:
                print(f"  - {line}")
            sys.exit(1)
        print("SimConfig defaults match config.py.")
    else:
        print(json.dumps(SimConfig.from_config_module().to_dict(), indent=2, sort_keys=True))
