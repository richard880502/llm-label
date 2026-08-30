import json
import os
import random
import threading
import time

import httpx


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value > 0 else default


def _auth_headers(api_key: str) -> dict:
    h = {"Content-Type": "application/json"}
    if api_key:
        h["Authorization"] = f"Bearer {api_key}"
    return h


def normalize_llm_content(content: str) -> str:
    """Normalize harmless Markdown escaping before JSON parsing."""
    if not isinstance(content, str):
        return content
    if "{" not in content or "}" not in content:
        return content
    return content.replace("\\_", "_")


# Shared keep-alive pool for all API labeling tasks.
_HTTP_MAX_CONNECTIONS = _positive_int_env("LLM_HTTP_MAX_CONNECTIONS", 100)
_HTTP_MAX_KEEPALIVE = min(
    _HTTP_MAX_CONNECTIONS,
    _positive_int_env("LLM_HTTP_MAX_KEEPALIVE_CONNECTIONS", 40),
)
_HTTP_KEEPALIVE_EXPIRY = float(os.getenv("LLM_HTTP_KEEPALIVE_EXPIRY_SECONDS", "30"))

# Per-task concurrency is configured in llm_configs. This second guard limits
# aggregate concurrency across *all* tasks so two recovered jobs cannot each
# open their full concurrency against the same upstream at once.
_LLM_MAX_CONCURRENT_REQUESTS = _positive_int_env("LLM_MAX_CONCURRENT_REQUESTS", 24)
_LLM_MAX_RETRIES = _positive_int_env("LLM_MAX_RETRIES", 3)
_request_slots = threading.BoundedSemaphore(_LLM_MAX_CONCURRENT_REQUESTS)

_client_lock = threading.Lock()
_client: httpx.Client | None = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = httpx.Client(
                    limits=httpx.Limits(
                        max_connections=_HTTP_MAX_CONNECTIONS,
                        max_keepalive_connections=_HTTP_MAX_KEEPALIVE,
                        keepalive_expiry=_HTTP_KEEPALIVE_EXPIRY,
                    ),
                    follow_redirects=True,
                )
    return _client


def _retry_delay(response: httpx.Response | None, attempt: int) -> float:
    if response is not None:
        retry_after = response.headers.get("retry-after", "").strip()
        if retry_after:
            try:
                return max(0.0, min(float(retry_after), 30.0))
            except ValueError:
                pass
    # Capped exponential backoff with jitter avoids synchronized retry storms.
    return min(0.5 * (2 ** attempt) + random.uniform(0.0, 0.25), 8.0)


def call_llm(
    api_url: str,
    model: str,
    prompt: str,
    api_key: str = "",
    timeout: int = 180,
    extra_body: dict | None = None,
) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
        "max_tokens": 4096,
    }
    if extra_body:
        payload.update(extra_body)

    url = f"{api_url.rstrip('/')}/chat/completions"
    headers = _auth_headers(api_key)
    last_error: Exception | None = None

    # Hold the global slot across retries so retry storms cannot exceed the
    # configured service-wide concurrency budget.
    with _request_slots:
        for attempt in range(_LLM_MAX_RETRIES + 1):
            response: httpx.Response | None = None
            try:
                response = _get_client().post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(timeout),
                )
                if response.status_code not in (408, 429) and response.status_code < 500:
                    response.raise_for_status()
                    data = response.json()
                    return normalize_llm_content(data["choices"][0]["message"]["content"])
                last_error = httpx.HTTPStatusError(
                    f"retryable LLM HTTP status {response.status_code}",
                    request=response.request,
                    response=response,
                )
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteTimeout, httpx.PoolTimeout) as error:
                last_error = error
            except httpx.HTTPStatusError:
                raise

            if attempt >= _LLM_MAX_RETRIES:
                break
            time.sleep(_retry_delay(response, attempt))

    if last_error is not None:
        raise last_error
    raise RuntimeError("LLM request failed without an error")


def list_models(api_url: str, api_key: str = "", timeout: int = 10) -> list[str]:
    try:
        response = _get_client().get(
            f"{api_url.rstrip('/')}/models",
            headers=_auth_headers(api_key),
            timeout=httpx.Timeout(timeout),
        )
        response.raise_for_status()
        data = response.json()
        return [m["id"] for m in data.get("data", [])]
    except Exception:
        return []
