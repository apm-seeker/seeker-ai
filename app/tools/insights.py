"""Statistical helpers and anomaly thresholds used by tool-response compaction.

Surfaces signal (top offenders, outliers, trend direction, anomaly flags)
inside the JSON the LLM sees, so the agent can reason about *why* the numbers
matter instead of re-deriving them from raw arrays.

Thresholds are explicit constants so the system prompt can refer to the same
vocabulary ("HIGH error", "SLOW p95") that appears in the insights blocks.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

# ---- Anomaly thresholds (also referenced from the system prompt) -----------

ERROR_RATE_HIGH = 0.05
ERROR_RATE_CRITICAL = 0.20

LATENCY_SLOW_MS = 1000
LATENCY_CRITICAL_MS = 3000

P95_AVG_RATIO_HIGH = 3.0

HEAP_PRESSURE_HIGH = 0.85
HEAP_PRESSURE_CRITICAL = 0.95


# ---- Generic stat helpers --------------------------------------------------


def percentile(values: Sequence[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    s = sorted(values)
    if pct <= 0:
        return float(s[0])
    if pct >= 100:
        return float(s[-1])
    rank = (pct / 100.0) * (len(s) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return float(s[lo])
    frac = rank - lo
    return float(s[lo] + (s[hi] - s[lo]) * frac)


def describe(values: Sequence[float]) -> dict[str, Any] | None:
    if not values:
        return None
    n = len(values)
    return {
        "count": n,
        "min": round(float(min(values)), 3),
        "max": round(float(max(values)), 3),
        "avg": round(sum(values) / n, 3),
        "p50": round(percentile(values, 50) or 0.0, 3),
        "p95": round(percentile(values, 95) or 0.0, 3),
        "p99": round(percentile(values, 99) or 0.0, 3),
    }


def trend(values: Sequence[float]) -> str | None:
    """Compare last-third mean vs first-third mean.
    Returns 'rising' / 'falling' / 'stable' / None (series too short).
    """
    if len(values) < 6:
        return None
    third = max(1, len(values) // 3)
    head = list(values[:third])
    tail = list(values[-third:])
    head_avg = sum(head) / len(head)
    tail_avg = sum(tail) / len(tail)
    if head_avg == 0:
        if tail_avg == 0:
            return "stable"
        return "rising" if tail_avg > 0 else "falling"
    delta_ratio = (tail_avg - head_avg) / abs(head_avg)
    if delta_ratio > 0.15:
        return "rising"
    if delta_ratio < -0.15:
        return "falling"
    return "stable"


def topn(
    items: Iterable[dict[str, Any]],
    key: str,
    n: int = 5,
    *,
    reverse: bool = True,
    keep: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    sorted_items = sorted(
        items, key=lambda d: _as_number(d.get(key)), reverse=reverse
    )[:n]
    if keep is None:
        return list(sorted_items)
    return [{k: it.get(k) for k in keep if k in it} for it in sorted_items]


def _as_number(v: Any) -> float:
    if v is None:
        return float("-inf")
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("-inf")


# ---- Severity helpers ------------------------------------------------------


def error_severity(error_rate: float | None) -> str | None:
    if error_rate is None:
        return None
    if error_rate >= ERROR_RATE_CRITICAL:
        return "critical"
    if error_rate >= ERROR_RATE_HIGH:
        return "high"
    return "ok"


def latency_severity(latency_ms: float | None) -> str | None:
    if latency_ms is None:
        return None
    if latency_ms >= LATENCY_CRITICAL_MS:
        return "critical"
    if latency_ms >= LATENCY_SLOW_MS:
        return "slow"
    return "ok"


def anomaly_flags(
    *,
    error_rate: float | None = None,
    p95_ms: float | None = None,
    avg_ms: float | None = None,
) -> list[str]:
    flags: list[str] = []
    sev = error_severity(error_rate) if error_rate is not None else None
    if sev == "critical":
        flags.append("error_rate_critical")
    elif sev == "high":
        flags.append("error_rate_high")
    lat_sev = latency_severity(p95_ms) if p95_ms is not None else None
    if lat_sev == "critical":
        flags.append("p95_critical")
    elif lat_sev == "slow":
        flags.append("p95_slow")
    if (
        p95_ms is not None
        and avg_ms is not None
        and avg_ms > 0
        and p95_ms / avg_ms >= P95_AVG_RATIO_HIGH
    ):
        flags.append("heavy_tail")
    return flags
