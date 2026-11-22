import { useCallback, useEffect, useRef, useState } from "react";
import { api, downloadUrl, type Engine, type Health, type Job, type Project, type UserPrefs, type Voice } from "../api";
import type { PlayerSource } from "../components/AudioPlayer";

interface Props {
  voices: Voice[]; engines: Engine[]; health: Health | null; prefs: UserPrefs;
  setPlayer: (p: PlayerSource) => void; onOpenProject: (id: string) => void; onChanged: () => void;
}

const KEY = "quick-last";
const fmtTime = (s: number) => {
  s = Math.max(0, Math.round(s));
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h ? `${h} giờ ${m} phút` : m ? `${m} phút ${sec}s` : `${sec}s`;
};
const CHARS_PER_SEC = 15;   // ước lượng của chính thư viện ZeroTTS

export function Quick({ voices, engines, health, prefs, setPlayer, onOpenProject, onChanged }: Props) {
  const [text, setText] = useState("");
  const [voice, setVoice] = useState<string>(() => { try { return localStorage.getItem("quick-voice") ?? ""; } catch { return ""; } });
  const [speed, setSpeed] = useState(1);
  const [fmt, setFmt] = useState(prefs.format);
  const [dir, setDir] = useState(prefs.exportDir);
  const [job, setJob] = useState<Job | null>(null);
  const [pid, setPid] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [drag, setDrag] = useState(false);
  const [resume, setResume] = useState<Project | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const timer = useRef<number | null>(null);

  const engine = engines.find((e) => e.id === "zerotts");
  const ready = engine?.status.state === "ready";
  const list = voices.filter((v) => v.engine === "zerotts");
  const fail = (e: unknown) => setErr(e instanceof Error ? e.message : String(e));
  const running = job?.status === "running";

  useEffect(() => {
    if (!voice && list.length) setVoice((list.find((v) => v.id === "maichi") ?? list[0]).id);
  }, [list, voice]);
  useEffect(() => { try { if (voice) localStorage.setItem("quick-voice", voice); } catch { /* ignore */ } }, [voice]);

  const stop = () => { if (timer.current) { clearInterval(timer.current); timer.current = null; } };
  const follow = useCallback((jobId: string, projectId: string) => {
    stop();
    setPid(projectId);
    try { localStorage.setItem(KEY, JSON.stringify({ jobId, projectId })); } catch { /* ignore */ }
    const tick = async () => {
      try {
        const j = await api.job(jobId);
        setJob(j);
        if (j.status !== "running") { stop(); onChanged(); }
      } catch { stop(); }
    };
    void tick();
    timer.current = window.setInterval(tick, 1000);
  }, [onChanged]);
  useEffect(() => stop, []);

  // Mở lại trang: nối tiếp tác vụ đang chạy, hoặc đề nghị tiếp tục dự án dở.
  useEffect(() => {
    let saved: { jobId: string; projectId: string } | null = null;
    try { saved = JSON.parse(localStorage.getItem(KEY) ?? "null"); } catch { /* ignore */ }
    if (!saved) return;
    const s = saved;
    api.job(s.jobId).then((j) => {
      if (j.status === "running") follow(s.jobId, s.projectId);
      else { setJob(j); setPid(s.projectId); }
    }).catch(async () => {
      try {
        const p = await api.project(s.projectId);
        if (p.segments.some((x) => x.status !== "completed")) setResume(p);
      } catch { /* project đã bị xóa */ }
    });
  }, [follow]);

  const readFiles = async (files: FileList | File[]) => {
    const parts: string[] = [];
    for (const f of Array.from(files)) {
      if (!/\.txt$/i.test(f.name) && f.type !== "text/plain") { setErr(`“${f.name}” không phải file .txt`); continue; }
      parts.push(await f.text());
    }
    if (parts.length) setText((t) => [t.trim(), ...parts.map((p) => p.trim())].filter(Boolean).join("\n\n"));
  };

  const start = async () => {
    setErr(null); setStarting(true); setJob(null); setResume(null);
    try {
      const r = await api.quick({ text, voice, speed, format: fmt, mp3_kbps: prefs.mp3_kbps, output_dir: dir || null, pauses: prefs.pauses });
      follow(r.job_id, r.project_id);
    } catch (e) { fail(e); } finally { setStarting(false); }
  };
  const retry = async (projectId: string) => {
    setErr(null); setStarting(true); setResume(null);
    try { const r = await api.autoResume(projectId, { format: fmt, mp3_kbps: prefs.mp3_kbps, output_dir: dir || null }); follow(r.job_id, projectId); }
    catch (e) { fail(e); } finally { setStarting(false); }
  };
  const preview = async () => {
    setPreviewing(true); setErr(null);
    try {
      const first = text.trim().split(/(?<=[.!?…])\s+/)[0]?.slice(0, 200) || "Xin chào các bạn, đây là giọng đọc thử nghiệm.";
      setPlayer({ src: await api.previewTts({ text: first, voice, speed, engine: "zerotts", normalize: true }), title: "Nghe thử", nonce: Date.now() });
    } catch (e) { fail(e); } finally { setPreviewing(false); }
  };
  const reset = () => { stop(); setJob(null); setPid(null); setErr(null); setText(""); try { localStorage.removeItem(KEY); } catch { /* ignore */ } };

  const chars = text.replace(/\s+/g, " ").trim().length;
  const words = text.trim() ? text.trim().split(/\s+/).length : 0;
  const estAudio = chars / CHARS_PER_SEC;
  const file = job?.result?.files[0];
  const phaseLabel = job?.status === "running" ? (job.phase === "merge" ? "Đang ghép thành 1 file" : "Đang đọc văn bản") : "";

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <div>
        <h1 className="text-2xl font-semibold">Tạo giọng đọc</h1>
        <p className="text-sm text-muted mt-1">Dán văn bản hoặc thả file .txt, chọn giọng rồi bấm tạo. Ứng dụng tự chia đoạn, tự đọc và ghép thành một file.</p>
      </div>

      {!health && <Box tone="red">Không kết nối được backend. Hãy chạy run.ps1.</Box>}
      {health && !ready && !err && <Box tone="amber">{engine?.status.state === "error" ? `Model lỗi: ${engine.status.error}` : "Đang nạp model giọng đọc, vài giây nữa…"}</Box>}
      {health && !health.ffmpeg.available && <Box tone="amber">Chưa có FFmpeg: chưa xuất được MP3 và chưa đổi được tốc độ. Cài bằng: winget install Gyan.FFmpeg</Box>}
      {err && <Box tone="red" onClose={() => setErr(null)}>{err}</Box>}

      {resume && !running && (
        <Box tone="amber">
          Có một lần tạo dang dở ({resume.segments.filter((s) => s.status === "completed").length}/{resume.segments.length} đoạn đã đọc xong).
          <div className="mt-2 flex gap-2"><button className="btn btn-primary" onClick={() => void retry(resume.id)} disabled={!ready || starting}>Tiếp tục</button>
            <button className="btn" onClick={() => { setResume(null); try { localStorage.removeItem(KEY); } catch { /* ignore */ } }}>Bỏ qua</button></div>
        </Box>
      )}

      <section
        className={`rounded-xl border bg-panel p-3 space-y-2 ${drag ? "border-accent bg-panel2" : "border-line"}`}
        onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); if (!running) void readFiles(e.dataTransfer.files); }}>
        <textarea className="input min-h-[240px] max-h-[50vh] resize-y leading-relaxed" value={text} disabled={running}
          onChange={(e) => setText(e.target.value)} placeholder={"Dán văn bản tiếng Việt vào đây, hoặc kéo thả file .txt vào khung này…\n\nMẹo: chèn [pause=1000] để nghỉ 1 giây ở chỗ bạn muốn."} />
        <div className="flex items-center gap-3 text-sm">
          <span className="text-muted">{chars.toLocaleString("vi-VN")} ký tự · {words.toLocaleString("vi-VN")} từ{chars > 0 && ` · khoảng ${fmtTime(estAudio)} âm thanh, mất cỡ ${fmtTime(estAudio)} để tạo`}</span>
          <div className="flex-1" />
          {text && !running && <button className="btn" onClick={() => setText("")}>Xóa</button>}
          <label className={`btn ${running ? "opacity-50" : "cursor-pointer"}`}>Chọn file .txt
            <input type="file" accept=".txt,text/plain" multiple hidden disabled={running} onChange={(e) => { if (e.target.files) void readFiles(e.target.files); e.target.value = ""; }} /></label>
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
        <label className="text-xs text-muted">Giọng đọc
          <div className="flex gap-2 mt-1">
            <select className="input" value={voice} onChange={(e) => setVoice(e.target.value)} disabled={running}>
              {list.map((v) => <option key={v.id} value={v.id}>{v.name}{v.gender ? ` · ${v.gender}` : ""}{v.source === "custom" ? " (của bạn)" : ""}</option>)}
            </select>
            <button className="btn whitespace-nowrap" disabled={!ready || !voice || previewing || running} onClick={() => void preview()}>{previewing ? "…" : "🔈 Nghe thử"}</button>
          </div>
        </label>
        <label className="text-xs text-muted">Tốc độ: {speed.toFixed(2)}×
          <input type="range" min={0.5} max={2} step={0.05} className="w-full mt-2" value={speed} disabled={running} onChange={(e) => setSpeed(Number(e.target.value))} />
        </label>
        <label className="text-xs text-muted">Định dạng
          <select className="input mt-1" value={fmt} disabled={running} onChange={(e) => setFmt(e.target.value as "wav" | "mp3")}>
            <option value="wav">WAV (chất lượng gốc)</option>
            <option value="mp3" disabled={!health?.ffmpeg.available}>MP3 (nhẹ hơn)</option>
          </select>
        </label>
        <label className="text-xs text-muted">Lưu vào thư mục
          <div className="flex gap-2 mt-1">
            <input className="input" value={dir} disabled={running} onChange={(e) => setDir(e.target.value)} placeholder="Mặc định: thư mục dữ liệu của ứng dụng" />
            <button className="btn" disabled={running} onClick={async () => { try { const r = await api.pickFolder(); if (r.path) setDir(r.path); } catch (e) { fail(e); } }}>Chọn…</button>
          </div>
        </label>
      </section>

      {!running && (
        <button className="btn btn-primary w-full !py-3 !text-base" disabled={!ready || !text.trim() || !voice || starting} onClick={() => void start()}>
          {starting ? "Đang chuẩn bị…" : "▶ Tạo file âm thanh"}
        </button>
      )}

      {job && (
        <section className="rounded-xl border border-line bg-panel p-4 space-y-3">
          {running && <>
            <div className="flex items-baseline gap-3">
              <div className="font-medium">{phaseLabel}</div>
              <div className="text-sm text-muted">{job.detail}</div>
              <div className="flex-1" />
              <div className="text-2xl font-semibold tabular-nums">{Math.floor(job.percent)}%</div>
            </div>
            <div className="h-3 rounded-full bg-panel2 overflow-hidden"><div className="h-full bg-accent transition-all duration-500" style={{ width: `${job.percent}%` }} /></div>
            <div className="flex items-center text-xs text-muted">
              <span>Đã chạy {fmtTime(job.elapsed)}{job.phase === "generate" && job.eta_s != null && job.eta_s > 0 ? ` · còn khoảng ${fmtTime(job.eta_s)}` : ""}</span>
              <div className="flex-1" />
              <button className="btn btn-danger" onClick={() => void api.cancelJob(job.id).catch(fail)}>Hủy</button>
            </div>
            <div className="text-xs text-muted">Có thể đóng trang; việc vẫn chạy trên máy. Bị hủy thì phần đã đọc được giữ lại để tiếp tục.</div>
          </>}

          {job.status === "done" && job.result && file && <>
            <div className="text-emerald-300 font-medium">✓ Hoàn tất{job.result.duration ? ` · dài ${fmtTime(job.result.duration)}` : ""} · mất {fmtTime(job.elapsed)}</div>
            <div className="text-sm break-all">{file}</div>
            <div className="flex flex-wrap gap-2">
              <button className="btn btn-primary" onClick={() => setPlayer({ src: `${downloadUrl(file)}&t=${Date.now()}`, title: file.split(/[\\/]/).pop() ?? "", nonce: Date.now() })}>▶ Nghe</button>
              <a className="btn" href={downloadUrl(file)} download>Tải về</a>
              <button className="btn" onClick={() => void api.openFolder(file).catch(fail)}>Mở thư mục</button>
              {pid && <button className="btn" onClick={() => onOpenProject(pid)}>Chỉnh sửa chi tiết</button>}
              <div className="flex-1" />
              <button className="btn" onClick={reset}>Tạo file mới</button>
            </div>
          </>}

          {job.status === "failed" && <>
            <div className="text-red-300 font-medium">Không hoàn tất được</div>
            <div className="text-sm text-red-200 break-words">{job.error}</div>
            <div className="flex gap-2">{pid && <button className="btn btn-primary" disabled={!ready || starting} onClick={() => void retry(pid)}>Thử lại (giữ phần đã đọc)</button>}
              <button className="btn" onClick={reset}>Làm lại từ đầu</button></div>
          </>}

          {job.status === "cancelled" && <>
            <div className="text-amber-300 font-medium">Đã hủy</div>
            <div className="text-sm text-muted">Phần đã đọc xong được giữ lại.</div>
            <div className="flex gap-2">{pid && <button className="btn btn-primary" disabled={!ready || starting} onClick={() => void retry(pid)}>Tiếp tục</button>}
              <button className="btn" onClick={reset}>Làm lại từ đầu</button></div>
          </>}
        </section>
      )}
    </div>
  );
}

function Box({ tone, children, onClose }: { tone: "red" | "amber"; children: React.ReactNode; onClose?: () => void }) {
  const c = tone === "red" ? "border-red-800 bg-red-950/50 text-red-200" : "border-amber-800 bg-amber-950/40 text-amber-200";
  return <div className={`rounded-lg border px-3 py-2 text-sm flex ${c}`}><div className="flex-1">{children}</div>{onClose && <button onClick={onClose}>✕</button>}</div>;
}
