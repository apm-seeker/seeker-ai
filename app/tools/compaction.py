"""Compact seeker-web tool responses for the LLM.

Each compact_* takes a Pydantic response model and returns a dict with:
- raw fields preserved (nodes/edges/rows/points/spans...),
- a `meta` block when truncation/sampling happened (legacy),
- an `insights` block carrying pre-computed top-N rankings, percentile stats,
  trend direction, and anomaly flags drawn from `app.tools.insights`.

The system prompt is written to quote `insights.flags` and `insights.top_by_*`
back to the user, so changes to the keys here need a matching prompt update.
"""

from __future__ import annotations

from typing import Any

from app.schemas.seeker import (
    AgentMetrics,
    MetricAgents,
    MetricTimeseries,
    Scatter,
    Topology,
    TraceHistogram,
    TraceView,
    UrlStats,
)
from app.tools.insights import (
    HEAP_PRESSURE_CRITICAL,
    HEAP_PRESSURE_HIGH,
    LATENCY_SLOW_MS,
    LATENCY_CRITICAL_MS,
    P95_AVG_RATIO_HIGH,
    anomaly_flags,
    describe,
    error_severity,
    latency_severity,
    topn,
    trend,
)

MAX_SPANS_PER_TRACE = 50
MAX_EVENTS_PER_SPAN = 30
MAX_SCATTER_POINTS = 100


# ---- topology --------------------------------------------------------------


def compact_topology(topology: Topology) -> dict[str, Any]:
    data = topology.model_dump(by_alias=False)
    nodes: list[dict[str, Any]] = data.get("nodes") or []
    edges: list[dict[str, Any]] = data.get("edges") or []
    name_by_id = {n.get("agent_id", ""): n.get("agent_name") for n in nodes}

    def edge_view(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "from": name_by_id.get(e.get("from_agent_id", ""))
            or e.get("from_agent_id"),
            "to": name_by_id.get(e.get("to_agent_id", "")) or e.get("to_agent_id"),
            "tps": round(float(e.get("tps") or 0), 3),
            "avg_latency": round(float(e.get("avg_latency") or 0), 1),
            "error_rate": round(float(e.get("error_rate") or 0), 4),
        }

    edge_views = [edge_view(e) for e in edges]
    top_tps = topn(edge_views, "tps", n=5)
    top_lat = topn(edge_views, "avg_latency", n=5)

    flags: list[str] = []
    high_err: list[dict[str, Any]] = []
    for n in nodes:
        sev = error_severity(n.get("error_rate"))
        if sev in ("high", "critical"):
            high_err.append(
                {
                    "agent_name": n.get("agent_name"),
                    "agent_id": n.get("agent_id"),
                    "error_rate": round(float(n.get("error_rate") or 0), 4),
                    "severity": sev,
                }
            )
            flags.append(f"{n.get('agent_name') or n.get('agent_id')}:error_rate_{sev}")

    for ev in edge_views:
        lat_sev = latency_severity(ev["avg_latency"])
        if lat_sev in ("slow", "critical"):
            flags.append(f"{ev['from']}->{ev['to']}:edge_latency_{lat_sev}")

    data["insights"] = {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "top_edges_by_tps": top_tps,
        "top_edges_by_avg_latency": top_lat,
        "high_error_services": high_err,
        "flags": flags,
    }
    return data


# ---- agent metrics ---------------------------------------------------------


def compact_agent_metrics(metrics: AgentMetrics) -> dict[str, Any]:
    data = metrics.model_dump(by_alias=False)
    err = data.get("error_rate")
    p95 = data.get("p95")
    p99 = data.get("p99")
    total = data.get("total_count") or 0
    err_count = data.get("error_count") or 0
    avg = None
    if total > 0 and p99 is not None and p95 is not None:
        # We don't get true avg from this endpoint — approximate as weighted
        # toward p50 if available, else fall back to p95 as a conservative proxy.
        avg = data.get("p50") or (p95 * 0.6)

    p95_avg_ratio = None
    if p95 is not None and avg and avg > 0:
        p95_avg_ratio = round(p95 / avg, 2)

    flags = anomaly_flags(error_rate=err, p95_ms=p95, avg_ms=avg)

    data["insights"] = {
        "severity": {
            "error": error_severity(err),
            "latency_p95": latency_severity(p95),
            "latency_p99": latency_severity(p99),
        },
        "p95_avg_ratio": p95_avg_ratio,
        "errored": err_count,
        "of": total,
        "flags": flags,
    }
    return data


