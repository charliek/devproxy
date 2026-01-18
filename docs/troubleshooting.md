# Troubleshooting Guide

This guide covers common issues when using devproxy.

## Certificate Issues

### Browser shows "Not Secure" or certificate warnings

**Symptoms:**
- Browser displays security warning
- "NET::ERR_CERT_AUTHORITY_INVALID" error
- Certificate not trusted

**Solutions:**

1. **Verify CA is installed:**
   ```bash
   mkcert -install
   ```

2. **Regenerate certificates:**
   ```bash
   devproxy certs --regenerate
   ```

3. **Check certificate domain matches:**
   ```bash
   openssl x509 -in ~/.devproxy/certs/_wildcard.local_stridelabs_ai.pem -text | grep DNS
   ```

4. **Firefox-specific:** Firefox uses its own certificate store. Import the CA manually:
   - Go to Settings → Privacy & Security → Certificates → View Certificates
   - Click "Authorities" → "Import"
   - Select `~/.local/share/mkcert/rootCA.pem` (Linux) or find via `mkcert -CAROOT`
   - Check "Trust this CA to identify websites"

### mkcert not found

**Symptoms:**
- "mkcert is not installed" error

**Solutions:**

```bash
# macOS
brew install mkcert

# Linux (Debian/Ubuntu)
sudo apt install mkcert

# Linux (Arch)
sudo pacman -S mkcert

# From source (requires Go)
go install filippo.io/mkcert@latest
```

Verify installation:
```bash
mkcert -version
```

## Port Binding Issues

### Permission denied when binding to port 443

**Symptoms:**
- "Permission denied" error
- "OSError: [Errno 13] Permission denied"

**Solutions:**

1. **Use sudo (simple but requires password):**
   ```bash
   sudo devproxy up --port 443
   ```

2. **Use a higher port (no special permissions needed):**
   ```bash
   devproxy up --port 6789
   ```

3. **Grant capabilities (Linux, recommended for port 443):**
   ```bash
   # Find your Python binary
   which python

   # Grant capability (persists across reboots)
   sudo setcap 'cap_net_bind_service=+ep' /path/to/python

   # Now run without sudo
   devproxy up --port 443
   ```

4. **Use port forwarding (macOS):**
   ```bash
   # Create pf rule
   echo "rdr pass inet proto tcp from any to any port 443 -> 127.0.0.1 port 6789" | \
     sudo tee /etc/pf.anchors/devproxy

   # Load the rule
   sudo pfctl -a "com.apple/devproxy" -f /etc/pf.anchors/devproxy
   sudo pfctl -e

   # Now 443 forwards to 6789
   devproxy up --port 6789
   ```

### Port already in use

**Symptoms:**
- "Address already in use" error
- "OSError: [Errno 98]"

**Solutions:**

1. **Find what's using the port:**
   ```bash
   lsof -i :6789
   # or
   ss -tlnp | grep 6789
   ```

2. **Use a different port:**
   ```bash
   devproxy up --port 8443
   ```

3. **Kill the conflicting process:**
   ```bash
   kill $(lsof -t -i :6789)
   ```

## Connection Issues

### Connection refused

**Symptoms:**
- "Connection refused" error in browser
- Cannot reach `https://app.local.stridelabs.ai`

**Checklist:**

1. **Is devproxy running?**
   ```bash
   devproxy status
   ```

2. **Is DNS resolving correctly?**
   ```bash
   dig app.local.stridelabs.ai
   # Should return 127.0.0.1
   ```

3. **Is the target service running?**
   ```bash
   curl http://localhost:3000
   ```

4. **Check firewall rules:**
   ```bash
   # Linux
   sudo iptables -L -n

   # macOS
   sudo pfctl -s rules
   ```

### DNS not resolving

**Symptoms:**
- "DNS_PROBE_FINISHED_NXDOMAIN" error
- Host not found

**Solutions:**

1. **Using wildcard DNS (recommended):**
   - Verify DNS record exists: `dig *.local.yourdomain.com`
   - Check with different DNS: `dig @8.8.8.8 app.local.yourdomain.com`

2. **Using hosts file:**
   ```bash
   # Check current entries
   devproxy hosts

   # Add entries
   sudo devproxy hosts --add
   ```

3. **Flush DNS cache:**
   ```bash
   # macOS
   sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder

   # Linux (systemd-resolved)
   sudo systemd-resolve --flush-caches
   ```

## Cookie and Session Issues

### Cookies not being sent to local services

**Symptoms:**
- Authentication fails
- Session lost between requests
- Cookies visible in devtools but not sent

**Requirements for cookies to work:**

| Attribute | Required Value | Reason |
|-----------|----------------|--------|
| `Domain` | `.stridelabs.ai` | Must include base domain for subdomain access |
| `Secure` | `true` | devproxy provides HTTPS |
| `SameSite` | `Lax` or `None` | `Strict` may block cross-subdomain |
| `Path` | `/` | Unless you want path-specific cookies |

**Debugging steps:**

1. **Check cookie attributes in browser devtools:**
   - Open Network tab
   - Find a request to your service
   - Check Request Headers for `Cookie`
   - Check Response Headers for `Set-Cookie`

2. **Verify cookie domain:**
   - Cookies without explicit `Domain` are host-only
   - Cookie set on `auth.stridelabs.ai` without `Domain=.stridelabs.ai` won't be sent to `app.local.stridelabs.ai`

3. **Check SameSite behavior:**
   - `SameSite=Strict`: Only sent for same-site requests (may break OAuth redirects)
   - `SameSite=Lax`: Sent for top-level navigations
   - `SameSite=None; Secure`: Always sent (requires HTTPS)

### OAuth/SSO redirects failing

**Symptoms:**
- Redirect loop after authentication
- "Invalid redirect URI" error

**Solutions:**

1. **Register local callback URL:**
   - Add `https://app.local.stridelabs.ai:6789/callback` to allowed redirect URIs
   - Or use port 443: `https://app.local.stridelabs.ai/callback`

2. **Check cookie domain on auth server:**
   - Auth cookies should have `Domain=.stridelabs.ai` to be accessible from `*.local.stridelabs.ai`

## Performance Issues

### Slow requests through proxy

**Symptoms:**
- Requests slower than direct connection
- High latency

**Solutions:**

1. **Disable web UI if not needed:**
   ```bash
   devproxy up --no-web-ui
   ```

2. **Check target service health:**
   ```bash
   # Direct request (bypass proxy)
   curl -o /dev/null -s -w "%{time_total}\n" http://localhost:3000

   # Through proxy
   curl -o /dev/null -s -w "%{time_total}\n" https://app.local.stridelabs.ai:6789
   ```

3. **Monitor with verbose mode:**
   ```bash
   devproxy up -v
   ```

## Getting Help

If you're still having issues:

1. **Check the configuration:**
   ```bash
   devproxy status
   ```

2. **Run with verbose logging:**
   ```bash
   devproxy up -v
   ```

3. **Open the web UI for request inspection:**
   - Default: http://localhost:8081

4. **File an issue:** https://github.com/charliek/devproxy/issues
