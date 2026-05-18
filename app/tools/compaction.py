from typing import Any

from app.schemas.seeker import Scatter, TraceView

MAX_SPANS_PER_TRACE = 50
MAX_EVENTS_PER_SPAN = 30
MAX_SCATTER_POINTS = 100


def compact_trace_view(view: TraceView) -> dict[str, Any]:
    """Trim a TraceView so the JSON sent to the LLM stays bounded.

    Strategy:
    - Keep all spans with `exception_info` (errors are diagnostically important).
    - Fill the remaining span budget by `elapsed_time` desc (slowest first).
    - Within each span, do the same for `events`.
    - Restore time/sequence order in the returned list so the LLM reads
      events chronologically.
    - When anything is trimmed, attach a `meta` block so the LLM (and the user)
      know they are looking at a subset.
    """
    data = view.model_dump(by_alias=False)
    spans = data.get("spans") or []
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
    return data


def compact_scatter(scatter: Scatter) -> dict[str, Any]:
    """Trim a Scatter so points list stays under MAX_SCATTER_POINTS.

    Strategy:
    - Always preserve every errored point (is_error=true).
    - Fill the remaining budget by uniformly sampling the successful points
      (every `step`-th element so the time distribution is preserved).
    - If errors alone exceed the cap, keep the earliest cap errors (still useful).
    - Summary stays untouched — it carries the true totals for the LLM's answer.
    """
    data = scatter.model_dump(by_alias=False)
    points = data.get("points") or []

    if len(points) <= MAX_SCATTER_POINTS:
        return data

    errors = [p for p in points if p.get("is_error")]
    normals = [p for p in points if not p.get("is_error")]
    budget = MAX_SCATTER_POINTS - len(errors)

    if budget <= 0:
        errors = errors[:MAX_SCATTER_POINTS]
        sampled: list[dict[str, Any]] = []
    elif normals:
        step = max(1, len(normals) // budget)
        sampled = normals[::step][:budget]
    else:
        sampled = []

    kept = sorted(errors + sampled, key=lambda p: p.get("start_time", 0))
    data["points"] = kept
    data["meta"] = {
        "points_sampled": {
            "original": len(points),
            "returned": len(kept),
            "errors_preserved": sum(1 for p in kept if p.get("is_error")),
            "strategy": "all errors + uniform sample of successes",
        }
    }
    return data


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
