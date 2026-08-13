"""Dated configuration loading, with a hard refusal on incomplete values.

Two distinct failure modes, deliberately different in kind:

  ConfigIncomplete (raised)   a required value is null or still marked
                              NEEDS_VALUE. The engine REFUSES to compute.
                              It does not warn, it does not substitute a
                              default, and it does not compute a partial
                              answer. Every missing path is listed at once so
                              the file can be filled in one pass.

  StalenessWarning (returned) every required value is present but the config
                              has not been reconciled against its sources
                              within staleness_warn_days. The number is
                              usable; its age is reported alongside the
                              result rather than hidden.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_DIR = os.path.join(REPO_ROOT, "config")
CONTRACTS_DIR = os.path.join(REPO_ROOT, "contracts")

MISSING = object()
NEEDS_VALUE_MARKERS = ("NEEDS_VALUE", "_NEEDS_VALUE")


class ConfigIncomplete(Exception):
    """A required configuration value is absent. The engine will not guess."""

    def __init__(self, missing, context=""):
        self.missing = list(missing)
        self.context = context
        head = f"refusing to compute{(' ' + context) if context else ''}: "
        body = f"{len(self.missing)} required value(s) are null or NEEDS_VALUE"
        lines = "\n".join(f"    - {m}" for m in self.missing)
        super().__init__(f"{head}{body}\n{lines}\n"
                         "  Fill these in and re-run. No defaults will be substituted.")


@dataclass
class StalenessWarning:
    config_kind: str
    verified_on: Optional[str]
    age_days: Optional[int]
    limit_days: int

    def __str__(self):
        if self.verified_on is None:
            return f"{self.config_kind}: never verified against its sources"
        return (f"{self.config_kind}: last verified {self.verified_on} "
                f"({self.age_days} days ago, limit {self.limit_days})")


@dataclass
class Config:
    """The three dated files, loaded together and queried by dotted path."""

    grading: dict = field(default_factory=dict)
    fees: dict = field(default_factory=dict)
    assumptions: dict = field(default_factory=dict)
    crossover_rules: dict = field(default_factory=dict)
    today: Optional[_dt.date] = None

    _ROOTS = ("grading", "fees", "assumptions", "crossover_rules")

    @classmethod
    def load(cls, config_dir=CONFIG_DIR, contracts_dir=CONTRACTS_DIR, today=None):
        def _yaml(name):
            path = os.path.join(config_dir, name)
            if not os.path.exists(path):
                return {}
            with open(path, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}

        def _json(name):
            path = os.path.join(contracts_dir, name)
            if not os.path.exists(path):
                return {}
            with open(path, encoding="utf-8") as f:
                return json.load(f)

        return cls(grading=_yaml("grading.yaml"), fees=_yaml("fees.yaml"),
                   crossover_rules=_yaml("crossover_rules.yaml"),
                   assumptions=_json("assumptions.json"),
                   today=today or _dt.date.today())

    # -- lookup ----------------------------------------------------------

    def get(self, path: str, default=MISSING) -> Any:
        """Resolve `root.a.b.c`. Returns MISSING when absent or null."""
        parts = path.split(".")
        root = parts[0]
        if root not in self._ROOTS:
            raise KeyError(f"unknown config root {root!r}; expected one of {self._ROOTS}")
        node = getattr(self, root)
        for p in parts[1:]:
            if isinstance(node, list):
                try:
                    node = node[int(p)]
                    continue
                except (ValueError, IndexError):
                    return default
            if not isinstance(node, dict) or p not in node:
                return default
            node = node[p]
        if node is None:
            return default
        if isinstance(node, str) and node in NEEDS_VALUE_MARKERS:
            return default
        return node

    def missing(self, paths) -> list:
        """Which of `paths` are null / NEEDS_VALUE. Order preserved."""
        return [p for p in paths if self.get(p) is MISSING]

    def require(self, paths, context="") -> None:
        """Refuse to proceed unless every path resolves to a real value."""
        gaps = self.missing(paths)
        if gaps:
            raise ConfigIncomplete(gaps, context)

    def decimal(self, path: str) -> Decimal:
        v = self.get(path)
        if v is MISSING:
            raise ConfigIncomplete([path])
        if isinstance(v, float):
            # YAML floats are binary; go through str so 0.1325 stays 0.1325.
            return Decimal(str(v))
        return Decimal(str(v))

    # -- staleness -------------------------------------------------------

    def staleness(self, which: str) -> Optional[StalenessWarning]:
        node = getattr(self, which, {}) or {}
        meta = node.get("meta") or {}
        limit = int(meta.get("staleness_warn_days") or 60)
        verified = meta.get("verified_on")
        if not verified:
            return StalenessWarning(which, None, None, limit)
        try:
            d = _dt.date.fromisoformat(str(verified))
        except ValueError:
            return StalenessWarning(which, str(verified), None, limit)
        age = (self.today - d).days
        if age > limit:
            return StalenessWarning(which, str(verified), age, limit)
        return None

    def staleness_warnings(self) -> list:
        out = []
        for which in self._ROOTS:
            w = self.staleness(which)
            if w is not None:
                out.append(w)
        return out


def business_days_to_calendar(business_days) -> int:
    """Deterministic 5-day week conversion, rounded up.

    Not a calendar: it does not know about holidays. It is a stated, testable
    convention so that annualised ROI is reproducible.
    """
    bd = Decimal(str(business_days))
    if bd < 0:
        raise ValueError("business days cannot be negative")
    weeks = bd / Decimal(5)
    calendar = weeks * Decimal(7)
    return int(calendar.to_integral_value(rounding="ROUND_CEILING"))
