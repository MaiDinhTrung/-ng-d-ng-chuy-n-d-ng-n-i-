import { useEffect, useRef, useState } from "react";
import type { Segment, Voice } from "../api";

const BADGE: Record<string, string> = {
  pending: "bg-zinc-700 text-zinc-200",
  generating: "bg-amber-600/30 text-amber-300 animate-pulse",
  completed: "bg-emerald-600/25 text-emerald-300",
  failed: "bg-red-600/30 text-red-300",
};
const LABEL: Record<string, string> = { pending: "Pending", generating: "Generating", completed: "Completed", failed: "Failed" };

interface Props {
  seg: Segment; voices: Voice[]; defaultVoice: string | null; active: boolean;
  onPatch: (id: string, body: Partial<Segment>) => Promise<void>;
  onGenerate: (id: string) => void; onPlay: (s: Segment) => void;
  onDelete: (id: string) => void; onAddAfter: (idx: number) => void;
}

export function SegmentCard({ seg, voices, defaultVoice, active, onPatch, onGenerate, onPlay, onDelete, onAddAfter }: Props) {
  const [text, setText] = useState(seg.text);
  const dirty = useRef(false);
  useEffect(() => { if (!dirty.current) setText(seg.text); }, [seg.text]);
  const [speed, setSpeed] = useState(seg.speed);
  useEffect(() => setSpeed(seg.speed), [seg.speed]);

  const commitText = async () => {
    if (text.trim() === seg.text) { dirty.current = false; return; }
    await onPatch(seg.id, { text }); dirty.current = false;
  };
  const busy = seg.status === "generating";
  const num = (v: number, k: "pause_before" | "pause_after") => (
    <input type="number" min={0} max={60000} step={50} defaultValue={v} key={`${k}-${v}`} className="input !w-20 !py-1"
      onBlur={(e) => { const n = Math.max(0, Math.min(60000, Number(e.target.value) || 0)); if (n !== v) void onPatch(seg.id, { [k]: n }); }} />
  );

  return (
    <div className={`rounded-xl border bg-panel p-3 ${active ? "border-accent" : "border-line"}`}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs text-muted w-8">#{seg.idx + 1}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full ${BADGE[seg.status]}`}>{LABEL[seg.status]}</span>
        {seg.duration != null && seg.status === "completed" && <span className="text-xs text-muted">{seg.duration.toFixed(2)}s</span>}
        <div className="flex-1" />
        <button className="btn !py-1" disabled={!seg.has_audio || busy} onClick={() => onPlay(seg)}>▶ Preview</button>
        <button className="btn !py-1 btn-primary" disabled={busy} onClick={() => onGenerate(seg.id)}>
          {seg.status === "completed" ? "Regenerate" : "Generate"}
        </button>
        <button className="btn !py-1 btn-danger" onClick={() => onDelete(seg.id)} title="Xóa đoạn">🗑</button>
      </div>
      <textarea className="input resize-y min-h-[56px]" rows={2} value={text}
        onChange={(e) => { dirty.current = true; setText(e.target.value); }} onBlur={() => void commitText()} />
      {seg.error && <div className="mt-1 text-xs text-red-300">Lỗi: {seg.error}</div>}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted">
        <label className="flex items-center gap-2">Voice
          <select className="input !w-44 !py-1" value={seg.voice ?? ""} onChange={(e) => void onPatch(seg.id, { voice: e.target.value || null })}>
            <option value="">Mặc định ({voices.find((v) => v.id === defaultVoice)?.name ?? "chưa chọn"})</option>
            {voices.map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-2">Speed {speed.toFixed(2)}×
          <input type="range" min={0.5} max={2} step={0.05} value={speed} className="w-28"
            onChange={(e) => setSpeed(Number(e.target.value))} onMouseUp={() => speed !== seg.speed && void onPatch(seg.id, { speed })}
            onKeyUp={() => speed !== seg.speed && void onPatch(seg.id, { speed })} onTouchEnd={() => speed !== seg.speed && void onPatch(seg.id, { speed })} />
        </label>
        <label className="flex items-center gap-2">Nghỉ trước {num(seg.pause_before, "pause_before")} ms</label>
        <label className="flex items-center gap-2">Nghỉ sau {num(seg.pause_after, "pause_after")} ms</label>
        <button className="btn !py-0.5 ml-auto" onClick={() => onAddAfter(seg.idx)}>+ Thêm đoạn bên dưới</button>
      </div>
    </div>
  );
}
