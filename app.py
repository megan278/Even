"""
ConDash Proxy Server -- corsproxy.io-compatible CORS proxy

Route: any HTTP method to /?url=<encoded-target>&key=<optional-api-key>

Designed to be drop-in compatible with corsproxy.io so users can swap between
the public hosted service and this self-hosted version with no app changes.
"""

import os
import logging
import ipaddress
import socket
from urllib.parse import urlparse

import requests as upstream
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# --- Configuration -------------------------------------------------

API_KEY = os.environ.get('CONDASH_API_KEY', '')
REQUEST_TIMEOUT = int(os.environ.get('REQUEST_TIMEOUT', '30'))
RATE_LIMIT = os.environ.get('RATE_LIMIT', '120/minute')
ALLOW_PRIVATE_IP = os.environ.get('ALLOW_PRIVATE_IP', 'false').strip().lower() == 'true'

# --- App Setup -----------------------------------------------------

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024  # 4 MB

CORS(app, resources={r"/*": {"origins": "*"}})

limiter = Limiter(
	get_remote_address,
	app=app,
	default_limits=[RATE_LIMIT],
	storage_uri='memory://',
)

logging.basicConfig(
	level=logging.INFO,
	format='%(asctime)s [%(levelname)s] %(message)s',
)
logger = logging.getLogger(__name__)

# --- Security Helpers ----------------------------------------------

ALLOWED_METHODS = frozenset({'GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'})

# Headers that should not be forwarded to the upstream server
HOP_BY_HOP = frozenset({
	'host', 'connection', 'keep-alive', 'transfer-encoding',
	'te', 'trailer', 'upgrade', 'proxy-authorization', 'proxy-connection',
	'content-length',  # requests library handles this automatically
	'accept-encoding',  # let requests negotiate its own encoding (gzip/deflate only, no brotli)
 
	# Headers that reveal this is an automated XHR/fetch and not a real browser navigation
	'origin', 'x-requested-with',
	'sec-fetch-mode', 'sec-fetch-site', 'sec-fetch-dest', 'sec-fetch-user',
	'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform',
})

# Fallback browser-like headers injected when the client hasn't supplied them.
# Keeps things looking like a plain browser page load to upstream servers.
BROWSER_DEFAULTS = {
	'User-Agent': (
		'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
		'AppleWebKit/537.36 (KHTML, like Gecko) '
		'Chrome/124.0.0.0 Safari/537.36'
	),
	'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
	'Accept-Language': 'en-US,en;q=0.9',
	'Cache-Control': 'no-cache',
	'Pragma': 'no-cache',
}

# Headers that should not be forwarded back to the client
EXCLUDED_RESPONSE_HEADERS = frozenset({
	'content-encoding', 'transfer-encoding', 'connection', 'content-length',
	'access-control-allow-origin', 'access-control-allow-methods',
	'access-control-allow-headers', 'access-control-expose-headers',
})


def validate_api_key(key: str) -> bool:
	"""Return True if auth passes. When no API_KEY is set, always passes."""
	if not API_KEY:
		return True
	return key == API_KEY


def is_safe_url(url: str) -> tuple[bool, str]:
	"""Validate URL scheme and basic structure."""
	try:
		parsed = urlparse(url)
	except Exception:
		return False, 'Malformed URL'
	if parsed.scheme not in ('http', 'https'):
		return False, 'Only http/https URLs are allowed'
	if not parsed.hostname:
		return False, 'Missing hostname'
	return True, ''


def is_private_ip(hostname: str | None) -> bool:
	"""Return True if the hostname resolves to a private/reserved IP (SSRF guard)."""
	if not hostname:
		return True
	try:
		for info in socket.getaddrinfo(hostname, None):
			ip = ipaddress.ip_address(info[4][0])
			if ip.is_private or ip.is_reserved or ip.is_loopback or ip.is_link_local:
				return True
		return False
	except (socket.gaierror, ValueError):
		# Unresolvable hostname -- block to be safe
		return True

# --- Routes --------------------------------------------------------

@app.route('/health', methods=['GET'])
@limiter.exempt
def health():
	return jsonify(status='ok')


@app.route('/', methods=['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'])
@limiter.limit(RATE_LIMIT)
def proxy():
    
	if request.method == 'OPTIONS':
		return Response("", status=204, headers={
			'Access-Control-Allow-Origin': '*',
			'Access-Control-Allow-Methods': ', '.join(ALLOWED_METHODS),
			'Access-Control-Allow-Headers': '*',
		})

	# -- Auth -------------------------------------------------------
	key = request.args.get('key', '')
	if not validate_api_key(key):
		return jsonify(error='Unauthorized'), 401

	# -- Target URL -------------------------------------------------
	url = request.args.get('url', '').strip()
	if not url:
		return jsonify(error='Missing "url" query parameter. Usage: /?url=https://example.com'), 400

	ok, err = is_safe_url(url)
	if not ok:
		return jsonify(error=err), 400

	parsed = urlparse(url)
	if not ALLOW_PRIVATE_IP and is_private_ip(parsed.hostname):
		return jsonify(error='Requests to private/internal addresses are not allowed'), 403

	# -- Forward the request ----------------------------------------
	method = request.method
	if method not in ALLOWED_METHODS:
		return jsonify(error='Unsupported HTTP method'), 400

	# Forward all request headers, stripping hop-by-hop and automation-revealing headers
	forward_headers = {
		k: v for k, v in request.headers
		if k.lower() not in HOP_BY_HOP
	}

	# Inject browser-like defaults for any headers the client didn't supply
	for header, value in BROWSER_DEFAULTS.items():
		if header.lower() not in {k.lower() for k in forward_headers}:
			forward_headers[header] = value
	body = request.get_data() or None

	logger.info('[PROXY] %s %s', method, url)

	try:
		resp = upstream.request(
			method, url,
			headers=forward_headers,
			data=body,
			timeout=REQUEST_TIMEOUT,
			allow_redirects=True,
			stream=False,
		)
	except upstream.Timeout:
		logger.warning('[PROXY] Timeout -> %s', url)
		return jsonify(error='Upstream request timed out'), 504
	except upstream.ConnectionError as e:
		logger.warning('[PROXY] Connection error -> %s: %s', url, e)
		return jsonify(error='Could not connect to upstream'), 502
	except Exception as e:
		logger.error('[PROXY] Unexpected error -> %s: %s', url, e)
		return jsonify(error='Proxy request failed'), 502

	# Strip hop-by-hop and CORS headers from response (we set our own)
	resp_headers = {
		k: v for k, v in resp.headers.items()
		if k.lower() not in EXCLUDED_RESPONSE_HEADERS
	}
	resp_headers['Access-Control-Allow-Origin'] = '*'
	resp_headers['Access-Control-Expose-Headers'] = '*'

	return Response(resp.content, status=resp.status_code, headers=resp_headers)


if __name__ == '__main__':
	port = int(os.environ.get('PORT', '5000'))
	debug = os.environ.get('FLASK_DEBUG', '0') == '1'
	app.run(host="0.0.0.0", port=port, debug=debug)
