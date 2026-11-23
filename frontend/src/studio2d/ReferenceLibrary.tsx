import { useCallback, useEffect, useRef, useState } from "react";
import { api2d, CATEGORIES, catLabel, type Category, type Reference } from "./api2d";

const kb = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function RefCard({ r, onSave, onDelete, action }: {
  r: Reference; onSave: (id: string, b: Partial<Reference>) => Promise<void>; onDelete: (r: Reference) => void;
  action?: { label: string; run: () => void };
}) {
  const [edit, setEdit] = useState(false);
  const [name, setName] = useState(r.name);
  const [desc, setDesc] = useState(r.description);
  const [tags, setTags] = useState(r.tags.join(", "));
  const [cat, setCat] = useState<Category>(r.category);
  return (
    <div className="rounded-xl border border-line bg-panel overflow-hidden flex flex-col">
      <a href={r.url} target="_blank" rel="noreferrer" className="block bg-black/40 aspect-[4/3]">
        <img src={r.thumb_url} alt={r.name} loading="lazy" className="w-full h-full object-contain" />
      </a>
      <div className="p-3 space-y-2 text-sm flex-1">
        {!edit ? (
          <>
            <div className="font-medium truncate" title={r.name}>{r.name}</div>
            <div className="text-xs text-muted">{catLabel(r.category)} · {r.width}×{r.height} · {kb(r.size)}</div>
            {r.description && <div className="text-xs line-clamp-3">{r.description}</div>}
            {r.tags.length > 0 && <div className="flex flex-wrap gap-1">{r.tags.map((t) => <span key={t} className="text-[11px] px-1.5 rounded bg-panel2 text-muted">{t}</span>)}</div>}
            <div className="text-[11px] text-muted font-mono select-all" title="ID dùng để tham chiếu">ID: {r.id}{r.used_by ? ` · ${r.used_by} dự án` : ""}</div>
          </>
        ) : (
          <>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
            <select className="input" value={cat} onChange={(e) => setCat(e.target.value as Category)}>
              {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
            <textarea className="input" rows={3} placeholder="Mô tả (Claude sẽ đọc mô tả này)" value={desc} onChange={(e) => setDesc(e.target.value)} />
            <input className="input" placeholder="Thẻ, cách nhau dấu phẩy" value={tags} onChange={(e) => setTags(e.target.value)} />
          </>
        )}
      </div>
      <div className="p-2 pt-0 flex gap-2">
        {action && !edit && <button className="btn btn-primary flex-1" onClick={action.run}>{action.label}</button>}
        {edit ? (
          <>
            <button className="btn btn-primary flex-1" onClick={async () => {
              await onSave(r.id, { name, description: desc, category: cat, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) });
              setEdit(false);
            }}>Lưu</button>
            <button className="btn" onClick={() => setEdit(false)}>Hủy</button>
          </>
        ) : (
          <>
            <button className="btn" onClick={() => setEdit(true)}>Sửa</button>
            <button className="btn btn-danger" onClick={() => onDelete(r)}>Xóa</button>
          </>
        )}
      </div>
    </div>
  );
}

