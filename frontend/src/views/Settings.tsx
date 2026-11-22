import { useState } from "react";
import { api, savePrefs, type Engine, type Health, type UserPrefs } from "../api";

export function Settings({ prefs, setPrefs, health, engines }: { prefs: UserPrefs; setPrefs: (p: UserPrefs) => void; health: Health | null; engines: Engine[] }) {
  const [p, setP] = useState(prefs);
  const [saved, setSaved] = useState(false);
  const upd = (patch: Partial<UserPrefs>) => { const n = { ...p, ...patch }; setP(n); setPrefs(n); savePrefs(n); setSaved(true); setTimeout(() => setSaved(false), 1200); };
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      <h1 className="text-xl font-semibold">Settings {saved && <span className="text-xs text-emerald-300 ml-2">đã lưu</span>}</h1>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-2 text-sm">
        <h2 className="font-medium">Hệ thống</h2>
        <div>Backend: <span className={health ? "text-emerald-300" : "text-red-300"}>{health ? "đang chạy" : "không kết nối"}</span></div>
        <div>FFmpeg: {health?.ffmpeg.available ? <span className="text-emerald-300">có · <span className="text-muted break-all">{health.ffmpeg.path}</span></span> : <span className="text-red-300">chưa có (cần cho MP3 và đổi tốc độ): winget install Gyan.FFmpeg</span>}</div>
        <div>Thư mục dữ liệu: <span className="text-muted break-all">{health?.data_dir}</span></div>
        <div className="text-xs text-muted">Mọi xử lý chạy cục bộ; văn bản và âm thanh không gửi ra ngoài.</div>
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-3 text-sm">
        <h2 className="font-medium">Engine</h2>
        {engines.map((e) => (
          <div key={e.id} className="space-y-1">
            <div><b>{e.name}</b> — <span className={e.status.state === "ready" ? "text-emerald-300" : "text-amber-300"}>{e.status.state}</span>{e.status.error && <span className="text-red-300"> {e.status.error}</span>}</div>
            <div className="text-xs text-muted">Giấy phép: {e.license}</div>
            <div className="text-xs text-muted">{e.capabilities.notes}</div>
            <div className="text-xs text-muted">Clone: {e.capabilities.voice_cloning ? "có" : "không"} · Sample rate: {e.capabilities.sample_rate} Hz</div>
          </div>))}
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-3 text-sm">
        <h2 className="font-medium">Mặc định cho dự án mới</h2>
        <div className="grid grid-cols-4 gap-3">
          {([["comma", "Dấu phẩy"], ["period", "Dấu chấm"], ["ellipsis", "Ba chấm"], ["newline", "Xuống dòng"]] as const).map(([k, l]) => (
            <label key={k} className="text-xs text-muted">{l} (ms)
              <input type="number" min={0} step={50} className="input mt-1" value={p.pauses[k]} onChange={(e) => upd({ pauses: { ...p.pauses, [k]: Math.max(0, Number(e.target.value) || 0) } })} /></label>
          ))}
        </div>
        <div className="grid grid-cols-3 gap-3">
          <label className="text-xs text-muted">Định dạng xuất
            <select className="input mt-1" value={p.format} onChange={(e) => upd({ format: e.target.value as "wav" | "mp3" })}><option value="wav">WAV</option><option value="mp3">MP3</option></select></label>
          <label className="text-xs text-muted">Bitrate MP3 (kbps)
            <input type="number" min={64} max={320} step={32} className="input mt-1" value={p.mp3_kbps} onChange={(e) => upd({ mp3_kbps: Number(e.target.value) || 192 })} /></label>
        </div>
        <label className="block text-xs text-muted">Thư mục xuất mặc định
          <div className="flex gap-2 mt-1">
            <input className="input" value={p.exportDir} placeholder="Mặc định: thư mục dữ liệu của ứng dụng" onChange={(e) => upd({ exportDir: e.target.value })} />
            <button className="btn" onClick={async () => { try { const r = await api.pickFolder(); if (r.path) upd({ exportDir: r.path }); } catch { /* ignore */ } }}>Chọn…</button>
          </div>
        </label>
      </section>
    </div>
  );
}
