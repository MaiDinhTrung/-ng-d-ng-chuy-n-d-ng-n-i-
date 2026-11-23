"""AI Visual Director + Storyboard Director. Claude chỉ phân tích và viết prompt; không render ảnh.

Mỗi hàm trả dữ liệu đã được kiểm tra/chuẩn hóa (id nhân vật/tư liệu lạ bị loại), không tin JSON thô của mô hình.
"""
from __future__ import annotations

from . import characters, cost, llm, projects, references, scenes

LANG = {"vi": "Vietnamese", "en": "English"}
CHUNK_CHARS = 2600


def _lang(p: dict) -> str:
    return LANG.get(p["language"], p["language"])


def _ref_lines(refs: list[dict], cats: tuple[str, ...]) -> str:
    rows = [f"- id={r['id']} | {r['category']} | {r['name']}: {r['description'] or '(no description)'}"
            for r in refs if r["category"] in cats]
    return "\n".join(rows) or "(none)"


def _brief(p: dict) -> str:
    return (f"Project: {p['name']}\nTopic: {p['topic']}\nDescription: {p['description']}\nTarget audience: {p['target_audience']}\n"
            f"Video type: {p['video_type']}\nVisual style: {p['visual_style']}\nAspect ratio: {p['aspect_ratio']}\n"
            f"Target duration (seconds): {p['duration_sec'] or 'not set'}")


# ---------------- kịch bản ----------------

def write_script(pid: str) -> str:
    p = projects.get_project(pid)
    if not (p["topic"].strip() or p["description"].strip()):
        raise ValueError("Cần nhập chủ đề hoặc mô tả để Agent viết kịch bản")
    words = int((p["duration_sec"] or 90) * 2.4)
    system = (f"You are a screenwriter for short 2D animated videos. Write the narration script in {_lang(p)}. "
              "Output ONLY the narration text (spoken words), in short paragraphs. No headings, no stage directions, "
              "no markdown. Use the reference notes only as factual/stylistic background.")
    user = (f"{_brief(p)}\n\nReference notes:\n{_ref_lines(p['references'], ('character', 'environment', 'style', 'storyboard'))}\n\n"
            f"Target length: about {words} words.")
    return llm.complete(system, user, project_id=pid, purpose="write_script", max_tokens=min(8000, words * 4 + 500)).strip()


# ---------------- nhân vật ----------------

CHAR_SYSTEM = """You are a character designer for a 2D animation pipeline. Read the script and identify every recurring or important
character. For each, write a precise visual profile that an image generator can follow identically across many scenes.
Respond with ONLY JSON: {"characters":[{"name":str,"description":str,"facial_features":str,"hair":str,"costume":str,
"main_colors":str,"weapons":str,"personality":str,"consistency_rules":str,"reference_ids":[str]}]}.
Write field values in the requested language. Only use reference_ids taken from the provided list, and only when a reference
image clearly depicts that character. Do not invent characters that do not appear in the script. Use "" when unknown."""


def extract_characters(pid: str) -> list[dict]:
    p = projects.get_project(pid)
    if not p["script"].strip():
        raise ValueError("Chưa có kịch bản để phân tích nhân vật")
    user = (f"{_brief(p)}\nOutput language for field values: {_lang(p)}\n\nCharacter reference images:\n"
            f"{_ref_lines(p['references'], ('character',))}\n\nScript:\n{p['script']}")
    data = llm.extract_json(llm.complete(CHAR_SYSTEM, user, project_id=pid, purpose="extract_characters", max_tokens=4000))
    items = data.get("characters") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise llm.LLMError("Claude không trả về danh sách nhân vật")
    existing = {c["name"].strip().lower() for c in characters.list_for_project(pid)}
    created = []
    valid_refs = {r["id"] for r in p["references"]}
    for it in items:
        if not isinstance(it, dict) or not str(it.get("name", "")).strip():
            continue
        if it["name"].strip().lower() in existing:        # không ghi đè hồ sơ người dùng đã có/đã xác nhận
            continue
        it["reference_ids"] = [i for i in it.get("reference_ids", []) if i in valid_refs]
        created.append(characters.create(pid, it))
        existing.add(it["name"].strip().lower())
    return created


# ---------------- storyboard ----------------

