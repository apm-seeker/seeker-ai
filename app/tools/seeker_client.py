from typing import Any

import httpx

from app.config import get_settings
from app.schemas.seeker import (
    AgentMetrics,
    MetricAgents,
    MetricTimeseries,
    Scatter,
    Topology,
    TraceDetails,
    TraceDetailsRequest,
    TraceHistogram,
    TraceView,
    UrlStats,
)


class SeekerWebError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(f"seeker-web {status_code}: {detail}")
        self.status_code = status_code
        self.detail = detail


class SeekerWebClient:
    def __init__(self, base_url: str, timeout_sec: float = 10.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_sec)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
    ) -> Any:
        try:
            response = await self._client.request(
                method, path, params=params, json=json
            )
        except httpx.HTTPError as exc:
            raise SeekerWebError(0, f"network error: {exc}") from exc

        if response.status_code >= 400:
            text = response.text or "(empty body)"
            raise SeekerWebError(response.status_code, text[:500])
        return response.json()

    async def get_topology(
        self, start_time_ms: int, end_time_ms: int
    ) -> Topology:
        data = await self._request(
            "GET",
            "/dashboard/topology",
            params={"startTime": start_time_ms, "endTime": end_time_ms},
        )
        return Topology.model_validate(data)

    async def get_agent_metrics(
        self, agent_id: str, start_time_ms: int, end_time_ms: int
    ) -> AgentMetrics:
        data = await self._request(
            "GET",
            "/dashboard/metrics",
            params={
                "agentId": agent_id,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
            },
        )
        return AgentMetrics.model_validate(data)

    async def get_agent_scatter(
        self, agent_id: str, start_time_ms: int, end_time_ms: int
    ) -> Scatter:
        data = await self._request(
            "GET",
            "/dashboard/scatter",
            params={
                "agentId": agent_id,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
            },
        )
        return Scatter.model_validate(data)

    async def get_trace_histogram(
        self, start_time_ms: int, end_time_ms: int, interval_ms: int
    ) -> TraceHistogram:
        data = await self._request(
            "GET",
            "/traces/histogram",
            params={
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "interval": interval_ms,
            },
        )
        return TraceHistogram.model_validate(data)

    async def get_url_stats(
        self, start_time_ms: int, end_time_ms: int
    ) -> UrlStats:
        data = await self._request(
            "GET",
            "/traces/url-stats",
            params={"startTime": start_time_ms, "endTime": end_time_ms},
        )
        return UrlStats.model_validate(data)

    async def search_traces(self, request: TraceDetailsRequest) -> TraceDetails:
        body = request.model_dump(by_alias=True, exclude_none=True)
        data = await self._request("POST", "/traces/details", json=body)
        return TraceDetails.model_validate(data)

    async def get_trace_detail(self, trace_id: str) -> TraceView:
        data = await self._request("GET", f"/traces/{trace_id}")
        return TraceView.model_validate(data)

    async def get_metric_agents(self) -> MetricAgents:
        data = await self._request("GET", "/metrics/agents")
        return MetricAgents.model_validate(data)

    async def get_metric_timeseries(
        self,
        agent_id: str,
        metric_name: str,
        start_time_ms: int,
        end_time_ms: int,
        interval_ms: int | None = None,
    ) -> MetricTimeseries:
        params: dict[str, Any] = {
            "agentId": agent_id,
            "metricName": metric_name,
            "startTime": start_time_ms,
            "endTime": end_time_ms,
        }
        if interval_ms is not None:
            params["intervalMs"] = interval_ms
        data = await self._request("GET", "/metrics/timeseries", params=params)
        return MetricTimeseries.model_validate(data)


_client: SeekerWebClient | None = None


def get_seeker_client() -> SeekerWebClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = SeekerWebClient(
            base_url=settings.seeker_web_base_url,
            timeout_sec=settings.seeker_web_timeout_sec,
        )
    return _client


async def dispose_seeker_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
