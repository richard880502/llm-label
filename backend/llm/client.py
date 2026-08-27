import json
from urllib import error, request as urllib_request


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
    req = urllib_request.Request(
        f"{api_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload).encode(),
        headers=_auth_headers(api_key),
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return normalize_llm_content(data["choices"][0]["message"]["content"])


def list_models(api_url: str, api_key: str = "", timeout: int = 10) -> list[str]:
    try:
        req = urllib_request.Request(
            f"{api_url.rstrip('/')}/models",
            headers=_auth_headers(api_key),
        )
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        return [m["id"] for m in data.get("data", [])]
    except Exception:
        return []