SB_SYSTEM = """You are a storyboard director for 2D animated videos. Split the given narration into consecutive scenes that,
together, cover ALL of the narration text exactly once and in order (copy the narration verbatim into each scene's "narration").
Each scene is one visual moment (usually 1-3 sentences). For each scene decide the visuals and write an image-generation prompt.
Respond with ONLY JSON: {"scenes":[{"title":str,"narration":str,"character_ids":[str],"environment":str,
"visual_description":str,"camera_angle":str,"camera_movement":one of [static,zoom_in,zoom_out,pan_left,pan_right,pan_up,pan_down,shake],
"character_action":str,"lighting":str,"duration":number(seconds),"transition":one of [cut,fade,dissolve,wipeleft,wiperight,slideleft,slideright,fadeblack,circleopen],
"effect":one of [none,vignette,warm,cool,flash],"image_prompt":str,"negative_prompt":str,"reference_ids":[str]}]}.
Rules: character_ids and reference_ids must come from the provided lists. Image prompts must be in English, describe only what is
visible in this single frame, and must NOT redefine characters' looks (the character sheet is injected automatically, keep their
names in the prompt). Keep style, color palette and lighting consistent with the visual style and neighbouring scenes.
Pick camera_movement/duration to suit the action (battle: shake or zoom_in; establishing shot: pan or zoom_out)."""


def _chunks(script: str) -> list[str]:
    paras = [x.strip() for x in script.replace("\r", "").split("\n") if x.strip()]
    out, cur = [], ""
    for para in paras:
        if cur and len(cur) + len(para) > CHUNK_CHARS:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{para}".strip()
        while len(cur) > CHUNK_CHARS * 1.5:             # đoạn đơn quá dài: cắt ở dấu câu gần nhất
            cut = max(cur.rfind(". ", 0, CHUNK_CHARS), cur.rfind("! ", 0, CHUNK_CHARS), cur.rfind("? ", 0, CHUNK_CHARS))
            cut = cut + 1 if cut > 0 else CHUNK_CHARS
            out.append(cur[:cut].strip())
            cur = cur[cut:].strip()
    if cur:
        out.append(cur)
    return out


def _context(p: dict, chars: list[dict]) -> str:
    cl = "\n".join(f"- id={c['id']} | {c['name']}: {characters.descriptor(c)}" for c in chars) or "(none)"
    return (f"{_brief(p)}\n\nCharacters:\n{cl}\n\nEnvironment references:\n{_ref_lines(p['references'], ('environment',))}\n"
            f"Visual style references:\n{_ref_lines(p['references'], ('style',))}\n"
            f"Storyboard/camera references:\n{_ref_lines(p['references'], ('storyboard',))}")


def _check_scene(it: dict, chars: dict[str, dict], refs: set[str]) -> dict:
    it = dict(it)
    it["character_ids"] = [i for i in it.get("character_ids", []) if i in chars]
    it["reference_ids"] = [i for i in it.get("reference_ids", []) if i in refs]
    # Ảnh tham chiếu của nhân vật xuất hiện trong cảnh luôn được đưa vào yêu cầu tạo ảnh.
    for cid in it["character_ids"]:
        for r in chars[cid]["reference_ids"]:
            if r in refs and r not in it["reference_ids"]:
                it["reference_ids"].append(r)
    return it


def build_storyboard(pid: str) -> list[dict]:
    p = projects.get_project(pid)
    if not p["script"].strip():
        raise ValueError("Chưa có kịch bản để chia cảnh")
    chars_list = characters.list_for_project(pid)
    chars = {c["id"]: c for c in chars_list}
    refs = {r["id"] for r in p["references"]}
    ctx = _context(p, chars_list)
    out: list[dict] = []
    prev = ""
    for i, chunk in enumerate(_chunks(p["script"])):
        user = f"{ctx}\n\nPrevious scene (for continuity): {prev or '(none)'}\n\nNarration part {i + 1}:\n{chunk}"
        data = llm.extract_json(llm.complete(SB_SYSTEM, user, project_id=pid, purpose="storyboard", max_tokens=7000))
        items = data.get("scenes") if isinstance(data, dict) else data
        if not isinstance(items, list) or not items:
            raise llm.LLMError("Claude không trả về danh sách cảnh")
        for it in items:
            if isinstance(it, dict) and str(it.get("narration", "")).strip():
                out.append(_check_scene(it, chars, refs))
        if out:
            prev = f"{out[-1].get('title', '')} — {out[-1].get('environment', '')}"
    if not out:
        raise llm.LLMError("Storyboard rỗng")
    return scenes.replace_all(pid, out)


