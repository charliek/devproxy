# devproxy — Technical Specification

> Local HTTPS development proxy with subdomain routing and request inspection

**Version:** 1.0.0-draft  
**Last Updated:** January 2025  
**Status:** Draft

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Use Cases](#3-use-cases)
4. [Solution Overview](#4-solution-overview)
5. [Architecture](#5-architecture)
6. [Configuration](#6-configuration)
7. [Technology Stack](#7-technology-stack)
8. [CLI Reference](#8-cli-reference)
9. [Deployment Patterns](#9-deployment-patterns)
10. [Security Considerations](#10-security-considerations)
11. [Cross-Platform Support](#11-cross-platform-support)
12. [Future Considerations](#12-future-considerations)

---

## 1. Executive Summary

**devproxy** is a developer tool that provides trusted HTTPS access to multiple local services through subdomain routing. It wraps mitmproxy to deliver a simple YAML-configured proxy that eliminates browser security warnings, enables cookie sharing across local services, and provides optional request inspection.

### Key Value Propositions

| Capability | Benefit |
|------------|---------|
| Trusted HTTPS locally | No browser warnings, no disabling certificate checks |
| Subdomain routing | `app.local.stridelabs.ai`, `api.local.stridelabs.ai` → different ports |
| Single configuration | One YAML file defines all service routing |
| Request inspection | Built-in web UI for debugging HTTP traffic |
| Process manager integration | Runs alongside services in Procfile/honcho workflows |

---

## 2. Problem Statement

### 2.1 The Local Development HTTPS Challenge

Modern web development requires HTTPS for:

- **Secure cookies** — `Secure` flag requires HTTPS; `SameSite=None` requires `Secure`
- **Service workers** — Only register on HTTPS origins (except localhost)
- **Mixed content blocking** — HTTPS pages cannot load HTTP resources
- **WebRTC, geolocation, clipboard** — Gated behind secure contexts
- **OAuth flows** — Many providers require HTTPS redirect URIs
- **Production parity** — Testing behavior that only manifests over TLS

### 2.2 Current Workarounds and Their Limitations

| Approach | Limitation |
|----------|------------|
| `localhost` exception | Only works for single service; no subdomains |
| Self-signed certificates | Browser warnings; must click through; breaks automated testing |
| Disable certificate validation | Security risk; doesn't catch TLS-related bugs |
| ngrok/Cloudflare Tunnel | Requires internet; exposes local services; latency |
| Caddy/nginx with mkcert | Manual configuration; no request inspection |
| HTTP Toolkit | Session-based; limited subdomain support |

### 2.3 Multi-Service Architecture Pain

Modern applications often consist of:

```
Frontend (React/Vue)     → localhost:3000
API Server               → localhost:8000  
Admin Dashboard          → localhost:3001
Auth Service (shared)    → production (auth.stridelabs.ai)
```

**Problems:**
- CORS complexity when services run on different ports
- Cookies cannot be shared across different ports on localhost
- OAuth redirects fail without proper domain structure
- Testing SSO/auth flows requires production-like subdomain setup

---

## 3. Use Cases

### 3.1 Primary Use Case: Multi-Service Web Development

**Persona:** Full-stack developer working on a microservices application

**Scenario:**  
Developer runs frontend, API, and admin services locally. They need:
- All services accessible via HTTPS
- Shared authentication cookies across services
- Clean URLs without port numbers
- Ability to debug request/response payloads

**Solution with devproxy:**

```yaml
# devproxy.yaml
domain: local.stridelabs.ai

services:
  app: 3000      # https://app.local.stridelabs.ai
  api: 8000      # https://api.local.stridelabs.ai
  admin: 3001    # https://admin.local.stridelabs.ai
```

### 3.2 Secondary Use Case: OAuth/SSO Development

**Persona:** Developer integrating with production auth service

**Scenario:**  
Application uses `auth.stridelabs.ai` for SSO. Auth cookies are scoped to `.stridelabs.ai`. Developer needs local services to receive these cookies.

**Solution:**  
Using `*.local.stridelabs.ai` subdomain:
- Cookies set with `Domain=.stridelabs.ai` are readable
- OAuth redirects work with registered `local.stridelabs.ai` callback URLs
- No production auth service modification needed

**Cookie Flow:**

```
1. User visits https://app.local.stridelabs.ai
2. Redirected to https://auth.stridelabs.ai/login
3. Auth sets cookie: session=xyz; Domain=.stridelabs.ai
4. Redirected back to https://app.local.stridelabs.ai
5. Browser sends cookie (domain matches!) ✓
```

### 3.3 Tertiary Use Case: API Debugging

**Persona:** Developer troubleshooting API integration issues

**Scenario:**  
Developer needs to inspect exact HTTP requests/responses between frontend and API, including headers, timing, and payload transformations.

**Solution:**  
Enable devproxy's web UI:
```bash
devproxy up --web-ui-port 8081
# Open http://localhost:8081 for mitmproxy web interface
```

### 3.4 Use Case: Team Onboarding

**Persona:** New team member setting up development environment

**Scenario:**  
New developer clones repo and needs to run the full stack locally with proper HTTPS and subdomain routing.

**Solution:**  
```bash
git clone <repo>
cd project
devproxy certs              # Generate/install certificates (one-time)
honcho start                # Starts all services including proxy
# Ready to develop at https://app.local.stridelabs.ai
```

---

## 4. Solution Overview

### 4.1 How It Works

```
                                    ┌─────────────────────────────────┐
                                    │  DNS (Cloudflare/Route53)       │
                                    │  *.local.stridelabs.ai → 127.0.0.1│
                                    └─────────────────────────────────┘
                                                    │
                                                    ▼
┌──────────────┐                    ┌─────────────────────────────────┐
│   Browser    │───── HTTPS ───────▶│         devproxy                │
│              │   (port 6789)      │  ┌───────────────────────────┐  │
│              │                    │  │  TLS Termination          │  │
│              │                    │  │  (mkcert certificates)    │  │
│              │                    │  └───────────────────────────┘  │
│              │                    │              │                  │
│              │                    │  ┌───────────────────────────┐  │
│              │◀─────────────────  │  │  Subdomain Router         │  │
│              │                    │  │  app.* → :3000            │  │
│              │                    │  │  api.* → :8000            │  │
└──────────────┘                    │  │  admin.* → :3001          │  │
                                    │  └───────────────────────────┘  │
       ┌────────────────────────────│              │                  │
       │                            │  ┌───────────────────────────┐  │
       │  http://localhost:8081     │  │  Request Inspector (opt)  │  │
       │  (mitmproxy web UI)        │  │  (mitmweb interface)      │  │
       │                            │  └───────────────────────────┘  │
       │                            └─────────────────────────────────┘
       │                                           │
       │                            ┌──────────────┼──────────────┐
       │                            ▼              ▼              ▼
       │                       ┌────────┐    ┌────────┐    ┌────────┐
       │                       │  :3000 │    │  :8000 │    │  :3001 │
       │                       │Frontend│    │  API   │    │ Admin  │
       │                       └────────┘    └────────┘    └────────┘
       │
       └──────────────▶ Real-time request/response inspection
```

### 4.2 Domain Resolution Strategies

devproxy supports two approaches for routing subdomains to localhost:

#### Strategy A: Real Domain with Wildcard DNS (Recommended)

**Setup (one-time, by domain owner):**
```
DNS Record: *.local.stridelabs.ai  →  A  →  127.0.0.1
```

**Advantages:**
- Works immediately for all team members
- No `/etc/hosts` modification needed
- No per-machine configuration
- Survives network changes

**Requirements:**
- Ownership of a domain
- DNS provider that supports wildcard A records

#### Strategy B: Local Domain with Hosts File

**Setup (per-machine):**
```bash
# /etc/hosts
127.0.0.1 app.dev.local api.dev.local admin.dev.local
```

**Advantages:**
- No domain ownership required
- Works offline
- Full control

**Disadvantages:**
- Manual setup per developer machine
- Must update when adding services
- Requires sudo/admin access

### 4.3 Certificate Management

devproxy uses **mkcert** for certificate generation:

```bash
# One-time CA installation (per machine)
mkcert -install

# devproxy automatically generates:
mkcert "*.local.stridelabs.ai" "local.stridelabs.ai"
# Output: _wildcard.local.stridelabs.ai.pem
#         _wildcard.local.stridelabs.ai-key.pem
```

**Why mkcert over Let's Encrypt for local dev:**

| Factor | mkcert | Let's Encrypt |
|--------|--------|---------------|
| Setup complexity | One command | DNS challenge setup |
| Renewal | Never expires locally | 90-day renewal |
| Offline support | Works offline | Requires internet |
| Team setup | Each dev installs CA | Shared cert management |
| Use case | Local development | Production/staging |

---

## 5. Architecture

### 5.1 Layer Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                           CLI Layer                                  │
│                         (cli/main.py)                               │
│  Commands: up, init, status, certs, hosts, version                  │
│  Framework: Typer + Rich                                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        Configuration Layer                          │
│                       (config/settings.py)                          │
│  - Pydantic Settings for environment variable binding               │
│  - YAML file loading and merging                                    │
│  - Validation and defaults                                          │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Service Layer                              │
├─────────────────────┬─────────────────────┬─────────────────────────┤
│   CertService       │   HostsService      │    ProxyService         │
│   - mkcert wrapper  │   - /etc/hosts mgmt │    - mitmproxy wrapper  │
│   - Cert generation │   - Entry add/remove│    - Lifecycle mgmt     │
│   - CA installation │   - Status check    │    - Addon registration │
└─────────────────────┴─────────────────────┴─────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          Addon Layer                                │
│                        (addons/router.py)                           │
│  - RouterAddon: Subdomain → port routing                            │
│  - RequestRecord: Captures request metadata                         │
│  - Callback hooks for logging/inspection                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       External Dependencies                         │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│  │  mitmproxy   │  │    mkcert    │  │  /etc/hosts  │              │
│  │  (Python)    │  │   (binary)   │  │   (system)   │              │
│  └──────────────┘  └──────────────┘  └──────────────┘              │
└─────────────────────────────────────────────────────────────────────┘
```

### 5.2 Module Structure

```
devproxy/
├── src/devproxy/
│   ├── __init__.py              # Package version
│   │
│   ├── cli/                     # CLI Layer
│   │   ├── __init__.py
│   │   └── main.py              # Typer application and commands
│   │
│   ├── config/                  # Configuration Layer
│   │   ├── __init__.py
│   │   └── settings.py          # Pydantic Settings classes
│   │
│   ├── models/                  # Data Models
│   │   ├── __init__.py
│   │   └── config.py            # DevProxyConfig, ServiceConfig, etc.
│   │
│   ├── services/                # Service Layer
│   │   ├── __init__.py
│   │   ├── cert_service.py      # Certificate management
│   │   ├── hosts_service.py     # Hosts file management
│   │   └── proxy_service.py     # Proxy lifecycle management
│   │
│   └── addons/                  # mitmproxy Addons
│       ├── __init__.py
│       └── router.py            # Subdomain routing addon
│
├── docs/
│   └── SPECIFICATION.md         # This document
│
├── pyproject.toml               # Project configuration
├── devproxy.yaml                # Default config filename
├── config.example.yaml          # Example configuration
└── README.md                    # Quick start guide
```

### 5.3 Data Flow

```
1. CLI Invocation
   $ devproxy up -c devproxy.yaml
           │
           ▼
2. Settings Resolution
   ┌─────────────────────────────────────────┐
   │  Priority (highest → lowest):           │
   │  1. CLI arguments (--port, --domain)    │
   │  2. Environment vars (DEVPROXY_*)       │
   │  3. Config file (devproxy.yaml)         │
   │  4. Default values                      │
   └─────────────────────────────────────────┘
           │
           ▼
3. Service Initialization
   ┌─────────────────────────────────────────┐
   │  CertService.ensure_certs()             │
   │  ├── Check for existing certs           │
   │  ├── Generate via mkcert if needed      │
   │  └── Return cert paths                  │
   └─────────────────────────────────────────┘
           │
           ▼
4. Proxy Startup
   ┌─────────────────────────────────────────┐
   │  ProxyService.start()                   │
   │  ├── Configure mitmproxy options        │
   │  ├── Register RouterAddon               │
   │  ├── Start WebMaster or DumpMaster      │
   │  └── Begin accepting connections        │
   └─────────────────────────────────────────┘
           │
           ▼
5. Request Handling (per request)
   ┌─────────────────────────────────────────┐
   │  RouterAddon.request()                  │
   │  ├── Extract hostname from request      │
   │  ├── Match to service config            │
   │  ├── Rewrite host:port to target        │
   │  └── Forward to upstream service        │
   └─────────────────────────────────────────┘
           │
           ▼
6. Response Handling
   ┌─────────────────────────────────────────┐
   │  RouterAddon.response()                 │
   │  ├── Calculate duration                 │
   │  ├── Record request metadata            │
   │  └── Invoke callback (if verbose)       │
   └─────────────────────────────────────────┘
```

---

## 6. Configuration

### 6.1 Configuration File

**Default filename:** `devproxy.yaml`

This file should be committed to version control, enabling consistent development environment setup across the team.

### 6.2 Complete Configuration Reference

```yaml
# =============================================================================
# devproxy.yaml — Development Proxy Configuration
# =============================================================================

# -----------------------------------------------------------------------------
# Domain Configuration
# -----------------------------------------------------------------------------
# Base domain for all services. Services are accessed as subdomains:
#   app.{domain}, api.{domain}, etc.
#
# Option A: Real domain with wildcard DNS (recommended)
#   Requires: *.local.stridelabs.ai → 127.0.0.1 in DNS
#   Benefit: No /etc/hosts modification needed
#
# Option B: Local domain
#   Requires: Manual /etc/hosts entries or auto_update_hosts: true
#
domain: local.stridelabs.ai

# -----------------------------------------------------------------------------
# Service Definitions
# -----------------------------------------------------------------------------
# Map subdomain names to local ports.
#
# Simple syntax (port only):
#   service_name: port
#
# Extended syntax (full configuration):
#   service_name:
#     port: 3000
#     host: localhost      # Target host (default: localhost)
#     enabled: true        # Enable/disable routing (default: true)
#
services:
  # Frontend application
  app: 3000
  
  # Backend API
  api: 8000
  
  # Admin dashboard (extended syntax example)
  admin:
    port: 3001
    host: localhost
    enabled: true
  
  # Example: Disabled service
  # legacy:
  #   port: 9000
  #   enabled: false

# -----------------------------------------------------------------------------
# Proxy Settings
# -----------------------------------------------------------------------------
proxy:
  # HTTPS listen port
  # Default: 6789 (unprivileged, no sudo required)
  # Use 443 for clean URLs (requires sudo or capabilities)
  https_port: 6789
  
  # mitmproxy web UI port (set to null to disable)
  # Access at http://localhost:{web_ui_port}
  web_ui_port: 8081
  
  # Web UI bind address
  # Use 0.0.0.0 to allow external access (use with caution)
  web_ui_host: 127.0.0.1

# -----------------------------------------------------------------------------
# Certificate Settings
# -----------------------------------------------------------------------------
certs:
  # Directory for storing generated certificates
  cert_dir: ~/.devproxy/certs
  
  # Custom certificate paths (optional)
  # If specified, auto_generate is ignored
  # cert_file: /path/to/wildcard.pem
  # key_file: /path/to/wildcard-key.pem
  
  # Automatically generate certificates using mkcert
  auto_generate: true

# -----------------------------------------------------------------------------
# Hosts File Management (only needed for local domains)
# -----------------------------------------------------------------------------
# Path to hosts file
hosts_file: /etc/hosts

# Automatically update hosts file with service entries
# Requires sudo/root privileges
# Not needed when using real domain with wildcard DNS
auto_update_hosts: false
```

### 6.3 Environment Variable Overrides

All settings can be overridden via environment variables with `DEVPROXY_` prefix:

```bash
# Simple settings
export DEVPROXY_DOMAIN=local.stridelabs.ai
export DEVPROXY_HTTPS_PORT=443
export DEVPROXY_WEB_UI_PORT=8081
export DEVPROXY_VERBOSE=true

# Nested settings use double underscore
export DEVPROXY_PROXY__HTTPS_PORT=443
export DEVPROXY_PROXY__WEB_UI_PORT=8081
export DEVPROXY_CERTS__AUTO_GENERATE=false
```

### 6.4 Configuration Precedence

```
Highest Priority
      │
      ▼
┌─────────────────────────────────┐
│  1. CLI Arguments               │  --port 443 --domain example.com
├─────────────────────────────────┤
│  2. Environment Variables       │  DEVPROXY_HTTPS_PORT=443
├─────────────────────────────────┤
│  3. Configuration File          │  devproxy.yaml
├─────────────────────────────────┤
│  4. Built-in Defaults           │  port=6789, domain=dev.local
└─────────────────────────────────┘
      │
      ▼
Lowest Priority
```

---

## 7. Technology Stack

### 7.1 Core Technologies

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Language | Python | ≥3.13 | Primary implementation language |
| Package Manager | uv | latest | Dependency management, no pip |
| CLI Framework | Typer | ≥0.15.0 | Command-line interface |
| Configuration | Pydantic Settings | ≥2.7.0 | Settings with env var support |
| Data Models | Pydantic | ≥2.10.0 | Configuration validation |
| YAML Parsing | PyYAML | ≥6.0.0 | Config file parsing |
| Proxy Engine | mitmproxy | ≥11.0.0 | HTTPS interception and routing |
| Terminal UI | Rich | ≥13.9.0 | Pretty console output |
| Certificates | mkcert | external | Locally-trusted certificate generation |

### 7.2 Why These Choices

#### Python ≥3.13
- Native support for modern type hints (`dict[str, X]`, `X | None`)
- Performance improvements
- Match statement support
- Matches target audience's likely stack

#### uv over pip
- Significantly faster dependency resolution
- Reproducible builds
- Integrated virtual environment management
- Modern Python packaging best practices

#### mitmproxy over alternatives

| Alternative | Why Not |
|-------------|---------|
| nginx | No Python API; external process; limited inspection |
| Caddy | No Python API; would need to shell out |
| HTTP Toolkit | Commercial; limited subdomain support |
| Custom proxy | Reinventing TLS termination is complex |

**mitmproxy advantages:**
- Full Python API for addon development
- Built-in web UI for request inspection
- Battle-tested TLS implementation
- Active maintenance and community

#### Pydantic Settings
- Type-safe configuration
- Automatic environment variable binding
- Validation with clear error messages
- Nested configuration support

### 7.3 External Dependencies

#### mkcert (required)

**Installation:**

```bash
# macOS
brew install mkcert

# Linux (Debian/Ubuntu)
sudo apt install mkcert

# Linux (Arch)
sudo pacman -S mkcert

# Linux (from source)
go install filippo.io/mkcert@latest

# Windows
choco install mkcert
# or
scoop install mkcert
```

**Verification:**
```bash
mkcert -version
# Expected: v1.4.4 or higher
```

### 7.4 Development Dependencies

| Package | Purpose |
|---------|---------|
| pytest | Testing framework |
| pytest-asyncio | Async test support |
| ruff | Linting and formatting |
| mypy | Static type checking |

---

## 8. CLI Reference

### 8.1 Global Options

```
devproxy [OPTIONS] COMMAND [ARGS]

Options:
  --install-completion    Install shell completion
  --show-completion       Show completion script
  --help                  Show help message
```

### 8.2 Commands

#### `devproxy up`

Start the development proxy server.

```
devproxy up [OPTIONS]

Options:
  -c, --config PATH       Path to config file [default: devproxy.yaml]
  -d, --domain TEXT       Override domain
  -p, --port INTEGER      Override HTTPS port [default: 6789]
  --web-ui / --no-web-ui  Enable/disable web UI [default: enabled]
  --web-ui-port INTEGER   Web UI port [default: 8081]
  -v, --verbose           Print requests to console
  --help                  Show help message
```

**Examples:**

```bash
# Basic usage
devproxy up

# Custom config file
devproxy up -c myproject.yaml

# Override port (use 443 for clean URLs)
sudo devproxy up --port 443

# Verbose mode (print requests)
devproxy up -v

# Headless mode (no web UI)
devproxy up --no-web-ui

# Full customization
devproxy up -c prod.yaml --domain staging.example.com --port 8443 -v
```

#### `devproxy init`

Create a new configuration file.

```
devproxy init [OPTIONS] [PATH]

Arguments:
  PATH    Path for config file [default: devproxy.yaml]

Options:
  -d, --domain TEXT    Base domain [default: dev.local]
  -f, --force          Overwrite existing file
  --help               Show help message
```

**Examples:**

```bash
# Create default config
devproxy init

# Custom domain
devproxy init --domain local.stridelabs.ai

# Custom path
devproxy init config/proxy.yaml

# Overwrite existing
devproxy init --force
```

#### `devproxy status`

Show current configuration and status.

```
devproxy status [OPTIONS]

Options:
  -c, --config PATH    Path to config file [default: devproxy.yaml]
  --help               Show help message
```

**Output:**

```
╭─────────────────────────── Configuration ────────────────────────────╮
│ Domain: local.stridelabs.ai                                          │
╰──────────────────────────────────────────────────────────────────────╯
              Services               
┏━━━━━━━┳━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━┓
┃ Name  ┃ Port ┃ Host      ┃ Status  ┃
┡━━━━━━━╇━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━┩
│ app   │ 3000 │ localhost │ enabled │
│ api   │ 8000 │ localhost │ enabled │
│ admin │ 3001 │ localhost │ enabled │
└───────┴──────┴───────────┴─────────┘

Proxy: port 6789
Web UI: 127.0.0.1:8081

Certificates: ✓ ~/.devproxy/certs/_wildcard.local.stridelabs.ai.pem

Hosts: ✓ Using DNS (no hosts file entries needed)
```

#### `devproxy certs`

Manage TLS certificates.

```
devproxy certs [OPTIONS]

Options:
  -c, --config PATH    Path to config file [default: devproxy.yaml]
  -r, --regenerate     Force regenerate certificates
  --help               Show help message
```

**Examples:**

```bash
# Check certificate status
devproxy certs

# Force regeneration
devproxy certs --regenerate
```

#### `devproxy hosts`

Manage /etc/hosts entries (only needed for local domains).

```
devproxy hosts [OPTIONS]

Options:
  -c, --config PATH    Path to config file [default: devproxy.yaml]
  -a, --add            Add entries to hosts file
  -r, --remove         Remove managed entries
  -p, --preview        Preview changes only
  --help               Show help message
```

**Examples:**

```bash
# Check status
devproxy hosts

# Preview changes
devproxy hosts --preview --add

# Add entries (requires sudo)
sudo devproxy hosts --add

# Remove entries
sudo devproxy hosts --remove
```

#### `devproxy version`

Show version information.

```
devproxy version
```

---

## 9. Deployment Patterns

### 9.1 Standalone Usage

Direct invocation for quick debugging sessions:

```bash
# Start proxy manually
devproxy up -v

# In another terminal, start your app
npm run dev
```

### 9.2 Procfile Integration (Recommended)

Run devproxy alongside your application services using honcho, foreman, or overmind.

**Procfile:**

```procfile
proxy: devproxy up --port 6789 --no-web-ui
web: npm run dev
api: python manage.py runserver 8000
worker: python manage.py runjobs
```

**Usage:**

```bash
# Start all services
honcho start

# Start specific services
honcho start proxy web api
```

**Considerations for Procfile usage:**

| Concern | Solution |
|---------|----------|
| No TTY | devproxy handles non-interactive mode gracefully |
| Log interleaving | Use `--no-web-ui` and `-v` to log to stdout |
| Graceful shutdown | devproxy handles SIGTERM from honcho |
| Port conflicts | Ensure proxy port doesn't conflict with services |

### 9.3 Using Port 443 (Clean URLs)

For URLs without port numbers (`https://app.local.stridelabs.ai`):

#### Option A: Run with sudo (Simple)

```bash
sudo devproxy up --port 443
```

**Procfile with sudo:**

```procfile
# Not recommended for Procfile - requires interactive sudo
proxy: sudo devproxy up --port 443
```

#### Option B: Linux Capabilities (Recommended for Linux)

Grant the Python interpreter capability to bind low ports:

```bash
# Find the Python binary in your virtualenv
which python
# Example: /home/user/project/.venv/bin/python3.13

# Grant capability (one-time, persists across reboots)
sudo setcap 'cap_net_bind_service=+ep' /home/user/project/.venv/bin/python3.13

# Now devproxy can bind to 443 without sudo
devproxy up --port 443
```

**Procfile with capabilities:**

```procfile
proxy: devproxy up --port 443 --no-web-ui
web: npm run dev
api: python manage.py runserver 8000
```

#### Option C: Port Forwarding (macOS)

macOS doesn't support Linux capabilities. Use pf (packet filter) instead:

```bash
# Create pf rule file
echo "rdr pass inet proto tcp from any to any port 443 -> 127.0.0.1 port 6789" | sudo tee /etc/pf.anchors/devproxy

# Load the rule
sudo pfctl -a "com.apple/devproxy" -f /etc/pf.anchors/devproxy
sudo pfctl -e

# Now 443 forwards to 6789
devproxy up --port 6789  # Accessible via https://app.local.stridelabs.ai:443
```

### 9.4 Docker Integration

If services run in Docker:

```yaml
# docker-compose.yml
services:
  app:
    build: ./frontend
    ports:
      - "3000:3000"
  
  api:
    build: ./backend
    ports:
      - "8000:8000"
```

```yaml
# devproxy.yaml
domain: local.stridelabs.ai
services:
  app: 3000
  api: 8000
```

devproxy runs on the host, routing to containerized services via mapped ports.

### 9.5 Environment-Specific Configuration

```bash
project/
├── devproxy.yaml           # Default (committed)
├── devproxy.local.yaml     # Personal overrides (gitignored)
└── .env                    # Environment variables (gitignored)
```

**devproxy.yaml (committed):**
```yaml
domain: local.stridelabs.ai
services:
  app: 3000
  api: 8000
```

**.env (gitignored):**
```bash
DEVPROXY_HTTPS_PORT=443
DEVPROXY_VERBOSE=true
```

---

## 10. Security Considerations

### 10.1 Certificate Security

| Aspect | Implementation |
|--------|----------------|
| CA Scope | mkcert CA is local to the machine; not trusted elsewhere |
| Key Storage | Private keys stored in `~/.devproxy/certs/` with user-only permissions |
| Rotation | Certificates don't expire for local use; regenerate with `--regenerate` if needed |

**Recommendation:** Do not commit certificates to version control. Add to `.gitignore`:

```gitignore
# devproxy certificates
~/.devproxy/
*.pem
*-key.pem
```

### 10.2 Network Exposure

**Default behavior:** Proxy binds to `0.0.0.0` (all interfaces) for HTTPS, `127.0.0.1` for web UI.

**Risk:** If on a shared network, others could access your local services.

**Mitigations:**
1. Use firewall rules to block external access to proxy port
2. Bind to localhost only (limits subdomain routing usefulness)
3. Use VPN when on untrusted networks

### 10.3 Hosts File Modification

The `auto_update_hosts` feature modifies `/etc/hosts`, which:
- Requires sudo/root privileges
- Affects system-wide DNS resolution
- Managed entries are clearly marked for easy identification

**Managed block format:**
```
# BEGIN devproxy managed block
127.0.0.1 app.dev.local api.dev.local admin.dev.local
# END devproxy managed block
```

**Recommendation:** Use real domain with wildcard DNS to avoid hosts file modification entirely.

### 10.4 Cookie Security with Production Auth

When using cookies from production auth service:

| Cookie Attribute | Requirement | Reason |
|-----------------|-------------|--------|
| `Domain` | `.stridelabs.ai` | Allow subdomain access including `*.local.stridelabs.ai` |
| `Secure` | Yes | devproxy provides HTTPS |
| `SameSite` | `Lax` or `None` | `Strict` may block redirects |
| `HttpOnly` | Yes (recommended) | Prevent XSS access to session |

**Note:** Cookies set without explicit `Domain` attribute are scoped to exact host only and won't work with this setup.

---

## 11. Cross-Platform Support

### 11.1 Support Matrix

| Platform | Status | Notes |
|----------|--------|-------|
| Linux (Ubuntu/Debian) | ✅ Full | Primary development platform |
| Linux (Fedora/RHEL) | ✅ Full | May need different mkcert install |
| macOS (Intel) | ✅ Full | Use pf for port 443 |
| macOS (Apple Silicon) | ✅ Full | Same as Intel |
| Windows (WSL2) | ✅ Full | Runs in Linux environment |
| Windows (Native) | ⚠️ Partial | mitmproxy support varies |

### 11.2 Platform-Specific Notes

#### Linux

```bash
# Install mkcert
sudo apt install mkcert  # Debian/Ubuntu
sudo dnf install mkcert  # Fedora
yay -S mkcert            # Arch (AUR)

# Install CA
mkcert -install

# Optional: Allow binding to port 443 without sudo
sudo setcap 'cap_net_bind_service=+ep' $(which python3)
```

#### macOS

```bash
# Install mkcert
brew install mkcert

# Install CA (adds to system keychain)
mkcert -install

# Port 443 requires either sudo or pf forwarding
# See Section 9.3 Option C
```

#### Windows (WSL2)

```bash
# Inside WSL2, follow Linux instructions
sudo apt install mkcert
mkcert -install

# Note: Browser must be configured to use WSL2's certificate store
# or install the CA in Windows as well
```

### 11.3 Browser Compatibility

After mkcert CA installation, certificates are trusted in:

| Browser | Status | Notes |
|---------|--------|-------|
| Chrome | ✅ | Automatic via system store |
| Firefox | ⚠️ | May need manual CA import |
| Safari | ✅ | Automatic via Keychain |
| Edge | ✅ | Automatic via system store |

**Firefox manual import:**
```
Settings → Privacy & Security → Certificates → View Certificates
→ Authorities → Import → Select ~/.local/share/mkcert/rootCA.pem
```

---

## 12. Future Considerations

### 12.1 Potential Enhancements

#### Request Recording & Replay

```yaml
# Future config option
recording:
  enabled: true
  path: ./recordings/
  format: har  # HTTP Archive format
```

#### Service Health Checks

```yaml
services:
  api:
    port: 8000
    healthcheck:
      path: /health
      interval: 10s
```

#### Hot Reload Configuration

Watch `devproxy.yaml` for changes and update routing without restart.

#### Docker-Native Mode

Run devproxy itself in Docker with proper networking:

```yaml
# docker-compose.yml
services:
  devproxy:
    image: devproxy:latest
    ports:
      - "443:443"
    volumes:
      - ./devproxy.yaml:/config/devproxy.yaml
```

### 12.2 Non-Goals

The following are explicitly out of scope:

| Feature | Reason |
|---------|--------|
| Production deployment | Use proper reverse proxy (nginx, Caddy, Traefik) |
| Let's Encrypt integration | Adds complexity; mkcert sufficient for local dev |
| Load balancing | Single-developer tool; use k8s/docker-compose for multi-instance |
| WebSocket inspection | mitmproxy limitation; standard proxying works |
| gRPC support | Different protocol; use grpcurl or similar |

---

## Appendix A: Quick Reference Card

```
┌─────────────────────────────────────────────────────────────────────┐
│                    devproxy Quick Reference                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SETUP                                                              │
│  ─────                                                              │
│  $ brew install mkcert && mkcert -install    # Install CA (once)   │
│  $ uv tool install devproxy                  # Install devproxy    │
│  $ devproxy init                             # Create config       │
│                                                                     │
│  DAILY USE                                                          │
│  ─────────                                                          │
│  $ devproxy up                    # Start proxy                     │
│  $ devproxy up -v                 # Start with request logging      │
│  $ devproxy up --port 443         # Use standard HTTPS port (sudo)  │
│  $ devproxy status                # Check configuration             │
│                                                                     │
│  CONFIG FILE (devproxy.yaml)                                        │
│  ───────────────────────────                                        │
│  domain: local.stridelabs.ai                                        │
│  services:                                                          │
│    app: 3000                      # https://app.local.stridelabs.ai │
│    api: 8000                      # https://api.local.stridelabs.ai │
│  proxy:                                                             │
│    https_port: 6789                                                 │
│    web_ui_port: 8081              # http://localhost:8081           │
│                                                                     │
│  ENV OVERRIDES                                                      │
│  ─────────────                                                      │
│  DEVPROXY_DOMAIN=example.com                                        │
│  DEVPROXY_HTTPS_PORT=443                                            │
│  DEVPROXY_VERBOSE=true                                              │
│                                                                     │
│  PROCFILE                                                           │
│  ────────                                                           │
│  proxy: devproxy up --port 6789 --no-web-ui                        │
│  web: npm run dev                                                   │
│  api: python manage.py runserver 8000                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Appendix B: Troubleshooting

### Certificate Issues

**Problem:** Browser shows "Not Secure" despite mkcert setup

**Solutions:**
1. Verify CA is installed: `mkcert -install`
2. Regenerate certificates: `devproxy certs --regenerate`
3. Firefox: Manually import CA (see Section 11.3)
4. Check certificate domain matches: `openssl x509 -in cert.pem -text | grep DNS`

### Port Binding Issues

**Problem:** `Permission denied` when binding to port 443

**Solutions:**
1. Use sudo: `sudo devproxy up --port 443`
2. Use capabilities (Linux): `sudo setcap 'cap_net_bind_service=+ep' $(which python3)`
3. Robugs setcap (Linux): `sudo setcap 'cap_net_bind_service=+ep' "$(readlink -f $(uv tool run --from devproxy which python))"` 
4. Use higher port: `devproxy up --port 6789`

### Connection Refused

**Problem:** Browser can't connect to `https://app.local.stridelabs.ai`

**Solutions:**
1. Verify DNS resolution: `dig app.local.stridelabs.ai`
2. Check proxy is running: `devproxy status`
3. Verify service is running: `curl http://localhost:3000`
4. Check firewall rules

### Cookie Not Sent

**Problem:** Auth cookies not reaching local services

**Solutions:**
1. Verify cookie `Domain` attribute includes base domain
2. Check `SameSite` attribute allows cross-site
3. Ensure HTTPS is working (required for `Secure` cookies)
4. Use browser devtools Network tab to inspect cookie headers

---

## Appendix C: Glossary

| Term | Definition |
|------|------------|
| **mkcert** | Tool that creates locally-trusted development certificates |
| **mitmproxy** | Interactive HTTPS proxy for debugging and development |
| **TLS Termination** | Decrypting HTTPS traffic at the proxy level |
| **Reverse Proxy** | Server that forwards requests to backend services |
| **Wildcard DNS** | DNS record that matches any subdomain (e.g., `*.example.com`) |
| **CA (Certificate Authority)** | Entity that issues digital certificates |
| **SameSite** | Cookie attribute controlling cross-site request behavior |
| **Procfile** | File defining process types for process managers like Honcho |
| **honcho** | Python process manager for Procfile-based applications |

---

*End of Specification*