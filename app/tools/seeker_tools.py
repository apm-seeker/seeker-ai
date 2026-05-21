import json
from typing import Annotated, Any

from langchain_core.tools import tool

from app.schemas.seeker import TraceDetailsRequest
from app.tools.compaction import (
    compact_agent_metrics,
    compact_jvm_timeseries,
    compact_metric_agents,
    compact_scatter,
    compact_topology,
    compact_trace_histogram,
    compact_trace_view,
    compact_url_stats,
)
from app.tools.seeker_client import SeekerWebError, get_seeker_client


def _err(exc: SeekerWebError) -> str:
    return json.dumps(
        {"error": str(exc), "status_code": exc.status_code},
        ensure_ascii=False,
    )


def _emit(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


@tool
async def get_service_topology(
    start_time_ms: Annotated[
        int, "Start of time range, epoch milliseconds (UTC)."
    ],
    end_time_ms: Annotated[
        int, "End of time range, epoch milliseconds (UTC)."
    ],
) -> str:
    """Return the service topology graph for the given time range.

    Use when the user asks about which services exist, how they connect,
    the overall service map, or which agents are sending traffic to which.

    Returns JSON with:
    - nodes[]: each agent with agentId, agentName, agentType, errorRate (0-1)
              (a synthetic node with agentId='' and agentName='USER' represents external traffic)
    - edges[]: each connection with fromAgentId, toAgentId, tps, avgLatency (ms), errorRate
    - insights: pre-computed summary with `node_count`, `edge_count`,
      `top_edges_by_tps` (top 5), `top_edges_by_avg_latency` (top 5),
      `high_error_services` (anything with error_rate >= 5%), and `flags`
      (e.g. "test2:error_rate_high", "USER->test1:edge_latency_slow").
      Prefer quoting from insights instead of re-sorting raw nodes/edges.
    """
    client = get_seeker_client()
    try:
        topo = await client.get_topology(start_time_ms, end_time_ms)
        return _emit(compact_topology(topo))
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def get_agent_metrics(
    agent_id: Annotated[
        str,
        "Agent identifier from topology. Use empty string '' to get metrics for the USER (external traffic) node.",
    ],
    start_time_ms: Annotated[int, "Start of time range, epoch milliseconds."],
    end_time_ms: Annotated[int, "End of time range, epoch milliseconds."],
) -> str:
    """Return aggregated request count and latency percentiles for a single agent.

    Use when the user asks about the performance of a specific service, e.g. error rate,
    average latency, p90/p95/p99 latency, request count.

    Returns JSON: totalCount, errorCount, errorRate (0-1), p99, p95, p90 (all in ms),
    plus an `insights` block with severity buckets (`ok`/`high`/`critical` for error
    and latency_p95/p99), p95/avg ratio, and `flags` such as "p95_slow", "heavy_tail",
    "error_rate_high".
    """
    client = get_seeker_client()
    try:
        metrics = await client.get_agent_metrics(
            agent_id, start_time_ms, end_time_ms
        )
        return _emit(compact_agent_metrics(metrics))
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def get_agent_scatter(
    agent_id: Annotated[
        str,
        "Agent identifier. Use empty string '' for USER (external traffic) points.",
    ],
    start_time_ms: Annotated[int, "Start of time range, epoch milliseconds."],
    end_time_ms: Annotated[int, "End of time range, epoch milliseconds."],
) -> str:
    """Return per-request scatter points (one point per request) for a single agent.

    Use when the user wants to see individual requests over time, identify outliers,
    or examine which traces are slow / errored.

    Returns JSON: summary {total_count, error_count, error_rate}, points[] with
    trace_id, span_id, start_time (epoch ms), elapsed_time (ms), status_code, is_error,
    plus `insights` containing `latency_stats_ms` (count/min/max/avg/p50/p95/p99),
    `error_window` (first/last error timestamps), and `flags`.

    If points exceed 100, the response is sampled (all errored points preserved,
    successes uniformly sampled) and a `meta.points_sampled` block reports the
    original total. The `summary` and `insights.latency_stats_ms` always reflect
    the full unsampled totals.
    """
    client = get_seeker_client()
    try:
        scatter = await client.get_agent_scatter(
            agent_id, start_time_ms, end_time_ms
        )
        return _emit(compact_scatter(scatter))
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def get_trace_histogram(
    start_time_ms: Annotated[int, "Start of time range, epoch milliseconds."],
    end_time_ms: Annotated[int, "End of time range, epoch milliseconds."],
    interval_ms: Annotated[
        int,
        "Bin width in milliseconds. Pick so (end - start) / interval is between 12 and 120 bins (e.g. 60000 for a 1h window, 300000 for a 12h window).",
    ],
) -> str:
    """Return a latency distribution histogram over time.

    Use when the user asks about response time distribution, slow-request trends,
    or wants to see how latencies are spread across time bins.

    Returns JSON: interval, boundaries[] (8 latency buckets from 0ms to 8000+ms),
    bins[] (each with timestamp and counts[] aligned to boundaries), and `insights`
    with `total_count`, `peak_bin` {timestamp, count, share_pct}, `slow_share_pct`
    (>= 1s buckets), `critical_share_pct` (>= 3s buckets), `trend`
    (rising/falling/stable), and `flags` like "slow_tail_present".
    """
    client = get_seeker_client()
    try:
        hist = await client.get_trace_histogram(
            start_time_ms, end_time_ms, interval_ms
        )
        return _emit(compact_trace_histogram(hist))
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def get_url_stats(
    start_time_ms: Annotated[int, "Start of time range, epoch milliseconds."],
    end_time_ms: Annotated[int, "End of time range, epoch milliseconds."],
) -> str:
    """Return per-URL request statistics (up to 100 rows, sorted by call count desc).

    Use when the user asks which endpoints are most-called, slowest, or have most failures.

    Returns JSON: rows[] with url, totalCount, failureCount (statusCode >= 400),
    avgMs (mean latency), p95Ms (95th percentile latency in ms), and `insights` with
    `top_by_calls`, `top_by_p95`, `top_by_failure_rate`, `heavy_tail_urls` (p95/avg >= 3),
    and `flags` summarising counts (e.g. "3_urls_p95_slow", "1_url_error_rate_critical").
    Quote insights directly — do not re-sort rows yourself.
    """
    client = get_seeker_client()
    try:
        stats = await client.get_url_stats(start_time_ms, end_time_ms)
        return _emit(compact_url_stats(stats))
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def search_traces(
    start_time_ms: Annotated[int, "Start of time range, epoch milliseconds."],
    end_time_ms: Annotated[int, "End of time range, epoch milliseconds."],
    url: Annotated[
        str | None, "URL substring filter, or null for all URLs."
    ] = None,
    statuses: Annotated[
        list[str] | None,
        "Status filter list. Allowed values: 'success', 'error'. Null/empty = all.",
    ] = None,
    duration_from_ms: Annotated[
        int | None,
        "Minimum duration in ms (inclusive). Null = no lower bound.",
    ] = None,
    duration_to_ms: Annotated[
        int | None,
        "Maximum duration in ms (exclusive). Null = no upper bound.",
    ] = None,
    agent_ids: Annotated[
        list[str] | None,
        "Filter traces involving any of these agent IDs. Null/empty = all.",
    ] = None,
    exception_classes: Annotated[
        list[str] | None,
        "Filter by exception class names (simple names, e.g. 'NullPointerException'). Null/empty = all.",
    ] = None,
    trace_id_prefix: Annotated[
        str | None,
        "Filter by trace ID prefix. Null/empty = no filter.",
    ] = None,
    order_by: Annotated[
        str,
        "Sort key. One of 'startTime_desc', 'startTime_asc', 'duration_desc', 'duration_asc'.",
    ] = "startTime_desc",
    limit: Annotated[int, "Max rows to return, 1-500."] = 100,
    offset: Annotated[int, "Pagination offset (>= 0)."] = 0,
) -> str:
    """Search trace summaries with filters, sorted and paginated.

    Use when the user wants a list of traces matching criteria — slow traces,
    error traces, traces involving a specific URL/agent/exception, etc.

    Returns JSON: rows[] with traceId, agents[], urlPath, duration (ms),
    statusCode, exceptionClass, startTime (epoch ms); total count; hasMore flag.
    """
    client = get_seeker_client()
    try:
        request = TraceDetailsRequest(
            start_time=start_time_ms,
            end_time=end_time_ms,
            url=url,
            statuses=statuses,  # type: ignore[arg-type]
            duration_from=duration_from_ms,
            duration_to=duration_to_ms,
            agent_ids=agent_ids,
            exception_classes=exception_classes,
            trace_id_prefix=trace_id_prefix,
            order_by=order_by,  # type: ignore[arg-type]
            limit=limit,
            offset=offset,
        )
        result = await client.search_traces(request)
        return result.model_dump_json(by_alias=False)
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def get_trace_detail(
    trace_id: Annotated[
        str, "Trace identifier (from topology, scatter, or search_traces results)."
    ],
) -> str:
    """Return a single trace's full callstack (all spans and span events).

    Use when the user wants to inspect what happened in a specific request — full
    span tree, method-level events, exceptions, agent hops, latency breakdown.

    Returns JSON: trace_id, start_time, duration, status_code, exception_class, agents[],
    spans[] (each with span_id, parent_span_id, agent_name, uri, exception_info, events[]),
    and `insights` containing `per_agent_latency` (total_ms / self_ms / span_count per agent),
    `critical_path` (longest root-to-leaf chain by elapsed_time), `slowest_spans` (top 3),
    `errored_spans` (up to 5 with truncated exception info), and `flags` such as
    "has_exception", "deep_call_stack", "trace_duration_slow".

    Build the tree by linking child.parent_span_id to parent.span_id. Root spans have
    parent_span_id == '-1'. If a trace has more than 50 spans, or any span has more
    than 30 events, the response is truncated with errored spans/events preserved first
    and remaining slots filled by elapsed_time desc; a `meta` block then reports
    original/returned counts.
    """
    client = get_seeker_client()
    try:
        view = await client.get_trace_detail(trace_id)
        return _emit(compact_trace_view(view))
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def get_metric_agents() -> str:
    """Return the list of agents that report JVM metrics.

    Use this when the user asks which services have JVM metric data, or as a
    discovery step before calling get_jvm_metric_timeseries when the user
    refers to a service by name rather than agent ID.

    Returns JSON: agents[] with id, agentName, agentGroup, applicationName,
    plus `insights.agent_count`.
    """
    client = get_seeker_client()
    try:
        agents = await client.get_metric_agents()
        return _emit(compact_metric_agents(agents))
    except SeekerWebError as exc:
        return _err(exc)


@tool
async def get_jvm_metric_timeseries(
    agent_id: Annotated[str, "Agent identifier from get_metric_agents."],
    metric_name: Annotated[
        str,
        "Exactly one of: 'jvm.memory', 'jvm.gc', 'jvm.thread', 'jvm.class'. "
        "Other values will be rejected by the server.",
    ],
    start_time_ms: Annotated[int, "Start of time range, epoch milliseconds."],
    end_time_ms: Annotated[int, "End of time range, epoch milliseconds."],
    interval_ms: Annotated[
        int | None,
        "Bucket width in ms. Leave null to let the server pick a sensible interval "
        "based on the time range; only set if the user explicitly asks for a resolution.",
    ] = None,
) -> str:
    """Return JVM metric time series for one agent and one metric group.

    Use this for JVM heap/memory usage, GC counts/time, thread counts, or
    loaded class counts over a time range.

    The response splits the chosen metric group into multiple series, one per
    (fieldName, tags) combination. For example metric_name='jvm.memory' yields
    series like heap_used / heap_committed / non_heap_used (and others). For
    metric_name='jvm.gc' the tags identify GC name/type, and the fields include
    cumulative counts and time totals.

    Returns JSON: intervalMs and series[] where each series has:
      - fieldName (e.g. heap_used)
      - type: 'GAUGE' (interpret value as-is) or 'CUMULATIVE' (interpret
        consecutive points' difference as rate/increment)
      - tags: extra labels distinguishing same-fieldName series
      - points: list of {t (epoch ms), v (numeric)}
    Plus an `insights` block with `per_series` (each carrying stats {count,min,max,
    avg,p50,p95,p99}, `last` value, and `trend`), `heap_pressure` (when memory
    fields are present), `gc_summary` (when GC fields are present), and `flags`
    such as "heap_pressure_high" / "gc_overhead_high".
    """
    client = get_seeker_client()
    try:
        ts = await client.get_metric_timeseries(
            agent_id=agent_id,
            metric_name=metric_name,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            interval_ms=interval_ms,
        )
        return _emit(compact_jvm_timeseries(ts, metric_name=metric_name))
    except SeekerWebError as exc:
        return _err(exc)


SEEKER_TOOLS = [
    get_service_topology,
    get_agent_metrics,
    get_agent_scatter,
    get_trace_histogram,
    get_url_stats,
    search_traces,
    get_trace_detail,
    get_metric_agents,
    get_jvm_metric_timeseries,
]
