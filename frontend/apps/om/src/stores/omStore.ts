/** O&M dashboard Zustand store. */

import { create } from 'zustand';
import type { Device, Alert, RealtimeEvent, PointCloudData } from '@robots/shared-types';
import type { EnergyView, SafetyView } from '@robots/api-client';

type ViewMode = 'dispatch' | 'energy' | 'safety';

interface OmState {
  devices: Device[];
  alerts: Alert[];
  events: RealtimeEvent[];
  pointcloud: PointCloudData | null;
  mappingEnabled: boolean;
  estopActive: boolean;
  estopSource: string | null;
  currentView: ViewMode;
  energyView: EnergyView | null;
  safetyView: SafetyView | null;
  selectedDeviceId: string | null;
  filterStatuses: Set<string>;
  setDevices: (d: Device[]) => void;
  setAlerts: (a: Alert[]) => void;
  upsertAlert: (a: Alert) => void;
  addEvent: (e: RealtimeEvent) => void;
  setPointcloud: (p: PointCloudData) => void;
  setMappingEnabled: (enabled: boolean) => void;
  setEstop: (active: boolean, source?: string) => void;
  setView: (v: ViewMode) => void;
  setEnergyView: (view: EnergyView | null) => void;
  setSafetyView: (view: SafetyView | null) => void;
  selectDevice: (id: string | null) => void;
  toggleFilter: (status: string) => void;
}

export const useOmStore = create<OmState>((set) => ({
  devices: [],
  alerts: [],
  events: [],
  pointcloud: null,
  mappingEnabled: false,
  estopActive: false,
  estopSource: null,
  currentView: 'dispatch',
  energyView: null,
  safetyView: null,
  selectedDeviceId: null,
  filterStatuses: new Set(),
  setDevices: (devices) => set({ devices }),
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
  setPointcloud: (pointcloud) => set({ pointcloud }),
  setMappingEnabled: (mappingEnabled) => set({ mappingEnabled }),
  setEstop: (active, source) => set({ estopActive: active, estopSource: source || null }),
  setView: (currentView) => set({ currentView }),
  setEnergyView: (energyView) => set({ energyView }),
  setSafetyView: (safetyView) => set({ safetyView }),
  selectDevice: (selectedDeviceId) => set({ selectedDeviceId }),
  toggleFilter: (status) => set((s) => {
    const next = new Set(s.filterStatuses);
    if (next.has(status)) next.delete(status); else next.add(status);
    return { filterStatuses: next };
  }),
}));