REGEN_SYSTEM = SB_SYSTEM.replace("Split the given narration into consecutive scenes that,\ntogether, cover ALL of the narration text exactly once and in order (copy the narration verbatim into each scene's \"narration\").",
                                 "Redesign the visuals of ONE scene. Keep the narration text exactly as given.") + \
    '\nRespond with ONLY JSON for ONE scene: {"scene":{...same fields...}}.'


def regenerate_scene(sid: str, instruction: str = "") -> dict:
    sc = scenes.get(sid)
    pid = sc["project_id"]
    p = projects.get_project(pid)
    chars_list = characters.list_for_project(pid)
    chars = {c["id"]: c for c in chars_list}
    allsc = scenes.list_for_project(pid)
    near = [s for s in allsc if abs(s["idx"] - sc["idx"]) == 1]
    nb = "\n".join(f"- scene {s['idx'] + 1} ({s['title']}): {s['environment']} / {s['lighting']} / {s['image_prompt'][:200]}" for s in near)
    user = (f"{_context(p, chars_list)}\n\nNeighbouring scenes:\n{nb or '(none)'}\n\nScene to redesign:\n"
            f"narration: {sc['narration']}\ncurrent title: {sc['title']}\ncurrent prompt: {sc['image_prompt']}\n"
            f"User instruction: {instruction or 'Create a fresh alternative take.'}")
    data = llm.extract_json(llm.complete(REGEN_SYSTEM, user, project_id=pid, purpose="regenerate_scene",
                                         max_tokens=3000, use_cache=False))
    item = data.get("scene") if isinstance(data, dict) and "scene" in data else data
    if not isinstance(item, dict):
        raise llm.LLMError("Claude không trả về cảnh hợp lệ")
    item = _check_scene({**item, "narration": sc["narration"]}, chars, {r["id"] for r in p["references"]})
    return scenes.update(sid, item)


# ---------------- prompt cuối cùng cho nhà cung cấp ảnh ----------------

def compose_image_request(sid: str) -> dict:
    """Ghép prompt cuối: phong cách dự án + hồ sơ nhân vật cố định + prompt cảnh. Có tính xác định (không gọi API)."""
    sc = scenes.get(sid)
    p = projects.get_project(sc["project_id"])
    chars = {c["id"]: c for c in characters.list_for_project(sc["project_id"])}
    cs = [chars[i] for i in sc["character_ids"] if i in chars]
    parts = []
    if p["visual_style"]:
        parts.append(f"Style: {p['visual_style']}.")
    if cs:
        parts.append("Characters (keep their appearance exactly): " + " ".join(characters.descriptor(c) for c in cs))
    base = sc["image_prompt"] or sc["visual_description"]
    parts.append(base)
    for label, v in (("Setting", sc["environment"]), ("Camera", sc["camera_angle"]), ("Lighting", sc["lighting"]),
                     ("Action", sc["character_action"])):
        if v and v.lower() not in base.lower():
            parts.append(f"{label}: {v}.")
    ref_ids = list(dict.fromkeys([*sc["reference_ids"], *[r for c in cs for r in c["reference_ids"]]]))
    return {"prompt": " ".join(parts), "negative_prompt": sc["negative_prompt"], "reference_ids": ref_ids,
            "aspect_ratio": p["aspect_ratio"]}


def estimate(pid: str, stage: str) -> dict:
    """Ước tính token trước khi chạy (thô). Cho biết đã có trong cache hay chưa là việc của UI: chỉ trả số ước tính."""
    p = projects.get_project(pid)
    base = cost.estimate_tokens(_brief(p) + p["script"] + "".join(r["description"] for r in p["references"]))
    if stage == "script":
        in_t, out_t = base, int((p["duration_sec"] or 90) * 2.4 * 2)
    elif stage == "characters":
        in_t, out_t = base + cost.estimate_tokens(CHAR_SYSTEM), 1500
    elif stage == "storyboard":
        n = max(1, len(_chunks(p["script"])))
        in_t = (base + cost.estimate_tokens(SB_SYSTEM)) * n
        out_t = max(800, int(cost.estimate_tokens(p["script"]) * 4))
    else:
        raise ValueError("stage phải là script | characters | storyboard")
    return {"stage": stage, "input_tokens": in_t, "output_tokens": out_t, "cost_usd": cost.llm_cost(in_t, out_t),
            "is_estimate": True, "prices_configured": cost.llm_prices() is not None}
