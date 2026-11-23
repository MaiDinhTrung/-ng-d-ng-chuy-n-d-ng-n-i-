export type AspectRatio = "16:9" | "9:16" | "1:1";
export type Category = "character" | "environment" | "style" | "storyboard";
export const CATEGORIES: [Category, string][] = [
  ["character", "Nhân vật"], ["environment", "Bối cảnh"], ["style", "Phong cách hình ảnh"], ["storyboard", "Storyboard"],
];
export const catLabel = (c: string) => CATEGORIES.find(([k]) => k === c)?.[1] ?? c;

export interface Reference {
  id: string; category: Category; name: string; description: string; tags: string[];
  mime: string; width: number; height: number; size: number; sha256: string; created_at: string;
  url: string; thumb_url: string; used_by?: number; note?: string;
}
export interface ProjectFields {
  name: string; description: string; topic: string; script: string; language: string; target_audience: string;
  video_type: string; duration_sec: number | null; aspect_ratio: AspectRatio; visual_style: string;
  voice_engine: string | null; voice_id: string | null;
}
export interface Project2D extends ProjectFields {
  id: string; status: string; created_at: string; updated_at: string; references: Reference[];
}
export interface ProjectSummary2D {
  id: string; name: string; topic: string; aspect_ratio: AspectRatio; visual_style: string; status: string;
  updated_at: string; reference_count: number;
}
export interface Revision { id: number; kind: string; changes: Record<string, unknown>; created_at: string }
export interface Status2D {
  ffmpeg: { available: boolean };
  providers: {
    claude: { configured: boolean; masked: string | null; role: string; verified: boolean };
    image: { configured: boolean; role: string; note: string; providers?: { id: string; name: string; configured: boolean }[] };
    video: { configured: boolean; role: string; note: string };
  };
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api/2d${path}`, init);
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

export const api2d = {
  status: () => req<Status2D>("/status"),
  projects: () => req<{ projects: ProjectSummary2D[] }>("/projects"),
  project: (id: string) => req<Project2D>(`/projects/${id}`),
  createProject: (b: Partial<ProjectFields> & { name: string }) => req<Project2D>("/projects", json("POST", b)),
  updateProject: (id: string, b: Partial<ProjectFields>) => req<Project2D>(`/projects/${id}`, json("PATCH", b)),
  deleteProject: (id: string) => req<{ deleted: string }>(`/projects/${id}`, json("DELETE")),
  revisions: (id: string) => req<{ revisions: Revision[] }>(`/projects/${id}/revisions`),
  link: (pid: string, rid: string, note = "") => req<Project2D>(`/projects/${pid}/references/${rid}`, json("PUT", { note })),
  unlink: (pid: string, rid: string) => req<Project2D>(`/projects/${pid}/references/${rid}`, json("DELETE")),
  references: (p: { category?: string; q?: string; project_id?: string } = {}) => {
    const qs = new URLSearchParams(Object.entries(p).filter(([, v]) => v) as [string, string][]).toString();
    return req<{ references: Reference[] }>(`/references${qs ? `?${qs}` : ""}`);
  },
  upload: (files: File[], category: Category, description: string, tags: string, projectId?: string) => {
    const f = new FormData();
    files.forEach((x) => f.append("files", x));
    f.append("category", category); f.append("description", description); f.append("tags", tags);
    if (projectId) f.append("project_id", projectId);
    return req<{ uploaded: Reference[]; failed: { filename: string; error: string }[] }>("/references", { method: "POST", body: f });
  },
  updateReference: (id: string, b: Partial<Pick<Reference, "name" | "description" | "category" | "tags">>) =>
    req<Reference>(`/references/${id}`, json("PATCH", b)),
  deleteReference: (id: string) => req<{ deleted: string }>(`/references/${id}`, json("DELETE")),

  // --- nhân vật ---
  characters: (pid: string) => req<{ characters: Character[] }>(`/projects/${pid}/characters`),
  createCharacter: (pid: string, b: Partial<Character> & { name: string }) => req<Character>(`/projects/${pid}/characters`, json("POST", b)),
  updateCharacter: (id: string, b: Partial<Character>) => req<Character>(`/characters/${id}`, json("PATCH", b)),
  deleteCharacter: (id: string) => req<{ deleted: string }>(`/characters/${id}`, json("DELETE")),
  confirmCharacters: (pid: string, characterId?: string, value = true) =>
    req<{ characters: Character[] }>(`/projects/${pid}/characters/confirm?value=${value}${characterId ? `&character_id=${characterId}` : ""}`, json("POST")),

  // --- storyboard ---
  scenes: (pid: string) => req<{ scenes: Scene[]; approved: boolean }>(`/projects/${pid}/scenes`),
  createScene: (pid: string, b: Partial<Scene> & { after_idx?: number | null }) => req<Scene>(`/projects/${pid}/scenes`, json("POST", b)),
  updateScene: (id: string, b: Partial<Scene>) => req<Scene>(`/scenes/${id}`, json("PATCH", b)),
  deleteScene: (id: string) => req<{ deleted: string }>(`/scenes/${id}`, json("DELETE")),
  moveScene: (id: string, direction: -1 | 1) => req<{ scenes: Scene[] }>(`/scenes/${id}/move?direction=${direction}`, json("POST")),
  approve: (pid: string, value = true) => req<{ approved: boolean }>(`/projects/${pid}/storyboard/approve?value=${value}`, json("POST")),
  regenerateScene: (id: string, instruction: string) => req<{ task_id: number }>(`/scenes/${id}/regenerate`, json("POST", { instruction })),
  runStage: (pid: string, stage: "script" | "characters" | "storyboard") => req<{ task_id: number }>(`/projects/${pid}/stage/${stage}`, json("POST")),
  estimate: (pid: string, stage: string) => req<Estimate>(`/projects/${pid}/estimate?stage=${stage}`),
  imageRequest: (sid: string) => req<{ prompt: string; negative_prompt: string; reference_ids: string[] }>(`/scenes/${sid}/image-request`),

  // --- ảnh ---
  sceneImages: (sid: string) => req<{ images: Generation[] }>(`/scenes/${sid}/images`),
  uploadSceneImage: (sid: string, file: File) => { const f = new FormData(); f.append("file", file); return req<Generation>(`/scenes/${sid}/image`, { method: "POST", body: f }); },
  selectImage: (sid: string, generation_id: string) => req<Scene>(`/scenes/${sid}/image/select`, json("POST", { generation_id })),
  generateImages: (sid: string, b: { provider_id: string; n: number }) => req<{ images: Generation[] }>(`/scenes/${sid}/images/generate`, json("POST", b)),

  // --- sản xuất ---
  meta: (pid: string) => req<Meta>(`/projects/${pid}/meta`),
  updateMeta: (pid: string, b: { subtitles?: boolean; bgm_volume?: number }) => req<Meta>(`/projects/${pid}/meta`, json("PATCH", b)),
  uploadBgm: (pid: string, file: File) => { const f = new FormData(); f.append("file", file); return req<Meta>(`/projects/${pid}/bgm`, { method: "PUT", body: f }); },
  deleteBgm: (pid: string) => req<Meta>(`/projects/${pid}/bgm`, json("DELETE")),
  produce: (pid: string, kind: "preview" | "final") => req<{ phase: string; tasks: number[]; message: string }>(`/projects/${pid}/produce`, json("POST", { kind })),
  tasks: (pid: string) => req<{ tasks: Task[] }>(`/projects/${pid}/tasks`),
  retryTask: (id: number) => req<{ retried: number }>(`/tasks/${id}/retry`, json("POST")),
  cancelTasks: (pid: string) => req<{ cancelled: number }>(`/projects/${pid}/tasks/cancel`, json("POST")),
  renders: (pid: string) => req<{ renders: Render[] }>(`/projects/${pid}/renders`),

  // --- chi phí ---
  cost: (pid?: string) => req<Cost>(pid ? `/projects/${pid}/cost` : "/cost"),
  setBudget: (pid: string, budget_usd: number | null) => req<Cost>(`/projects/${pid}/budget`, json("PUT", { budget_usd })),
};

export interface Character {
  id: string; project_id: string; name: string; description: string; facial_features: string; hair: string; costume: string;
  main_colors: string; weapons: string; personality: string; consistency_rules: string; reference_ids: string[]; confirmed: boolean;
}
export const MOVEMENTS = ["static", "zoom_in", "zoom_out", "pan_left", "pan_right", "pan_up", "pan_down", "shake"];
export const TRANSITIONS = ["cut", "fade", "dissolve", "wipeleft", "wiperight", "slideleft", "slideright", "fadeblack", "circleopen"];
export const EFFECTS = ["none", "vignette", "warm", "cool", "flash"];
export interface Scene {
  id: string; project_id: string; idx: number; title: string; narration: string; character_ids: string[]; environment: string;
  visual_description: string; camera_angle: string; camera_movement: string; character_action: string; lighting: string;
  duration: number; transition: string; effect: string; image_prompt: string; negative_prompt: string; reference_ids: string[];
  image_gen_id: string | null; has_image: boolean; has_audio: boolean; audio_duration: number | null;
}
export interface Generation {
  id: string; scene_id: string; provider: string; model: string | null; prompt: string; status: string; cost_usd: number | null;
  error: string | null; created_at: string;
}
export interface Meta { project_id: string; storyboard_approved: number; budget_usd: number | null; bgm_file: string | null; bgm_volume: number; subtitles: number }
export interface Task {
  id: number; project_id: string; scene_id: string | null; kind: string; status: "pending" | "running" | "completed" | "failed";
  progress: number; log: string; error: string | null; attempts: number; created_at: string; updated_at: string;
}
export interface Render { id: string; kind: string; file: string; duration: number | null; width: number; height: number; created_at: string; url: string }
export interface Estimate { stage: string; input_tokens: number; output_tokens: number; cost_usd: number | null; prices_configured: boolean }
export interface Cost {
  by_kind: Record<string, { calls: number; input_tokens: number; output_tokens: number; cost_usd: number; unpriced_calls: number }>;
  spent_usd: number; prices_configured: boolean; unpriced_calls: number;
  budget_usd?: number | null; budget_ratio?: number | null; warning?: boolean; exceeded?: boolean; budget_enforceable?: boolean;
}
