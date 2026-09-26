"""Small, rate-limited client for the SEC's public JSON endpoints."""

import copy
import os
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Any

import httpx

_BASE_URL = "https://data.sec.gov"
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_CONTACT = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")


class SecError(RuntimeError):
    """SEC data was unavailable or did not match the documented shape."""


def normalize_cik(cik: str | int) -> str:
    """Return SEC's ten-digit CIK form; reject anything else."""
    raw = str(cik)
    if not re.fullmatch(r"\d{1,10}", raw):
        raise ValueError("CIK must contain 1 to 10 digits")
    return raw.zfill(10)


class _RateLimiter:
    def __init__(
        self,
        interval: float = 0.5,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.interval = interval
        self.clock = clock
        self.sleep = sleep
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            delay = max(0.0, self._next_at - self.clock())
            if delay:
                self.sleep(delay)
            self._next_at = self.clock() + self.interval


# Shared across client instances in this process. Distributed deployments need a
# shared limiter if they expose SEC fetching to many simultaneous users.
_RATE_LIMITER = _RateLimiter()


class SecClient:
    """Fetch submissions and company facts with bounded retries and a TTL cache.

    The cache is local to this client/process and is not persistent on Vercel.
    Callers must provide a real organization/name and contact email in User-Agent.
    """

    def __init__(
        self,
        user_agent: str | None = None,
        *,
        client: httpx.Client | None = None,
        cache_ttl: float = 900.0,
        cache_size: int = 16,
        max_retries: int = 2,
        limiter: _RateLimiter = _RATE_LIMITER,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        agent = (user_agent or os.getenv("SEC_USER_AGENT", "")).strip()
        if (
            len(agent) < 12
            or not _CONTACT.search(agent)
            or "example.com" in agent.lower()
            or "your-email" in agent.lower()
        ):
            raise ValueError("SEC_USER_AGENT needs a name and real contact email")
        if cache_ttl < 0 or cache_size < 0 or not 0 <= max_retries <= 5:
            raise ValueError("Invalid SEC cache or retry settings")
        self.user_agent = agent
        self._client = client or httpx.Client(timeout=10.0, follow_redirects=False)
        self._owns_client = client is None
        self._cache_ttl = cache_ttl
        self._cache_size = cache_size
        self._max_retries = max_retries
        self._cache: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._limiter = limiter
        self._clock = clock
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> "SecClient":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _get_json(self, path: str) -> dict[str, Any]:
        now = self._clock()
        cached = self._cache.get(path)
        if cached and cached[0] > now:
            self._cache.move_to_end(path)
            return copy.deepcopy(cached[1])
        self._cache.pop(path, None)
        url = f"{_BASE_URL}{path}"
        for attempt in range(self._max_retries + 1):
            self._limiter.wait()
            try:
                response = self._client.get(
                    url,
                    headers={
                        "User-Agent": self.user_agent,
                        "Accept": "application/json",
                    },
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == self._max_retries:
                    raise SecError("SEC request failed after retries") from exc
                self._sleep(min(2**attempt, 8))
                continue
            if response.status_code in _RETRY_STATUSES and attempt < self._max_retries:
                retry_after = response.headers.get("Retry-After", "")
                delay = (
                    min(float(retry_after), 60) if retry_after.isdigit() else 2**attempt
                )
                self._sleep(delay)
                continue
            if response.status_code != 200:
                raise SecError(f"SEC returned HTTP {response.status_code}")
            if len(response.content) > 25_000_000:
                raise SecError("SEC response exceeds the size limit")
            try:
                data = response.json()
            except ValueError as exc:
                raise SecError("SEC returned invalid JSON") from exc
            if not isinstance(data, dict):
                raise SecError("SEC returned an unexpected JSON structure")
            if self._cache_size and self._cache_ttl:
                self._cache[path] = (self._clock() + self._cache_ttl, data)
                self._cache.move_to_end(path)
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
            return copy.deepcopy(data)
        raise SecError("SEC request failed after retries")

    def submissions(self, cik: str | int) -> dict[str, Any]:
        return self._get_json(f"/submissions/CIK{normalize_cik(cik)}.json")

    def company_facts(self, cik: str | int) -> dict[str, Any]:
        return self._get_json(f"/api/xbrl/companyfacts/CIK{normalize_cik(cik)}.json")
