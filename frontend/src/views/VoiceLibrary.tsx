import { useState } from "react";
import { api, type Voice } from "../api";
import type { PlayerSource } from "../components/AudioPlayer";

export function VoiceLibrary({ voices, cloning, reload, setPlayer }: {
  voices: Voice[]; cloning: { available: boolean; reason: string } | null; reload: () => void; setPlayer: (p: PlayerSource) => void;
}) {
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const fail = (e: unknown) => setErr(e instanceof Error ? e.message : String(e));

  const importPack = async (f: File) => {
    setBusy(true); setErr(null); setMsg(null);
    try { const r = await api.importVoice(f); setMsg(`Đã nạp: ${r.imported.join(", ")}`); reload(); } catch (e) { fail(e); } finally { setBusy(false); }
  };
  const preview = async (v: Voice) => {
    setErr(null);
    try {
      if (v.has_preview) setPlayer({ src: `/api/voices/${v.engine}/${v.id}/preview`, title: `Nghe thử: ${v.name}`, nonce: Date.now() });
      else setPlayer({ src: await api.previewTts({ text: "Xin chào các bạn, mình là giọng đọc này.", voice: v.id, speed: 1, engine: v.engine, normalize: true }), title: `Nghe thử: ${v.name}`, nonce: Date.now() });
    } catch (e) { fail(e); }
  };

  const groups: [string, Voice[]][] = [["Giọng tích hợp trong model", voices.filter((v) => v.source === "builtin")], ["Giọng của bạn", voices.filter((v) => v.source === "custom")]];

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <h1 className="text-xl font-semibold">Voice Library</h1>
      {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">{err}</div>}
      {msg && <div className="rounded-lg border border-emerald-800 bg-emerald-950/40 px-3 py-2 text-sm text-emerald-200">{msg}</div>}

      {groups.map(([title, list]) => (
        <section key={title} className="space-y-3">
          <h2 className="font-medium text-muted">{title} ({list.length})</h2>
          {list.length === 0 && <div className="text-sm text-muted">Chưa có giọng nào.</div>}
          <div className="grid grid-cols-2 gap-3">
            {list.map((v) => (
              <div key={v.engine + v.id} className="rounded-xl border border-line bg-panel p-3 space-y-1">
                <div className="flex items-center gap-2"><b>{v.name}</b><span className="text-xs text-muted">{v.id}</span><div className="flex-1" />
                  <span className="text-xs px-2 py-0.5 rounded-full bg-emerald-600/25 text-emerald-300">{v.status === "ok" ? "Hợp lệ" : v.status}</span></div>
                <div className="text-xs text-muted">{[v.gender, v.region].filter(Boolean).join(" · ") || "—"} · engine {v.engine}</div>
                {v.description && <div className="text-sm">{v.description}</div>}
                {v.tags.length > 0 && <div className="flex flex-wrap gap-1">{v.tags.map((t) => <span key={t} className="text-xs px-1.5 py-0.5 rounded bg-panel2">{t}</span>)}</div>}
                {v.created_at && <div className="text-xs text-muted">Thêm: {new Date(v.created_at).toLocaleString("vi-VN")}</div>}
                {v.reference_path && <div className="text-xs text-muted break-all">Voice pack: {v.reference_path}</div>}
                <div className="flex gap-2 pt-1">
                  <button className="btn !py-1" onClick={() => void preview(v)}>🔈 Nghe thử</button>
                  {v.source === "custom" && <button className="btn btn-danger !py-1" onClick={async () => { if (confirm(`Xóa giọng “${v.name}”?`)) { try { await api.deleteVoice(v.id, v.engine); reload(); } catch (e) { fail(e); } } }}>Xóa</button>}
                </div>
              </div>
            ))}
          </div>
        </section>
      ))}

      <section className="rounded-xl border border-line bg-panel p-4 space-y-2">
        <h2 className="font-medium">Thêm voice pack có sẵn</h2>
        <p className="text-sm text-muted">Nạp file .zip chứa thư mục có <code>voice.npz</code> (định dạng của ZeroTTS). Gói được kiểm tra khớp với model trước khi thêm; chạy hoàn toàn trên máy bạn.
          Chỉ dùng giọng bạn sở hữu hoặc đã được cho phép rõ ràng.</p>
        <label className={`btn inline-block ${busy ? "opacity-50" : "cursor-pointer"}`}>{busy ? "Đang nạp…" : "Chọn file .zip"}
          <input type="file" accept=".zip" hidden disabled={busy} onChange={(e) => { const f = e.target.files?.[0]; if (f) void importPack(f); e.target.value = ""; }} /></label>
      </section>

      <section className="rounded-xl border border-line bg-panel p-4 space-y-2">
        <h2 className="font-medium">Voice cloning</h2>
        {cloning?.available ? <div className="text-sm text-emerald-300">Engine clone sẵn sàng.</div> : (
          <>
            <div className="text-amber-300 text-sm font-medium">{cloning?.reason ?? "Chưa có engine clone tương thích"}</div>
            <p className="text-sm text-muted">ZeroTTS hiện không công bố voice encoder nên không thể tạo giọng từ file ghi âm. Khi có engine clone tiếng Việt với giấy phép phù hợp, tính năng này sẽ được bật ở đây.</p>
            <button className="btn" disabled>Tạo giọng từ file ghi âm</button>
          </>
        )}
      </section>
    </div>
  );
}
