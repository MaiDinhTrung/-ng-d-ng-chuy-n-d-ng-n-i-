import { useEffect, useRef, useState } from "react";

export interface PlayerSource { src: string; title: string; nonce: number }

const fmt = (t: number) => {
  if (!isFinite(t)) return "0:00";
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
};

/** Thanh phát cố định ở đáy: Play/Pause, ±5s, thanh thời gian + waveform thật, âm lượng. */
export function AudioPlayer({ source }: { source: PlayerSource | null }) {
  const audio = useRef<HTMLAudioElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [dur, setDur] = useState(0);
  const [vol, setVol] = useState(() => { try { return Number(localStorage.getItem("vol") ?? "1"); } catch { return 1; } });
  const [peaks, setPeaks] = useState<Float32Array | null>(null);

  useEffect(() => { if (audio.current) audio.current.volume = vol; try { localStorage.setItem("vol", String(vol)); } catch { /* ignore */ } }, [vol]);

  useEffect(() => {
    setPeaks(null); setTime(0); setDur(0);
    if (!source) return;
    const a = audio.current!;
    a.src = source.src;
    a.play().catch(() => setPlaying(false));
    let cancelled = false;
    (async () => {
      try {
        const resp = await fetch(source.src);
        // File dài (vd. bản ghép cả giờ) giải mã sẽ tốn hàng GB RAM: bỏ waveform, vẫn phát bình thường.
        if (Number(resp.headers.get("content-length") ?? 0) > 40_000_000) { void resp.body?.cancel(); return; }
        const buf = await resp.arrayBuffer();
        const ctx = new AudioContext();
        const dec = await ctx.decodeAudioData(buf);
        void ctx.close();
        const ch = dec.getChannelData(0), N = 700, step = Math.max(1, Math.floor(ch.length / N));
        const p = new Float32Array(N);
        for (let i = 0; i < N; i++) { let m = 0; for (let j = i * step; j < Math.min(ch.length, (i + 1) * step); j++) m = Math.max(m, Math.abs(ch[j])); p[i] = m; }
        if (!cancelled) setPeaks(p);
      } catch { /* waveform là tùy chọn */ }
    })();
    return () => { cancelled = true; };
  }, [source?.src, source?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const c = canvas.current; if (!c) return;
    const dpr = window.devicePixelRatio || 1, w = c.clientWidth, h = c.clientHeight;
    c.width = w * dpr; c.height = h * dpr;
    const g = c.getContext("2d")!; g.scale(dpr, dpr); g.clearRect(0, 0, w, h);
    const ratio = dur ? time / dur : 0;
    if (!peaks) { g.fillStyle = "#2a323d"; g.fillRect(0, h / 2 - 1, w, 2); g.fillStyle = "#6ea8fe"; g.fillRect(0, h / 2 - 1, w * ratio, 2); return; }
    const bw = w / peaks.length;
    for (let i = 0; i < peaks.length; i++) {
      const bh = Math.max(2, peaks[i] * h * 0.95);
      g.fillStyle = i / peaks.length < ratio ? "#6ea8fe" : "#3a4556";
      g.fillRect(i * bw, (h - bh) / 2, Math.max(1, bw - 0.5), bh);
    }
  }, [peaks, time, dur]);

  const toggle = () => { const a = audio.current!; if (!source) return; a.paused ? void a.play() : a.pause(); };
  const seek = (e: React.MouseEvent<HTMLCanvasElement>) => {
    const a = audio.current!; if (!dur) return;
    const r = e.currentTarget.getBoundingClientRect(); a.currentTime = ((e.clientX - r.left) / r.width) * dur;
  };
  const skip = (d: number) => { const a = audio.current!; a.currentTime = Math.max(0, Math.min(dur, a.currentTime + d)); };

  return (
    <div className="border-t border-line bg-panel px-4 py-2 flex items-center gap-3">
      <audio ref={audio} onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)} onLoadedMetadata={(e) => setDur(e.currentTarget.duration)} />
      <button className="btn" onClick={() => skip(-5)} disabled={!source} title="Lùi 5 giây">⏪ 5s</button>
      <button className="btn btn-primary w-24" onClick={toggle} disabled={!source}>{playing ? "⏸ Tạm dừng" : "▶ Phát"}</button>
      <button className="btn" onClick={() => skip(5)} disabled={!source} title="Tiến 5 giây">5s ⏩</button>
      <div className="w-14 text-xs text-muted tabular-nums text-right">{fmt(time)}</div>
      <canvas ref={canvas} onClick={seek} className="flex-1 h-12 cursor-pointer min-w-0" />
      <div className="w-14 text-xs text-muted tabular-nums">{fmt(dur)}</div>
      <div className="w-56 truncate text-sm text-muted" title={source?.title}>{source?.title ?? "Chưa chọn âm thanh"}</div>
      <label className="flex items-center gap-2 text-xs text-muted" title="Âm lượng">🔊
        <input type="range" min={0} max={1} step={0.01} value={vol} onChange={(e) => setVol(Number(e.target.value))} className="w-24" />
      </label>
    </div>
  );
}
