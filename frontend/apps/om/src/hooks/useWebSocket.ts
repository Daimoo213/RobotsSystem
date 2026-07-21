/** WebSocket hook for O&M端. */

import { useEffect } from 'react';
import { getEnergyView, getLatestPointcloud, getSafetyView, getWSClient, listAlerts, listDevices, setRole } from '@robots/api-client';
import { useOmStore } from '../stores/omStore';
import type { Device, Alert, PointCloudData } from '@robots/shared-types';

export function useWebSocket() {
  const store = useOmStore();

  useEffect(() => {
    setRole('om');
    listDevices().then(store.setDevices).catch(console.error);
    listAlerts().then(store.setAlerts).catch(console.error);
    getLatestPointcloud().then((snapshot) => {
      if (snapshot.has_data && snapshot.points.length) store.setPointcloud(snapshot as PointCloudData);
    }).catch(console.error);
    getEnergyView().then(store.setEnergyView).catch(console.error);
    getSafetyView().then(store.setSafetyView).catch(console.error);

    const ws = getWSClient('om', ['devices', 'alerts', 'events', 'pointcloud', 'estop']);

    const unsubDevices = ws.subscribe('devices', (data) => {
      const devices = (data as { devices?: Device[] }).devices;
      if (devices) store.setDevices(devices);
    });
    const unsubAlerts = ws.subscribe('alerts', (data) => {
      const alert = data as unknown as Alert;
      if (alert?.id) store.upsertAlert(alert);
    });
    const unsubEvents = ws.subscribe('events', (data) => {
      const e = data as { time?: string; type?: string; message?: string };
      if (e?.message) store.addEvent({ time: e.time || new Date().toISOString(), type: e.type || 'normal', message: e.message });
      if (e?.type?.startsWith('map_')) window.dispatchEvent(new Event('robots:map-changed'));
    });
    const unsubPC = ws.subscribe('pointcloud', (data) => {
      const pc = data as unknown as PointCloudData;
      if (pc?.points) store.setPointcloud(pc);
    });
    const unsubEstop = ws.subscribe('estop', (data) => {
      const estop = data as { active?: boolean; source?: string };
      store.setEstop(estop.active || false, estop.source);
    });

    return () => {
      unsubDevices(); unsubAlerts(); unsubEvents(); unsubPC(); unsubEstop();
    };
  }, []);
}
