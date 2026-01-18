"""Hosts file management service."""

import os
from dataclasses import dataclass
from pathlib import Path

# Markers for the managed block in hosts file
BEGIN_MARKER = "# BEGIN devproxy managed block"
END_MARKER = "# END devproxy managed block"


@dataclass
class HostsEntry:
    """Represents a single hosts file entry."""

    ip: str
    hostname: str

    def __str__(self) -> str:
        return f"{self.ip} {self.hostname}"


@dataclass
class HostsChange:
    """Represents a change to be made to the hosts file."""

    action: str  # "add" or "remove"
    entries: list[HostsEntry]

    @property
    def description(self) -> str:
        """Human-readable description of the change."""
        if self.action == "add":
            return f"Add {len(self.entries)} entries"
        else:
            return f"Remove {len(self.entries)} entries"


class HostsFileError(Exception):
    """Raised when hosts file operations fail."""

    pass


class HostsService:
    """Service for managing /etc/hosts file entries.

    Manages a dedicated block in the hosts file marked with BEGIN/END comments
    to avoid interfering with other entries.
    """

    def __init__(
        self,
        hosts_file: Path,
        domain: str,
        services: dict[str, tuple[str, int]],
    ):
        """Initialize the hosts service.

        Args:
            hosts_file: Path to the hosts file.
            domain: Base domain for service hostnames.
            services: Mapping of service names to (host, port) tuples.

        Raises:
            HostsFileError: If the hosts file path is invalid.
        """
        # Validate hosts file path to prevent writing to unintended locations
        if hosts_file.name != "hosts":
            raise HostsFileError(
                f"Invalid hosts file path: {hosts_file}. "
                "Path must point to a file named 'hosts'."
            )
        self.hosts_file = hosts_file
        self.domain = domain
        self.services = services

    def _read_hosts_file(self) -> list[str]:
        """Read the hosts file content.

        Returns:
            List of lines from the hosts file.

        Raises:
            HostsFileError: If the file cannot be read.
        """
        try:
            if not self.hosts_file.exists():
                return []
            return self.hosts_file.read_text().splitlines()
        except PermissionError as e:
            raise HostsFileError(
                f"Cannot read {self.hosts_file}: Permission denied"
            ) from e
        except OSError as e:
            raise HostsFileError(f"Cannot read {self.hosts_file}: {e}") from e

    def _write_hosts_file(self, lines: list[str]) -> None:
        """Write content to the hosts file.

        Args:
            lines: Lines to write.

        Raises:
            HostsFileError: If the file cannot be written.
        """
        try:
            content = "\n".join(lines)
            # Ensure file ends with newline
            if content and not content.endswith("\n"):
                content += "\n"
            self.hosts_file.write_text(content)
        except PermissionError as e:
            raise HostsFileError(
                f"Cannot write to {self.hosts_file}: Permission denied.\n"
                f"Try running with sudo: sudo devproxy hosts --add"
            ) from e
        except OSError as e:
            raise HostsFileError(f"Cannot write to {self.hosts_file}: {e}") from e

    def _find_managed_block(self, lines: list[str]) -> tuple[int | None, int | None]:
        """Find the start and end indices of the managed block.

        Args:
            lines: Lines from the hosts file.

        Returns:
            Tuple of (start_index, end_index), either can be None if not found.

        Raises:
            HostsFileError: If the hosts file has unpaired markers (corrupted).
        """
        start_idx = None
        end_idx = None

        for i, line in enumerate(lines):
            if line.strip() == BEGIN_MARKER:
                start_idx = i
            elif line.strip() == END_MARKER:
                end_idx = i
                break

        # Validate markers are paired
        if start_idx is not None and end_idx is None:
            raise HostsFileError(
                f"Corrupted hosts file: found BEGIN marker at line {start_idx + 1} "
                "but no END marker. Please manually fix the file by adding "
                f"'{END_MARKER}' or removing the incomplete block."
            )

        return start_idx, end_idx

    def get_required_entries(self) -> list[HostsEntry]:
        """Get the list of hosts entries that should exist.

        Returns:
            List of HostsEntry objects for all services.
        """
        entries = []
        for service_name in self.services:
            hostname = f"{service_name}.{self.domain}"
            entries.append(HostsEntry(ip="127.0.0.1", hostname=hostname))
        return entries

    def get_current_entries(self) -> list[HostsEntry]:
        """Get the current managed entries from the hosts file.

        Returns:
            List of HostsEntry objects currently in the managed block.
        """
        lines = self._read_hosts_file()
        start_idx, end_idx = self._find_managed_block(lines)

        if start_idx is None or end_idx is None:
            return []

        entries = []
        for line in lines[start_idx + 1 : end_idx]:
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split()
                if len(parts) >= 2:
                    ip = parts[0]
                    # Handle multiple hostnames on one line
                    for hostname in parts[1:]:
                        entries.append(HostsEntry(ip=ip, hostname=hostname))

        return entries

    def get_missing_entries(self) -> list[HostsEntry]:
        """Get entries that should exist but don't.

        Returns:
            List of missing HostsEntry objects.
        """
        required = {e.hostname for e in self.get_required_entries()}
        current = {e.hostname for e in self.get_current_entries()}
        missing_hostnames = required - current

        return [e for e in self.get_required_entries() if e.hostname in missing_hostnames]

    def needs_update(self) -> bool:
        """Check if the hosts file needs to be updated.

        Returns:
            True if there are missing or extra entries.
        """
        required = {e.hostname for e in self.get_required_entries()}
        current = {e.hostname for e in self.get_current_entries()}
        return required != current

    def _build_managed_block(self) -> list[str]:
        """Build the managed block content.

        Returns:
            List of lines for the managed block.
        """
        lines = [BEGIN_MARKER]
        entries = self.get_required_entries()
        # Group all hostnames on one line for cleaner output
        if entries:
            hostnames = " ".join(e.hostname for e in entries)
            lines.append(f"127.0.0.1 {hostnames}")
        lines.append(END_MARKER)
        return lines

    def add_entries(self, preview: bool = False) -> HostsChange:
        """Add or update managed entries in the hosts file.

        Args:
            preview: If True, only calculate changes without applying.

        Returns:
            HostsChange describing what was (or would be) done.

        Raises:
            HostsFileError: If the hosts file cannot be modified.
        """
        entries = self.get_required_entries()
        change = HostsChange(action="add", entries=entries)

        if preview:
            return change

        # Check write permission before attempting
        if not os.access(self.hosts_file, os.W_OK):
            raise HostsFileError(
                f"Cannot write to {self.hosts_file}: Permission denied.\n"
                f"Try running with sudo: sudo devproxy hosts --add"
            )

        lines = self._read_hosts_file()
        start_idx, end_idx = self._find_managed_block(lines)

        managed_block = self._build_managed_block()

        if start_idx is not None and end_idx is not None:
            # Replace existing managed block
            new_lines = lines[:start_idx] + managed_block + lines[end_idx + 1 :]
        elif start_idx is not None:
            # Partial block found - remove and append new
            new_lines = [l for l in lines if l.strip() != BEGIN_MARKER]
            new_lines.extend(["", *managed_block])
        else:
            # No existing block - append
            new_lines = lines
            # Add blank line separator if file has content
            if new_lines and new_lines[-1].strip():
                new_lines.append("")
            new_lines.extend(managed_block)

        self._write_hosts_file(new_lines)
        return change

    def remove_entries(self, preview: bool = False) -> HostsChange:
        """Remove managed entries from the hosts file.

        Args:
            preview: If True, only calculate changes without applying.

        Returns:
            HostsChange describing what was (or would be) done.

        Raises:
            HostsFileError: If the hosts file cannot be modified.
        """
        current_entries = self.get_current_entries()
        change = HostsChange(action="remove", entries=current_entries)

        if preview:
            return change

        if not current_entries:
            # Nothing to remove
            return change

        # Check write permission before attempting
        if not os.access(self.hosts_file, os.W_OK):
            raise HostsFileError(
                f"Cannot write to {self.hosts_file}: Permission denied.\n"
                f"Try running with sudo: sudo devproxy hosts --remove"
            )

        lines = self._read_hosts_file()
        start_idx, end_idx = self._find_managed_block(lines)

        if start_idx is None or end_idx is None:
            # No managed block to remove
            return change

        # Remove the managed block (including markers)
        new_lines = lines[:start_idx] + lines[end_idx + 1 :]

        # Clean up any double blank lines left behind
        cleaned_lines = []
        prev_blank = False
        for line in new_lines:
            is_blank = not line.strip()
            if is_blank and prev_blank:
                continue
            cleaned_lines.append(line)
            prev_blank = is_blank

        self._write_hosts_file(cleaned_lines)
        return change

    def get_status(self) -> dict[str, bool | list[str] | str]:
        """Get the current status of hosts file management.

        Returns:
            Dictionary with status information.
        """
        required = self.get_required_entries()
        current = self.get_current_entries()

        return {
            "hosts_file": str(self.hosts_file),
            "writable": os.access(self.hosts_file, os.W_OK),
            "has_managed_block": len(current) > 0,
            "needs_update": self.needs_update(),
            "required_entries": [str(e) for e in required],
            "current_entries": [str(e) for e in current],
        }
