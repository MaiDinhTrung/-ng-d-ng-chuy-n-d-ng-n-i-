import { useState } from "react";
import type { Voice } from "../api";
import { CostTab } from "./CostTab";
import { ProjectsTab } from "./ProjectsTab";
import { ProvidersTab } from "./ProvidersTab";
import { ReferenceLibrary } from "./ReferenceLibrary";

type Tab = "projects" | "refs" | "cost" | "providers";
const TABS: [Tab, string][] = [["projects", "Dự án 2D"], ["refs", "Thư viện tư liệu"], ["cost", "Cost Manager"], ["providers", "AI Providers"]];

/** Vỏ của phân hệ 2D Animation: thanh tab con riêng, không đụng điều hướng của Audio. */
export function Studio2D({ voices }: { voices: Voice[] }) {
  const [tab, setTab] = useState<Tab>("projects");
  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center gap-1 border-b border-line bg-panel px-4 pt-2">
        <div className="font-semibold mr-4 pb-2">🎬 2D Animation Studio</div>
        {TABS.map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`px-3 py-2 text-sm rounded-t-lg border-b-2 ${tab === k ? "border-accent text-accent" : "border-transparent text-muted hover:text-white"}`}>{label}</button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === "projects" && <ProjectsTab voices={voices} openLibrary={() => setTab("refs")} />}
        {tab === "refs" && <ReferenceLibrary />}
        {tab === "cost" && <CostTab />}
        {tab === "providers" && <ProvidersTab />}
      </div>
    </div>
  );
}
