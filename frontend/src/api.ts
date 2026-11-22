export type Status = "pending" | "generating" | "completed" | "failed";

export interface Segment {
  id: string;
  project_id: string;
  idx: number;
  text: string;
  voice: string | null;
  speed: number;
  pause_before: number;
  pause_after: number;
  status: Status;
  error: string | null;
  duration: number | null;
  updated_at: string;
  has_audio: boolean;
}

export interface Pauses { comma: number; period: number; ellipsis: number; newline: number }

export interface ProjectSettings {
  engine: string;
  voice: string | null;
  speed: number;
  pauses: Pauses;
  split_commas: boolean;
  normalize: boolean;
}

export interface Project {
  id: string;
  name: string;
  source_text: string;
  settings: ProjectSettings;
  created_at: string;
  updated_at: string;
  segments: Segment[];
}

export interface ProjectSummary {
  id: string; name: string; settings: ProjectSettings; created_at: string; updated_at: string;
  segment_count: number; completed_count: number;
}

export interface Voice {
  id: string; name: string; gender: string; region: string; description: string; tags: string[];
  source: "builtin" | "custom"; has_preview: boolean; engine: string; status: string;
  reference_path: string | null; created_at: string | null;
}

export interface Engine {
  id: string; name: string; license: string;
  status: { state: string; error: string | null };
  capabilities: { speed_control: boolean; voice_cloning: boolean; streaming: boolean; languages: string[]; sample_rate: number; notes: string };
}

export interface ExportResult { files: string[]; directory: string; format: string; mode: string; duration: number | null }
export interface Job {
  id: string; status: "running" | "done" | "failed" | "cancelled"; phase: string; percent: number; detail: string;
  done: number; total: number; result: (ExportResult & { project_id?: string }) | null; error: string | null;
  elapsed: number; eta_s?: number | null; project_id?: string;
}
export interface QuickBody {
  text: string; voice: string; speed: number; format: "wav" | "mp3"; mp3_kbps: number; output_dir: string | null;
  pauses?: Partial<Pauses>; name?: string;
}

export interface Health {
  ok: boolean; ffmpeg: { available: boolean; path: string | null }; data_dir: string;
  engines: Record<string, { state: string; error: string | null }>; queue: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, init);
  if (!r.ok) {
    let msg = `${r.status}`;
    try { const j = await r.json(); msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

const json = (method: string, body?: unknown): RequestInit => ({
  method, headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => req<Health>("/health"),
  engines: () => req<{ engines: Engine[]; cloning: { available: boolean; reason: string } }>("/engines"),
  voices: () => req<{ voices: Voice[]; cloning: { available: boolean; reason: string } }>("/voices"),
  importVoice: (file: File, engine = "zerotts") => {
    const f = new FormData(); f.append("file", file); f.append("engine", engine);
    return req<{ imported: string[] }>("/voices/import", { method: "POST", body: f });
  },
  deleteVoice: (id: string, engine: string) => req<{ deleted: string }>(`/voices/${encodeURIComponent(id)}?engine=${engine}`, json("DELETE")),
  previewTts: async (p: { text: string; voice: string | null; speed: number; engine: string; normalize: boolean }) => {
    const r = await fetch("/api/tts/preview", json("POST", p));
    if (!r.ok) { let m = `${r.status}`; try { m = (await r.json()).detail; } catch { /* ignore */ } throw new Error(m); }
    return URL.createObjectURL(await r.blob());
  },
  projects: () => req<{ projects: ProjectSummary[] }>("/projects"),
  project: (id: string) => req<Project>(`/projects/${id}`),
  createProject: (name: string, text: string, settings?: Partial<ProjectSettings>) => req<Project>("/projects", json("POST", { name, text, settings })),
  updateProject: (id: string, body: { name?: string; settings?: Partial<Omit<ProjectSettings, "pauses">> & { pauses?: Partial<Pauses> }; apply_to_segments?: ("voice" | "speed")[] }) =>
    req<Project>(`/projects/${id}`, json("PATCH", body)),
  deleteProject: (id: string) => req<{ deleted: string }>(`/projects/${id}`, json("DELETE")),
  resegment: (id: string, text: string) => req<Project>(`/projects/${id}/resegment`, json("POST", { text })),
  addSegment: (id: string, text: string, after_idx: number | null) => req<Segment>(`/projects/${id}/segments`, json("POST", { text, after_idx })),
  generate: (id: string, opts: { force?: boolean; segment_ids?: string[] } = {}) => req<{ queued: number }>(`/projects/${id}/generate`, json("POST", opts)),
  exportProject: (id: string, body: { format: "wav" | "mp3"; mode: "merged" | "segments"; output_dir?: string | null; mp3_kbps?: number }) =>
    req<{ job_id: string }>(`/projects/${id}/export`, json("POST", body)),
  job: (id: string) => req<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => req<{ cancelling: string }>(`/jobs/${id}/cancel`, json("POST")),
  quick: (b: QuickBody) => req<{ job_id: string; project_id: string; segments: number }>("/quick", json("POST", b)),
  autoResume: (pid: string, b: { format: "wav" | "mp3"; mp3_kbps: number; output_dir: string | null }) =>
    req<{ job_id: string; project_id: string }>(`/projects/${pid}/auto`, json("POST", b)),
  openFolder: (path: string) => req<{ opened: string }>(`/system/open-folder?path=${encodeURIComponent(path)}`, json("POST")),
  patchSegment: (id: string, body: Partial<Pick<Segment, "text" | "voice" | "speed" | "pause_before" | "pause_after">>) => req<Segment>(`/segments/${id}`, json("PATCH", body)),
  deleteSegment: (id: string) => req<{ deleted: string }>(`/segments/${id}`, json("DELETE")),
  regenerate: (id: string) => req<Segment>(`/segments/${id}/regenerate`, json("POST")),
  history: () => req<{ items: (Segment & { project_name: string })[] }>("/history"),
  pickFolder: () => req<{ path: string | null }>("/system/pick-folder", json("POST")),
};

export const segmentAudioUrl = (s: Segment) => `/api/segments/${s.id}/audio?v=${encodeURIComponent(s.updated_at)}-${s.speed}`;
export const downloadUrl = (path: string) => `/api/exports/download?path=${encodeURIComponent(path)}`;

// ---- cài đặt phía người dùng (localStorage) ----
export interface UserPrefs { pauses: Pauses; exportDir: string; format: "wav" | "mp3"; mp3_kbps: number }
export const DEFAULT_PREFS: UserPrefs = { pauses: { comma: 250, period: 450, ellipsis: 800, newline: 700 }, exportDir: "", format: "wav", mp3_kbps: 192 };
export function loadPrefs(): UserPrefs {
  try { return { ...DEFAULT_PREFS, ...JSON.parse(localStorage.getItem("prefs") || "{}") }; } catch { return DEFAULT_PREFS; }
}
export function savePrefs(p: UserPrefs) { try { localStorage.setItem("prefs", JSON.stringify(p)); } catch { /* ignore */ } }
