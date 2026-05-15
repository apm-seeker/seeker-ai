import json
from typing import Annotated, Any

from langchain_core.tools import tool

from app.schemas.seeker import TraceDetailsRequest
from app.tools.seeker_client import SeekerWebError, get_seeker_client


def _err(exc: SeekerWebError) -> str:
    return json.dumps(
        {"error": str(exc), "status_code": exc.status_code},
        ensure_ascii=False,
    )


def _dump(obj: Any) -> str:
    return obj.model_dump_json(by_alias=False)


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
    """
    client = get_seeker_client()
    try:
        return _dump(await client.get_topology(start_time_ms, end_time_ms))
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

    Returns JSON: totalCount, errorCount, errorRate (0-1), p99, p95, p90 (all in ms).
    """
    client = get_seeker_client()
    try:
        return _dump(
            await client.get_agent_metrics(agent_id, start_time_ms, end_time_ms)
        )
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

    Returns JSON: summary {totalCount, errorCount, errorRate}, points[] with
    traceId, spanId, startTime (epoch ms), elapsedTime (ms), statusCode, isError.
    """
    client = get_seeker_client()
    try:
        return _dump(
            await client.get_agent_scatter(agent_id, start_time_ms, end_time_ms)
        )
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
    bins[] (each with timestamp and counts[] aligned to boundaries).
    """
    client = get_seeker_client()
    try:
        return _dump(
            await client.get_trace_histogram(
                start_time_ms, end_time_ms, interval_ms
            )
        )
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
    avgMs (mean latency), p95Ms (95th percentile latency in ms).
    """
    client = get_seeker_client()
    try:
        return _dump(await client.get_url_stats(start_time_ms, end_time_ms))
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
        return _dump(await client.search_traces(request))
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

    Returns JSON: traceId, startTime, duration, statusCode, exceptionClass, agents[],
    spans[] (each with spanId, parentSpanId, agentName, uri, exceptionInfo, events[]).
    Build the tree by linking child.parentSpanId to parent.spanId. Root spans have
    parentSpanId == '-1'.
    """
    client = get_seeker_client()
    try:
        return _dump(await client.get_trace_detail(trace_id))
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
]
