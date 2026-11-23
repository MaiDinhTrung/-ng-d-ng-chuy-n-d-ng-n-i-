"""Client Claude (Messages API) qua httpx. Claude chỉ phân tích/viết; không bao giờ render ảnh.

- Khóa chỉ đọc từ .env ở backend. Mô hình: ANTHROPIC_MODEL (mặc định claude-sonnet-5-5).
- Cache theo hash đầu vào: cùng yêu cầu thì không gọi lại API (và không tốn token).
- Mọi lần gọi đều ghi token vào s2d_usage; kiểm tra ngân sách trước khi gọi.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import httpx

from ..services import secret_store
from . import cost, store

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"

_transport: httpx.BaseTransport | None = None     # test có thể thay bằng MockTransport


def set_transport(t: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = t


class LLMError(RuntimeError):
    pass


class NotConfigured(LLMError):
    pass


def model() -> str:
    return secret_store.get("ANTHROPIC_MODEL") or DEFAULT_MODEL


def is_configured() -> bool:
    return bool(secret_store.get("ANTHROPIC_API_KEY"))


def _key(system: str, user: str, max_tokens: int) -> str:
    return hashlib.sha256(json.dumps([model(), system, user, max_tokens], ensure_ascii=False).encode()).hexdigest()


def complete(system: str, user: str, *, project_id: str | None, purpose: str, max_tokens: int = 4096,
             use_cache: bool = True, est_output_tokens: int | None = None) -> str:
    key = _key(system, user, max_tokens)
    if use_cache:
        hit = store.query("SELECT response FROM s2d_llm_cache WHERE key=?", (key,))
        if hit:
            cost.record(project_id, "llm", "claude", model(), purpose + " (cache)", 0, 0, 0.0)
            return hit[0]["response"]
    api_key = secret_store.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise NotConfigured("Chưa có ANTHROPIC_API_KEY trong .env (xem .env.example), nên chưa gọi được Claude.")
    est_in = cost.estimate_tokens(system + user)
    cost.check_budget(project_id, cost.llm_cost(est_in, est_output_tokens or max_tokens // 2))

    body = {"model": model(), "max_tokens": max_tokens, "system": system,
            "messages": [{"role": "user", "content": user}]}
    headers = {"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    last: str = ""
    with httpx.Client(timeout=180, transport=_transport) as c:
        for attempt in range(3):
            try:
                r = c.post(API_URL, headers=headers, json=body)
            except httpx.HTTPError as e:
                last = f"Lỗi mạng: {type(e).__name__}"
            else:
                if r.status_code == 200:
                    break
                last = _err(r)
                if r.status_code not in (429, 500, 502, 503, 529):
                    raise LLMError(f"Claude API {r.status_code}: {last}")
            time.sleep(1.5 * (attempt + 1) if _transport is None else 0)
        else:
            raise LLMError(f"Claude API không phản hồi sau 3 lần thử: {last}")
    data = r.json()
    usage = data.get("usage") or {}
    in_t, out_t = int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0))
    cost.record(project_id, "llm", "claude", data.get("model") or model(), purpose, in_t, out_t, cost.llm_cost(in_t, out_t))
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    if data.get("stop_reason") == "max_tokens":
        raise LLMError("Claude trả lời bị cắt cụt (hết max_tokens). Hãy chia nhỏ nội dung rồi thử lại.")
    if not text.strip():
        raise LLMError("Claude trả về nội dung rỗng")
    with store.tx() as c2:
        c2.execute("INSERT OR REPLACE INTO s2d_llm_cache(key,response,created_at) VALUES(?,?,?)", (key, text, store.now()))
    return text


def _err(r: httpx.Response) -> str:
    try:
        return str(r.json().get("error", {}).get("message", r.text))[:300]
    except ValueError:
        return r.text[:300]


def extract_json(text: str):
    """Lấy JSON từ câu trả lời (chịu được ```json fence và lời dẫn thừa)."""
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    cand = m.group(1) if m else text
    start = min([i for i in (cand.find("{"), cand.find("[")) if i >= 0], default=-1)
    if start < 0:
        raise LLMError("Câu trả lời của Claude không chứa JSON")
    try:
        obj, _ = json.JSONDecoder().raw_decode(cand[start:])
        return obj
    except json.JSONDecodeError as e:
        raise LLMError(f"JSON của Claude không hợp lệ: {e.msg}") from e
