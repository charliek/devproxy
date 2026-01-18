"""Tests for devproxy services."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from devproxy.models.config import CertsConfig
from devproxy.services.cert_service import (
    CertificateError,
    CertService,
    MkcertNotFoundError,
)
from devproxy.services.hosts_service import (
    HostsEntry,
    HostsService,
)


class TestCertService:
    """Tests for CertService."""

    @pytest.fixture
    def cert_service(self, temp_dir: Path) -> CertService:
        """Create a CertService for testing."""
        config = CertsConfig(cert_dir=temp_dir / "certs")
        return CertService(config, "test.local")

    def test_check_mkcert_installed_true(self, cert_service: CertService) -> None:
        """Test mkcert detection when installed."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            assert cert_service.check_mkcert_installed() is True

    def test_check_mkcert_installed_false(self, cert_service: CertService) -> None:
        """Test mkcert detection when not installed."""
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert cert_service.check_mkcert_installed() is False

    def test_get_cert_paths(self, cert_service: CertService) -> None:
        """Test certificate path generation."""
        paths = cert_service._get_cert_paths()
        assert "test_local" in str(paths.cert_file)
        assert paths.cert_file.suffix == ".pem"
        assert paths.key_file.suffix == ".pem"
        assert "-key" in str(paths.key_file)

    def test_get_cert_paths_custom(self, temp_dir: Path) -> None:
        """Test custom certificate paths are used."""
        config = CertsConfig(
            cert_file=temp_dir / "custom.pem",
            key_file=temp_dir / "custom-key.pem",
        )
        service = CertService(config, "test.local")
        paths = service._get_cert_paths()
        assert paths.cert_file == temp_dir / "custom.pem"
        assert paths.key_file == temp_dir / "custom-key.pem"

    def test_certs_exist_false(self, cert_service: CertService) -> None:
        """Test certs_exist returns False when no certs."""
        assert cert_service.certs_exist() is False

    def test_certs_exist_true(self, cert_service: CertService) -> None:
        """Test certs_exist returns True when certs exist."""
        paths = cert_service._get_cert_paths()
        paths.cert_file.parent.mkdir(parents=True, exist_ok=True)
        paths.cert_file.touch()
        paths.key_file.touch()
        assert cert_service.certs_exist() is True

    def test_run_mkcert_not_found(self, cert_service: CertService) -> None:
        """Test MkcertNotFoundError when mkcert missing."""
        with (
            patch("subprocess.run", side_effect=FileNotFoundError),
            pytest.raises(MkcertNotFoundError),
        ):
            cert_service._run_mkcert("-version")

    def test_run_mkcert_failure(self, cert_service: CertService) -> None:
        """Test CertificateError on mkcert failure."""
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error message")
            with pytest.raises(CertificateError):
                cert_service._run_mkcert("-invalid", check=True)

    def test_get_cert_info(self, cert_service: CertService) -> None:
        """Test get_cert_info returns status dictionary."""
        with (
            patch.object(cert_service, "check_mkcert_installed", return_value=True),
            patch.object(cert_service, "get_mkcert_version", return_value="v1.4.4"),
            patch.object(cert_service, "is_ca_installed", return_value=True),
        ):
            info = cert_service.get_cert_info()
            assert "exists" in info
            assert "mkcert_installed" in info
            assert info["mkcert_installed"] is True
            assert info["mkcert_version"] == "v1.4.4"


class TestHostsService:
    """Tests for HostsService."""

    @pytest.fixture
    def hosts_service(self, temp_hosts_file: Path) -> HostsService:
        """Create a HostsService for testing."""
        return HostsService(
            hosts_file=temp_hosts_file,
            domain="test.local",
            services={"app": ("localhost", 3000), "api": ("localhost", 8000)},
        )

    def test_get_required_entries(self, hosts_service: HostsService) -> None:
        """Test required entries generation."""
        entries = hosts_service.get_required_entries()
        hostnames = [e.hostname for e in entries]
        assert "app.test.local" in hostnames
        assert "api.test.local" in hostnames
        assert all(e.ip == "127.0.0.1" for e in entries)

    def test_get_current_entries_empty(self, hosts_service: HostsService) -> None:
        """Test getting current entries when none exist."""
        entries = hosts_service.get_current_entries()
        assert len(entries) == 0

    def test_add_entries(self, hosts_service: HostsService) -> None:
        """Test adding entries to hosts file."""
        change = hosts_service.add_entries()
        assert change.action == "add"
        assert len(change.entries) == 2

        # Verify entries were added
        content = hosts_service.hosts_file.read_text()
        assert "BEGIN devproxy managed block" in content
        assert "app.test.local" in content
        assert "api.test.local" in content
        assert "END devproxy managed block" in content

    def test_add_entries_preview(self, hosts_service: HostsService) -> None:
        """Test preview mode doesn't modify file."""
        original_content = hosts_service.hosts_file.read_text()
        change = hosts_service.add_entries(preview=True)
        assert change.action == "add"
        assert hosts_service.hosts_file.read_text() == original_content

    def test_remove_entries(self, hosts_service: HostsService) -> None:
        """Test removing entries from hosts file."""
        # First add entries
        hosts_service.add_entries()
        assert "devproxy managed block" in hosts_service.hosts_file.read_text()

        # Then remove them
        change = hosts_service.remove_entries()
        assert change.action == "remove"

        content = hosts_service.hosts_file.read_text()
        assert "devproxy managed block" not in content
        assert "localhost" in content  # Original entries preserved

    def test_needs_update_true(self, hosts_service: HostsService) -> None:
        """Test needs_update returns True when entries missing."""
        assert hosts_service.needs_update() is True

    def test_needs_update_false(self, hosts_service: HostsService) -> None:
        """Test needs_update returns False after adding."""
        hosts_service.add_entries()
        assert hosts_service.needs_update() is False

    def test_get_status(self, hosts_service: HostsService) -> None:
        """Test status dictionary generation."""
        status = hosts_service.get_status()
        assert "hosts_file" in status
        assert "writable" in status
        assert "has_managed_block" in status
        assert "needs_update" in status
        assert "required_entries" in status

    def test_idempotent_add(self, hosts_service: HostsService) -> None:
        """Test adding entries multiple times is idempotent."""
        hosts_service.add_entries()
        content1 = hosts_service.hosts_file.read_text()

        hosts_service.add_entries()
        content2 = hosts_service.hosts_file.read_text()

        # Should have exactly one managed block
        assert content1.count("BEGIN devproxy") == 1
        assert content2.count("BEGIN devproxy") == 1


class TestHostsEntry:
    """Tests for HostsEntry dataclass."""

    def test_str_representation(self) -> None:
        """Test string representation."""
        entry = HostsEntry(ip="127.0.0.1", hostname="test.local")
        assert str(entry) == "127.0.0.1 test.local"
