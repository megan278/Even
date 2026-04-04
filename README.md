# ConDash Proxy Server

A lightweight, self-hosted CORS proxy server — drop-in compatible with [corsproxy.io](https://corsproxy.io/).

Built for ConDash, a dashboard app for the Even Realities G2 smart glasses, but works as a general-purpose proxy for any app that targets corsproxy.io.

---

## How It Works

Requests are forwarded using the same URL format as corsproxy.io:

```
GET /?url=https://example.com/api&key=your-api-key
```

The server:
- Forwards the request to the target URL with browser-like headers
- Strips automation-revealing headers (`Sec-Fetch-*`, `Origin`, etc.)
- Returns the upstream response with `Access-Control-Allow-Origin: *`

Any app using corsproxy.io can switch to this server by just changing the proxy base URL in its settings.

---

## Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET / POST / PUT / PATCH / DELETE /?url=<encoded-url>&key=<key>` | Proxy any request |
| `GET /health` | Health check — returns `{"status": "ok"}` |

### Parameters

| Parameter | Required | Description |
|-----------|----------|-------------|
| `url` | Yes | Full URL of the upstream target (URL-encoded) |
| `key` | Conditional | API key — required if `CONDASH_API_KEY` is set |

---

## Security

- **SSRF protection** — Blocks requests to private, loopback, and link-local IP ranges (disable with `ALLOW_PRIVATE_IP=true` for LAN use)
- **Rate limiting** — Per-IP rate limit (default: 120 requests/minute, configurable)
- **Optional API key auth** — Set `CONDASH_API_KEY` to require a key on all requests
- **4 MB request body cap**
- **Hop-by-hop header stripping** — Prevents header leakage to upstream

---

## Configuration

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

| Variable | Default | Description |
|----------|---------|-------------|
| `CONDASH_API_KEY` | *(empty)* | API key for auth. Leave empty to disable auth entirely |
| `RATE_LIMIT` | `120/minute` | Rate limit per IP. [Flask-Limiter format](https://flask-limiter.readthedocs.io/en/stable/#rate-limit-string-notation) |
| `REQUEST_TIMEOUT` | `30` | Upstream request timeout in seconds |
| `PORT` | `5000` | Server port |
| `ALLOW_PRIVATE_IP` | `false` | Set to `true` to allow proxying to private/internal IPs (e.g. self-hosted services on a LAN). Disables SSRF protection — only use on a trusted network |

---

## Running

### Local (Python)

Requires Python 3.10+.

```bash
pip install -r requirements.txt

# Development
python app.py

# Production
gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 60 app:app
```

### Docker

```bash
docker build -t condash-proxy .
docker run -p 5000:5000 --env-file .env condash-proxy
```

### Docker Compose (with auto-updates via Watchtower)

The included `deploy/docker-compose.yml` sets up the proxy alongside [Watchtower](https://containrrr.dev/watchtower/), which automatically pulls and restarts the container when a new image is published to GHCR.

1. **Fork this repo** and enable GitHub Actions (or build/push the image manually).

2. Set the image name in your `.env`:

   ```env
   GITHUB_REPO=your-github-username/your-repo-name
   GHCR_USER=your-github-username
   GHCR_PAT=your-github-pat-with-read-packages-scope
   ```

3. Update the image reference in `deploy/docker-compose.yml` to match your fork:

   ```yaml
   image: ghcr.io/your-github-username/your-repo-name:latest
   ```

4. Deploy:

   ```bash
   docker compose -f deploy/docker-compose.yml up -d
   ```

> **Without auto-updates:** Remove the `watchtower` service block from `docker-compose.yml` and just use `docker compose up -d`.

---

## Connecting ConDash

In the ConDash companion app, go to **App Settings** and set:

| Setting | Value |
|---------|-------|
| Proxy Server URL | `http://your-server-ip:5000/` |
| Proxy API Key | Your `CONDASH_API_KEY` value (or leave blank if not set) |

---

## Stack

- [Flask](https://flask.palletsprojects.com/) + [Gunicorn](https://gunicorn.org/)
- [flask-cors](https://flask-cors.readthedocs.io/)
- [Flask-Limiter](https://flask-limiter.readthedocs.io/)
- [Requests](https://requests.readthedocs.io/)
