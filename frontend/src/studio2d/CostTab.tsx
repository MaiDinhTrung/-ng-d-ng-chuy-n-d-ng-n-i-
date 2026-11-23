import { useEffect, useState } from "react";
import { api2d, type Cost } from "./api2d";

export function CostTab() {
  const [c, setC] = useState<Cost | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { api2d.cost().then(setC).catch((e) => setErr(String(e.message ?? e))); }, []);
  if (err) return <div className="m-6 text-red-300">{err}</div>;
  if (!c) return <div className="m-6 text-muted">Đang tải…</div>;
  return (
    <div className="p-6 max-w-3xl mx-auto space-y-4">
      <h1 className="text-xl font-semibold">Cost Manager</h1>
      <div className="rounded-xl border border-line bg-panel p-4 text-sm space-y-2">
        <div>Tổng chi (đã biết giá): <b>${c.spent_usd.toFixed(4)}</b></div>
        {!c.prices_configured && <div className="text-xs text-amber-300">Chưa đặt giá token trong .env nên chi phí Claude chưa quy ra tiền (token vẫn được đếm). Đặt <code>ANTHROPIC_PRICE_IN_PER_MTOK</code> và <code>ANTHROPIC_PRICE_OUT_PER_MTOK</code> theo bảng giá hiện hành của Anthropic.</div>}
        {c.unpriced_calls > 0 && <div className="text-xs text-muted">{c.unpriced_calls} lần gọi chưa có giá.</div>}
      </div>
      <table className="w-full text-sm rounded-xl border border-line bg-panel overflow-hidden">
        <thead className="text-xs text-muted text-left"><tr><th className="p-2">Loại</th><th>Lần gọi</th><th>Token vào</th><th>Token ra</th><th>Chi phí</th></tr></thead>
        <tbody>
          {Object.entries(c.by_kind).map(([k, v]) => <tr key={k} className="border-t border-line"><td className="p-2">{k}</td><td>{v.calls}</td><td>{v.input_tokens}</td><td>{v.output_tokens}</td><td>${v.cost_usd.toFixed(4)}</td></tr>)}
          {Object.keys(c.by_kind).length === 0 && <tr><td className="p-3 text-muted" colSpan={5}>Chưa có lần gọi nào.</td></tr>}
        </tbody>
      </table>
      <p className="text-xs text-muted">Ngân sách đặt riêng cho từng dự án ở tab Sản xuất.</p>
    </div>
  );
}