# ---- scatter ---------------------------------------------------------------


def compact_scatter(scatter: Scatter) -> dict[str, Any]:
    data = scatter.model_dump(by_alias=False)
    raw_points: list[dict[str, Any]] = data.get("points") or []
    summary = data.get("summary") or {}

    latencies = [float(p.get("elapsed_time") or 0) for p in raw_points]
    latency_stats = describe(latencies)
    avg = latency_stats["avg"] if latency_stats else None
    p95 = latency_stats["p95"] if latency_stats else None

    error_points = [p for p in raw_points if p.get("is_error")]
    error_window = None
    if error_points:
        starts = [int(p.get("start_time") or 0) for p in error_points]
        error_window = {
            "first_error_ms": min(starts),
            "last_error_ms": max(starts),
            "count": len(error_points),
        }

    err_rate = summary.get("error_rate")
    flags = anomaly_flags(error_rate=err_rate, p95_ms=p95, avg_ms=avg)

    insights: dict[str, Any] = {
        "latency_stats_ms": latency_stats,
        "error_window": error_window,
        "flags": flags,
    }

    # Reuse the existing sampling strategy: keep all errors + uniform sample of successes.
    if len(raw_points) > MAX_SCATTER_POINTS:
        errors = [p for p in raw_points if p.get("is_error")]
        normals = [p for p in raw_points if not p.get("is_error")]
        budget = MAX_SCATTER_POINTS - len(errors)
        if budget <= 0:
            kept_errors = errors[:MAX_SCATTER_POINTS]
            sampled: list[dict[str, Any]] = []
        elif normals:
            step = max(1, len(normals) // budget)
            sampled = normals[::step][:budget]
            kept_errors = errors
        else:
            sampled = []
            kept_errors = errors

        kept = sorted(
            kept_errors + sampled, key=lambda p: p.get("start_time", 0)
        )
        data["points"] = kept
        data["meta"] = {
            "points_sampled": {
                "original": len(raw_points),
                "returned": len(kept),
                "errors_preserved": sum(1 for p in kept if p.get("is_error")),
                "strategy": "all errors + uniform sample of successes",
            }
        }

    data["insights"] = insights
    return data


# ---- trace histogram -------------------------------------------------------


def compact_trace_histogram(hist: TraceHistogram) -> dict[str, Any]:
    data = hist.model_dump(by_alias=False)
    boundaries: list[dict[str, Any]] = data.get("boundaries") or []
    bins: list[dict[str, Any]] = data.get("bins") or []

    # Each bin.counts aligns to `boundaries`. Identify which boundary indexes
    # represent "slow" (>= LATENCY_SLOW_MS) and "critical" (>= LATENCY_CRITICAL_MS).
    slow_idx: list[int] = []
    critical_idx: list[int] = []
    for i, b in enumerate(boundaries):
        lo = b.get("from_") if "from_" in b else b.get("from")
        try:
            lo_v = float(lo) if lo is not None else 0
        except (TypeError, ValueError):
            lo_v = 0
        if lo_v >= LATENCY_CRITICAL_MS:
            critical_idx.append(i)
        if lo_v >= LATENCY_SLOW_MS:
            slow_idx.append(i)

    bin_totals: list[int] = []
    slow_share = 0
    critical_share = 0
    total = 0
    peak_idx = -1
    peak_count = -1
    for i, b in enumerate(bins):
        counts = b.get("counts") or []
        bin_total = sum(int(c or 0) for c in counts)
        bin_totals.append(bin_total)
        total += bin_total
        if bin_total > peak_count:
            peak_count = bin_total
            peak_idx = i
        for j in slow_idx:
            if j < len(counts):
                slow_share += int(counts[j] or 0)
        for j in critical_idx:
            if j < len(counts):
                critical_share += int(counts[j] or 0)

    peak_bin = None
    if peak_idx >= 0 and total > 0:
        peak_bin = {
            "timestamp": bins[peak_idx].get("timestamp"),
            "count": peak_count,
            "share_pct": round(peak_count / total * 100, 2),
        }

    flags: list[str] = []
    if total > 0:
        slow_pct = slow_share / total * 100
        critical_pct = critical_share / total * 100
        if critical_pct >= 1:
            flags.append("critical_tail_present")
        elif slow_pct >= 5:
            flags.append("slow_tail_present")
    else:
        slow_pct = critical_pct = 0.0

    data["insights"] = {
        "total_count": total,
        "peak_bin": peak_bin,
        "slow_share_pct": round(slow_pct, 2),
        "critical_share_pct": round(critical_pct, 2),
        "trend": trend(bin_totals),
        "flags": flags,
    }
    return data


# ---- URL stats -------------------------------------------------------------


def compact_url_stats(stats: UrlStats) -> dict[str, Any]:
    data = stats.model_dump(by_alias=False)
    rows: list[dict[str, Any]] = data.get("rows") or []

    enriched: list[dict[str, Any]] = []
    for r in rows:
        total = int(r.get("total_count") or 0)
        failure = int(r.get("failure_count") or 0)
        avg = float(r.get("avg_ms") or 0)
        p95 = float(r.get("p95_ms") or 0)
        failure_rate = failure / total if total > 0 else 0.0
        p95_avg_ratio = (p95 / avg) if avg > 0 else None
        enriched.append(
            {
                "url": r.get("url"),
                "total_count": total,
                "failure_count": failure,
                "failure_rate": round(failure_rate, 4),
                "avg_ms": int(avg),
                "p95_ms": int(p95),
                "p95_avg_ratio": round(p95_avg_ratio, 2)
                if p95_avg_ratio is not None
                else None,
            }
        )

    top_calls_keep = ("url", "total_count", "avg_ms", "p95_ms", "failure_count")
    top_p95_keep = ("url", "p95_ms", "avg_ms", "total_count")
    top_fail_keep = ("url", "failure_count", "total_count", "failure_rate")
    top_tail_keep = ("url", "p95_avg_ratio", "avg_ms", "p95_ms", "total_count")

    top_by_calls = topn(enriched, "total_count", n=5, keep=top_calls_keep)
    top_by_p95 = topn(enriched, "p95_ms", n=5, keep=top_p95_keep)
    top_by_failure = topn(
        [e for e in enriched if e["failure_count"] > 0],
        "failure_rate",
        n=5,
        keep=top_fail_keep,
    )
    heavy_tail = topn(
        [
            e
            for e in enriched
            if e["p95_avg_ratio"] is not None
            and e["p95_avg_ratio"] >= P95_AVG_RATIO_HIGH
        ],
        "p95_avg_ratio",
        n=5,
        keep=top_tail_keep,
    )

    flags: list[str] = []
    slow_urls = [e for e in enriched if e["p95_ms"] >= LATENCY_SLOW_MS]
    critical_urls = [e for e in enriched if e["p95_ms"] >= LATENCY_CRITICAL_MS]
    crit_err_urls = [
        e for e in enriched if e["failure_rate"] >= 0.20 and e["total_count"] >= 10
    ]
    high_err_urls = [
        e
        for e in enriched
        if 0.05 <= e["failure_rate"] < 0.20 and e["total_count"] >= 10
    ]
    if critical_urls:
        flags.append(f"{len(critical_urls)}_urls_p95_critical")
    if slow_urls and not critical_urls:
        flags.append(f"{len(slow_urls)}_urls_p95_slow")
    if crit_err_urls:
        flags.append(f"{len(crit_err_urls)}_urls_error_rate_critical")
    if high_err_urls:
        flags.append(f"{len(high_err_urls)}_urls_error_rate_high")

    data["insights"] = {
        "total_urls": len(enriched),
        "top_by_calls": top_by_calls,
        "top_by_p95": top_by_p95,
        "top_by_failure_rate": top_by_failure,
        "heavy_tail_urls": heavy_tail,
        "flags": flags,
    }
    return data


# ---- trace detail (trace view) ---------------------------------------------


def compact_trace_view(view: TraceView) -> dict[str, Any]:
    data = view.model_dump(by_alias=False)
    spans: list[dict[str, Any]] = data.get("spans") or []
    meta: dict[str, Any] = {}

    if len(spans) > MAX_SPANS_PER_TRACE:
        kept = _select_spans(spans, MAX_SPANS_PER_TRACE)
        kept.sort(key=lambda s: s.get("start_time", 0))
        meta["spans_truncated"] = {
            "original": len(spans),
            "returned": len(kept),
            "strategy": "errors first, then by elapsed_time desc",
        }
        data["spans"] = kept

    events_truncated: list[dict[str, Any]] = []
    for span in data["spans"]:
        events = span.get("events") or []
        if len(events) > MAX_EVENTS_PER_SPAN:
            kept = _select_events(events, MAX_EVENTS_PER_SPAN)
            kept.sort(key=lambda e: e.get("sequence", 0))
            events_truncated.append(
                {
                    "span_id": span.get("span_id"),
                    "original": len(events),
                    "returned": len(kept),
                }
            )
            span["events"] = kept

    if events_truncated:
        meta["events_truncated"] = events_truncated
    if meta:
        meta["strategy_events"] = "errors first, then by elapsed_time desc"
        data["meta"] = meta

    # ---- insights derived from full (post-trim) span list ------------------
    used_spans = data["spans"]
    by_id = {s.get("span_id"): s for s in used_spans}

    # per-agent latency: aggregate "self time" by subtracting children
    self_by_id: dict[str, float] = {}
    for s in used_spans:
        elapsed = float(s.get("elapsed_time") or 0)
        self_by_id[s.get("span_id")] = elapsed
    for s in used_spans:
        parent = s.get("parent_span_id")
        if parent and parent in self_by_id and parent != s.get("span_id"):
            self_by_id[parent] -= float(s.get("elapsed_time") or 0)

    per_agent: dict[str, dict[str, Any]] = {}
    for s in used_spans:
        name = s.get("agent_name") or s.get("agent_id") or "?"
        agg = per_agent.setdefault(
            name,
            {"agent_name": name, "total_ms": 0.0, "self_ms": 0.0, "span_count": 0},
        )
        agg["total_ms"] += float(s.get("elapsed_time") or 0)
        agg["self_ms"] += max(0.0, self_by_id.get(s.get("span_id"), 0.0))
        agg["span_count"] += 1
    per_agent_list = sorted(
        per_agent.values(), key=lambda a: a["self_ms"], reverse=True
    )
    for a in per_agent_list:
        a["total_ms"] = round(a["total_ms"], 1)
        a["self_ms"] = round(a["self_ms"], 1)

    # critical path: longest chain root->leaf by elapsed_time
    children: dict[str, list[dict[str, Any]]] = {}
    roots: list[dict[str, Any]] = []
    for s in used_spans:
        parent = s.get("parent_span_id")
        if parent in (None, "-1") or parent not in by_id:
            roots.append(s)
        else:
            children.setdefault(parent, []).append(s)
    crit_path: list[dict[str, Any]] = []
    if roots:
        roots.sort(key=lambda s: float(s.get("elapsed_time") or 0), reverse=True)
        node = roots[0]
        while node is not None:
            crit_path.append(
                {
                    "span_id": node.get("span_id"),
                    "agent_name": node.get("agent_name"),
                    "uri": node.get("uri"),
                    "end_point": node.get("end_point"),
                    "elapsed_time": int(node.get("elapsed_time") or 0),
                    "status_code": node.get("status_code"),
                }
            )
            kids = children.get(node.get("span_id")) or []
            if not kids:
                break
            kids.sort(key=lambda s: float(s.get("elapsed_time") or 0), reverse=True)
            node = kids[0]

    slowest = sorted(
        used_spans, key=lambda s: float(s.get("elapsed_time") or 0), reverse=True
    )[:3]
    slowest_view = [
        {
            "span_id": s.get("span_id"),
            "agent_name": s.get("agent_name"),
            "uri": s.get("uri") or s.get("end_point"),
            "elapsed_time": int(s.get("elapsed_time") or 0),
        }
        for s in slowest
    ]

    errored = [s for s in used_spans if s.get("exception_info")]
    errored_view = [
        {
            "span_id": s.get("span_id"),
            "agent_name": s.get("agent_name"),
            "uri": s.get("uri") or s.get("end_point"),
            "exception": (s.get("exception_info") or "")[:200],
        }
        for s in errored[:5]
    ]

    flags: list[str] = []
    if errored:
        flags.append("has_exception")
    if len(used_spans) >= 20:
        flags.append("deep_call_stack")
    duration = float(data.get("duration") or 0)
    if duration >= LATENCY_CRITICAL_MS:
        flags.append("trace_duration_critical")
    elif duration >= LATENCY_SLOW_MS:
        flags.append("trace_duration_slow")

    data["insights"] = {
        "per_agent_latency": per_agent_list,
        "critical_path": crit_path,
        "slowest_spans": slowest_view,
        "errored_spans": errored_view,
        "flags": flags,
    }
    return data


# ---- JVM timeseries --------------------------------------------------------


def compact_jvm_timeseries(
    ts: MetricTimeseries, metric_name: str | None = None
) -> dict[str, Any]:
    data = ts.model_dump(by_alias=False)
    series_list: list[dict[str, Any]] = data.get("series") or []

    per_series_summary: list[dict[str, Any]] = []
    heap_used_max: float | None = None
    heap_committed_max: float | None = None
    gc_time_total: float = 0.0
    gc_count_total: float = 0.0

    for s in series_list:
        points = s.get("points") or []
        values = [float(p.get("v") or 0) for p in points]
        stats = describe(values)
        last_v = values[-1] if values else None
        per_series_summary.append(
            {
                "field_name": s.get("field_name"),
                "type": s.get("type"),
                "tags": s.get("tags") or {},
                "stats": stats,
                "last": round(float(last_v), 3) if last_v is not None else None,
                "trend": trend(values),
            }
        )

        fname = (s.get("field_name") or "").lower()
        if fname == "heap_used" and stats:
            heap_used_max = max(
                heap_used_max if heap_used_max is not None else 0.0, stats["max"]
            )
        elif fname == "heap_committed" and stats:
            heap_committed_max = max(
                heap_committed_max if heap_committed_max is not None else 0.0,
                stats["max"],
            )
        if s.get("type") == "CUMULATIVE" and values and "gc" in fname:
            increment = max(0.0, values[-1] - values[0])
            if "time" in fname or "ms" in fname:
                gc_time_total += increment
            elif "count" in fname:
                gc_count_total += increment

    flags: list[str] = []
    heap_pressure = None
    if heap_used_max is not None and heap_committed_max and heap_committed_max > 0:
        ratio = heap_used_max / heap_committed_max
        sev = (
            "critical"
            if ratio >= HEAP_PRESSURE_CRITICAL
            else "high"
            if ratio >= HEAP_PRESSURE_HIGH
            else "ok"
        )
        heap_pressure = {"max_ratio": round(ratio, 3), "severity": sev}
        if sev != "ok":
            flags.append(f"heap_pressure_{sev}")

    gc_summary = None
    interval_ms = int(data.get("interval_ms") or 0)
    if interval_ms and (gc_time_total or gc_count_total):
        window_ms = max(1, interval_ms * max(1, len(series_list[0].get("points") or [])))
        overhead_pct = gc_time_total / window_ms * 100 if gc_time_total else 0.0
        gc_summary = {
            "gc_time_total_ms": round(gc_time_total, 1),
            "gc_count_total": int(gc_count_total),
            "overhead_pct": round(overhead_pct, 2),
        }
        if overhead_pct >= 10:
            flags.append("gc_overhead_high")

    insights: dict[str, Any] = {
        "series_count": len(series_list),
        "per_series": per_series_summary,
        "flags": flags,
    }
    if metric_name:
        insights["metric_name"] = metric_name
    if heap_pressure is not None:
        insights["heap_pressure"] = heap_pressure
    if gc_summary is not None:
        insights["gc_summary"] = gc_summary

    data["insights"] = insights
    return data


# ---- metric agents (cheap discovery endpoint) ------------------------------


def compact_metric_agents(agents: MetricAgents) -> dict[str, Any]:
    data = agents.model_dump(by_alias=False)
    rows = data.get("agents") or []
    data["insights"] = {"agent_count": len(rows)}
    return data


# ---- internal selectors (used by compact_trace_view) -----------------------


def _select_spans(spans: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    errored = [s for s in spans if s.get("exception_info")]
    normal = [s for s in spans if not s.get("exception_info")]
    if len(errored) >= cap:
        errored.sort(key=lambda s: s.get("elapsed_time", 0), reverse=True)
        return errored[:cap]
    normal.sort(key=lambda s: s.get("elapsed_time", 0), reverse=True)
    return errored + normal[: cap - len(errored)]


def _select_events(events: list[dict[str, Any]], cap: int) -> list[dict[str, Any]]:
    errored = [e for e in events if e.get("exception_info")]
    others = [e for e in events if not e.get("exception_info")]
    if len(errored) >= cap:
        errored.sort(key=lambda e: e.get("elapsed_time", 0), reverse=True)
        return errored[:cap]
    others.sort(key=lambda e: e.get("elapsed_time", 0), reverse=True)
    return errored + others[: cap - len(errored)]
