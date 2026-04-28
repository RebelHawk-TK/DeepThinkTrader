"""Tunable parameter registry for adaptive retraining (roadmap idea #2).

Phase 1 scope: define which params are tunable, their valid ranges, and provide
a JSON-backed store the bot reads at startup. No call sites are migrated yet —
existing code keeps reading Config.X attributes. Phase 2 will add a recommender,
Phase 3 will close the auto-tune loop.

Why a separate registry rather than just env vars: each tunable needs a valid
range so a future auto-tuner can't push Kelly to 1000 or sector cap to 5%.
The bounds are part of the contract.

Edit tunable_params.json directly to override defaults. Bot picks up new
values on next restart (no live reload yet — Phase 3 work).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParamSpec:
    name: str
    default: float
    low: float
    high: float
    description: str
    is_int: bool = False


# Tunable parameters. Names match snake_case form of Config attribute.
# Defaults reflect current AGGRESSIVE / general values in config.py — change
# the JSON file to override, do NOT change defaults here unless the safe value
# itself is moving.
_SPECS: tuple[ParamSpec, ...] = (
    ParamSpec("kelly_safety_multiplier", 0.5, 0.1, 1.0,
              "Multiplier on raw Kelly fraction. Lower = more conservative sizing."),
    ParamSpec("max_risk_per_trade", 0.03, 0.005, 0.05,
              "Fraction of equity risked per trade (mode: aggressive=0.03)."),
    ParamSpec("max_daily_loss", 0.08, 0.02, 0.10,
              "Daily loss circuit breaker as fraction of equity."),
    ParamSpec("min_conviction", 6.0, 5.0, 9.5,
              "Minimum conviction score (out of 10) to enter a trade."),
    ParamSpec("min_reward_risk_ratio", 1.5, 1.0, 4.0,
              "Required reward:risk ratio to enter."),
    ParamSpec("max_position_pct", 0.15, 0.02, 0.25,
              "Cap on single position as fraction of equity."),
    ParamSpec("max_open_positions", 15.0, 3.0, 25.0,
              "Cap on concurrent open positions.", is_int=True),
    ParamSpec("max_sector_exposure_pct", 0.25, 0.10, 0.50,
              "Cap on aggregate exposure to one sector."),
    ParamSpec("max_drawdown_halt_pct", 0.08, 0.05, 0.15,
              "Drawdown threshold that halts new trading."),
    ParamSpec("trailing_stop_activation_pct", 2.0, 1.0, 5.0,
              "Profit % at which trailing stop activates."),
    ParamSpec("trailing_stop_distance_pct", 1.5, 0.5, 5.0,
              "Distance from peak that trailing stop sits."),
)

_SPECS_BY_NAME: dict[str, ParamSpec] = {s.name: s for s in _SPECS}

_PARAMS_PATH = Path(__file__).resolve().parent.parent / "tunable_params.json"


class TunableParams:
    """JSON-backed parameter store. Thread-safe for read/write.

    Not meant to be a hot-path config replacement — values are loaded once
    at startup. Phase 3 may add live reload via mtime polling.
    """

    def __init__(self, path: Path = _PARAMS_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._values: dict[str, float] = {s.name: s.default for s in _SPECS}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._write_atomic(self._values)
            logger.info(f"tunable_params: created {self._path} with defaults")
            return
        try:
            with open(self._path) as f:
                stored = json.load(f)
        except Exception as e:
            logger.warning(f"tunable_params: failed to read {self._path} — using defaults ({e})")
            return

        applied = 0
        for name, value in stored.items():
            spec = _SPECS_BY_NAME.get(name)
            if spec is None:
                logger.warning(f"tunable_params: ignoring unknown key {name!r}")
                continue
            try:
                v = float(value)
            except (TypeError, ValueError):
                logger.warning(f"tunable_params: {name}={value!r} not numeric — keeping default")
                continue
            if not (spec.low <= v <= spec.high):
                logger.warning(
                    f"tunable_params: {name}={v} out of range [{spec.low}, {spec.high}] — clamping"
                )
                v = max(spec.low, min(spec.high, v))
            self._values[name] = int(v) if spec.is_int else v
            applied += 1
        if applied:
            logger.info(f"tunable_params: loaded {applied} value(s) from {self._path}")

    def _write_atomic(self, values: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(values, f, indent=2, sort_keys=True)
        os.replace(tmp, self._path)

    def get(self, name: str) -> float:
        with self._lock:
            return self._values[name]

    def get_all(self) -> dict[str, float]:
        with self._lock:
            return dict(self._values)

    def set(self, name: str, value: float) -> float:
        spec = _SPECS_BY_NAME.get(name)
        if spec is None:
            raise KeyError(f"unknown tunable param: {name!r}")
        v = float(value)
        if not (spec.low <= v <= spec.high):
            raise ValueError(f"{name}={v} out of range [{spec.low}, {spec.high}]")
        v = int(v) if spec.is_int else v
        with self._lock:
            self._values[name] = v
            self._write_atomic(self._values)
        logger.info(f"tunable_params: set {name}={v}")
        return v

    def reset(self, name: str) -> float:
        spec = _SPECS_BY_NAME[name]
        return self.set(name, spec.default)

    def specs(self) -> tuple[ParamSpec, ...]:
        return _SPECS


_singleton: TunableParams | None = None
_singleton_lock = threading.Lock()


def get_tunable_params() -> TunableParams:
    """Module-level singleton accessor."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = TunableParams()
    return _singleton
