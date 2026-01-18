"""mitmproxy addon for subdomain-based routing."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from mitmproxy import ctx, http


@dataclass
class RequestRecord:
    """Record of a proxied request for logging/inspection."""

    method: str
    url: str
    subdomain: str | None
    target_host: str
    target_port: int
    status_code: int | None
    duration_ms: float
    timestamp: float

    def __str__(self) -> str:
        status = self.status_code or "---"
        return (
            f"{self.method:6} {status:3} {self.duration_ms:6.0f}ms "
            f"{self.subdomain or 'unknown':>10} -> {self.target_host}:{self.target_port} "
            f"{self.url}"
        )


class RouterAddon:
    """mitmproxy addon that routes requests based on subdomain.

    Routes requests like `app.local.stridelabs.ai` to configured local ports.
    """

    def __init__(
        self,
        routes: dict[str, tuple[str, int]],
        domain: str,
        on_request: Callable[[RequestRecord], None] | None = None,
        verbose: bool = False,
    ):
        """Initialize the router addon.

        Args:
            routes: Mapping of subdomain to (host, port) tuples.
                    e.g., {"app": ("localhost", 3000), "api": ("localhost", 8000)}
            domain: Base domain for routing (e.g., "local.stridelabs.ai").
            on_request: Optional callback invoked for each completed request.
            verbose: If True, log requests to console.
        """
        self.routes = routes
        self.domain = domain
        self.on_request = on_request
        self.verbose = verbose

        # Track request start times for duration calculation
        self._request_times: dict[str, float] = {}
        # Limit tracked requests to prevent memory leak from orphaned entries
        self._max_tracked_requests = 10000

    def _extract_subdomain(self, hostname: str) -> str | None:
        """Extract the subdomain from a hostname.

        Args:
            hostname: Full hostname (e.g., "app.local.stridelabs.ai").

        Returns:
            Subdomain string or None if not matching our domain.
        """
        # Check if hostname ends with our domain
        suffix = f".{self.domain}"
        if hostname.endswith(suffix):
            subdomain = hostname[: -len(suffix)]
            # Handle case of exactly one subdomain level
            if subdomain and "." not in subdomain:
                return subdomain
        return None

    def _get_flow_id(self, flow: http.HTTPFlow) -> str:
        """Get a unique ID for a flow to track timing."""
        return str(id(flow))

    def request(self, flow: http.HTTPFlow) -> None:
        """Handle incoming request - route based on subdomain.

        This is called by mitmproxy for each incoming request.
        """
        # Cleanup old entries if dict grows too large (prevents memory leak)
        if len(self._request_times) > self._max_tracked_requests:
            cutoff = time.time() - 300  # Remove entries older than 5 minutes
            self._request_times = {k: v for k, v in self._request_times.items() if v > cutoff}

        # Record start time
        self._request_times[self._get_flow_id(flow)] = time.time()

        # Get the hostname from the request
        hostname = flow.request.pretty_host

        # Extract subdomain
        subdomain = self._extract_subdomain(hostname)

        if subdomain and subdomain in self.routes:
            target_host, target_port = self.routes[subdomain]

            # Rewrite the request to target the local service over HTTP
            flow.request.scheme = "http"
            flow.request.host = target_host
            flow.request.port = target_port

            # Store routing info in flow for response handler
            flow.metadata["devproxy_subdomain"] = subdomain
            flow.metadata["devproxy_target"] = (target_host, target_port)

            if self.verbose:
                ctx.log.alert(f"Routing {subdomain}.{self.domain} -> {target_host}:{target_port}")
        elif subdomain:
            # Subdomain matches our domain pattern but no route configured
            flow.metadata["devproxy_subdomain"] = subdomain
            flow.metadata["devproxy_unrouted"] = True
            if self.verbose:
                ctx.log.alert(f"No route configured for subdomain: {subdomain}")

    def response(self, flow: http.HTTPFlow) -> None:
        """Handle response - log and invoke callback.

        This is called by mitmproxy when a response is received.
        """
        flow_id = self._get_flow_id(flow)
        start_time = self._request_times.pop(flow_id, None)

        duration_ms = (time.time() - start_time) * 1000 if start_time else 0

        subdomain = flow.metadata.get("devproxy_subdomain")
        target = flow.metadata.get("devproxy_target", ("unknown", 0))

        record = RequestRecord(
            method=flow.request.method,
            url=flow.request.pretty_url,
            subdomain=subdomain,
            target_host=target[0],
            target_port=target[1],
            status_code=flow.response.status_code if flow.response else None,
            duration_ms=duration_ms,
            timestamp=time.time(),
        )

        # Invoke callback if provided
        if self.on_request:
            self.on_request(record)

        # Log if verbose
        if self.verbose:
            status = record.status_code or "---"
            ctx.log.alert(f"{record.method} {status} {record.duration_ms:.0f}ms {record.url}")

    def error(self, flow: http.HTTPFlow) -> None:
        """Handle errors in request processing."""
        flow_id = self._get_flow_id(flow)
        self._request_times.pop(flow_id, None)

        subdomain = flow.metadata.get("devproxy_subdomain", "unknown")
        error_msg = flow.error.msg if flow.error else "Unknown error"

        if self.verbose:
            ctx.log.alert(f"Error for {subdomain}: {error_msg}")
