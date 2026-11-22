import type { ProjectSummary } from "../api";

export function Projects({ projects, currentId, onOpen, onDelete, onNew }: {
  projects: ProjectSummary[]; currentId: string | null; onOpen: (id: string) => void; onDelete: (id: string) => void; onNew: () => void;
}) {
  return (
    <div className="p-6 max-w-4xl mx-auto space-y-4">
      <div className="flex items-center"><h1 className="text-xl font-semibold flex-1">Dự án của tôi</h1><button className="btn btn-primary" onClick={onNew}>+ Dự án mới</button></div>
      {projects.length === 0 && <div className="text-muted">Chưa có dự án nào.</div>}
      {projects.map((p) => (
        <div key={p.id} className={`rounded-xl border bg-panel p-4 flex items-center gap-4 ${p.id === currentId ? "border-accent" : "border-line"}`}>
          <div className="flex-1 min-w-0">
            <div className="font-medium truncate">{p.name}</div>
            <div className="text-xs text-muted">{p.completed_count}/{p.segment_count} đoạn đã tạo · giọng {p.settings.voice ?? "chưa chọn"} · sửa {new Date(p.updated_at).toLocaleString("vi-VN")}</div>
          </div>
          <button className="btn" onClick={() => onOpen(p.id)}>Mở</button>
          <button className="btn btn-danger" onClick={() => confirm(`Xóa dự án “${p.name}” và toàn bộ âm thanh liên quan?`) && onDelete(p.id)}>Xóa</button>
        </div>
      ))}
    </div>
  );
}
