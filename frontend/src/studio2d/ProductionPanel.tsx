import { useCallback, useEffect, useRef, useState } from "react";
import { api2d, type Cost, type Meta, type Render, type Task } from "./api2d";

const KIND: Record<string, string> = { script: "Viết kịch bản", characters: "Phân tích nhân vật", storyboard: "Chia cảnh", scene_regen: "Tạo lại cảnh",
  scene_audio: "Đọc lời dẫn", scene_clip: "Dựng clip cảnh", render: "Ghép video" };
const ST: Record<string, string> = { pending: "Chờ", running: "Đang chạy", completed: "Xong", failed: "Lỗi" };
const COLOR: Record<string, string> = { pending: "text-muted", running: "text-accent", completed: "text-green-400", failed: "text-red-300" };

export function ProductionPanel({ pid, tasks, busy, reloadTasks, refreshKey }: { pid: string; tasks: Task[]; busy: boolean; reloadTasks: () => void; refreshKey: number }) {
  const [meta, setMeta] = useState<Meta | null>(null);
  const [renders, setRenders] = useState<Render[]>([]);
  const [cost, setCost] = useState<Cost | null>(null);
  const [budget, setBudget] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const bgm = useRef<HTMLInputElement>(null);
  const fail = (e: unknown) => setErr(String(e instanceof Error ? e.message : e));

  const load = useCallback(() => {
    api2d.meta(pid).then(setMeta).catch(fail);
    api2d.renders(pid).then((r) => setRenders(r.renders)).catch(fail);
    api2d.cost(pid).then((c) => { setCost(c); setBudget(c.budget_usd != null ? String(c.budget_usd) : ""); }).catch(fail);
  }, [pid]);
  useEffect(load, [load, refreshKey]);

  const produce = async (kind: "preview" | "final") => {
    setErr(null); setMsg(null);
    try { const r = await api2d.produce(pid, kind); setMsg(r.message); reloadTasks(); } catch (e) { fail(e); }
  };
  const failedCount = tasks.filter((t) => t.status === "failed").length;
  const done = tasks.filter((t) => t.status === "completed").length;
  const pct = tasks.length ? Math.round((100 * done) / tasks.length) : 0;
  const latestPreview = renders.find((r) => r.kind === "preview");
  const latestFinal = renders.find((r) => r.kind === "final");

  return (
    <div className="space-y-4">
      <section className="rounded-xl border border-line bg-panel p-4 space-y-3 text-sm">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="font-medium flex-1">Sản xuất video</h2>
          <button className="btn btn-primary" disabled={busy} onClick={() => void produce("preview")}>▶ Start Production (preview)</button>
          <button className="btn" disabled={busy} onClick={() => void produce("final")}>Xuất MP4 chất lượng cao</button>
          {busy && <button className="btn btn-danger" onClick={() => void api2d.cancelTasks(pid).then(reloadTasks)}>Hủy hàng chờ</button>}
        </div>
        <div className="text-xs text-muted">Lần đầu (chưa có storyboard) Agent chuẩn bị kịch bản, nhân vật, cảnh rồi dừng chờ bạn duyệt. Sau khi duyệt, bấm lại để đọc lời dẫn, dựng clip và ghép video. Công đoạn không đổi sẽ tự bỏ qua.</div>
        {msg && <div className="text-xs text-green-300">{msg}</div>}
        {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-red-200">{err}</div>}
        {tasks.length > 0 && (
          <div>
            <div className="h-2 rounded bg-bg overflow-hidden"><div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} /></div>
            <div className="text-xs text-muted mt-1">{done}/{tasks.length} công đoạn xong{failedCount ? ` · ${failedCount} lỗi` : ""}</div>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-2 text-sm">
        <h2 className="font-medium">Cài đặt dựng</h2>
        {meta && (
          <div className="flex flex-wrap items-center gap-4">
            <label className="flex items-center gap-2"><input type="checkbox" checked={!!meta.subtitles} onChange={(e) => void api2d.updateMeta(pid, { subtitles: e.target.checked }).then(setMeta)} />Phụ đề</label>
            <div className="flex items-center gap-2">Nhạc nền: {meta.bgm_file ? <><b>{meta.bgm_file}</b>
              <button className="btn !py-0.5" onClick={() => void api2d.deleteBgm(pid).then(setMeta)}>Bỏ</button></> : "không có"}
              <input ref={bgm} type="file" accept="audio/*" className="text-xs w-56" onChange={(e) => { const f = e.target.files?.[0]; if (f) void api2d.uploadBgm(pid, f).then((m) => { setMeta(m); if (bgm.current) bgm.current.value = ""; }).catch(fail); }} /></div>
            <label className="flex items-center gap-2">Âm lượng nhạc nền
              <input type="range" min={0} max={0.6} step={0.05} value={meta.bgm_volume} onChange={(e) => setMeta({ ...meta, bgm_volume: Number(e.target.value) })}
                onMouseUp={() => void api2d.updateMeta(pid, { bgm_volume: meta.bgm_volume }).then(setMeta)} />{Math.round(meta.bgm_volume * 100)}%</label>
          </div>
        )}
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-3 text-sm">
        <h2 className="font-medium">Video</h2>
        {renders.length === 0 && <div className="text-xs text-muted">Chưa có bản dựng.</div>}
        <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))" }}>
          {[latestPreview, latestFinal].filter(Boolean).map((r) => r && (
            <div key={r.id} className="space-y-1">
              <div className="text-xs text-muted">{r.kind === "final" ? "Bản cuối" : "Bản xem trước"} · {r.width}×{r.height} · {r.duration?.toFixed(1)}s · {new Date(r.created_at).toLocaleString("vi-VN")}</div>
              <video src={r.url} controls className="w-full max-h-[60vh] rounded-lg bg-black" />
              <a className="text-accent text-xs" href={`${r.url}?download=true`}>Tải MP4</a>
            </div>
          ))}
        </div>
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-2 text-sm">
        <h2 className="font-medium">Chi phí & ngân sách</h2>
        {cost && (
          <>
            <div className="flex flex-wrap gap-4 text-xs">
              {Object.entries(cost.by_kind).map(([k, v]) => <div key={k}><b>{k}</b>: {v.calls} lần · {v.input_tokens}↑ {v.output_tokens}↓ token · ${v.cost_usd.toFixed(4)}{v.unpriced_calls ? ` (+${v.unpriced_calls} lần chưa có giá)` : ""}</div>)}
              {Object.keys(cost.by_kind).length === 0 && <div className="text-muted">Chưa phát sinh chi phí.</div>}
            </div>
            {!cost.prices_configured && <div className="text-xs text-amber-300">Chưa đặt giá token (ANTHROPIC_PRICE_IN_PER_MTOK / ANTHROPIC_PRICE_OUT_PER_MTOK trong .env): token vẫn được đếm nhưng chưa quy ra tiền và ngân sách chưa áp dụng được cho Claude.</div>}
            {cost.warning && <div className={`text-xs ${cost.exceeded ? "text-red-300" : "text-amber-300"}`}>{cost.exceeded ? "Đã vượt ngân sách dự án — các lệnh gọi trả phí bị chặn." : "Đã dùng trên 80% ngân sách."}</div>}
            <div className="flex items-center gap-2">Ngân sách (USD): <input className="input !w-32" type="number" min={0} step="0.5" value={budget} onChange={(e) => setBudget(e.target.value)} />
              <button className="btn" onClick={() => void api2d.setBudget(pid, budget === "" ? null : Number(budget)).then(setCost).catch(fail)}>Đặt</button>
              <span className="text-xs text-muted">Tổng đã chi: ${cost.spent_usd.toFixed(4)}</span></div>
          </>
        )}
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-2 text-sm">
        <h2 className="font-medium">Tiến độ & nhật ký</h2>
        {tasks.length === 0 && <div className="text-xs text-muted">Chưa có công đoạn nào.</div>}
        <ul className="space-y-1">
          {[...tasks].reverse().slice(0, 60).map((t) => (
            <li key={t.id} className="text-xs">
              <div className="flex items-center gap-2 cursor-pointer" onClick={() => setOpen(open === t.id ? null : t.id)}>
                <span className={`w-16 ${COLOR[t.status]}`}>{ST[t.status]}</span><span className="flex-1">{KIND[t.kind] ?? t.kind}{t.scene_id ? ` · cảnh ${t.scene_id.slice(0, 4)}` : ""}{t.attempts > 1 ? ` (lần ${t.attempts})` : ""}</span>
                {t.status === "failed" && <button className="btn !py-0 !px-2 !text-xs" onClick={(e) => { e.stopPropagation(); void api2d.retryTask(t.id).then(reloadTasks); }}>Thử lại</button>}
              </div>
              {t.error && <div className="text-red-300 pl-16">{t.error}</div>}
              {open === t.id && t.log && <pre className="whitespace-pre-wrap bg-bg border border-line rounded p-2 mt-1 text-[11px]">{t.log}</pre>}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
