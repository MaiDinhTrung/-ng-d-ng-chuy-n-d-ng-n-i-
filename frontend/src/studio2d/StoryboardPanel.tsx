import { useCallback, useEffect, useRef, useState } from "react";
import { api2d, EFFECTS, MOVEMENTS, TRANSITIONS, type Character, type Estimate, type Generation, type Scene } from "./api2d";

const imgUrl = (gid: string) => `/api/2d/generations/${gid}/file`;

function SceneCard({ s, chars, total, onChange, claudeReady, imageProviders }: {
  s: Scene; chars: Character[]; total: number; onChange: () => void; claudeReady: boolean; imageProviders: { id: string; name: string; configured: boolean }[];
}) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState(s);
  const [gens, setGens] = useState<Generation[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [instr, setInstr] = useState("");
  const file = useRef<HTMLInputElement>(null);
  useEffect(() => setF(s), [s]);
  const fail = (e: unknown) => setErr(String(e instanceof Error ? e.message : e));
  const loadGens = useCallback(() => { api2d.sceneImages(s.id).then((r) => setGens(r.images)).catch(fail); }, [s.id]);
  useEffect(() => { if (open) loadGens(); }, [open, loadGens, s.image_gen_id]);
  const keys = ["title", "narration", "environment", "visual_description", "camera_angle", "camera_movement", "character_action", "lighting", "duration", "transition", "effect", "image_prompt", "negative_prompt", "character_ids"] as const;
  const dirty = keys.some((k) => JSON.stringify(f[k]) !== JSON.stringify(s[k]));
  const save = async () => { try { await api2d.updateScene(s.id, Object.fromEntries(keys.map((k) => [k, f[k]]))); setErr(null); onChange(); } catch (e) { fail(e); } };
  const T = (k: keyof Scene, label: string, rows = 1, span = false) => (
    <label className={`text-xs text-muted ${span ? "col-span-2" : ""}`}>{label}
      <textarea className="input mt-1" rows={rows} value={String(f[k] ?? "")} onChange={(e) => setF({ ...f, [k]: e.target.value })} /></label>
  );
  const Sel = (k: "camera_movement" | "transition" | "effect", label: string, opts: string[]) => (
    <label className="text-xs text-muted">{label}
      <select className="input mt-1" value={f[k]} onChange={(e) => setF({ ...f, [k]: e.target.value })}>{opts.map((o) => <option key={o}>{o}</option>)}</select></label>
  );
  return (
    <div className="rounded-xl border border-line bg-panel overflow-hidden flex flex-col">
      <div className="aspect-video bg-black/40 flex items-center justify-center text-xs text-muted">
        {s.image_gen_id ? <img src={imgUrl(s.image_gen_id)} alt={s.title} className="w-full h-full object-contain" loading="lazy" /> : "Chưa có ảnh"}
      </div>
      <div className="p-3 space-y-1 text-sm flex-1">
        <div className="flex items-center gap-2"><span className="text-muted text-xs">#{s.idx + 1}</span><b className="truncate flex-1">{s.title || "(chưa đặt tên)"}</b>
          <span className="text-[11px] text-muted">{s.camera_movement} · {s.audio_duration ? `${s.audio_duration.toFixed(1)}s` : `${s.duration}s`}</span></div>
        <div className="text-xs line-clamp-3">{s.narration}</div>
        <div className="flex flex-wrap gap-1">{s.character_ids.map((id) => <span key={id} className="text-[11px] px-1.5 rounded bg-panel2 text-accent">{chars.find((c) => c.id === id)?.name ?? "?"}</span>)}
          {s.has_audio && <span className="text-[11px] px-1.5 rounded bg-panel2 text-green-400">🔊 audio</span>}</div>
      </div>
      <div className="p-2 pt-0 flex flex-wrap gap-1">
        <button className="btn !px-2" disabled={s.idx === 0} onClick={() => void api2d.moveScene(s.id, -1).then(onChange)}>↑</button>
        <button className="btn !px-2" disabled={s.idx === total - 1} onClick={() => void api2d.moveScene(s.id, 1).then(onChange)}>↓</button>
        <button className="btn flex-1" onClick={() => setOpen((o) => !o)}>{open ? "Đóng" : "Sửa / ảnh"}</button>
        <button className="btn btn-danger" onClick={() => confirm(`Xóa cảnh #${s.idx + 1}?`) && void api2d.deleteScene(s.id).then(onChange)}>Xóa</button>
      </div>
      {open && (
        <div className="p-3 border-t border-line space-y-3 text-sm">
          {err && <div className="text-xs text-red-300">{err}</div>}
          <div className="grid grid-cols-2 gap-2">
            {T("title", "Tên cảnh", 1, true)}{T("narration", "Lời dẫn", 3, true)}{T("environment", "Bối cảnh")}{T("lighting", "Ánh sáng")}
            {T("camera_angle", "Góc máy")}{T("character_action", "Hành động")}{T("visual_description", "Mô tả hình ảnh", 2, true)}
            {Sel("camera_movement", "Chuyển động camera", MOVEMENTS)}{Sel("transition", "Chuyển cảnh vào", TRANSITIONS)}{Sel("effect", "Hiệu ứng", EFFECTS)}
            <label className="text-xs text-muted">Thời lượng dự kiến (giây; khi có audio sẽ theo lời dẫn)
              <input className="input mt-1" type="number" min={1} max={60} value={f.duration} onChange={(e) => setF({ ...f, duration: Number(e.target.value) })} /></label>
            {T("image_prompt", "Prompt ảnh (tiếng Anh)", 3, true)}{T("negative_prompt", "Negative prompt", 1, true)}
            <div className="col-span-2 text-xs text-muted">Nhân vật trong cảnh:
              <div className="flex flex-wrap gap-2 mt-1">{chars.map((c) => <label key={c.id} className="flex items-center gap-1"><input type="checkbox" checked={f.character_ids.includes(c.id)}
                onChange={(e) => setF({ ...f, character_ids: e.target.checked ? [...f.character_ids, c.id] : f.character_ids.filter((x) => x !== c.id) })} />{c.name}</label>)}
                {chars.length === 0 && "chưa có nhân vật"}</div></div>
          </div>
          <div className="flex gap-2"><button className="btn btn-primary" disabled={!dirty} onClick={() => void save()}>Lưu cảnh</button>
            <button className="btn" onClick={() => void api2d.imageRequest(s.id).then((r) => setPrompt(r.prompt + (r.negative_prompt ? `\n\nNEGATIVE: ${r.negative_prompt}` : "")))}>Xem prompt cuối cùng</button></div>
          {prompt && <pre className="whitespace-pre-wrap text-xs bg-bg border border-line rounded-lg p-2 select-all">{prompt}</pre>}
          <div className="flex gap-2">
            <input className="input" placeholder="Yêu cầu cho Claude khi thiết kế lại cảnh này (tuỳ chọn)" value={instr} onChange={(e) => setInstr(e.target.value)} />
            <button className="btn" disabled={!claudeReady} title={claudeReady ? "" : "Chưa có ANTHROPIC_API_KEY"} onClick={() => void api2d.regenerateScene(s.id, instr).then(() => { setInstr(""); onChange(); }).catch(fail)}>Tạo lại cảnh</button>
          </div>
          <div className="space-y-2">
            <div className="font-medium">Ảnh của cảnh</div>
            <div className="flex flex-wrap gap-2 items-center">
              <input ref={file} type="file" accept="image/png,image/jpeg,image/webp" className="text-xs"
                onChange={(e) => { const x = e.target.files?.[0]; if (x) void api2d.uploadSceneImage(s.id, x).then(() => { onChange(); loadGens(); if (file.current) file.current.value = ""; }).catch(fail); }} />
              {imageProviders.filter((p) => p.configured).map((p) => <button key={p.id} className="btn" onClick={() => void api2d.generateImages(s.id, { provider_id: p.id, n: 1 }).then(() => { onChange(); loadGens(); }).catch(fail)}>Tạo bằng {p.name}</button>)}
              {imageProviders.length === 0 && <span className="text-xs text-muted">Chưa có nhà cung cấp tạo ảnh; hãy tự tải ảnh lên.</span>}
            </div>
            <div className="flex flex-wrap gap-2">
              {gens.filter((g) => g.status === "completed").map((g) => (
                <button key={g.id} title={`${g.provider}${g.model ? ` · ${g.model}` : ""}${g.cost_usd ? ` · $${g.cost_usd.toFixed(3)}` : ""}`}
                  onClick={() => void api2d.selectImage(s.id, g.id).then(onChange)} className={`rounded-lg overflow-hidden border-2 ${g.id === s.image_gen_id ? "border-accent" : "border-transparent"}`}>
                  <img src={imgUrl(g.id)} className="h-16 w-24 object-cover" alt="" /></button>))}
              {gens.filter((g) => g.status === "failed").map((g) => <span key={g.id} className="text-[11px] text-red-300" title={g.error ?? ""}>✗ {g.provider}: lỗi</span>)}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function StoryboardPanel({ pid, hasScript, claudeReady, refreshKey, queue, busy, onChanged }: {
  pid: string; hasScript: boolean; claudeReady: boolean; refreshKey: number; queue: (s: "storyboard") => Promise<void>; busy: boolean; onChanged: () => void;
}) {
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [approved, setApproved] = useState(false);
  const [chars, setChars] = useState<Character[]>([]);
  const [prov, setProv] = useState<{ id: string; name: string; configured: boolean }[]>([]);
  const [est, setEst] = useState<Estimate | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(() => {
    api2d.scenes(pid).then((r) => { setScenes(r.scenes); setApproved(r.approved); }).catch((e) => setErr(String(e.message ?? e)));
    api2d.characters(pid).then((r) => setChars(r.characters)).catch(() => undefined);
    api2d.status().then((s) => setProv(s.providers.image.providers ?? [])).catch(() => undefined);
    onChanged();
  }, [pid, onChanged]);
  useEffect(load, [load, refreshKey]);
  const missing = scenes.filter((s) => !s.has_image).length;

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-line bg-panel p-4 flex flex-wrap items-center gap-3 text-sm">
        <div className="flex-1 min-w-60">{scenes.length} cảnh · {missing ? `${missing} cảnh chưa có ảnh` : "đủ ảnh"} · {approved ? <span className="text-green-400">✓ Đã duyệt</span> : <span className="text-amber-300">Chưa duyệt</span>}</div>
        <button className="btn" onClick={() => void api2d.estimate(pid, "storyboard").then(setEst).catch((e) => setErr(String(e.message ?? e)))}>Ước tính chi phí</button>
        <button className="btn" disabled={busy || !hasScript || !claudeReady} title={!claudeReady ? "Chưa có ANTHROPIC_API_KEY" : !hasScript ? "Cần kịch bản" : ""}
          onClick={() => (scenes.length === 0 || confirm("Tạo lại sẽ thay toàn bộ cảnh hiện có (ảnh đã chọn của các cảnh cũ không còn gắn). Tiếp tục?")) && void queue("storyboard")}>{scenes.length ? "Claude tạo lại storyboard" : "Claude chia cảnh"}</button>
        <button className="btn" onClick={() => void api2d.createScene(pid, { title: "Cảnh mới", narration: "" }).then(load).catch((e) => setErr(String(e.message ?? e)))}>+ Thêm cảnh</button>
        <button className="btn btn-primary" disabled={!scenes.length} onClick={() => void api2d.approve(pid, !approved).then(load).catch((e) => setErr(String(e.message ?? e)))}>{approved ? "Bỏ duyệt" : "Duyệt storyboard"}</button>
      </div>
      {est && <div className="text-xs text-muted">Ước tính (thô): ~{est.input_tokens} token vào, ~{est.output_tokens} token ra{est.cost_usd !== null ? `, ≈ $${est.cost_usd.toFixed(4)}` : " — chưa cấu hình giá nên chưa quy ra tiền"}.</div>}
      {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">{err}</div>}
      {scenes.length === 0 && <div className="text-sm text-muted">Chưa có cảnh. Nhập kịch bản ở tab Thông tin rồi để Claude chia cảnh, hoặc thêm cảnh thủ công.</div>}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(230px, 1fr))" }}>
        {scenes.map((s) => <SceneCard key={s.id} s={s} chars={chars} total={scenes.length} onChange={load} claudeReady={claudeReady} imageProviders={prov} />)}
      </div>
    </div>
  );
}
