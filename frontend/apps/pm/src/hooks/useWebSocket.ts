/** WebSocket hook for PM端. */

import { useEffect } from 'react';
import { getWSClient, setRole, listDevices, listTasks, listAlerts, listScripts, listProcesses } from '@robots/api-client';
import { usePmStore } from '../stores/pmStore';
import type { Device, Alert, Task } from '@robots/shared-types';

export function useWebSocket() {
  const store = usePmStore();

  useEffect(() => {
    setRole('pm');

    // Initial REST fetch
    listDevices().then(store.setDevices).catch(console.error);
    listTasks().then(store.setTasks).catch(console.error);
    listAlerts().then(store.setAlerts).catch(console.error);
    listScripts().then(store.setScripts).catch(console.error);
    listProcesses().then(store.setProcesses).catch(console.error);

    // WebSocket
    const ws = getWSClient('pm', ['devices', 'tasks', 'alerts', 'events', 'estop', 'script']);

    const unsubDevices = ws.subscribe('devices', (data) => {
      const devices = (data as { devices?: Device[] }).devices;
      if (devices) store.setDevices(devices);
    });

    // 处理 tasks 频道消息：task_created / task_updated / task_deleted / task_assigned / task_completed
    const unsubTasks = ws.subscribe('tasks', (data) => {
      const msg = data as { type?: string; id?: string; [key: string]: unknown };
      if (!msg?.type) return;

      if (msg.type === 'task_created' || msg.type === 'task_assigned' || msg.type === 'task_completed' || msg.type === 'task_waiting' || msg.type === 'task_reassigned' || msg.type === 'task_resource_plan_updated' || msg.type === 'task_schedule_updated' || msg.type === 'task_cancel_requested' || msg.type === 'task_cancelled') {
        // 完整任务对象在 data 里
        const task = data as unknown as Task;
        if (task?.id) {
          store.updateTask(task); // 如果已存在则更新
          // 如果不存在则添加（updateTask 只 map，不会添加新项）
          const exists = usePmStore.getState().tasks.some((t) => t.id === task.id);
          if (!exists) store.addTask(task);
        }
      } else if (msg.type === 'task_updated') {
        const task = data as unknown as Task;
        if (task?.id) store.updateTask(task);
      } else if (msg.type === 'task_deleted') {
        const taskId = msg.task_id as string | undefined;
        if (taskId) store.removeTask(taskId);
      } else if (msg.type === 'task_paused' || msg.type === 'task_resumed') {
        const task = data as unknown as Task;
        if (task?.id) store.updateTask(task);
      }
    });

    const unsubAlerts = ws.subscribe('alerts', (data) => {
      const alert = data as unknown as Alert;
      if (alert?.id) store.upsertAlert(alert);
    });

    const unsubEvents = ws.subscribe('events', (data) => {
      const event = data as { time?: string; type?: string; message?: string };
      if (event?.message) {
        store.addEvent({
          time: event.time || new Date().toISOString(),
          type: event.type || 'normal',
          message: event.message,
        });
      }
    });

    const unsubEstop = ws.subscribe('estop', (data) => {
      const estop = data as { active?: boolean; source?: string };
      store.setEstop(estop.active || false, estop.source);
    });

    return () => {
      unsubDevices();
      unsubTasks();
      unsubAlerts();
      unsubEvents();
      unsubEstop();
    };
  }, []);
}
