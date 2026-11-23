import { useCallback, useEffect, useState } from "react";
import { api2d, type Character, type Estimate } from "./api2d";

const FIELDS: [keyof Character, string][] = [
  ["description", "Mô tả"], ["facial_features", "Khuôn mặt"], ["hair", "Tóc"], ["costume", "Trang phục"], ["main_colors", "Màu chủ đạo"],
  ["weapons", "Vũ khí"], ["personality", "Tính cách"], ["consistency_rules", "Quy tắc nhất quán (không được thay đổi)"],
];

function Card({ c, refs, onChange, onDelete }: { c: Character; refs: { id: string; name: string; thumb_url: string }[]; onChange: () => void; onDelete: () => void }) {
  const [f, setF] = useState(c);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => setF(c), [c]);
  const dirty = FIELDS.some(([k]) => f[k] !== c[k]) || f.name !== c.name || JSON.stringify(f.reference_ids) !== JSON.stringify(c.reference_ids);
  const save = async () => {
    try { await api2d.updateCharacter(c.id, { name: f.name, reference_ids: f.reference_ids, ...Object.fromEntries(FIELDS.map(([k]) => [k, f[k]])) }); onChange(); setErr(null); }
    catch (e) { setErr(String(e instanceof Error ? e.message : e)); }
  };
  return (
    <div className={`rounded-xl border bg-panel p-4 space-y-2 text-sm ${c.confirmed ? "border-green-800" : "border-line"}`}>
      <div className="flex items-center gap-2">
        <input className="input !w-auto flex-1 font-medium" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />
        <span className={`text-xs ${c.confirmed ? "text-green-400" : "text-amber-300"}`}>{c.confirmed ? "✓ Đã xác nhận" : "Chưa xác nhận"}</span>
      </div>
      {err && <div className="text-xs text-red-300">{err}</div>}
      <div className="grid grid-cols-2 gap-2">
        {FIELDS.map(([k, label]) => (
          <label key={k} className={`text-xs text-muted ${k === "description" || k === "consistency_rules" ? "col-span-2" : ""}`}>{label}
            <textarea className="input mt-1" rows={k === "description" || k === "consistency_rules" ? 2 : 1} value={String(f[k] ?? "")} onChange={(e) => setF({ ...f, [k]: e.target.value })} />
          </label>
        ))}
      </div>
      <div className="text-xs text-muted">Ảnh tham chiếu (từ thư viện của dự án — mọi cảnh có nhân vật này sẽ dùng lại):</div>
      <div className="flex flex-wrap gap-2">
        {refs.length === 0 && <span className="text-xs text-muted">Dự án chưa gắn ảnh nhân vật nào.</span>}
        {refs.map((r) => {
          const on = f.reference_ids.includes(r.id);
          return <button key={r.id} title={r.name} onClick={() => setF({ ...f, reference_ids: on ? f.reference_ids.filter((x) => x !== r.id) : [...f.reference_ids, r.id] })}
            className={`rounded-lg overflow-hidden border-2 ${on ? "border-accent" : "border-transparent opacity-60"}`}><img src={r.thumb_url} className="h-14 w-14 object-cover" alt={r.name} /></button>;
        })}
      </div>
      <div className="flex gap-2 pt-1">
        <button className="btn btn-primary" disabled={!dirty} onClick={() => void save()}>Lưu</button>
        <button className="btn" disabled={dirty} onClick={() => void api2d.confirmCharacters(c.project_id, c.id, !c.confirmed).then(onChange)}>{c.confirmed ? "Bỏ xác nhận" : "Xác nhận"}</button>
        <div className="flex-1" />
        <button className="btn btn-danger" onClick={() => confirm(`Xóa nhân vật “${c.name}”?`) && onDelete()}>Xóa</button>
      </div>
      {dirty && <div className="text-[11px] text-muted">Lưu trước khi xác nhận. Sửa hồ sơ sẽ bỏ xác nhận.</div>}
    </div>
  );
}

export function CharactersPanel({ pid, hasScript, claudeReady, refreshKey, queue, busy, refs }: {
  pid: string; hasScript: boolean; claudeReady: boolean; refreshKey: number; queue: (s: "characters") => Promise<void>; busy: boolean;
  refs: { id: string; name: string; thumb_url: string; category: string }[];
}) {
  const [list, setList] = useState<Character[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [est, setEst] = useState<Estimate | null>(null);
  const load = useCallback(() => { api2d.characters(pid).then((r) => setList(r.characters)).catch((e) => setErr(String(e.message ?? e))); }, [pid]);
  useEffect(load, [load, refreshKey]);
  const charRefs = refs.filter((r) => r.category === "character");

  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-line bg-panel p-4 flex flex-wrap items-center gap-3 text-sm">
        <div className="flex-1 min-w-60">Hồ sơ nhân vật được chèn nguyên văn vào prompt mọi cảnh có nhân vật đó để giữ ngoại hình nhất quán. Bạn phải <b>xác nhận</b> trước khi sản xuất.</div>
        <button className="btn" onClick={() => void api2d.estimate(pid, "characters").then(setEst).catch((e) => setErr(String(e.message ?? e)))}>Ước tính chi phí</button>
        <button className="btn btn-primary" disabled={busy || !hasScript || !claudeReady} title={!claudeReady ? "Chưa có ANTHROPIC_API_KEY" : !hasScript ? "Cần kịch bản" : ""}
          onClick={() => void queue("characters")}>Để Claude phân tích nhân vật</button>
        <button className="btn" onClick={() => void api2d.createCharacter(pid, { name: "Nhân vật mới" }).then(load)}>+ Thêm thủ công</button>
        <button className="btn" disabled={!list.length || list.every((c) => c.confirmed)} onClick={() => void api2d.confirmCharacters(pid).then(load)}>Xác nhận tất cả</button>
      </div>
      {est && <div className="text-xs text-muted">Ước tính (thô): ~{est.input_tokens} token vào, ~{est.output_tokens} token ra{est.cost_usd !== null ? `, ≈ $${est.cost_usd.toFixed(4)}` : " — chưa cấu hình giá nên chưa quy ra tiền"}.</div>}
      {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">{err}</div>}
      {list.length === 0 && <div className="text-sm text-muted">Chưa có nhân vật.</div>}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))" }}>
        {list.map((c) => <Card key={c.id} c={c} refs={charRefs} onChange={load} onDelete={() => void api2d.deleteCharacter(c.id).then(load)} />)}
      </div>
    </div>
  );
}
