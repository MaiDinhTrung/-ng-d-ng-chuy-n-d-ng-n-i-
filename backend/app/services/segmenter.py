"""Chia văn bản thành đoạn + khoảng nghỉ. Hàm thuần, không phụ thuộc engine.

Quy tắc nghỉ (mặc định, chỉnh được theo project):
  dấu phẩy -> comma, dấu chấm/!/? -> period, '...'/'…' -> ellipsis, xuống dòng -> newline.
Thẻ [pause=500] không bao giờ đi vào text của đoạn; nó đặt pause_after của đoạn trước
(hoặc pause_before của đoạn đầu tiên) và ghi đè nghỉ tự động.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..config import DEFAULT_PAUSES_MS

PAUSE_TAG = re.compile(r"\[\s*pause\s*=\s*(\d{1,6})\s*(?:ms)?\s*\]", re.IGNORECASE)
# Câu kết thúc bằng ... / … / . ! ? và phải theo sau bởi khoảng trắng hoặc hết dòng
# (để "3.5" hay "a.b" không bị cắt).
SENTENCE = re.compile(r"(.+?(?:\.{3,}|…+|[.!?]+))(?=\s|$)|(.+?)$", re.DOTALL)
CLAUSE = re.compile(r"(?<=[,;:])\s+")
HAS_WORD = re.compile(r"\w", re.UNICODE)
MAX_PAUSE_MS = 60000


@dataclass
class Seg:
    text: str
    pause_before: int = 0
    pause_after: int = 0
    explicit_after: bool = False


def _terminator_pause(piece: str, pauses: dict) -> int:
    s = piece.rstrip()
    if s.endswith("...") or s.endswith("…"):
        return pauses["ellipsis"]
    if s and s[-1] in ".!?":
        return pauses["period"]
    if s and s[-1] in ",;:":
        return pauses["comma"]
    return pauses["period"]


def _pack_clauses(text: str, max_chars: int, pauses: dict) -> list[tuple[str, int]]:
    """Cắt câu dài thành các đoạn ≤ max_chars, ưu tiên ranh giới mệnh đề rồi từ."""
    if len(text) <= max_chars:
        return [(text, 0)]
    clauses = CLAUSE.split(text)
    atoms: list[str] = []
    for c in clauses:
        if len(c) <= max_chars:
            atoms.append(c)
            continue
        words, cur = c.split(), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > max_chars:
                atoms.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        if cur:
            atoms.append(cur)
    out: list[tuple[str, int]] = []
    cur = ""
    for a in atoms:
        if cur and len(cur) + 1 + len(a) > max_chars:
            out.append((cur, pauses["comma"]))
            cur = a
        else:
            cur = f"{cur} {a}".strip()
    if cur:
        out.append((cur, 0))
    return out


def parse_text(text: str, pauses: dict | None = None, split_commas: bool = False,
               max_chars: int = 220) -> list[Seg]:
    p = {**DEFAULT_PAUSES_MS, **(pauses or {})}
    segs: list[Seg] = []
    pending_before = 0

    def add_text(piece: str) -> None:
        nonlocal pending_before
        piece = piece.strip()
        if not piece or not HAS_WORD.search(piece):
            return
        if split_commas:
            parts = [x.strip() for x in CLAUSE.split(piece) if x.strip()]
        else:
            parts = [piece]
        for k, part in enumerate(parts):
            last = k == len(parts) - 1
            subs = _pack_clauses(part, max_chars, p)
            for j, (sub, gap) in enumerate(subs):
                is_end = last and j == len(subs) - 1
                if is_end:
                    after = _terminator_pause(piece, p)
                else:
                    after = gap or p["comma"]
                segs.append(Seg(sub, pending_before, after))
                pending_before = 0

    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line_start = len(segs)
        pos = 0
        for m in PAUSE_TAG.finditer(line):
            chunk = line[pos:m.start()]
            for sm in SENTENCE.finditer(chunk):
                add_text(sm.group(1) or sm.group(2) or "")
            ms = min(int(m.group(1)), MAX_PAUSE_MS)
            if segs:
                segs[-1].pause_after = ms
                segs[-1].explicit_after = True
            else:
                pending_before += ms
            pos = m.end()
        for sm in SENTENCE.finditer(line[pos:]):
            add_text(sm.group(1) or sm.group(2) or "")
        # Hết dòng: nghỉ "xuống dòng" nếu đoạn cuối chưa có nghỉ tường minh.
        if len(segs) > line_start and not segs[-1].explicit_after:
            segs[-1].pause_after = max(segs[-1].pause_after, p["newline"])

    if segs and not segs[-1].explicit_after:
        segs[-1].pause_after = 0
    return segs
