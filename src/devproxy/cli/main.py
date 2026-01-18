"""CLI interface for devproxy."""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from devproxy import __version__
from devproxy.addons.router import RequestRecord
from devproxy.config.settings import generate_default_config, load_settings
from devproxy.models.config import CertsConfig
from devproxy.services.cert_service import (
    CertificateError,
    CertService,
    MkcertNotFoundError,
)
from devproxy.services.hosts_service import HostsFileError, HostsService
from devproxy.services.proxy_service import ProxyService, ProxyStartError

app = typer.Typer(
    name="devproxy",
    help="Local HTTPS development proxy with subdomain routing.",
    rich_markup_mode="rich",
    no_args_is_help=True,
)

console = Console()
error_console = Console(stderr=True)


def _print_error(message: str) -> None:
    """Print an error message to stderr."""
    error_console.print(f"[bold red]Error:[/bold red] {message}")


def _print_success(message: str) -> None:
    """Print a success message."""
    console.print(f"[bold green]✓[/bold green] {message}")


def _print_warning(message: str) -> None:
    """Print a warning message."""
    console.print(f"[bold yellow]![/bold yellow] {message}")


@app.command()
def up(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    domain: Annotated[
        str | None,
        typer.Option("--domain", "-d", help="Override base domain"),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", "-p", help="Override HTTPS port"),
    ] = None,
    web_ui: Annotated[
        bool,
        typer.Option("--web-ui/--no-web-ui", help="Enable/disable mitmproxy web UI"),
    ] = True,
    web_ui_port: Annotated[
        int | None,
        typer.Option("--web-ui-port", help="Web UI port"),
    ] = None,
    verbose: Annotated[
        bool,
        typer.Option("--verbose", "-v", help="Print requests to console"),
    ] = False,
) -> None:
    """Start the development proxy server."""
    try:
        # Load settings with CLI overrides
        overrides: dict[str, Any] = {}
        if domain:
            overrides["domain"] = domain
        if port:
            overrides["proxy"] = {"https_port": port}
        if web_ui_port:
            if "proxy" not in overrides:
                overrides["proxy"] = {}
            overrides["proxy"]["web_ui_port"] = web_ui_port
        if not web_ui:
            if "proxy" not in overrides:
                overrides["proxy"] = {}
            overrides["proxy"]["web_ui_port"] = None

        settings = load_settings(config, **overrides)
        settings.verbose = verbose

        # Check for services
        if not settings.services:
            _print_error(
                "No services configured. Add services to your devproxy.yaml:\n\n"
                "services:\n"
                "  app: 3000\n"
                "  api: 8000"
            )
            raise typer.Exit(1)

        # Ensure certificates exist
        cert_service = CertService(settings.certs, settings.domain)

        if not cert_service.check_mkcert_installed():
            _print_error(
                "mkcert is not installed. Install it first:\n"
                "  macOS: brew install mkcert\n"
                "  Linux: apt install mkcert\n"
                "Then run: mkcert -install"
            )
            raise typer.Exit(1)

        if not cert_service.is_ca_installed():
            _print_warning("mkcert CA is not installed. Installing now...")
            try:
                cert_service.install_ca()
                _print_success("mkcert CA installed")
            except CertificateError as e:
                _print_error(f"Failed to install CA: {e}")
                raise typer.Exit(1) from None

        try:
            cert_paths = cert_service.ensure_certs()
        except CertificateError as e:
            _print_error(str(e))
            raise typer.Exit(1) from None

        # Display startup info
        console.print()
        console.print(
            Panel(
                f"[bold]Domain:[/bold] {settings.domain}\n"
                f"[bold]HTTPS Port:[/bold] {settings.proxy.https_port}",
                title="devproxy",
                expand=False,
            )
        )

        # Show service table
        table = Table(title="Services", show_header=True)
        table.add_column("Service", style="cyan")
        table.add_column("URL", style="green")
        table.add_column("Target", style="yellow")

        port_suffix = f":{settings.proxy.https_port}" if settings.proxy.https_port != 443 else ""

        for name, svc in settings.get_enabled_services().items():
            url = f"https://{name}.{settings.domain}{port_suffix}"
            target = f"{svc.host}:{svc.port}"
            table.add_row(name, url, target)

        console.print(table)
        console.print()

        # Create request logger if verbose
        def log_request(record: RequestRecord) -> None:
            status_color = "green" if record.status_code and record.status_code < 400 else "red"
            console.print(
                f"[dim]{record.method:6}[/dim] "
                f"[{status_color}]{record.status_code or '---':>3}[/{status_color}] "
                f"[dim]{record.duration_ms:>6.0f}ms[/dim] "
                f"{record.url}"
            )

        # Create proxy
        proxy = ProxyService(
            proxy_config=settings.proxy,
            domain=settings.domain,
            routes=settings.get_route_table(),
            cert_file=cert_paths.cert_file,
            key_file=cert_paths.key_file,
            verbose=verbose,
            on_request=log_request if verbose else None,
        )

        # Set up signal handlers
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        shutdown_task: asyncio.Task[None] | None = None

        def handle_signal(_sig: int, _frame: object) -> None:
            nonlocal shutdown_task
            console.print("\n[dim]Shutting down...[/dim]")
            # Store task reference to prevent garbage collection during signal handling
            shutdown_task = loop.create_task(proxy.shutdown())

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        try:
            # Start proxy first to get web URL with auth token
            loop.run_until_complete(proxy.start())

            # Print web UI URL with token after proxy starts
            if proxy.web_url:
                console.print(f"[dim]Web UI:[/dim] {proxy.web_url}")

            console.print("[dim]Press Ctrl+C to stop[/dim]")
            console.print()

            # Run the proxy (master is guaranteed to exist after start())
            assert proxy._master is not None
            loop.run_until_complete(proxy._run_master(proxy._master))
        except ProxyStartError as e:
            _print_error(str(e))
            raise typer.Exit(1) from None
        finally:
            loop.run_until_complete(proxy.shutdown())
            loop.close()

    except MkcertNotFoundError as e:
        _print_error(str(e))
        raise typer.Exit(1) from None
    except FileNotFoundError as e:
        _print_error(f"Configuration file not found: {e}")
        raise typer.Exit(1) from None


