import json
import os
import threading

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
    """Normalize harmless Markdown escaping before JSON parsing.

    Some chat models escape underscores as ``\_`` even while otherwise returning
    a JSON-shaped object (for example ``"emotional\_subtypes"``). ``\_`` is not
    a legal JSON escape sequence, but removing that Markdown-only backslash does
    not change the semantic text. Keep the normalization intentionally narrow so
    genuinely malformed JSON still fails in the classifier parser.
    """
    if not isinstance(content, str):
        return content
    if "{" not in content or "}" not in content:
        return content
    return content.replace("\\_", "_")


# One shared client means API task concurrency reuses keep-alive TCP/TLS
# connections instead of opening a fresh socket for every row. httpx.Client is
# thread-safe and call_llm is invoked from the classifier's executor threads.
_HTTP_MAX_CONNECTIONS = _positive_int_env("LLM_HTTP_MAX_CONNECTIONS", 100)
_HTTP_MAX_KEEPALIVE = min(
    _HTTP_MAX_CONNECTIONS,
    _positive_int_env("LLM_HTTP_MAX_KEEPALIVE_CONNECTIONS", 40),
)
_HTTP_KEEPALIVE_EXPIRY = float(os.getenv("LLM_HTTP_KEEPALIVE_EXPIRY_SECONDS", "30"))
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

    response = _get_client().post(
        f"{api_url.rstrip('/')}/chat/completions",
        json=payload,
        headers=_auth_headers(api_key),
        timeout=httpx.Timeout(timeout),
    )
    response.raise_for_status()
    data = response.json()
    return normalize_llm_content(data["choices"][0]["message"]["content"])


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
