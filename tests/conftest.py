"""Shared test fixtures for devproxy tests."""

from pathlib import Path
from typing import Generator
import tempfile

import pytest

from devproxy.models.config import CertsConfig, DevProxyConfig, ProxyConfig, ServiceConfig
from devproxy.config.settings import DevProxySettings


@pytest.fixture
def sample_config() -> DevProxyConfig:
    """Create a sample DevProxyConfig for testing."""
    return DevProxyConfig(
        domain="test.local",
        services={
            "app": ServiceConfig(port=3000),
            "api": ServiceConfig(port=8000, host="localhost", enabled=True),
        },
        proxy=ProxyConfig(https_port=6789, web_ui_port=8081),
        certs=CertsConfig(cert_dir=Path("/tmp/test-certs")),
    )


@pytest.fixture
def sample_settings() -> DevProxySettings:
    """Create sample DevProxySettings for testing."""
    return DevProxySettings(
        domain="test.local",
        services={
            "app": ServiceConfig(port=3000),
            "api": ServiceConfig(port=8000),
        },
    )


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def temp_hosts_file(temp_dir: Path) -> Path:
    """Create a temporary hosts file."""
    hosts_file = temp_dir / "hosts"
    hosts_file.write_text(
        "# Sample hosts file\n"
        "127.0.0.1 localhost\n"
        "::1 localhost\n"
    )
    return hosts_file


@pytest.fixture
def temp_config_file(temp_dir: Path) -> Path:
    """Create a temporary config file."""
    config_file = temp_dir / "devproxy.yaml"
    config_file.write_text(
        """
domain: test.local

services:
  app: 3000
  api: 8000

proxy:
  https_port: 6789
"""
    )
    return config_file
