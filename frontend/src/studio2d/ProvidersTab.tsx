import { useEffect, useState } from "react";
import { api2d, type Status2D } from "./api2d";

const Dot = ({ ok }: { ok: boolean }) => <span className={ok ? "text-green-400" : "text-muted"}>{ok ? "●" : "○"}</span>;

export function ProvidersTab() {
  const [s, setS] = useState<Status2D | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api2d.status().then(setS).catch((e) => setErr(String(e.message ?? e))); }, []);
  if (err) return <div className="m-6 text-red-300">{err}</div>;
  if (!s) return <div className="m-6 text-muted">Đang tải…</div>;
  const c = s.providers.claude;
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-4">
      <h1 className="text-xl font-semibold">AI Providers</h1>
      <p className="text-sm text-muted">Khóa API chỉ được đọc ở backend từ file <code>.env</code> (đã nằm trong .gitignore) và không bao giờ gửi tới trình duyệt.
        Sao chép <code>.env.example</code> thành <code>.env</code>, điền khóa rồi khởi động lại backend.</p>
      <div className="rounded-xl border border-line bg-panel p-4 space-y-1">
        <div><Dot ok={c.configured} /> <b>Claude (Anthropic)</b> — {c.role}</div>
        <div className="text-sm text-muted">
          {c.configured ? <>Đã tìm thấy <code>ANTHROPIC_API_KEY</code> ({c.masked}). </> : <>Chưa có <code>ANTHROPIC_API_KEY</code> trong .env. </>}
          Chưa kiểm tra kết nối thật (sẽ làm ở giai đoạn 2).
        </div>
      </div>
      <div className="rounded-xl border border-line bg-panel p-4 space-y-1">
        <div><Dot ok={s.providers.image.configured} /> <b>Image Provider</b> — {s.providers.image.role}</div>
        <div className="text-sm text-muted">{s.providers.image.note}</div>
      </div>
      <div className="rounded-xl border border-line bg-panel p-4 space-y-1">
        <div><Dot ok={s.providers.video.configured} /> <b>Video Provider</b> — {s.providers.video.role}</div>
        <div className="text-sm text-muted">{s.providers.video.note}</div>
      </div>
      <div className="rounded-xl border border-line bg-panel p-4"><Dot ok={s.ffmpeg.available} /> <b>FFmpeg</b> (chạy local) — {s.ffmpeg.available ? "sẵn sàng" : "chưa tìm thấy"}</div>
    </div>
  );
}
