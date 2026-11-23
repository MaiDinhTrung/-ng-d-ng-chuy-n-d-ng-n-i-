import { useCallback, useEffect, useState } from "react";
import type { Voice } from "../api";
import { api2d, catLabel, type AspectRatio, type Project2D, type ProjectFields, type ProjectSummary2D, type Revision } from "./api2d";
import { CharactersPanel } from "./CharactersPanel";
import { ProductionPanel } from "./ProductionPanel";
import { ReferenceLibrary } from "./ReferenceLibrary";
import { StoryboardPanel } from "./StoryboardPanel";
import { useTasks } from "./useTasks";

const LANGS: [string, string][] = [["vi", "Tiếng Việt"], ["en", "English"]];
const VIDEO_TYPES = ["Lịch sử / chiến sử", "Truyện kể", "Giáo dục", "Quảng cáo", "Tin tức", "Khác"];
const RATIOS: AspectRatio[] = ["16:9", "9:16", "1:1"];
const STATUS_LABEL: Record<string, string> = { draft: "Nháp", scripting: "Viết kịch bản", storyboard: "Storyboard", imaging: "Tạo ảnh", animating: "Chuyển động", rendering: "Dựng video", done: "Hoàn tất", failed: "Lỗi" };
const REV_KIND: Record<string, string> = { create: "Tạo dự án", update: "Chỉnh sửa", link_reference: "Gắn tư liệu", unlink_reference: "Gỡ tư liệu" };

const EMPTY: ProjectFields = { name: "", description: "", topic: "", script: "", language: "vi", target_audience: "", video_type: "",
  duration_sec: null, aspect_ratio: "16:9", visual_style: "", voice_engine: null, voice_id: null };
const pick = (p: Project2D): ProjectFields => ({ name: p.name, description: p.description, topic: p.topic, script: p.script, language: p.language,
  target_audience: p.target_audience, video_type: p.video_type, duration_sec: p.duration_sec, aspect_ratio: p.aspect_ratio,
  visual_style: p.visual_style, voice_engine: p.voice_engine, voice_id: p.voice_id });