/** Thư viện tư liệu dùng chung. Nếu truyền `projectId`, mỗi thẻ có nút gắn tư liệu vào dự án đó. */
export function ReferenceLibrary({ projectId, onLinked }: { projectId?: string; onLinked?: () => void }) {
  const [cat, setCat] = useState<Category | "">("");
  const [q, setQ] = useState("");
  const [refs, setRefs] = useState<Reference[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [upCat, setUpCat] = useState<Category>("character");
  const [upDesc, setUpDesc] = useState("");
  const [upTags, setUpTags] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(() => {
    api2d.references({ category: cat || undefined, q: q || undefined }).then((r) => { setRefs(r.references); setErr(null); })
      .catch((e) => setErr(String(e.message ?? e)));
  }, [cat, q]);
  useEffect(() => { const t = setTimeout(load, q ? 250 : 0); return () => clearTimeout(t); }, [load, q]);

  const upload = async () => {
    setBusy(true); setErr(null); setMsg(null);
    try {
      const r = await api2d.upload(files, upCat, upDesc, upTags, projectId);
      setMsg(`Đã tải ${r.uploaded.length} ảnh${r.failed.length ? `; lỗi ${r.failed.length}: ${r.failed.map((f) => `${f.filename} (${f.error})`).join("; ")}` : ""}`);
      setFiles([]); setUpDesc(""); setUpTags(""); if (fileInput.current) fileInput.current.value = "";
      load(); if (projectId) onLinked?.();
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  };

  return (
    <div className="p-4 max-w-7xl mx-auto space-y-3">
      {!projectId && <h1 className="text-xl font-semibold">Thư viện tư liệu</h1>}
      <section className="rounded-xl border border-line bg-panel p-3 grid grid-cols-2 gap-2 text-xs">
        <div className="col-span-2 font-medium">Tải ảnh tham chiếu{projectId ? " (tự gắn vào dự án đang mở)" : ""}</div>
        <label className="text-xs text-muted">Danh mục
          <select className="input mt-1" value={upCat} onChange={(e) => setUpCat(e.target.value as Category)}>
            {CATEGORIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label className="text-xs text-muted">Thẻ (cách nhau dấu phẩy: mặt trước, giáp, biểu cảm…)
          <input className="input mt-1" value={upTags} onChange={(e) => setUpTags(e.target.value)} />
        </label>
        <label className="text-xs text-muted col-span-2">Mô tả (áp dụng cho mọi ảnh trong lần tải này; sửa riêng từng ảnh sau)
          <textarea className="input mt-1" rows={1} value={upDesc} onChange={(e) => setUpDesc(e.target.value)} />
        </label>
        <div className="col-span-2 flex items-center gap-3">
          <input ref={fileInput} type="file" multiple accept="image/png,image/jpeg,image/webp,image/gif" className="text-xs flex-1"
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
          <button className="btn btn-primary" disabled={busy || files.length === 0} onClick={() => void upload()}>
            {busy ? "Đang tải…" : `Tải lên${files.length ? ` (${files.length})` : ""}`}
          </button>
        </div>
      </section>
      {msg && <div className="text-sm text-green-300">{msg}</div>}
      {err && <div className="rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">{err}</div>}

      <div className="flex flex-wrap items-center gap-2">
        {([["", "Tất cả"], ...CATEGORIES] as [string, string][]).map(([k, l]) => (
          <button key={k} onClick={() => setCat(k as Category | "")}
            className={`btn ${cat === k ? "!border-accent text-accent" : ""}`}>{l}</button>
        ))}
        <input className="input !w-64 ml-auto" placeholder="Tìm theo tên, mô tả, thẻ…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>

      {refs.length === 0 && !err && <div className="text-muted text-sm">Chưa có tư liệu nào trong mục này.</div>}
      <div className="grid gap-4" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(165px, 1fr))" }}>
        {refs.map((r) => (
          <RefCard key={r.id} r={r}
            onSave={async (id, b) => { try { await api2d.updateReference(id, b); load(); } catch (e) { setErr(String(e instanceof Error ? e.message : e)); } }}
            onDelete={(x) => {
              if (confirm(`Xóa tư liệu “${x.name}”?${x.used_by ? ` Đang gắn với ${x.used_by} dự án, liên kết sẽ bị gỡ.` : ""}`))
                api2d.deleteReference(x.id).then(() => { load(); onLinked?.(); }).catch((e) => setErr(String(e.message ?? e)));
            }}
            action={projectId ? { label: "Gắn vào dự án", run: () => { api2d.link(projectId, r.id).then(() => { setMsg(`Đã gắn “${r.name}”`); onLinked?.(); }).catch((e) => setErr(String(e.message ?? e))); } } : undefined} />
        ))}
      </div>
    </div>
  );
}
