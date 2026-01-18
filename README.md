# devproxy

Local HTTPS development proxy with subdomain routing and request inspection.

**devproxy** provides trusted HTTPS access to multiple local services through subdomain routing. It wraps mitmproxy to deliver a simple YAML-configured proxy that eliminates browser security warnings and enables cookie sharing across local services.

## Features

- **Trusted HTTPS locally** - No browser warnings using mkcert certificates
- **Subdomain routing** - `app.local.stridelabs.ai` → `localhost:3000`
- **Single configuration** - One YAML file defines all service routing
- **Request inspection** - Built-in web UI for debugging HTTP traffic
- **Process manager integration** - Works with Procfile/honcho workflows

## Quick Start

### Prerequisites

Install [mkcert](https://github.com/FiloSottile/mkcert) for certificate generation:

```bash
# macOS
brew install mkcert

# Linux (Debian/Ubuntu)
sudo apt install mkcert

# Linux (Arch)
sudo pacman -S mkcert
```

Install the CA certificate (one-time setup):

```bash
mkcert -install
```

### Installation

```bash
# Using uv (recommended)
uv tool install devproxy

# Or install from source
git clone https://github.com/charliek/devproxy.git
cd devproxy
uv sync
```

### Setup

1. Create a configuration file:

```bash
devproxy init --domain local.stridelabs.ai
```

2. Edit `devproxy.yaml` with your services:

```yaml
domain: local.stridelabs.ai

services:
  app: 3000      # https://app.local.stridelabs.ai
  api: 8000      # https://api.local.stridelabs.ai
  admin: 3001    # https://admin.local.stridelabs.ai

proxy:
  https_port: 6789
  web_ui_port: 8081
```

3. **DNS Setup**: Configure your domain to resolve to localhost. Options:

   **Option A: Wildcard DNS (Recommended)**

   Add a DNS record: `*.local.yourdomain.com → 127.0.0.1`

   **Option B: Hosts file**

   ```bash
   sudo devproxy hosts --add
   ```

4. Start the proxy:

```bash
devproxy up
```

Access your services at:
- https://app.local.stridelabs.ai:6789
- https://api.local.stridelabs.ai:6789

## CLI Commands

| Command | Description |
|---------|-------------|
| `devproxy up` | Start the proxy server |
| `devproxy init` | Create a new configuration file |
| `devproxy status` | Show configuration and status |
| `devproxy certs` | Manage TLS certificates |
| `devproxy hosts` | Manage /etc/hosts entries |
| `devproxy version` | Show version information |

### Common Options

```bash
# Start with verbose logging
devproxy up -v

# Use custom config file
devproxy up -c myconfig.yaml

# Override port (use 443 for clean URLs, requires sudo)
sudo devproxy up --port 443

# Disable web UI
devproxy up --no-web-ui
```

## Configuration

### Full Configuration Reference

```yaml
# Base domain for all services
domain: local.stridelabs.ai

# Service definitions
services:
  # Simple syntax (port only)
  app: 3000

  # Extended syntax
  api:
    port: 8000
    host: localhost
    enabled: true

# Proxy settings
proxy:
  https_port: 6789        # HTTPS listen port
  web_ui_port: 8081       # mitmproxy web UI port (null to disable)
  web_ui_host: 127.0.0.1  # Web UI bind address

# Certificate settings
certs:
  cert_dir: ~/.devproxy/certs
  auto_generate: true
  # Or use custom certificates:
  # cert_file: /path/to/cert.pem
  # key_file: /path/to/key.pem
```

### Environment Variables

Override any setting with `DEVPROXY_` prefix:

```bash
export DEVPROXY_DOMAIN=local.example.com
export DEVPROXY_PROXY__HTTPS_PORT=443
export DEVPROXY_VERBOSE=true
```

## Procfile Integration

Run devproxy alongside your services:

```procfile
proxy: devproxy up --no-web-ui
web: npm run dev
api: python manage.py runserver 8000
```

```bash
honcho start
```

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common issues:
- Certificate and browser trust issues
- Port binding permissions
- Connection refused errors
- Cookie/session problems

## How It Works

```
Browser ──HTTPS──▶ devproxy (port 6789) ──HTTP──▶ localhost:3000 (app)
                         │                    ──▶ localhost:8000 (api)
                         │                    ──▶ localhost:3001 (admin)
                         │
                         └──▶ Web UI (port 8081) for request inspection
```

1. DNS resolves `*.local.stridelabs.ai` to `127.0.0.1`
2. Browser connects to devproxy over HTTPS
3. devproxy terminates TLS using mkcert certificates
4. Routes request to the appropriate local service based on subdomain
5. Returns response to browser

## License

MIT
