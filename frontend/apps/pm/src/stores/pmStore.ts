/** PM dashboard Zustand store. */

import { create } from 'zustand';
import type { Device, Task, Alert, Script, RealtimeEvent, ProcessOption } from '@robots/shared-types';
import type { KpiData, TrendData, ResourceLoad, CameraInfo } from '@robots/api-client';

interface PmState {
  devices: Device[];
  tasks: Task[];
  alerts: Alert[];
  events: RealtimeEvent[];
  scripts: Script[];
  processes: ProcessOption[];
  kpiData: KpiData | null;
  trendData: TrendData | null;
  resourceLoad: ResourceLoad[];
  cameras: CameraInfo[];
  activeStage: string;
  estopActive: boolean;
  estopSource: string | null;
  // Actions
  setDevices: (devices: Device[]) => void;
  setTasks: (tasks: Task[]) => void;
  addTask: (task: Task) => void;
  updateTask: (task: Task) => void;
  removeTask: (taskId: string) => void;
  setAlerts: (alerts: Alert[]) => void;
  upsertAlert: (alert: Alert) => void;
  addEvent: (event: RealtimeEvent) => void;
  setScripts: (scripts: Script[]) => void;
  setProcesses: (processes: ProcessOption[]) => void;
  setKpiData: (data: KpiData) => void;
  setTrendData: (data: TrendData) => void;
  setResourceLoad: (data: ResourceLoad[]) => void;
  setCameras: (data: CameraInfo[]) => void;
  setActiveStage: (stage: string) => void;
  setEstop: (active: boolean, source?: string) => void;
}

export const usePmStore = create<PmState>((set) => ({
  devices: [],
  tasks: [],
  alerts: [],
  events: [],
  scripts: [],
  processes: [],
  kpiData: null,
  trendData: null,
  resourceLoad: [],
  cameras: [],
  activeStage: 'earthwork',
  estopActive: false,
  estopSource: null,

  setDevices: (devices) => set({ devices }),
  setTasks: (tasks) => set({ tasks }),
  addTask: (task) => set((s) => {
    if (s.tasks.some((t) => t.id === task.id)) return s;
    return { tasks: [...s.tasks, task] };
  }),
  updateTask: (task) => set((s) => ({
    tasks: s.tasks.map((t) => (t.id === task.id ? { ...t, ...task } : t)),
  })),
  removeTask: (taskId) => set((s) => ({
    tasks: s.tasks.filter((t) => t.id !== taskId),
  })),
  setAlerts: (alerts) => set({ alerts }),
  upsertAlert: (alert) => set((s) => {
    const exists = s.alerts.some((item) => item.id === alert.id);
    return {
      alerts: exists
        ? s.alerts.map((item) => (item.id === alert.id ? alert : item))
        : [alert, ...s.alerts].slice(0, 100),
    };
  }),
  addEvent: (event) => set((s) => ({ events: [event, ...s.events].slice(0, 50) })),
  setScripts: (scripts) => set({ scripts }),
  setProcesses: (processes) => set({ processes }),
  setKpiData: (kpiData) => set({ kpiData }),
  setTrendData: (trendData) => set({ trendData }),
  setResourceLoad: (resourceLoad) => set({ resourceLoad }),
  setCameras: (cameras) => set({ cameras }),
  setActiveStage: (stage) => set({ activeStage: stage }),
  setEstop: (active, source) => set({ estopActive: active, estopSource: source || null }),
}));
