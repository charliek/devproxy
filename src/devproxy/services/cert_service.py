"""Certificate management service using mkcert."""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from devproxy.models.config import CertsConfig


@dataclass
class CertPaths:
    """Paths to certificate and key files."""

    cert_file: Path
    key_file: Path


class MkcertNotFoundError(Exception):
    """Raised when mkcert is not installed."""

    pass


class CertificateError(Exception):
    """Raised when certificate operations fail."""

    pass


class CertService:
    """Service for managing TLS certificates using mkcert.

    Handles certificate generation, CA installation checks, and cert path management.
    """

    def __init__(self, config: CertsConfig, domain: str):
        """Initialize the certificate service.

        Args:
            config: Certificate configuration.
            domain: Base domain for certificate generation.
        """
        self.config = config
        self.domain = domain

    def _run_mkcert(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        """Run mkcert with the given arguments.

        Args:
            *args: Arguments to pass to mkcert.
            check: Whether to raise on non-zero exit code.

        Returns:
            CompletedProcess with stdout/stderr.

        Raises:
            MkcertNotFoundError: If mkcert is not installed.
            CertificateError: If the command fails and check=True.
        """
        try:
            result = subprocess.run(
                ["mkcert", *args],
                capture_output=True,
                text=True,
                check=False,
            )
            if check and result.returncode != 0:
                raise CertificateError(
                    f"mkcert command failed: {result.stderr or result.stdout}"
                )
            return result
        except FileNotFoundError as e:
            raise MkcertNotFoundError(
                "mkcert is not installed. Install it with:\n"
                "  macOS: brew install mkcert\n"
                "  Linux: apt install mkcert (or see https://github.com/FiloSottile/mkcert)\n"
                "  Windows: choco install mkcert"
            ) from e

    def check_mkcert_installed(self) -> bool:
        """Check if mkcert is installed and accessible.

        Returns:
            True if mkcert is installed, False otherwise.
        """
        try:
            result = subprocess.run(
                ["mkcert", "-version"],
                capture_output=True,
                text=True,
                check=False,
            )
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def get_mkcert_version(self) -> str | None:
        """Get the installed mkcert version.

        Returns:
            Version string, or None if mkcert is not installed.
        """
        try:
            result = self._run_mkcert("-version", check=False)
            if result.returncode == 0:
                return result.stdout.strip() or result.stderr.strip()
            return None
        except MkcertNotFoundError:
            return None

    def is_ca_installed(self) -> bool:
        """Check if the mkcert CA is installed in the system trust store.

        Returns:
            True if the CA appears to be installed.
        """
        # mkcert doesn't have a direct "check CA" command, but we can check
        # if the CA root directory exists and has the CA files
        try:
            result = self._run_mkcert("-CAROOT", check=False)
            if result.returncode == 0:
                ca_root = Path(result.stdout.strip())
                root_cert = ca_root / "rootCA.pem"
                return root_cert.exists()
            return False
        except MkcertNotFoundError:
            return False

    def install_ca(self) -> None:
        """Install the mkcert CA into the system trust store.

        This typically requires user interaction (password prompt on macOS/Linux).

        Raises:
            MkcertNotFoundError: If mkcert is not installed.
            CertificateError: If CA installation fails.
        """
        self._run_mkcert("-install")

    def _get_cert_paths(self) -> CertPaths:
        """Get the paths where certificates should be stored.

        Returns:
            CertPaths with cert_file and key_file paths.
        """
        # Use custom paths if provided
        if self.config.cert_file and self.config.key_file:
            return CertPaths(
                cert_file=self.config.cert_file,
                key_file=self.config.key_file,
            )

        # Generate paths based on domain
        cert_dir = self.config.cert_dir
        # mkcert naming convention for wildcard certs
        safe_domain = self.domain.replace(".", "_")
        cert_file = cert_dir / f"_wildcard.{safe_domain}.pem"
        key_file = cert_dir / f"_wildcard.{safe_domain}-key.pem"

        return CertPaths(cert_file=cert_file, key_file=key_file)

    def certs_exist(self) -> bool:
        """Check if certificates already exist.

        Returns:
            True if both cert and key files exist.
        """
        paths = self._get_cert_paths()
        return paths.cert_file.exists() and paths.key_file.exists()

    def _generate_certs(self) -> CertPaths:
        """Generate new certificates using mkcert.

        Returns:
            CertPaths to the generated files.

        Raises:
            MkcertNotFoundError: If mkcert is not installed.
            CertificateError: If certificate generation fails.
        """
        paths = self._get_cert_paths()

        # Ensure cert directory exists
        paths.cert_file.parent.mkdir(parents=True, exist_ok=True)

        # Generate wildcard cert for the domain
        # mkcert -cert-file path -key-file path *.domain.com domain.com
        self._run_mkcert(
            "-cert-file",
            str(paths.cert_file),
            "-key-file",
            str(paths.key_file),
            f"*.{self.domain}",
            self.domain,
        )

        # Verify files were created
        if not paths.cert_file.exists() or not paths.key_file.exists():
            raise CertificateError("Certificate files were not created")

        return paths

    def ensure_certs(self, force: bool = False) -> CertPaths:
        """Ensure certificates exist, generating if needed.

        Args:
            force: If True, regenerate even if certs exist.

        Returns:
            CertPaths to the certificate files.

        Raises:
            MkcertNotFoundError: If mkcert is not installed.
            CertificateError: If certificate operations fail.
        """
        # If using custom certs, just verify they exist
        if self.config.cert_file and self.config.key_file:
            paths = self._get_cert_paths()
            if not paths.cert_file.exists():
                raise CertificateError(f"Custom cert file not found: {paths.cert_file}")
            if not paths.key_file.exists():
                raise CertificateError(f"Custom key file not found: {paths.key_file}")
            return paths

        # Check if auto-generation is enabled
        if not self.config.auto_generate:
            paths = self._get_cert_paths()
            if not self.certs_exist():
                raise CertificateError(
                    f"Certificates not found and auto_generate is disabled.\n"
                    f"Expected: {paths.cert_file}\n"
                    f"Either enable auto_generate or provide custom cert paths."
                )
            return paths

        # Generate if needed
        if force or not self.certs_exist():
            return self._generate_certs()

        return self._get_cert_paths()

    def get_cert_info(self) -> dict[str, str | bool | None]:
        """Get information about certificate status.

        Returns:
            Dictionary with certificate status information.
        """
        paths = self._get_cert_paths()
        return {
            "cert_file": str(paths.cert_file) if paths.cert_file.exists() else None,
            "key_file": str(paths.key_file) if paths.key_file.exists() else None,
            "exists": self.certs_exist(),
            "mkcert_installed": self.check_mkcert_installed(),
            "mkcert_version": self.get_mkcert_version(),
            "ca_installed": self.is_ca_installed(),
            "using_custom_certs": self.config.cert_file is not None,
        }
