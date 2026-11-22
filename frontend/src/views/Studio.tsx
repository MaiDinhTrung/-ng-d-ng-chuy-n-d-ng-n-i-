import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, downloadUrl, segmentAudioUrl, type Engine, type ExportResult, type Health, type Project, type Segment, type UserPrefs, type Voice } from "../api";
import type { PlayerSource } from "../components/AudioPlayer";
import { SegmentCard } from "../components/SegmentCard";

interface Props {
  projectId: string | null; voices: Voice[]; engines: Engine[]; health: Health | null; prefs: UserPrefs;
  setPlayer: (p: PlayerSource) => void; onChanged: () => void; onNew: () => void; activeSrc: string | null;
}

const words = (t: string) => (t.trim() ? t.trim().split(/\s+/).length : 0);

export function Studio({ projectId, voices, engines, health, prefs, setPlayer, onChanged, onNew, activeSrc }: Props) {
  const [project, setProject] = useState<Project | null>(null);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [sample, setSample] = useState("Xin chào các bạn, đây là giọng đọc thử nghiệm.");
  const [busy, setBusy] = useState<string | null>(null);
  const [progress, setProgress] = useState<string | null>(null);
  const [fmt, setFmt] = useState(prefs.format);
  const [mode, setMode] = useState<"merged" | "segments">("merged");
  const [dir, setDir] = useState(prefs.exportDir);
  const [result, setResult] = useState<ExportResult | null>(null);
  const loadedId = useRef<string | null>(null);

  const fail = (e: unknown) => setErr(e instanceof Error ? e.message : String(e));

  const load = useCallback(async (id: string, resetText: boolean) => {
    const p = await api.project(id);
    setProject(p);
    if (resetText) setText(p.source_text);
    return p;
  }, []);

  useEffect(() => {
    setErr(null); setMsg(null); setResult(null);
    if (!projectId) { setProject(null); setText(""); loadedId.current = null; return; }
    loadedId.current = projectId;
    load(projectId, true).catch(fail);
  }, [projectId, load]);

  // Poll khi còn đoạn đang chờ/đang tạo (dữ liệu bền: refresh trang vẫn thấy trạng thái thật).
  const active = project?.segments.some((s) => s.status === "generating" || (s.status === "pending" && (health?.queue ?? 0) > 0));
  useEffect(() => {
    if (!projectId || !active) return;
    const t = setInterval(() => { load(projectId, false).then(onChanged).catch(() => undefined); }, 1200);
    return () => clearInterval(t);
  }, [projectId, active, load, onChanged]);

  const run = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setErr(null); setMsg(null);
    try { await fn(); } catch (e) { fail(e); } finally { setBusy(null); }
  };

  const settings = project?.settings;
  const engine = engines.find((e) => e.id === settings?.engine);
  const engineVoices = useMemo(() => voices.filter((v) => v.engine === settings?.engine), [voices, settings?.engine]);
  const voice = engineVoices.find((v) => v.id === settings?.voice);

  if (!projectId || !project || !settings) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center space-y-3">
          <div className="text-xl">Chưa mở dự án nào</div>
          <button className="btn btn-primary" onClick={onNew}>+ Dự án mới</button>
        </div>
      </div>
    );
  }
  const pid = project.id;

  const setSettings = (s: Parameters<typeof api.updateProject>[1]["settings"], apply?: ("voice" | "speed")[]) =>
    run("settings", async () => { setProject(await api.updateProject(pid, { settings: s, apply_to_segments: apply })); onChanged(); });

  const resegment = () => run("seg", async () => {
    if (project.segments.length && !confirm("Chia lại sẽ giữ âm thanh của các đoạn có nội dung không đổi và xóa các đoạn cũ không còn khớp. Tiếp tục?")) return;
    setProject(await api.resegment(pid, text)); setMsg("Đã chia đoạn."); onChanged();
  });

  const patchSeg = async (id: string, body: Partial<Segment>) => {
    try { await api.patchSegment(id, body); await load(pid, false); onChanged(); } catch (e) { fail(e); await load(pid, false); }
  };

  const generate = (force: boolean) => run("gen", async () => {
    const r = await api.generate(pid, { force });
    setMsg(r.queued ? `Đã xếp hàng ${r.queued} đoạn.` : "Không có đoạn nào cần tạo.");
    await load(pid, false);
  });
  const genOne = async (id: string) => { try { await api.regenerate(id); await load(pid, false); } catch (e) { fail(e); } };

  const playSeg = (s: Segment) => setPlayer({ src: segmentAudioUrl(s), title: `#${s.idx + 1} ${s.text}`, nonce: Date.now() });

  const doPreview = () => run("preview", async () => {
    const url = await api.previewTts({ text: sample, voice: settings.voice, speed: settings.speed, engine: settings.engine, normalize: settings.normalize });
    setPlayer({ src: url, title: `Nghe thử: ${voice?.name ?? "mặc định"}`, nonce: Date.now() });
  });

  const exportNow = (listen = false) => run(listen ? "listen" : "export", async () => {
    const { job_id } = await api.exportProject(pid, listen ? { format: "wav", mode: "merged" } : { format: fmt, mode, output_dir: dir || null, mp3_kbps: prefs.mp3_kbps });
    let r: ExportResult | null = null;
    for (;;) {                       // xuất chạy nền; theo dõi tiến độ
      const j = await api.job(job_id);
      setProgress(j.total ? `${j.done}/${j.total} đoạn` : "đang chuẩn bị…");
      if (j.status === "failed") { setProgress(null); throw new Error(j.error ?? "Xuất thất bại"); }
      if (j.status === "done") { r = j.result; break; }
      await new Promise((res) => setTimeout(res, 700));
    }
    setProgress(null);
    if (!r) return;
    if (listen) { setPlayer({ src: downloadUrl(r.files[0]) + `&t=${Date.now()}`, title: "Bản ghép (đã chèn khoảng lặng)", nonce: Date.now() }); return; }
    setResult(r); setMsg(`Đã xuất ${r.files.length} file.`);
  });

  const addSeg = async (idx: number | null) => {
    const t = prompt("Nội dung đoạn mới:");
    if (!t?.trim()) return;
    try { await api.addSegment(pid, t, idx); await load(pid, false); onChanged(); } catch (e) { fail(e); }
  };
  const delSeg = async (id: string) => { try { await api.deleteSegment(id); await load(pid, false); onChanged(); } catch (e) { fail(e); } };

  const counts = project.segments.reduce((a, s) => ({ ...a, [s.status]: (a[s.status] ?? 0) + 1 }), {} as Record<string, number>);
  const allDone = project.segments.length > 0 && counts.completed === project.segments.length;
  const engineReady = engine?.status.state === "ready";

  return (
    <div className="h-full grid grid-cols-[minmax(0,1fr)_340px] gap-4 p-4 overflow-hidden">
      <div className="min-w-0 overflow-y-auto pr-1 space-y-4">
        <div className="flex items-center gap-3">
          <input className="input !text-lg !font-semibold !w-80" defaultValue={project.name} key={project.id + project.name}
            onBlur={(e) => { const n = e.target.value.trim(); if (n && n !== project.name) void run("rename", async () => { setProject(await api.updateProject(pid, { name: n })); onChanged(); }); }} />
          <div className="text-xs text-muted">{project.segments.length} đoạn · {counts.completed ?? 0} xong{counts.failed ? ` · ${counts.failed} lỗi` : ""}</div>
          <div className="flex-1" />
          <button className="btn btn-primary" disabled={!engineReady || !project.segments.length || !!busy} onClick={() => generate(false)}>▶ Tạo âm thanh (đoạn chưa xong)</button>
          <button className="btn" disabled={!engineReady || !project.segments.length || !!busy} onClick={() => confirm("Tạo lại TẤT CẢ đoạn?") && generate(true)}>Tạo lại tất cả</button>
        </div>

        {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200 flex">
          <span className="flex-1">{err}</span><button onClick={() => setErr(null)}>✕</button></div>}
        {msg && <div className="rounded-lg border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-200">{msg}</div>}

        <section className="rounded-xl border border-line bg-panel p-3 space-y-2">
          <div className="flex items-center gap-3 text-sm">
            <b>Văn bản</b>
            <span className="text-muted">{text.length.toLocaleString("vi-VN")} ký tự · {words(text).toLocaleString("vi-VN")} từ</span>
            <div className="flex-1" />
            <label className="btn cursor-pointer">Tải file TXT
              <input type="file" accept=".txt,text/plain" hidden onChange={async (e) => { const f = e.target.files?.[0]; if (f) setText(await f.text()); e.target.value = ""; }} />
            </label>
            <button className="btn btn-primary" disabled={!text.trim() || !!busy} onClick={resegment}>Chia đoạn</button>
          </div>
          <textarea className="input min-h-[180px] max-h-[40vh] resize-y leading-relaxed" value={text} onChange={(e) => setText(e.target.value)}
            placeholder={"Nhập hoặc dán văn bản tiếng Việt…\nChèn [pause=500] để nghỉ 500ms. Xuống dòng = nghỉ giữa các đoạn."} />
          {text !== project.source_text && <div className="text-xs text-amber-300">Văn bản đã sửa nhưng chưa bấm “Chia đoạn”.</div>}
          <details className="text-sm">
            <summary className="cursor-pointer text-muted">Khoảng nghỉ tự động &amp; tùy chọn chia đoạn</summary>
            <div className="mt-2 grid grid-cols-4 gap-3">
              {([["comma", "Dấu phẩy"], ["period", "Dấu chấm/!/?"], ["ellipsis", "Dấu ba chấm"], ["newline", "Xuống dòng"]] as const).map(([k, l]) => (
                <label key={k} className="text-xs text-muted">{l} (ms)
                  <input type="number" min={0} max={60000} step={50} className="input mt-1" defaultValue={settings.pauses[k]} key={`${k}${settings.pauses[k]}`}
                    onBlur={(e) => { const n = Math.max(0, Number(e.target.value) || 0); if (n !== settings.pauses[k]) void setSettings({ pauses: { [k]: n } }); }} />
                </label>
              ))}
            </div>
            <div className="mt-2 flex gap-6 text-xs text-muted">
              <label className="flex items-center gap-2"><input type="checkbox" checked={settings.split_commas} onChange={(e) => void setSettings({ split_commas: e.target.checked })} />Tách đoạn tại dấu phẩy (nghỉ “dấu phẩy” giữa các đoạn)</label>
              <label className="flex items-center gap-2"><input type="checkbox" checked={settings.normalize} onChange={(e) => void setSettings({ normalize: e.target.checked })} />Chuẩn hóa số/ngày giờ trước khi đọc</label>
            </div>
            <div className="mt-1 text-xs text-muted">Áp dụng cho lần “Chia đoạn” tiếp theo. Có thể chỉnh nghỉ từng đoạn ở thẻ đoạn.</div>
          </details>
        </section>

        <section className="space-y-3">
          {project.segments.length === 0 && <div className="text-muted text-sm">Chưa có đoạn. Nhập văn bản rồi bấm “Chia đoạn”.</div>}
          {project.segments.map((s) => (
            <SegmentCard key={s.id} seg={s} voices={engineVoices} defaultVoice={settings.voice} active={!!activeSrc && activeSrc.includes(s.id)}
              onPatch={patchSeg} onGenerate={genOne} onPlay={playSeg} onDelete={delSeg} onAddAfter={(i) => void addSeg(i)} />
          ))}
          {project.segments.length > 0 && <button className="btn" onClick={() => void addSeg(null)}>+ Thêm đoạn cuối</button>}
        </section>
      </div>

      <aside className="overflow-y-auto space-y-4">
        <section className="rounded-xl border border-line bg-panel p-3 space-y-3 text-sm">
          <b>Giọng đọc</b>
          <label className="block text-xs text-muted">Engine
            <select className="input mt-1" value={settings.engine} onChange={(e) => void setSettings({ engine: e.target.value })}>
              {engines.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
            </select>
          </label>
          {engine && <div className={`text-xs ${engineReady ? "text-emerald-300" : engine.status.state === "error" ? "text-red-300" : "text-amber-300"}`}>
            {engineReady ? "● Sẵn sàng" : engine.status.state === "loading" ? "● Đang nạp model…" : `● ${engine.status.state}${engine.status.error ? `: ${engine.status.error}` : ""}`}</div>}
          <label className="block text-xs text-muted">Giọng
            <select className="input mt-1" value={settings.voice ?? ""} onChange={(e) => void setSettings({ voice: e.target.value || null })}>
              <option value="">— chọn giọng —</option>
              {engineVoices.map((v) => <option key={v.id} value={v.id}>{v.name}{v.gender ? ` · ${v.gender}` : ""}{v.source === "custom" ? " (của bạn)" : ""}</option>)}
            </select>
          </label>
          {voice && <div className="text-xs text-muted space-y-0.5">
            <div>{[voice.gender, voice.region].filter(Boolean).join(" · ") || "Không có thông tin giới tính/vùng"}</div>
            {voice.tags.length > 0 && <div className="flex flex-wrap gap-1">{voice.tags.map((t) => <span key={t} className="px-1.5 py-0.5 rounded bg-panel2">{t}</span>)}</div>}
          </div>}
          <label className="block text-xs text-muted">Tốc độ mặc định: {settings.speed.toFixed(2)}×
            <input type="range" min={0.5} max={2} step={0.05} className="w-full" value={settings.speed}
              onChange={(e) => setProject({ ...project, settings: { ...settings, speed: Number(e.target.value) } })}
              onMouseUp={() => void setSettings({ speed: settings.speed })} onKeyUp={() => void setSettings({ speed: settings.speed })} />
          </label>
          {engine && !engine.capabilities.speed_control && <div className="text-[11px] text-muted">Engine này không có tham số tốc độ; tốc độ được áp dụng sau khi tạo bằng FFmpeg (giữ cao độ).</div>}
          <div className="flex gap-2">
            <button className="btn flex-1 !text-xs" disabled={!!busy} onClick={() => void setSettings({ voice: settings.voice }, ["voice"])}>Áp giọng cho mọi đoạn</button>
            <button className="btn flex-1 !text-xs" disabled={!!busy} onClick={() => void setSettings({ speed: settings.speed }, ["speed"])}>Áp tốc độ cho mọi đoạn</button>
          </div>
          <textarea className="input" rows={2} value={sample} onChange={(e) => setSample(e.target.value)} />
          <button className="btn btn-primary w-full" disabled={!engineReady || !settings.voice || !sample.trim() || busy === "preview"} onClick={doPreview}>
            {busy === "preview" ? "Đang tạo…" : "🔈 Nghe thử"}</button>
          {!settings.voice && <div className="text-[11px] text-amber-300">Chọn một giọng để tạo âm thanh.</div>}
        </section>

        <section className="rounded-xl border border-line bg-panel p-3 space-y-3 text-sm">
          <b>Xuất file</b>
          <div className="grid grid-cols-2 gap-2">
            <label className="text-xs text-muted">Định dạng
              <select className="input mt-1" value={fmt} onChange={(e) => setFmt(e.target.value as "wav" | "mp3")}>
                <option value="wav">WAV</option>
                <option value="mp3" disabled={!health?.ffmpeg.available}>MP3{health?.ffmpeg.available ? "" : " (cần FFmpeg)"}</option>
              </select></label>
            <label className="text-xs text-muted">Kiểu
              <select className="input mt-1" value={mode} onChange={(e) => setMode(e.target.value as "merged" | "segments")}>
                <option value="merged">Ghép thành 1 file</option>
                <option value="segments">Từng đoạn</option>
              </select></label>
          </div>
          <label className="block text-xs text-muted">Thư mục lưu
            <div className="flex gap-2 mt-1">
              <input className="input" value={dir} onChange={(e) => setDir(e.target.value)} placeholder="Mặc định: thư mục dữ liệu của ứng dụng" />
              <button className="btn" onClick={async () => { try { const r = await api.pickFolder(); if (r.path) setDir(r.path); } catch (e) { fail(e); } }}>Chọn…</button>
            </div>
          </label>
          <button className="btn btn-primary w-full" disabled={!allDone || !!busy} onClick={() => exportNow(false)}>{busy === "export" ? `Đang xuất… ${progress ?? ""}` : "Xuất"}</button>
          <button className="btn w-full" disabled={!allDone || !!busy} onClick={() => exportNow(true)}>🎧 Nghe bản ghép (có khoảng lặng thật)</button>
          {!allDone && <div className="text-[11px] text-muted">Cần tạo xong mọi đoạn trước khi xuất.</div>}
          {result && <div className="text-xs space-y-1">
            <div className="text-muted break-all">Đã lưu tại: {result.directory}</div>
            {result.files.slice(0, 6).map((f) => <div key={f} className="break-all">{f.split(/[\\/]/).pop()}{" "}
              <a className="text-accent underline" href={downloadUrl(f)} onClick={(e) => { if (!f.includes("exports")) e.preventDefault(); }}>{f.includes("exports") ? "tải" : ""}</a></div>)}
            {result.files.length > 6 && <div className="text-muted">…và {result.files.length - 6} file nữa</div>}
          </div>}
        </section>
      </aside>
    </div>
  );
}