@app.command()
def init(
    path: Annotated[
        Path,
        typer.Argument(help="Path for configuration file"),
    ] = Path("devproxy.yaml"),
    domain: Annotated[
        str,
        typer.Option("--domain", "-d", help="Base domain"),
    ] = "local.stridelabs.ai",
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Overwrite existing file"),
    ] = False,
) -> None:
    """Create a new configuration file."""
    if path.exists() and not force:
        _print_error(f"File already exists: {path}\nUse --force to overwrite.")
        raise typer.Exit(1)

    content = generate_default_config(domain)
    path.write_text(content)
    _print_success(f"Created configuration file: {path}")


@app.command()
def status(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
) -> None:
    """Show current configuration and status."""
    try:
        settings = load_settings(config)
    except FileNotFoundError:
        _print_warning("No configuration file found. Run 'devproxy init' to create one.")
        raise typer.Exit(0) from None

    # Configuration panel
    config_info = f"[bold]Domain:[/bold] {settings.domain}"
    if settings._config_path:
        config_info += f"\n[bold]Config file:[/bold] {settings._config_path}"

    console.print(Panel(config_info, title="Configuration", expand=False))

    # Services table
    if settings.services:
        table = Table(title="Services", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Port", style="yellow")
        table.add_column("Host", style="dim")
        table.add_column("Status", style="green")

        for name, svc in settings.services.items():
            status = "enabled" if svc.enabled else "[dim]disabled[/dim]"
            table.add_row(name, str(svc.port), svc.host, status)

        console.print(table)
    else:
        _print_warning("No services configured")

    # Proxy settings
    console.print()
    console.print(f"[bold]Proxy:[/bold] port {settings.proxy.https_port}")
    if settings.proxy.web_ui_port:
        console.print(
            f"[bold]Web UI:[/bold] {settings.proxy.web_ui_host}:{settings.proxy.web_ui_port}"
        )
    else:
        console.print("[bold]Web UI:[/bold] disabled")

    # Certificate status
    console.print()
    cert_service = CertService(settings.certs, settings.domain)
    cert_info = cert_service.get_cert_info()

    if cert_info["exists"]:
        console.print(f"[bold green]✓[/bold green] Certificates: {cert_info['cert_file']}")
    else:
        console.print("[bold yellow]![/bold yellow] Certificates: not generated")

    if cert_info["mkcert_installed"]:
        console.print(f"[bold green]✓[/bold green] mkcert: {cert_info['mkcert_version']}")
        if cert_info["ca_installed"]:
            console.print("[bold green]✓[/bold green] CA: installed")
        else:
            console.print("[bold yellow]![/bold yellow] CA: not installed (run 'mkcert -install')")
    else:
        console.print("[bold red]✗[/bold red] mkcert: not installed")


@app.command()
def certs(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    regenerate: Annotated[
        bool,
        typer.Option("--regenerate", "-r", help="Force regenerate certificates"),
    ] = False,
) -> None:
    """Manage TLS certificates."""
    settings = load_settings(config)
    cert_service = CertService(settings.certs, settings.domain)

    if not cert_service.check_mkcert_installed():
        _print_error(
            "mkcert is not installed. Install it first:\n"
            "  macOS: brew install mkcert\n"
            "  Linux: apt install mkcert"
        )
        raise typer.Exit(1)

    # Show current status
    info = cert_service.get_cert_info()
    console.print(f"[bold]mkcert version:[/bold] {info['mkcert_version']}")
    console.print(f"[bold]CA installed:[/bold] {'Yes' if info['ca_installed'] else 'No'}")
    console.print(f"[bold]Certificate directory:[/bold] {settings.certs.cert_dir}")

    if info["exists"] and not regenerate:
        console.print()
        console.print(f"[bold green]✓[/bold green] Certificate: {info['cert_file']}")
        console.print(f"[bold green]✓[/bold green] Key: {info['key_file']}")
        console.print()
        console.print("[dim]Use --regenerate to force regeneration[/dim]")
        return

    # Generate certificates
    if not info["ca_installed"]:
        _print_warning("CA not installed. Installing...")
        try:
            cert_service.install_ca()
            _print_success("CA installed")
        except CertificateError as e:
            _print_error(f"Failed to install CA: {e}")
            raise typer.Exit(1) from None

    console.print()
    if regenerate:
        console.print("[dim]Regenerating certificates...[/dim]")
    else:
        console.print("[dim]Generating certificates...[/dim]")

    try:
        paths = cert_service.ensure_certs(force=regenerate)
        _print_success(f"Certificate: {paths.cert_file}")
        _print_success(f"Key: {paths.key_file}")
    except CertificateError as e:
        _print_error(str(e))
        raise typer.Exit(1) from None


@app.command()
def hosts(
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to configuration file"),
    ] = None,
    add: Annotated[
        bool,
        typer.Option("--add", "-a", help="Add entries to hosts file"),
    ] = False,
    remove: Annotated[
        bool,
        typer.Option("--remove", "-r", help="Remove managed entries"),
    ] = False,
    preview: Annotated[
        bool,
        typer.Option("--preview", "-p", help="Preview changes only"),
    ] = False,
) -> None:
    """Manage /etc/hosts entries.

    This command is only needed if you're using a local domain without
    wildcard DNS. If using a real domain with *.local.yourdomain.com -> 127.0.0.1
    DNS configured, you don't need hosts file entries.
    """
    settings = load_settings(config)

    if not settings.services:
        _print_error("No services configured")
        raise typer.Exit(1)

    hosts_service = HostsService(
        hosts_file=settings.hosts_file,
        domain=settings.domain,
        services=settings.get_route_table(),
    )

    if add and remove:
        _print_error("Cannot use --add and --remove together")
        raise typer.Exit(1)

    try:
        if add:
            change = hosts_service.add_entries(preview=preview)
            if preview:
                console.print("[bold]Would add these entries:[/bold]")
                for entry in change.entries:
                    console.print(f"  {entry}")
                console.print()
                console.print("[dim]Run without --preview to apply changes[/dim]")
            else:
                _print_success(f"Added {len(change.entries)} entries to {settings.hosts_file}")
                for entry in change.entries:
                    console.print(f"  {entry}")

        elif remove:
            change = hosts_service.remove_entries(preview=preview)
            if not change.entries:
                console.print("No managed entries to remove")
                return

            if preview:
                console.print("[bold]Would remove these entries:[/bold]")
                for entry in change.entries:
                    console.print(f"  {entry}")
                console.print()
                console.print("[dim]Run without --preview to apply changes[/dim]")
            else:
                _print_success(f"Removed {len(change.entries)} entries from {settings.hosts_file}")

        else:
            # Show status
            status = hosts_service.get_status()
            console.print(f"[bold]Hosts file:[/bold] {status['hosts_file']}")
            console.print(
                f"[bold]Writable:[/bold] {'Yes' if status['writable'] else 'No (need sudo)'}"
            )
            console.print()

            current_entries = status["current_entries"]
            assert isinstance(current_entries, list)
            if current_entries:
                console.print("[bold]Current managed entries:[/bold]")
                for entry in current_entries:
                    console.print(f"  {entry}")
            else:
                console.print("[dim]No managed entries in hosts file[/dim]")

            console.print()
            console.print("[bold]Required entries:[/bold]")
            required_entries = status["required_entries"]
            assert isinstance(required_entries, list)
            for entry in required_entries:
                console.print(f"  {entry}")

            if status["needs_update"]:
                console.print()
                _print_warning("Hosts file needs update. Run: devproxy hosts --add")

    except HostsFileError as e:
        _print_error(str(e))
        raise typer.Exit(1) from None


@app.command()
def version() -> None:
    """Show version information."""
    console.print(f"devproxy [bold]{__version__}[/bold]")

    # Show mkcert version if available
    cert_service = CertService(CertsConfig(), "placeholder.local")
    mkcert_version = cert_service.get_mkcert_version()
    if mkcert_version:
        console.print(f"mkcert  [bold]{mkcert_version}[/bold]")
    else:
        console.print("mkcert  [dim]not installed[/dim]")

    console.print(f"Python  [bold]{sys.version.split()[0]}[/bold]")


if __name__ == "__main__":
    app()
