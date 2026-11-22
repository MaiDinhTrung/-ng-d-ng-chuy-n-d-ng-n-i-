import { useCallback, useEffect, useState } from "react";
import { api, loadPrefs, type Engine, type Health, type ProjectSummary, type UserPrefs, type Voice } from "./api";
import { AudioPlayer, type PlayerSource } from "./components/AudioPlayer";
import { History } from "./views/History";
import { Projects } from "./views/Projects";
import { Quick } from "./views/Quick";
import { Settings } from "./views/Settings";
import { Studio } from "./views/Studio";
import { VoiceLibrary } from "./views/VoiceLibrary";

type View = "quick" | "studio" | "projects" | "voices" | "history" | "settings";
const NAV: [View, string, string][] = [["quick", "⚡", "Tạo nhanh"], ["studio", "✎", "Chỉnh sửa chi tiết"], ["projects", "🗂", "My Projects"], ["voices", "🎙", "Voice Library"], ["history", "🕘", "Audio History"], ["settings", "⚙", "Settings"]];

export default function App() {
  const [view, setView] = useState<View>(() => (new URLSearchParams(location.search).get("p") ? "studio" : "quick"));
  const [pid, setPid] = useState<string | null>(() => {
    const q = new URLSearchParams(location.search).get("p");
    if (q) return q;
    try { return localStorage.getItem("pid"); } catch { return null; }
  });
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [voices, setVoices] = useState<Voice[]>([]);
  const [cloning, setCloning] = useState<{ available: boolean; reason: string } | null>(null);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [prefs, setPrefs] = useState<UserPrefs>(loadPrefs);
  const [player, setPlayer] = useState<PlayerSource | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const reloadProjects = useCallback(() => { api.projects().then((r) => setProjects(r.projects)).catch(() => undefined); }, []);
  const reloadVoices = useCallback(() => { api.voices().then((r) => { setVoices(r.voices); setCloning(r.cloning); }).catch(() => undefined); }, []);
  const reloadEngines = useCallback(() => { api.engines().then((r) => setEngines(r.engines)).catch(() => undefined); }, []);

  useEffect(() => { reloadProjects(); reloadVoices(); reloadEngines(); }, [reloadProjects, reloadVoices, reloadEngines]);
  useEffect(() => {
    const tick = () => api.health().then((h) => { setHealth(h); }).catch(() => setHealth(null));
    tick(); const t = setInterval(tick, 3000); return () => clearInterval(t);
  }, []);
  // Khi model nạp xong, tải lại danh sách giọng/engine.
  const ready = health?.engines.zerotts?.state;
  useEffect(() => { reloadVoices(); reloadEngines(); }, [ready, reloadVoices, reloadEngines]);

  const open = (id: string | null) => { setPid(id); try { id ? localStorage.setItem("pid", id) : localStorage.removeItem("pid"); } catch { /* ignore */ } setView("studio"); };
  const newProject = async () => {
    try {
      const p = await api.createProject("Dự án mới", "", { pauses: prefs.pauses, voice: voices.find((v) => v.source === "builtin")?.id ?? null });
      reloadProjects(); open(p.id);
    } catch (e) { setErr(e instanceof Error ? e.message : String(e)); }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 flex min-h-0">
        <nav className="w-52 shrink-0 border-r border-line bg-panel p-3 flex flex-col gap-1">
          <div className="px-2 py-3 font-semibold">🎧 Voice Studio</div>
          {NAV.map(([v, icon, label]) => (
            <button key={v} onClick={() => setView(v)} className={`text-left px-3 py-2 rounded-lg text-sm hover:bg-panel2 ${view === v ? "bg-panel2 text-accent" : ""}`}>{icon} {label}</button>
          ))}
          <div className="flex-1" />
          <div className="text-[11px] text-muted px-2 space-y-0.5">
            <div>Backend: {health ? "●" : "○"} {health ? "online" : "offline"}</div>
            <div>FFmpeg: {health?.ffmpeg.available ? "●" : "○"}</div>
            <div>Model: {ready ?? "…"}</div>
          </div>
        </nav>
        <main className="flex-1 min-w-0 overflow-y-auto">
          {!health && <div className="m-4 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">Không kết nối được backend (127.0.0.1:8000). Hãy chạy run.ps1.</div>}
          {err && <div className="m-4 rounded-lg border border-red-800 bg-red-950/50 px-3 py-2 text-sm text-red-200">{err}</div>}
          {view === "quick" && <Quick voices={voices} engines={engines} health={health} prefs={prefs} setPlayer={setPlayer}
            onOpenProject={open} onChanged={reloadProjects} />}
          {view === "studio" && <div className="h-full"><Studio projectId={pid} voices={voices} engines={engines} health={health} prefs={prefs} setPlayer={setPlayer}
            onChanged={reloadProjects} onNew={() => void newProject()} activeSrc={player?.src ?? null} /></div>}
          {view === "projects" && <Projects projects={projects} currentId={pid} onOpen={open} onNew={() => void newProject()}
            onDelete={async (id) => { try { await api.deleteProject(id); if (id === pid) open(null); reloadProjects(); } catch (e) { setErr(String(e)); } }} />}
          {view === "voices" && <VoiceLibrary voices={voices} cloning={cloning} reload={reloadVoices} setPlayer={setPlayer} />}
          {view === "history" && <History setPlayer={setPlayer} onOpen={open} />}
          {view === "settings" && <Settings prefs={prefs} setPrefs={setPrefs} health={health} engines={engines} />}
        </main>
      </div>
      <AudioPlayer source={player} />
    </div>
  );
}
