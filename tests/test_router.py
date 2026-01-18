"""Tests for the mitmproxy router addon."""

from unittest.mock import MagicMock

import pytest

from devproxy.addons.router import RequestRecord, RouterAddon


class TestRouterAddon:
    """Tests for RouterAddon class."""

    @pytest.fixture
    def router(self) -> RouterAddon:
        """Create a RouterAddon for testing."""
        return RouterAddon(
            routes={
                "app": ("localhost", 3000),
                "api": ("localhost", 8000),
            },
            domain="test.local",
            verbose=False,
        )

    def test_extract_subdomain_valid(self, router: RouterAddon) -> None:
        """Test subdomain extraction for valid hostnames."""
        assert router._extract_subdomain("app.test.local") == "app"
        assert router._extract_subdomain("api.test.local") == "api"

    def test_extract_subdomain_no_match(self, router: RouterAddon) -> None:
        """Test subdomain extraction for non-matching hostnames."""
        assert router._extract_subdomain("app.other.domain") is None
        assert router._extract_subdomain("test.local") is None
        assert router._extract_subdomain("localhost") is None

    def test_extract_subdomain_nested(self, router: RouterAddon) -> None:
        """Test that nested subdomains are not matched."""
        # Only single-level subdomains should match
        assert router._extract_subdomain("foo.app.test.local") is None

    def test_request_routing(self, router: RouterAddon) -> None:
        """Test that requests are routed correctly."""
        # Create a mock flow
        flow = MagicMock()
        flow.request.pretty_host = "app.test.local"
        flow.request.host = "app.test.local"
        flow.request.port = 443
        flow.metadata = {}

        router.request(flow)

        # Verify routing
        assert flow.request.host == "localhost"
        assert flow.request.port == 3000
        assert flow.metadata["devproxy_subdomain"] == "app"
        assert flow.metadata["devproxy_target"] == ("localhost", 3000)

    def test_request_no_route(self, router: RouterAddon) -> None:
        """Test handling of requests with no matching route."""
        flow = MagicMock()
        flow.request.pretty_host = "unknown.test.local"
        flow.request.host = "unknown.test.local"
        flow.request.port = 443
        flow.metadata = {}

        router.request(flow)

        # Should mark as unrouted but not modify host/port
        assert flow.metadata.get("devproxy_unrouted") is True
        assert flow.request.host == "unknown.test.local"

    def test_request_non_matching_domain(self, router: RouterAddon) -> None:
        """Test handling of requests to different domains."""
        flow = MagicMock()
        flow.request.pretty_host = "example.com"
        flow.request.host = "example.com"
        flow.request.port = 443
        flow.metadata = {}

        router.request(flow)

        # Should not modify anything
        assert "devproxy_subdomain" not in flow.metadata
        assert flow.request.host == "example.com"

    def test_response_creates_record(self, router: RouterAddon) -> None:
        """Test that response handler creates request record."""
        records = []

        def capture_record(record: RequestRecord) -> None:
            records.append(record)

        router.on_request = capture_record

        # Setup flow
        flow = MagicMock()
        flow.request.method = "GET"
        flow.request.pretty_url = "https://app.test.local/path"
        flow.response.status_code = 200
        flow.metadata = {
            "devproxy_subdomain": "app",
            "devproxy_target": ("localhost", 3000),
        }

        # Simulate request/response cycle
        flow_id = router._get_flow_id(flow)
        router._request_times[flow_id] = 0  # Set start time

        router.response(flow)

        assert len(records) == 1
        assert records[0].method == "GET"
        assert records[0].subdomain == "app"
        assert records[0].status_code == 200


class TestRequestRecord:
    """Tests for RequestRecord dataclass."""

    def test_str_representation(self) -> None:
        """Test string representation of request record."""
        record = RequestRecord(
            method="GET",
            url="https://app.test.local/path",
            subdomain="app",
            target_host="localhost",
            target_port=3000,
            status_code=200,
            duration_ms=42.5,
            timestamp=0,
        )
        string = str(record)
        assert "GET" in string
        assert "200" in string
        assert "app" in string
        assert "localhost:3000" in string
