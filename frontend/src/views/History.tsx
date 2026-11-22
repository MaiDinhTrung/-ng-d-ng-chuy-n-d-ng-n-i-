import { useEffect, useState } from "react";
import { api, segmentAudioUrl, type Segment } from "../api";
import type { PlayerSource } from "../components/AudioPlayer";

type Item = Segment & { project_name: string };

export function History({ setPlayer, onOpen }: { setPlayer: (p: PlayerSource) => void; onOpen: (projectId: string) => void }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api.history().then((r) => setItems(r.items)).catch((e) => setErr(String(e.message ?? e))); }, []);
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-3">
      <h1 className="text-xl font-semibold">Audio History</h1>
      {err && <div className="text-red-300 text-sm">{err}</div>}
      {items?.length === 0 && <div className="text-muted">Chưa có âm thanh nào được tạo.</div>}
      {items?.map((s) => (
        <div key={s.id} className="rounded-xl border border-line bg-panel p-3 flex items-center gap-3">
          <button className="btn" onClick={() => setPlayer({ src: segmentAudioUrl(s), title: s.text, nonce: Date.now() })}>▶</button>
          <div className="flex-1 min-w-0">
            <div className="truncate">{s.text}</div>
            <div className="text-xs text-muted">{s.project_name} · đoạn #{s.idx + 1} · {s.duration?.toFixed(2)}s · {new Date(s.updated_at.endsWith("Z") || s.updated_at.includes("+") ? s.updated_at : s.updated_at.replace(" ", "T") + "Z").toLocaleString("vi-VN")}</div>
          </div>
          <button className="btn" onClick={() => onOpen(s.project_id)}>Mở dự án</button>
        </div>
      ))}
    </div>
  );
}
