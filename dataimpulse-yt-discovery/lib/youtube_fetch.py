"""
HTTP session manager with proxy support, exponential backoff retries,
rate limiting, CONSENT cookie, and SQLite response caching.
"""

import logging
import random
import ssl
import time

import requests
import requests.adapters

from lib import db as db_mod

log = logging.getLogger(__name__)

# Markers that indicate YouTube anti-bot pages
CAPTCHA_MARKERS = [
    "unusual traffic from your computer",
    "our systems have detected unusual traffic",
    "solve the above challenge",
    "recaptcha",
    "/sorry/index",
]


class YouTubeFetcher:
    """Manages HTTP session, proxy rotation, rate-limiting, caching, and retries."""

    def __init__(self, cfg: dict, db_conn):
        self.cfg = cfg
        self.db_conn = db_conn

        proxy_cfg = cfg.get("proxy", {})
        rl_cfg = cfg.get("rate_limit", {})

        self.proxy_url = proxy_cfg.get("resolved_url")
        self.fallback_direct = proxy_cfg.get("fallback_direct", True)
        self.ssl_verify = proxy_cfg.get("ssl_verify", True)
        self.retry_max = rl_cfg.get("retry_max", 3)
        self.retry_base_wait = rl_cfg.get("retry_base_wait", 2)
        self.min_interval = 1.0 / max(rl_cfg.get("requests_per_second", 1.5), 0.1)

        self._last_request_time = 0.0
        self._using_proxy = False  # Start direct, switch on 403/429
        self._ssl_fallback = False  # Only set True after SSL failure through proxy

        # Build session
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        # CONSENT cookie to bypass EU consent page
        consent_val = f"YES+cb.20210328-17-p0.en+FX+{random.randint(100, 999)}"
        self.session.cookies.set("CONSENT", consent_val, domain=".youtube.com")

        # Stats
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0, "proxy_switches": 0}

    # ── Rate limiting ────────────────────────────────────────

    def _rate_limit(self):
        """Sleep to enforce requests_per_second."""
        elapsed = time.monotonic() - self._last_request_time
        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            time.sleep(sleep_time)
        self._last_request_time = time.monotonic()

    # ── Core fetch ───────────────────────────────────────────

    def fetch(self, url: str, use_cache: bool = True,
              cache_ttl_hours: int = 24) -> str | None:
        """
        Fetch a URL with retries, proxy fallback, rate-limiting, and caching.
        Returns response text or None on failure.
        """
        # Check cache first
        if use_cache and self.db_conn:
            cached = db_mod.get_cached_response(self.db_conn, url, cache_ttl_hours)
            if cached is not None:
                self.stats["cache_hits"] += 1
                log.debug("Cache hit: %s", url)
                return cached

        last_error = None
        for attempt in range(self.retry_max):
            self._rate_limit()
            self.stats["requests"] += 1

            try:
                kwargs = {"timeout": 30}

                # Proxy configuration
                if self._using_proxy and self.proxy_url:
                    kwargs["proxies"] = {
                        "http": self.proxy_url,
                        "https": self.proxy_url,
                    }

                # SSL verification
                if self._ssl_fallback:
                    kwargs["verify"] = False
                else:
                    kwargs["verify"] = self.ssl_verify

                resp = self.session.get(url, **kwargs)

                # Check for CAPTCHA / unusual traffic
                if resp.status_code == 200:
                    text_lower = resp.text[:5000].lower()
                    if any(marker in text_lower for marker in CAPTCHA_MARKERS):
                        log.warning("CAPTCHA/anti-bot page detected for %s — skipping", url)
                        return None

                    # Cache the good response
                    if self.db_conn:
                        db_mod.store_cached_response(
                            self.db_conn, url, resp.text, resp.status_code
                        )
                    return resp.text

                if resp.status_code == 429:
                    wait = min(self.retry_base_wait * (2 ** attempt), 60)
                    log.warning("[429] Rate limited on %s — waiting %ds (attempt %d/%d)",
                                url, wait, attempt + 1, self.retry_max)
                    self.stats["retries"] += 1
                    time.sleep(wait)
                    # Also switch to proxy if not already
                    if not self._using_proxy and self.proxy_url:
                        self._using_proxy = True
                        self.stats["proxy_switches"] += 1
                        log.info("Switched to proxy after 429")
                    continue

                if resp.status_code == 403:
                    if not self._using_proxy and self.proxy_url and self.fallback_direct:
                        self._using_proxy = True
                        self.stats["proxy_switches"] += 1
                        log.info("Switched to proxy after 403 on %s", url)
                        self.stats["retries"] += 1
                        continue
                    wait = self.retry_base_wait * (2 ** attempt)
                    log.warning("[403] Forbidden on %s — waiting %ds", url, wait)
                    self.stats["retries"] += 1
                    time.sleep(wait)
                    continue

                # Other errors
                log.warning("[%d] HTTP error on %s (attempt %d/%d)",
                            resp.status_code, url, attempt + 1, self.retry_max)
                self.stats["retries"] += 1
                time.sleep(self.retry_base_wait * (2 ** attempt))

            except requests.exceptions.SSLError as e:
                last_error = e
                if self._using_proxy and not self._ssl_fallback:
                    log.warning("SSL error through proxy on %s — falling back to verify=False", url)
                    self._ssl_fallback = True
                    self.stats["retries"] += 1
                    continue
                log.warning("SSL error on %s: %s (attempt %d/%d)",
                            url, e, attempt + 1, self.retry_max)
                self.stats["retries"] += 1
                time.sleep(self.retry_base_wait * (2 ** attempt))

            except requests.exceptions.ConnectionError as e:
                last_error = e
                # Try proxy if direct failed
                if not self._using_proxy and self.proxy_url:
                    self._using_proxy = True
                    self.stats["proxy_switches"] += 1
                    log.info("Connection error, switching to proxy")
                    self.stats["retries"] += 1
                    continue
                log.warning("Connection error on %s: %s (attempt %d/%d)",
                            url, e, attempt + 1, self.retry_max)
                self.stats["retries"] += 1
                time.sleep(self.retry_base_wait * (2 ** attempt))

            except requests.exceptions.RequestException as e:
                last_error = e
                log.warning("Request error on %s: %s (attempt %d/%d)",
                            url, e, attempt + 1, self.retry_max)
                self.stats["retries"] += 1
                if attempt < self.retry_max - 1:
                    time.sleep(self.retry_base_wait * (2 ** attempt))

        log.error("Failed to fetch %s after %d attempts. Last error: %s",
                  url, self.retry_max, last_error)
        return None

    def post_json(self, url: str, payload: dict,
                  use_cache: bool = False) -> dict | None:
        """
        POST JSON (for INNERTUBE continuation requests).
        Returns parsed JSON dict or None.
        """
        cache_key = url + "|" + str(hash(str(sorted(payload.items()))))

        if use_cache and self.db_conn:
            cached = db_mod.get_cached_response(self.db_conn, cache_key, 24)
            if cached is not None:
                import json
                self.stats["cache_hits"] += 1
                try:
                    return json.loads(cached)
                except Exception:
                    pass

        last_error = None
        for attempt in range(self.retry_max):
            self._rate_limit()
            self.stats["requests"] += 1

            try:
                kwargs = {"timeout": 30, "json": payload}

                if self._using_proxy and self.proxy_url:
                    kwargs["proxies"] = {
                        "http": self.proxy_url,
                        "https": self.proxy_url,
                    }

                if self._ssl_fallback:
                    kwargs["verify"] = False
                else:
                    kwargs["verify"] = self.ssl_verify

                headers = {
                    "Content-Type": "application/json",
                    "X-YouTube-Client-Name": "1",
                    "X-YouTube-Client-Version": "2.20240101.00.00",
                }
                resp = self.session.post(url, headers=headers, **kwargs)

                if resp.status_code == 200:
                    import json
                    data = resp.json()
                    if self.db_conn and use_cache:
                        db_mod.store_cached_response(
                            self.db_conn, cache_key, json.dumps(data), 200
                        )
                    return data

                if resp.status_code == 429:
                    wait = min(self.retry_base_wait * (2 ** attempt), 60)
                    log.warning("[429] POST rate limited — waiting %ds", wait)
                    self.stats["retries"] += 1
                    time.sleep(wait)
                    if not self._using_proxy and self.proxy_url:
                        self._using_proxy = True
                        self.stats["proxy_switches"] += 1
                    continue

                if resp.status_code == 403 and not self._using_proxy and self.proxy_url:
                    self._using_proxy = True
                    self.stats["proxy_switches"] += 1
                    self.stats["retries"] += 1
                    log.info("POST 403, switching to proxy")
                    continue

                log.warning("[%d] POST error (attempt %d/%d)",
                            resp.status_code, attempt + 1, self.retry_max)
                self.stats["retries"] += 1
                time.sleep(self.retry_base_wait * (2 ** attempt))

            except requests.exceptions.SSLError:
                if self._using_proxy and not self._ssl_fallback:
                    self._ssl_fallback = True
                    log.warning("POST SSL error through proxy — falling back to verify=False")
                    self.stats["retries"] += 1
                    continue
                self.stats["retries"] += 1
                time.sleep(self.retry_base_wait * (2 ** attempt))

            except requests.exceptions.RequestException as e:
                last_error = e
                self.stats["retries"] += 1
                if attempt < self.retry_max - 1:
                    time.sleep(self.retry_base_wait * (2 ** attempt))

        log.error("Failed POST %s after %d attempts", url, self.retry_max)
        return None

    def get_stats(self) -> dict:
        """Return request statistics."""
        return dict(self.stats)
