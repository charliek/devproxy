"""Proxy service that manages mitmproxy lifecycle."""

import asyncio
import errno
from collections.abc import Callable
from pathlib import Path
from typing import Any

from mitmproxy import options
from mitmproxy.tools.dump import DumpMaster
from mitmproxy.tools.web.master import WebMaster

from devproxy.addons.router import RequestRecord, RouterAddon
from devproxy.models.config import ProxyConfig


class ProxyStartError(Exception):
    """Raised when the proxy fails to start."""

    pass


class ProxyService:
    """Service that manages mitmproxy lifecycle and configuration.

    Handles starting/stopping the proxy with proper certificate configuration
    and subdomain routing.
    """

    def __init__(
        self,
        proxy_config: ProxyConfig,
        domain: str,
        routes: dict[str, tuple[str, int]],
        cert_file: Path,
        key_file: Path,
        verbose: bool = False,
        on_request: Callable[[RequestRecord], None] | None = None,
    ):
        """Initialize the proxy service.

        Args:
            proxy_config: Proxy configuration (ports, web UI settings).
            domain: Base domain for routing.
            routes: Mapping of subdomain to (host, port) tuples.
            cert_file: Path to TLS certificate file.
            key_file: Path to TLS private key file.
            verbose: Enable verbose request logging.
            on_request: Callback for completed requests.
        """
        self.proxy_config = proxy_config
        self.domain = domain
        self.routes = routes
        self.cert_file = cert_file
        self.key_file = key_file
        self.verbose = verbose
        self.on_request = on_request

        self._master: DumpMaster | WebMaster | None = None
        self._shutdown_event: asyncio.Event | None = None

    def _get_combined_cert_path(self) -> Path:
        """Create a combined PEM file with cert and key for mitmproxy.

        mitmproxy expects a single PEM file containing both the certificate
        and private key. This method creates that combined file.

        Returns:
            Path to the combined PEM file.
        """
        combined_path = self.cert_file.parent / f"{self.cert_file.stem}-combined.pem"

        # Read cert and key
        cert_content = self.cert_file.read_text()
        key_content = self.key_file.read_text()

        # Write combined PEM (cert first, then key)
        combined_path.write_text(cert_content + key_content)

        return combined_path

    def _build_options(self) -> options.Options:
        """Build mitmproxy options from configuration.

        Returns:
            Configured Options instance.
        """
        # Create combined cert+key PEM file for mitmproxy
        # mitmproxy expects format: [domain=]path where path is PEM with cert+key
        combined_cert = self._get_combined_cert_path()
        cert_spec = f"*={combined_cert}"

        opts = options.Options(
            listen_host="0.0.0.0",
            listen_port=self.proxy_config.https_port,
            certs=[cert_spec],
            # Regular mode allows RouterAddon to dynamically route requests
            mode=["regular"],
            # SSL/TLS settings
            ssl_insecure=True,  # Allow self-signed certs from backends
        )

        return opts

    def _create_router_addon(self) -> RouterAddon:
        """Create the router addon with current configuration.

        Returns:
            Configured RouterAddon instance.
        """
        return RouterAddon(
            routes=self.routes,
            domain=self.domain,
            on_request=self.on_request,
            verbose=self.verbose,
        )

    async def _run_master(self, master: DumpMaster | WebMaster) -> None:
        """Run the mitmproxy master until shutdown.

        Args:
            master: The master instance to run.
        """
        try:
            await master.run()
        except asyncio.CancelledError:
            pass

    async def start(self) -> None:
        """Start the proxy server.

        Raises:
            ProxyStartError: If the proxy fails to start.
        """
        if self._master is not None:
            raise ProxyStartError("Proxy is already running")

        opts = self._build_options()
        router = self._create_router_addon()

        try:
            # Choose master type based on web UI configuration
            if self.proxy_config.web_ui_port:
                self._master = WebMaster(opts)
                # Configure web UI options AFTER WebMaster creation
                # (WebAddon registers these options during master init)
                self._master.options.web_open_browser = False
                self._master.options.web_host = self.proxy_config.web_ui_host
                self._master.options.web_port = self.proxy_config.web_ui_port
            else:
                self._master = DumpMaster(opts)

            # Add our routing addon
            self._master.addons.add(router)

            # Create shutdown event
            self._shutdown_event = asyncio.Event()

        except OSError as e:
            self._master = None
            if e.errno == errno.EACCES:
                raise ProxyStartError(
                    f"Permission denied binding to port {self.proxy_config.https_port}.\n"
                    f"Options:\n"
                    f"  - Use sudo: sudo devproxy up\n"
                    f"  - Use a port > 1024: devproxy up --port 6789\n"
                    f"  - Grant capabilities (Linux): sudo setcap 'cap_net_bind_service=+ep' $(which python)"
                ) from e
            elif e.errno == errno.EADDRINUSE:
                raise ProxyStartError(
                    f"Port {self.proxy_config.https_port} is already in use.\n"
                    f"Check for other processes: lsof -i :{self.proxy_config.https_port}"
                ) from e
            else:
                raise ProxyStartError(f"Failed to start proxy: {e}") from e

    async def run(self) -> None:
        """Run the proxy until interrupted.

        This is the main entry point for running the proxy. It will block
        until the proxy is shut down.

        Raises:
            ProxyStartError: If the proxy fails to start.
        """
        await self.start()

        if self._master is None:
            raise ProxyStartError("Proxy failed to initialize")

        try:
            await self._run_master(self._master)
        except Exception as e:
            raise ProxyStartError(f"Proxy error: {e}") from e
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully shut down the proxy."""
        if self._master is not None:
            self._master.shutdown()
            self._master = None

        if self._shutdown_event is not None:
            self._shutdown_event.set()

    @property
    def web_url(self) -> str | None:
        """Get the web UI URL with auth token.

        Returns:
            The web URL with token, or None if web UI is disabled or not started.
        """
        if isinstance(self._master, WebMaster):
            return self._master.web_url
        return None

    def get_status(self) -> dict[str, Any]:
        """Get current proxy status.

        Returns:
            Dictionary with proxy status information.
        """
        return {
            "running": self._master is not None,
            "https_port": self.proxy_config.https_port,
            "web_ui_port": self.proxy_config.web_ui_port,
            "web_ui_host": self.proxy_config.web_ui_host,
            "domain": self.domain,
            "routes": {
                name: f"{host}:{port}" for name, (host, port) in self.routes.items()
            },
            "cert_file": str(self.cert_file),
        }
