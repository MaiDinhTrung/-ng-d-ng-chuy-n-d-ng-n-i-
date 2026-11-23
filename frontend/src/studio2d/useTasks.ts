import { useCallback, useEffect, useRef, useState } from "react";
import { api2d, type Task } from "./api2d";

/** Theo dõi task nền của một dự án (poll 1.5s khi có việc đang chờ/chạy). Gọi onSettled khi có task vừa xong. */
export function useTasks(pid: string, onSettled?: () => void) {
  const [tasks, setTasks] = useState<Task[]>([]);
  const seen = useRef<string>("");
  const cb = useRef(onSettled);
  cb.current = onSettled;

  const load = useCallback(async () => {
    try {
      const { tasks: t } = await api2d.tasks(pid);
      setTasks(t);
      const sig = t.filter((x) => x.status === "completed" || x.status === "failed").map((x) => `${x.id}:${x.status}`).join(",");
      if (seen.current && sig !== seen.current) cb.current?.();
      seen.current = sig;
      return t;
    } catch { return []; }
  }, [pid]);

  useEffect(() => {
    let stop = false;
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      const t = await load();
      if (stop) return;
      const busy = t.some((x) => x.status === "pending" || x.status === "running");
      timer = setTimeout(tick, busy ? 1500 : 5000);
    };
    void tick();
    return () => { stop = true; clearTimeout(timer); };
  }, [load]);

  return { tasks, reload: load, busy: tasks.some((x) => x.status === "pending" || x.status === "running") };
}
