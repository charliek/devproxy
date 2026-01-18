"""Pydantic models for devproxy configuration."""

import re
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

# Domain name validation pattern (RFC 1123 compliant)
DOMAIN_PATTERN = re.compile(
    r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)*$"
)


class ServiceConfig(BaseModel):
    """Configuration for a single service.

    Supports both simple syntax (just port) and extended syntax (full config).
    """

    port: int = Field(..., ge=1, le=65535, description="Port number the service runs on")
    host: str = Field(default="localhost", description="Host where the service runs")
    enabled: bool = Field(default=True, description="Whether routing to this service is enabled")

    @field_validator("host", mode="before")
    @classmethod
    def validate_host(cls, v: str) -> str:
        """Ensure host is not empty."""
        if not v or not v.strip():
            return "localhost"
        return v.strip()


class ProxyConfig(BaseModel):
    """Configuration for the proxy server."""

    https_port: int = Field(
        default=6789,
        ge=1,
        le=65535,
        description="HTTPS port for the proxy to listen on",
    )
    web_ui_port: int | None = Field(
        default=8081,
        ge=1,
        le=65535,
        description="Port for mitmproxy web UI (null to disable)",
    )
    web_ui_host: str = Field(
        default="127.0.0.1",
        description="Host for web UI binding",
    )


class CertsConfig(BaseModel):
    """Configuration for TLS certificates."""

    cert_dir: Path = Field(
        default=Path("~/.devproxy/certs"),
        description="Directory to store generated certificates",
    )
    cert_file: Path | None = Field(
        default=None,
        description="Custom certificate file path (overrides auto_generate)",
    )
    key_file: Path | None = Field(
        default=None,
        description="Custom key file path (overrides auto_generate)",
    )
    auto_generate: bool = Field(
        default=True,
        description="Automatically generate certificates using mkcert",
    )

    @field_validator("cert_dir", mode="before")
    @classmethod
    def expand_cert_dir(cls, v: str | Path) -> Path:
        """Expand ~ in cert_dir path."""
        return Path(v).expanduser()

    @field_validator("cert_file", "key_file", mode="before")
    @classmethod
    def expand_cert_paths(cls, v: str | Path | None) -> Path | None:
        """Expand ~ in cert/key file paths."""
        if v is None:
            return None
        return Path(v).expanduser()

    @model_validator(mode="after")
    def validate_custom_certs(self) -> "CertsConfig":
        """Ensure both cert_file and key_file are provided together."""
        if (self.cert_file is None) != (self.key_file is None):
            raise ValueError("Both cert_file and key_file must be provided together, or neither")
        return self


# Type alias for service configuration that can be either simple (int) or extended (dict)
ServiceConfigInput = int | ServiceConfig | dict[str, int | str | bool]


class DevProxyConfig(BaseModel):
    """Root configuration model for devproxy."""

    domain: str = Field(
        default="local.stridelabs.ai",
        description="Base domain for all services",
    )
    services: Annotated[
        dict[str, ServiceConfig],
        Field(default_factory=dict, description="Service name to configuration mapping"),
    ]
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    certs: CertsConfig = Field(default_factory=CertsConfig)
    hosts_file: Path = Field(
        default=Path("/etc/hosts"),
        description="Path to hosts file",
    )
    auto_update_hosts: bool = Field(
        default=False,
        description="Automatically update hosts file with service entries",
    )

    @field_validator("services", mode="before")
    @classmethod
    def normalize_services(
        cls, v: dict[str, ServiceConfigInput] | None
    ) -> dict[str, ServiceConfig]:
        """Normalize service definitions to extended format.

        Supports:
        - Simple: {"app": 3000}
        - Extended: {"app": {"port": 3000, "host": "localhost", "enabled": true}}
        """
        if v is None:
            return {}

        result: dict[str, ServiceConfig] = {}
        for name, config in v.items():
            if isinstance(config, int):
                # Simple syntax: just port number
                result[name] = ServiceConfig(port=config)
            elif isinstance(config, ServiceConfig):
                # Already a ServiceConfig
                result[name] = config
            elif isinstance(config, dict):
                # Extended syntax: dict with port, host, enabled
                result[name] = ServiceConfig(**config)
            else:
                raise ValueError(f"Invalid service config for '{name}': {config}")
        return result

    @field_validator("domain", mode="before")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validate and clean domain name.

        Ensures the domain contains only valid characters to prevent
        command injection when passed to external tools like mkcert.
        """
        if not v or not v.strip():
            return "local.stridelabs.ai"
        # Remove any leading/trailing dots and whitespace
        cleaned = v.strip().strip(".")
        if not DOMAIN_PATTERN.match(cleaned):
            raise ValueError(
                f"Invalid domain name: {cleaned!r}. "
                "Domain must contain only alphanumeric characters, hyphens, and dots."
            )
        return cleaned

    def get_service_urls(self) -> dict[str, str]:
        """Get mapping of service names to their full URLs."""
        return {
            name: f"https://{name}.{self.domain}"
            for name, config in self.services.items()
            if config.enabled
        }

    def get_enabled_services(self) -> dict[str, ServiceConfig]:
        """Get only enabled services."""
        return {name: config for name, config in self.services.items() if config.enabled}

    def get_route_table(self) -> dict[str, tuple[str, int]]:
        """Get routing table mapping subdomains to (host, port) tuples."""
        return {
            name: (config.host, config.port)
            for name, config in self.services.items()
            if config.enabled
        }
