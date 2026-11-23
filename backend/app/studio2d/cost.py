"""Cost Manager: ghi nhận token/chi phí, ước tính trước khi chạy, ngân sách theo dự án.

Giá KHÔNG được hard-code (giá thay đổi và tôi không có nguồn xác thực trong ứng dụng): đặt trong .env
  ANTHROPIC_PRICE_IN_PER_MTOK / ANTHROPIC_PRICE_OUT_PER_MTOK  (USD cho 1 triệu token)
Nếu chưa đặt, token vẫn được đếm đầy đủ nhưng chi phí = None và ngân sách không thể áp dụng cho Claude.
"""
from __future__ import annotations

from ..services import secret_store
from . import store

WARN_RATIO = 0.8


class BudgetExceeded(RuntimeError):
    pass


def llm_prices() -> tuple[float, float] | None:
    a, b = secret_store.get("ANTHROPIC_PRICE_IN_PER_MTOK"), secret_store.get("ANTHROPIC_PRICE_OUT_PER_MTOK")
    try:
        return (float(a), float(b)) if a and b else None
    except ValueError:
        return None


def llm_cost(in_tok: int, out_tok: int) -> float | None:
    p = llm_prices()
    return None if p is None else (in_tok * p[0] + out_tok * p[1]) / 1_000_000


def ensure_meta(pid: str) -> None:
    with store.tx() as c:
        c.execute("INSERT OR IGNORE INTO s2d_meta(project_id) VALUES(?)", (pid,))


def record(project_id: str | None, kind: str, provider: str, model: str | None, purpose: str,
           in_tok: int = 0, out_tok: int = 0, cost: float | None = None) -> None:
    with store.tx() as c:
        c.execute("""INSERT INTO s2d_usage(project_id,kind,provider,model,purpose,input_tokens,output_tokens,cost_usd,created_at)
                     VALUES(?,?,?,?,?,?,?,?,?)""", (project_id, kind, provider, model, purpose, in_tok, out_tok, cost, store.now()))


def set_budget(pid: str, budget: float | None) -> None:
    ensure_meta(pid)
    with store.tx() as c:
        c.execute("UPDATE s2d_meta SET budget_usd=? WHERE project_id=?", (budget, pid))


def summary(pid: str | None = None) -> dict:
    where, args = ("WHERE project_id=?", (pid,)) if pid else ("", ())
    rows = store.query(f"""SELECT kind, COUNT(*) AS calls, SUM(input_tokens) AS in_tok, SUM(output_tokens) AS out_tok,
                           SUM(cost_usd) AS cost, SUM(cost_usd IS NULL) AS unpriced
                           FROM s2d_usage {where} GROUP BY kind""", args)
    by_kind = {r["kind"]: {"calls": r["calls"], "input_tokens": r["in_tok"] or 0, "output_tokens": r["out_tok"] or 0,
                           "cost_usd": round(r["cost"] or 0.0, 6), "unpriced_calls": r["unpriced"] or 0} for r in rows}
    spent = round(sum(v["cost_usd"] for v in by_kind.values()), 6)
    out = {"by_kind": by_kind, "spent_usd": spent, "prices_configured": llm_prices() is not None,
           "unpriced_calls": sum(v["unpriced_calls"] for v in by_kind.values())}
    if pid:
        m = store.query("SELECT budget_usd FROM s2d_meta WHERE project_id=?", (pid,))
        budget = m[0]["budget_usd"] if m else None
        out["budget_usd"] = budget
        out["budget_ratio"] = (spent / budget) if budget else None
        out["warning"] = bool(budget and spent >= budget * WARN_RATIO)
        out["exceeded"] = bool(budget and spent >= budget)
        out["budget_enforceable"] = llm_prices() is not None
    return out


def check_budget(pid: str | None, estimated_cost: float | None = None) -> None:
    """Chặn trước khi gọi API trả phí nếu đã/sắp vượt ngân sách."""
    if not pid:
        return
    s = summary(pid)
    b = s["budget_usd"]
    if b is None:
        return
    if s["spent_usd"] >= b or (estimated_cost is not None and s["spent_usd"] + estimated_cost > b):
        raise BudgetExceeded(f"Sẽ vượt ngân sách dự án (${s['spent_usd']:.4f} / ${b:.2f}). Tăng ngân sách để tiếp tục.")


def estimate_tokens(text: str) -> int:
    """Ước lượng thô (~3 ký tự/token cho tiếng Việt). Chỉ để ước tính trước; số thật lấy từ API."""
    return max(1, len(text) // 3)
