"""Tests for devproxy data models."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from devproxy.models.config import (
    CertsConfig,
    DevProxyConfig,
    ProxyConfig,
    ServiceConfig,
)


class TestServiceConfig:
    """Tests for ServiceConfig model."""

    def test_basic_creation(self) -> None:
        """Test basic ServiceConfig creation."""
        config = ServiceConfig(port=3000)
        assert config.port == 3000
        assert config.host == "localhost"
        assert config.enabled is True

    def test_full_config(self) -> None:
        """Test ServiceConfig with all fields."""
        config = ServiceConfig(port=8080, host="127.0.0.1", enabled=False)
        assert config.port == 8080
        assert config.host == "127.0.0.1"
        assert config.enabled is False

    def test_invalid_port(self) -> None:
        """Test that invalid port raises error."""
        with pytest.raises(ValidationError):
            ServiceConfig(port=0)
        with pytest.raises(ValidationError):
            ServiceConfig(port=70000)

    def test_empty_host_defaults_to_localhost(self) -> None:
        """Test that empty host defaults to localhost."""
        config = ServiceConfig(port=3000, host="")
        assert config.host == "localhost"


class TestProxyConfig:
    """Tests for ProxyConfig model."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = ProxyConfig()
        assert config.https_port == 6789
        assert config.web_ui_port == 8081
        assert config.web_ui_host == "127.0.0.1"

    def test_custom_values(self) -> None:
        """Test custom configuration."""
        config = ProxyConfig(https_port=443, web_ui_port=9000, web_ui_host="0.0.0.0")
        assert config.https_port == 443
        assert config.web_ui_port == 9000
        assert config.web_ui_host == "0.0.0.0"

    def test_disabled_web_ui(self) -> None:
        """Test disabling web UI."""
        config = ProxyConfig(web_ui_port=None)
        assert config.web_ui_port is None


class TestCertsConfig:
    """Tests for CertsConfig model."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = CertsConfig()
        assert config.auto_generate is True
        assert config.cert_file is None
        assert config.key_file is None

    def test_path_expansion(self) -> None:
        """Test that ~ paths are expanded."""
        config = CertsConfig(cert_dir=Path("~/.devproxy/certs"))
        assert "~" not in str(config.cert_dir)
        assert config.cert_dir.is_absolute()

    def test_custom_cert_paths(self) -> None:
        """Test custom certificate paths."""
        config = CertsConfig(
            cert_file=Path("/custom/cert.pem"),
            key_file=Path("/custom/key.pem"),
        )
        assert config.cert_file == Path("/custom/cert.pem")
        assert config.key_file == Path("/custom/key.pem")

    def test_partial_custom_certs_fails(self) -> None:
        """Test that providing only one of cert_file/key_file fails."""
        with pytest.raises(ValidationError):
            CertsConfig(cert_file=Path("/custom/cert.pem"))
        with pytest.raises(ValidationError):
            CertsConfig(key_file=Path("/custom/key.pem"))


class TestDevProxyConfig:
    """Tests for DevProxyConfig model."""

    def test_simple_service_syntax(self) -> None:
        """Test simple service definition (just port)."""
        config = DevProxyConfig(
            domain="test.local",
            services={"app": 3000, "api": 8000},  # type: ignore[arg-type]
        )
        assert config.services["app"].port == 3000
        assert config.services["app"].host == "localhost"
        assert config.services["api"].port == 8000

    def test_extended_service_syntax(self) -> None:
        """Test extended service definition."""
        config = DevProxyConfig(
            domain="test.local",
            services={
                "app": {"port": 3000, "host": "192.168.1.100", "enabled": False},  # type: ignore[dict-item]
            },
        )
        assert config.services["app"].port == 3000
        assert config.services["app"].host == "192.168.1.100"
        assert config.services["app"].enabled is False

    def test_mixed_service_syntax(self) -> None:
        """Test mixing simple and extended service definitions."""
        config = DevProxyConfig(
            domain="test.local",
            services={
                "app": 3000,  # type: ignore[dict-item]
                "api": {"port": 8000, "enabled": True},  # type: ignore[dict-item]
            },
        )
        assert config.services["app"].port == 3000
        assert config.services["api"].port == 8000

    def test_get_service_urls(self) -> None:
        """Test URL generation for services."""
        config = DevProxyConfig(
            domain="test.local",
            services={"app": 3000, "api": 8000},  # type: ignore[arg-type]
        )
        urls = config.get_service_urls()
        assert urls["app"] == "https://app.test.local"
        assert urls["api"] == "https://api.test.local"

    def test_get_enabled_services(self) -> None:
        """Test filtering for enabled services."""
        config = DevProxyConfig(
            domain="test.local",
            services={
                "app": 3000,  # type: ignore[dict-item]
                "disabled": {"port": 9000, "enabled": False},  # type: ignore[dict-item]
            },
        )
        enabled = config.get_enabled_services()
        assert "app" in enabled
        assert "disabled" not in enabled

    def test_get_route_table(self) -> None:
        """Test route table generation."""
        config = DevProxyConfig(
            domain="test.local",
            services={"app": 3000, "api": 8000},  # type: ignore[arg-type]
        )
        routes = config.get_route_table()
        assert routes["app"] == ("localhost", 3000)
        assert routes["api"] == ("localhost", 8000)

    def test_domain_validation(self) -> None:
        """Test domain is cleaned up."""
        config = DevProxyConfig(domain="  .test.local.  ")
        assert config.domain == "test.local"

    def test_empty_services(self) -> None:
        """Test config with no services."""
        config = DevProxyConfig(domain="test.local")
        assert config.services == {}
