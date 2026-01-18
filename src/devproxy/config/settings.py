"""Settings management with YAML file and environment variable support."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from devproxy.models.config import CertsConfig, DevProxyConfig, ProxyConfig, ServiceConfig

# Default config file names to search for
DEFAULT_CONFIG_FILES = ["devproxy.yaml", "devproxy.yml"]


class DevProxySettings(BaseSettings):
    """Application settings with environment variable and YAML file support.

    Configuration priority (highest to lowest):
    1. CLI arguments (passed via __init__)
    2. Environment variables (DEVPROXY_*)
    3. Configuration file (devproxy.yaml)
    4. Default values
    """

    model_config = SettingsConfigDict(
        env_prefix="DEVPROXY_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    # Core settings (can be overridden by env vars)
    domain: str = Field(default="local.stridelabs.ai")
    verbose: bool = Field(default=False)

    # Nested configurations
    services: dict[str, ServiceConfig] = Field(default_factory=dict)
    proxy: ProxyConfig = Field(default_factory=ProxyConfig)
    certs: CertsConfig = Field(default_factory=CertsConfig)

    # Hosts file settings
    hosts_file: Path = Field(default=Path("/etc/hosts"))
    auto_update_hosts: bool = Field(default=False)

    # Internal: path to loaded config file (not from config)
    _config_path: Path | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_services(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Normalize service definitions from simple to extended format."""
        if "services" in data and isinstance(data["services"], dict):
            normalized = {}
            for name, config in data["services"].items():
                if isinstance(config, int):
                    normalized[name] = ServiceConfig(port=config)
                elif isinstance(config, dict):
                    normalized[name] = ServiceConfig(**config)
                elif isinstance(config, ServiceConfig):
                    normalized[name] = config
                else:
                    raise ValueError(f"Invalid service config for '{name}'")
            data["services"] = normalized
        return data

    def get_service_urls(self) -> dict[str, str]:
        """Get mapping of service names to their full URLs."""
        port_suffix = f":{self.proxy.https_port}" if self.proxy.https_port != 443 else ""
        return {
            name: f"https://{name}.{self.domain}{port_suffix}"
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

    def to_config(self) -> DevProxyConfig:
        """Convert settings to a DevProxyConfig model."""
        return DevProxyConfig(
            domain=self.domain,
            services=self.services,
            proxy=self.proxy,
            certs=self.certs,
            hosts_file=self.hosts_file,
            auto_update_hosts=self.auto_update_hosts,
        )


def _load_yaml_file(path: Path) -> dict[str, Any]:
    """Load and parse a YAML configuration file."""
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data if data else {}


def _find_config_file(config_path: Path | None = None) -> Path | None:
    """Find the configuration file to use.

    Args:
        config_path: Explicit path to config file, or None to search.

    Returns:
        Path to config file if found, None otherwise.
    """
    if config_path is not None:
        path = Path(config_path).resolve()
        if path.exists():
            return path
        return None

    # Search for default config files in current directory
    cwd = Path.cwd()
    for filename in DEFAULT_CONFIG_FILES:
        path = cwd / filename
        if path.exists():
            return path

    return None


def load_settings(
    config_path: Path | str | None = None,
    **overrides: Any,
) -> DevProxySettings:
    """Load settings from YAML file and environment variables.

    Args:
        config_path: Path to configuration file, or None to search for default.
        **overrides: Additional settings to override (e.g., from CLI arguments).

    Returns:
        Configured DevProxySettings instance.

    Configuration is loaded in this priority order:
    1. Explicit overrides (CLI arguments)
    2. Environment variables (DEVPROXY_*)
    3. YAML configuration file
    4. Default values
    """
    # Find and load YAML config
    if config_path is not None:
        config_path = Path(config_path)

    found_path = _find_config_file(config_path)
    yaml_config = _load_yaml_file(found_path) if found_path else {}

    # Filter out None values from overrides
    filtered_overrides = {k: v for k, v in overrides.items() if v is not None}

    # Merge: YAML config provides base, overrides take precedence
    # Environment variables are handled automatically by pydantic-settings
    merged_config = {**yaml_config, **filtered_overrides}

    settings = DevProxySettings(**merged_config)
    settings._config_path = found_path

    return settings


def generate_default_config(domain: str = "local.stridelabs.ai") -> str:
    """Generate a default configuration file content.

    Args:
        domain: Base domain to use in the config.

    Returns:
        YAML string with default configuration.
    """
    config = f"""# devproxy configuration
# Documentation: https://github.com/charliek/devproxy

domain: {domain}

services:
  # Add your services here
  # Simple syntax (port only):
  #   app: 3000
  # Extended syntax:
  #   api:
  #     port: 8000
  #     host: localhost
  #     enabled: true

proxy:
  https_port: 6789
  web_ui_port: 8081
  web_ui_host: 127.0.0.1

certs:
  cert_dir: ~/.devproxy/certs
  auto_generate: true

# Hosts file management (only needed for local domains without DNS)
# hosts_file: /etc/hosts
# auto_update_hosts: false
"""
    return config