function Editor({ project, voices, reload, openLibrary }: { project: Project2D; voices: Voice[]; reload: () => void; openLibrary: () => void }) {
  const [f, setF] = useState<ProjectFields>(pick(project));
  const [p, setP] = useState(project);
  const [revs, setRevs] = useState<Revision[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const dirty = JSON.stringify(f) !== JSON.stringify(pick(p));
  const set = <K extends keyof ProjectFields>(k: K, v: ProjectFields[K]) => { setF((x) => ({ ...x, [k]: v })); setSaved(false); };

  const refresh = useCallback(async () => {
    try { const n = await api2d.project(p.id); setP(n); reload(); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  }, [p.id, reload]);

  const save = async () => {
    setErr(null);
    try {
      const diff = Object.fromEntries(Object.entries(f).filter(([k, v]) => JSON.stringify(v) !== JSON.stringify(pick(p)[k as keyof ProjectFields])));
      const n = await api2d.updateProject(p.id, diff); setP(n); setF(pick(n)); setSaved(true); reload();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  const voice = voices.find((v) => v.id === f.voice_id);
  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line bg-panel p-3 grid grid-cols-2 lg:grid-cols-4 gap-x-3 gap-y-2 text-xs">
        <div className="col-span-2 lg:col-span-4 flex items-center gap-3">
          <h2 className="font-medium flex-1">Thông tin dự án</h2>
          <span className="text-xs text-muted">{STATUS_LABEL[p.status] ?? p.status} · ID {p.id}</span>
          <button className="btn btn-primary" disabled={!dirty || !f.name.trim()} onClick={() => void save()}>Lưu</button>
        </div>
        {saved && !dirty && <div className="col-span-2 lg:col-span-4 text-xs text-green-300">Đã lưu.</div>}
        {err && <div className="col-span-2 lg:col-span-4 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-red-200">{err}</div>}
        <label className="text-xs text-muted col-span-2 lg:col-span-2">Tên dự án
          <input className="input mt-1" value={f.name} onChange={(e) => set("name", e.target.value)} /></label>
        <label className="text-xs text-muted col-span-2 lg:col-span-4">Mô tả dự án
          <textarea className="input mt-1" rows={1} value={f.description} onChange={(e) => set("description", e.target.value)} /></label>
        <label className="text-xs text-muted col-span-2 lg:col-span-2">Chủ đề nội dung
          <input className="input mt-1" value={f.topic} onChange={(e) => set("topic", e.target.value)} /></label>
        <label className="text-xs text-muted">Ngôn ngữ
          <select className="input mt-1" value={f.language} onChange={(e) => set("language", e.target.value)}>
            {LANGS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select></label>
        <label className="text-xs text-muted">Đối tượng khán giả
          <input className="input mt-1" value={f.target_audience} onChange={(e) => set("target_audience", e.target.value)} /></label>
        <label className="text-xs text-muted">Loại video
          <input className="input mt-1" list="s2d-types" value={f.video_type} onChange={(e) => set("video_type", e.target.value)} />
          <datalist id="s2d-types">{VIDEO_TYPES.map((t) => <option key={t} value={t} />)}</datalist></label>
        <label className="text-xs text-muted">Thời lượng dự kiến (giây)
          <input className="input mt-1" type="number" min={1} value={f.duration_sec ?? ""}
            onChange={(e) => set("duration_sec", e.target.value ? Math.max(1, Math.round(Number(e.target.value))) : null)} /></label>
        <label className="text-xs text-muted">Tỉ lệ khung hình
          <select className="input mt-1" value={f.aspect_ratio} onChange={(e) => set("aspect_ratio", e.target.value as AspectRatio)}>
            {RATIOS.map((r) => <option key={r}>{r}</option>)}
          </select></label>
        <label className="text-xs text-muted">Phong cách hình ảnh
          <input className="input mt-1" value={f.visual_style} placeholder="vd: tranh thủy mặc, truyện tranh cổ trang"
            onChange={(e) => set("visual_style", e.target.value)} /></label>
        <label className="text-xs text-muted col-span-2">Giọng đọc (dùng module Audio hiện có)
          <select className="input mt-1" value={f.voice_id ?? ""} onChange={(e) => {
            const v = voices.find((x) => x.id === e.target.value);
            setF((x) => ({ ...x, voice_id: v?.id ?? null, voice_engine: v?.engine ?? null })); setSaved(false);
          }}>
            <option value="">Chưa chọn</option>
            {f.voice_id && !voice && <option value={f.voice_id}>{f.voice_id} (không còn trong thư viện giọng)</option>}
            {voices.map((v) => <option key={`${v.engine}:${v.id}`} value={v.id}>{v.name}{v.region ? ` · ${v.region}` : ""}</option>)}
          </select></label>
        <label className="text-xs text-muted col-span-2 lg:col-span-4">Kịch bản / nội dung (để trống nếu muốn Agent tự viết)
          <textarea className="input mt-1" rows={5} value={f.script} onChange={(e) => set("script", e.target.value)} /></label>
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-3">
        <div className="flex items-center gap-3">
          <h2 className="font-medium flex-1">Tư liệu tham khảo của dự án ({p.references.length})</h2>
          <button className="btn" onClick={() => setAdding((a) => !a)}>{adding ? "Đóng" : "+ Thêm / tải tư liệu"}</button>
          <button className="btn" onClick={openLibrary}>Mở thư viện</button>
        </div>
        {p.references.length === 0 && <div className="text-xs text-muted">Chưa gắn tư liệu nào.</div>}
        <div className="grid gap-3" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))" }}>
          {p.references.map((r) => (
            <div key={r.id} className="rounded-lg border border-line overflow-hidden text-xs">
              <img src={r.thumb_url} alt={r.name} loading="lazy" className="w-full aspect-[4/3] object-contain bg-black/40" />
              <div className="p-2 space-y-1">
                <div className="truncate font-medium" title={r.name}>{r.name}</div>
                <div className="text-muted">{catLabel(r.category)}</div>
                <button className="btn !py-0.5 !px-2 !text-xs w-full" onClick={() => void api2d.unlink(p.id, r.id).then(() => refresh())}>Gỡ khỏi dự án</button>
              </div>
            </div>
          ))}
        </div>
        {adding && <div className="border-t border-line pt-3 -mx-6"><ReferenceLibrary projectId={p.id} onLinked={() => void refresh()} /></div>}
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 text-sm">
        <button className="text-muted hover:text-white" onClick={() => revs ? setRevs(null) : void api2d.revisions(p.id).then((r) => setRevs(r.revisions))}>
          {revs ? "▾" : "▸"} Lịch sử chỉnh sửa
        </button>
        {revs && <ul className="mt-2 space-y-1 text-xs">{revs.map((r) => (
          <li key={r.id} className="flex gap-2"><span className="text-muted shrink-0">{new Date(r.created_at).toLocaleString("vi-VN")}</span>
            <span>{REV_KIND[r.kind] ?? r.kind}{r.kind === "update" ? `: ${Object.keys(r.changes).join(", ")}` : ""}</span></li>))}</ul>}
      </section>
    </div>
  );
}

type Sub = "info" | "chars" | "story" | "prod";
const SUBS: [Sub, string][] = [["info", "Thông tin & tư liệu"], ["chars", "Nhân vật"], ["story", "Storyboard"], ["prod", "Sản xuất"]];

function Workspace({ project, voices, reload, openLibrary }: { project: Project2D; voices: Voice[]; reload: () => void; openLibrary: () => void }) {
  const [sub, setSub] = useState<Sub>("info");
  const [tick, setTick] = useState(0);
  const [claudeReady, setClaudeReady] = useState(false);
  const [script, setScript] = useState(project.script);
  const [refs, setRefs] = useState(project.references);
  const [err, setErr] = useState<string | null>(null);
  const { tasks, reload: reloadTasks, busy } = useTasks(project.id, () => { setTick((t) => t + 1); reload(); api2d.project(project.id).then((p) => { setScript(p.script); setRefs(p.references); }).catch(() => undefined); });
  useEffect(() => { api2d.status().then((s) => setClaudeReady(s.providers.claude.configured)).catch(() => undefined); }, []);
  const queue = async (stage: "characters" | "storyboard") => {
    setErr(null);
    try { await api2d.runStage(project.id, stage); reloadTasks(); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  };
  return (
    <div className="space-y-4">
      <div className="flex gap-1 border-b border-line">
        {SUBS.map(([k, l]) => (
          <button key={k} onClick={() => setSub(k)} className={`px-3 py-2 text-sm border-b-2 ${sub === k ? "border-accent text-accent" : "border-transparent text-muted hover:text-white"}`}>{l}</button>
        ))}
        {busy && <span className="ml-auto self-center text-xs text-accent">⏳ Đang xử lý nền…</span>}
      </div>
      {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">{err}</div>}
      {!claudeReady && sub !== "info" && sub !== "prod" && <div className="text-xs text-amber-300">Chưa có ANTHROPIC_API_KEY trong .env: các nút dùng Claude bị khóa. Bạn vẫn nhập nhân vật/cảnh/ảnh thủ công được.</div>}
      {sub === "info" && <Editor key={project.id + tick} project={project} voices={voices} reload={reload} openLibrary={openLibrary} />}
      {sub === "chars" && <CharactersPanel pid={project.id} hasScript={!!script.trim()} claudeReady={claudeReady} refreshKey={tick} queue={queue} busy={busy} refs={refs} />}
      {sub === "story" && <StoryboardPanel pid={project.id} hasScript={!!script.trim()} claudeReady={claudeReady} refreshKey={tick} queue={queue} busy={busy} onChanged={reload} />}
      {sub === "prod" && <ProductionPanel pid={project.id} tasks={tasks} busy={busy} reloadTasks={() => void reloadTasks()} refreshKey={tick} />}
    </div>
  );
}

export function ProjectsTab({ voices, openLibrary }: { voices: Voice[]; openLibrary: () => void }) {
  const [list, setList] = useState<ProjectSummary2D[]>([]);
  const [cur, setCur] = useState<Project2D | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reload = useCallback(() => { api2d.projects().then((r) => setList(r.projects)).catch((e) => setErr(String(e.message ?? e))); }, []);
  useEffect(() => { reload(); }, [reload]);
  useEffect(() => {
    let id: string | null = null;
    try { id = localStorage.getItem("s2d-pid"); } catch { /* ignore */ }
    if (id) api2d.project(id).then(setCur).catch(() => undefined);
  }, []);

  const open = async (id: string | null) => {
    try { localStorage.setItem("s2d-pid", id ?? ""); } catch { /* ignore */ }
    setErr(null);
    if (!id) return setCur(null);
    try { setCur(await api2d.project(id)); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  };
  const create = async () => {
    try { const p = await api2d.createProject({ ...EMPTY, name: "Dự án 2D mới" }); reload(); void open(p.id); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  };

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-52 shrink-0 border-r border-line p-3 space-y-2 overflow-y-auto">
        <button className="btn btn-primary w-full" onClick={() => void create()}>+ Dự án mới</button>
        {list.length === 0 && <div className="text-xs text-muted px-1">Chưa có dự án 2D.</div>}
        {list.map((p) => (
          <div key={p.id} className={`rounded-lg border p-2 text-sm cursor-pointer hover:bg-panel2 ${cur?.id === p.id ? "border-accent" : "border-line"}`}
            onClick={() => void open(p.id)}>
            <div className="truncate font-medium">{p.name}</div>
            <div className="text-[11px] text-muted">{STATUS_LABEL[p.status] ?? p.status} · {p.aspect_ratio} · {p.reference_count} tư liệu</div>
            <div className="text-[11px] text-muted">{new Date(p.updated_at).toLocaleString("vi-VN")}</div>
          </div>
        ))}
      </aside>
      <div className="flex-1 min-w-0 overflow-y-auto p-4">
        <div className="max-w-6xl mx-auto space-y-3">
          {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">{err}</div>}
          {!cur ? <div className="text-muted">Chọn một dự án hoặc tạo dự án mới.</div> : (
            <>
              <div className="flex justify-end">
                <button className="btn btn-danger" onClick={() => confirm(`Xóa dự án “${cur.name}”? Tư liệu trong thư viện vẫn được giữ lại.`) &&
                  void api2d.deleteProject(cur.id).then(() => { reload(); void open(null); }).catch((e) => setErr(String(e.message ?? e)))}>Xóa dự án</button>
              </div>
              <Workspace key={cur.id} project={cur} voices={voices} reload={reload} openLibrary={openLibrary} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
