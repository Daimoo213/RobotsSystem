/** 格式化时间 HH:MM:SS */
export function formatTime(iso: string | null | undefined): string {
  if (!iso) return '--';
  const d = new Date(iso);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

/** 格式化日期时间 MM-DD HH:MM */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '--';
  const d = new Date(iso);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  const hh = String(d.getHours()).padStart(2, '0');
  const mi = String(d.getMinutes()).padStart(2, '0');
  return `${mm}-${dd} ${hh}:${mi}`;
}

/** 格式化电量 */
export function formatBattery(battery: number): string {
  return `${Math.round(battery)}%`;
}

/** 格式化进度 */
export function formatProgress(progress: number): string {
  return `${Math.round(progress)}%`;
}

/** 格式化位置 */
export function formatPosition(pos: { x: number; y: number; z: number }): string {
  return `(${Math.round(pos.x)}, ${Math.round(pos.y)}, ${Math.round(pos.z)})`;
}

/** 格式化运行时长 */
export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}h${m}m`;
  if (m > 0) return `${m}m${s}s`;
  return `${s}s`;
}

/** 获取状态颜色 */
export function getStatusColor(status: string): string {
  const map: Record<string, string> = {
    idle: '#687988', charging: '#3D8CFF', moving: '#2FD7FF',
    working: '#34DF9A', maintenance: '#FFB33D',
    occupancy: '#B56CFF', fault: '#FF5C6D',
    pending: '#3D8CFF', assigned: '#2FD7FF', running: '#34DF9A',
    paused: '#FFB33D', completed: '#34DF9A', failed: '#FF5C6D',
  };
  return map[status] || '#687988';
}

/** 获取健康指标颜色 */
export function getHealthColor(value: string): string {
  const map: Record<string, string> = {
    ok: '#34DF9A', warn: '#FFB33D', fail: '#FF5C6D', busy: '#3D8CFF',
  };
  return map[value] || '#687988';
}
