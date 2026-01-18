"""Tests for devproxy settings module."""

from pathlib import Path

import pytest

from devproxy.config.settings import (
    DevProxySettings,
    generate_default_config,
    load_settings,
)


class TestDevProxySettings:
    """Tests for DevProxySettings class."""

    def test_default_values(self) -> None:
        """Test default settings values."""
        settings = DevProxySettings()
        assert settings.domain == "local.stridelabs.ai"
        assert settings.verbose is False
        assert settings.proxy.https_port == 6789
        assert settings.proxy.web_ui_port == 8081

    def test_service_normalization(self) -> None:
        """Test that services are normalized from simple to extended format."""
        settings = DevProxySettings(
            services={"app": 3000, "api": 8000},  # type: ignore[arg-type]
        )
        assert settings.services["app"].port == 3000
        assert settings.services["app"].host == "localhost"

    def test_get_service_urls(self) -> None:
        """Test URL generation includes port suffix."""
        settings = DevProxySettings(
            domain="test.local",
            services={"app": 3000},  # type: ignore[arg-type]
        )
        urls = settings.get_service_urls()
        assert urls["app"] == "https://app.test.local:6789"

    def test_get_service_urls_port_443(self) -> None:
        """Test URL generation without port suffix for 443."""
        settings = DevProxySettings(
            domain="test.local",
            services={"app": 3000},  # type: ignore[arg-type]
            proxy={"https_port": 443},  # type: ignore[arg-type]
        )
        urls = settings.get_service_urls()
        assert urls["app"] == "https://app.test.local"


class TestLoadSettings:
    """Tests for load_settings function."""

    def test_load_from_yaml_file(self, temp_config_file: Path) -> None:
        """Test loading settings from YAML file."""
        settings = load_settings(temp_config_file)
        assert settings.domain == "test.local"
        assert "app" in settings.services
        assert settings.services["app"].port == 3000

    def test_load_with_overrides(self, temp_config_file: Path) -> None:
        """Test that explicit overrides take precedence."""
        settings = load_settings(temp_config_file, domain="override.local")
        assert settings.domain == "override.local"

    def test_load_missing_file_returns_defaults(self, temp_dir: Path) -> None:
        """Test that missing file uses defaults."""
        settings = load_settings(temp_dir / "nonexistent.yaml")
        assert settings.domain == "local.stridelabs.ai"

    def test_config_path_stored(self, temp_config_file: Path) -> None:
        """Test that config path is stored in settings."""
        settings = load_settings(temp_config_file)
        assert settings._config_path == temp_config_file


class TestGenerateDefaultConfig:
    """Tests for generate_default_config function."""

    def test_generates_valid_yaml(self) -> None:
        """Test that generated config is valid YAML."""
        import yaml

        config = generate_default_config()
        data = yaml.safe_load(config)
        assert data is not None
        assert "domain" in data
        assert "services" in data
        assert "proxy" in data

    def test_uses_provided_domain(self) -> None:
        """Test that domain parameter is used."""
        config = generate_default_config(domain="custom.example.com")
        assert "custom.example.com" in config

    def test_default_domain(self) -> None:
        """Test default domain value."""
        config = generate_default_config()
        assert "local.stridelabs.ai" in config
