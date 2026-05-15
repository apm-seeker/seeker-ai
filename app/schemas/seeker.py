from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _CamelModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="allow")


# --- /dashboard/topology ---


class TopologyNode(_CamelModel):
    agent_id: str = Field(alias="agentId")
    agent_name: str | None = Field(default=None, alias="agentName")
    agent_type: str | None = Field(default=None, alias="agentType")
    error_rate: float = Field(default=0.0, alias="errorRate")


class TopologyEdge(_CamelModel):
    from_agent_id: str = Field(alias="fromAgentId")
    to_agent_id: str = Field(alias="toAgentId")
    tps: float = 0.0
    avg_latency: float = Field(default=0.0, alias="avgLatency")
    error_rate: float = Field(default=0.0, alias="errorRate")


class Topology(_CamelModel):
    nodes: list[TopologyNode] = []
    edges: list[TopologyEdge] = []


# --- /dashboard/metrics ---


class AgentMetrics(_CamelModel):
    total_count: int = Field(default=0, alias="totalCount")
    error_count: int = Field(default=0, alias="errorCount")
    error_rate: float | None = Field(default=None, alias="errorRate")
    p99: float | None = None
    p95: float | None = None
    p90: float | None = None


# --- /dashboard/scatter ---


class ScatterSummary(_CamelModel):
    total_count: int = Field(default=0, alias="totalCount")
    error_count: int = Field(default=0, alias="errorCount")
    error_rate: float | None = Field(default=None, alias="errorRate")


class ScatterPoint(_CamelModel):
    trace_id: str = Field(alias="traceId")
    span_id: int = Field(alias="spanId")
    start_time: int = Field(alias="startTime")
    elapsed_time: int = Field(alias="elapsedTime")
    status_code: int = Field(alias="statusCode")
    is_error: bool = Field(default=False, alias="isError")


class Scatter(_CamelModel):
    summary: ScatterSummary
    points: list[ScatterPoint] = []


# --- /traces/histogram ---


class HistogramBoundary(_CamelModel):
    from_: int = Field(alias="from")
    to: int | None = None


class HistogramBin(_CamelModel):
    timestamp: int
    counts: list[int] = []


class TraceHistogram(_CamelModel):
    interval: int
    boundaries: list[HistogramBoundary] = []
    bins: list[HistogramBin] = []


# --- /traces/url-stats ---


class UrlStatRow(_CamelModel):
    url: str
    total_count: int = Field(default=0, alias="totalCount")
    failure_count: int = Field(default=0, alias="failureCount")
    avg_ms: int = Field(default=0, alias="avgMs")
    p95_ms: int = Field(default=0, alias="p95Ms")


class UrlStats(_CamelModel):
    rows: list[UrlStatRow] = []


# --- /traces/details ---

TraceOrderBy = Literal[
    "startTime_desc", "startTime_asc", "duration_desc", "duration_asc"
]
TraceStatus = Literal["success", "error"]


class TraceDetailsRequest(_CamelModel):
    start_time: int = Field(alias="startTime")
    end_time: int = Field(alias="endTime")
    url: str | None = None
    statuses: list[TraceStatus] | None = None
    duration_from: int | None = Field(default=None, alias="durationFrom")
    duration_to: int | None = Field(default=None, alias="durationTo")
    agent_ids: list[str] | None = Field(default=None, alias="agentIds")
    exception_classes: list[str] | None = Field(
        default=None, alias="exceptionClasses"
    )
    trace_id_prefix: str | None = Field(default=None, alias="traceIdPrefix")
    order_by: TraceOrderBy | None = Field(default="startTime_desc", alias="orderBy")
    limit: int | None = 100
    offset: int | None = 0


class AgentRef(_CamelModel):
    id: str
    agent_name: str | None = Field(default=None, alias="agentName")


class TraceDetailRow(_CamelModel):
    trace_id: str = Field(alias="traceId")
    agents: list[AgentRef] = []
    url_path: str | None = Field(default=None, alias="urlPath")
    duration: int = 0
    status_code: int = Field(default=0, alias="statusCode")
    exception_class: str | None = Field(default=None, alias="exceptionClass")
    start_time: int = Field(alias="startTime")


class TraceDetails(_CamelModel):
    rows: list[TraceDetailRow] = []
    total: int = 0
    has_more: bool = Field(default=False, alias="hasMore")


# --- /traces/{traceId} ---


class SpanEvent(_CamelModel):
    sequence: int = 0
    depth: int = 0
    start_time: int = Field(alias="startTime")
    elapsed_time: int = Field(alias="elapsedTime")
    class_name: str | None = Field(default=None, alias="className")
    method_name: str | None = Field(default=None, alias="methodName")
    exception_info: str | None = Field(default=None, alias="exceptionInfo")
    attributes: dict[str, Any] = {}


class Span(_CamelModel):
    span_id: str = Field(alias="spanId")
    parent_span_id: str = Field(alias="parentSpanId")
    agent_id: str = Field(alias="agentId")
    agent_name: str | None = Field(default=None, alias="agentName")
    start_time: int = Field(alias="startTime")
    elapsed_time: int = Field(alias="elapsedTime")
    uri: str | None = None
    end_point: str | None = Field(default=None, alias="endPoint")
    remote_address: str | None = Field(default=None, alias="remoteAddress")
    status_code: int = Field(default=0, alias="statusCode")
    exception_info: str | None = Field(default=None, alias="exceptionInfo")
    events: list[SpanEvent] = []


class TraceView(_CamelModel):
    trace_id: str = Field(alias="traceId")
    start_time: int = Field(alias="startTime")
    duration: int = 0
    status_code: int = Field(default=0, alias="statusCode")
    exception_class: str | None = Field(default=None, alias="exceptionClass")
    agents: list[AgentRef] = []
    spans: list[Span] = []
