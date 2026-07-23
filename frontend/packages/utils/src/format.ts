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
  if (h > 0) return `${h}小时${m}分钟`;
  if (m > 0) return `${m}分钟${s}秒`;
  return `${s}秒`;
}

/** 将接口计量单位转换为界面中文。 */
export function formatUnit(unit: string | null | undefined): string {
  if (!unit) return '';
  const labels: Record<string, string> = {
    'm³': '立方米', m3: '立方米', t: '吨', m: '米', km: '千米', '㎡': '平方米',
    '车次': '车次', '天': '天',
  };
  return labels[unit] || (/[一-鿿]/.test(unit) ? unit : '计量单位');
}

/** 将外部系统的等级、布尔状态等枚举转换为界面中文。 */
export function formatDisplayValue(value: string | null | undefined, fallback = '未知'): string {
  if (!value) return fallback;
  const labels: Record<string, string> = {
    online: '在线', offline: '离线', normal: '正常', healthy: '正常', ok: '正常',
    excellent: '优', good: '良', moderate: '中', medium: '中',
    poor: '差', low: '低', high: '高', safe: '安全', warning: '警告',
    danger: '危险', critical: '严重', unknown: '未知', no_data: '无数据',
  };
  return labels[value.toLowerCase()] || (/[一-鿿]/.test(value) ? value : fallback);
}

/** 将后端历史英文运行消息转换为界面中文。未知英文消息统一隐藏原文。 */
export function formatUserMessage(message: string | null | undefined): string {
  if (!message) return '';
  if (/[一-鿿]/.test(message)) return message;
  const patterns: Array<[RegExp, (match: RegExpMatchArray) => string]> = [
    [/^Global emergency stop activated\.$/, () => '全局急停已触发。'],
    [/^Global emergency stop released\.$/, () => '全局急停已解除。'],
    [/^Global emergency stop is active\.$/, () => '全局急停处于激活状态。'],
    [/^Active task template changed\.$/, () => '当前任务模板已变更。'],
    [/^Task (.+) dispatched to (.+) after prior mission cancellation\.$/, (m) => `任务 ${m[1]} 已在原任务取消后分配给设备 ${m[2]}。`],
    [/^Task (.+) dispatched to (.+)\.$/, (m) => `任务 ${m[1]} 已分配给设备 ${m[2]}。`],
    [/^Device (.+) heartbeat timed out\.$/, (m) => `设备 ${m[1]} 心跳超时。`],
    [/^Device (.+) battery is below the safety threshold \((.+)%\)\.$/, (m) => `设备 ${m[1]} 电量低于安全阈值（${m[2]}%）。`],
    [/^Device (.+) reported a task or equipment fault\.$/, (m) => `设备 ${m[1]} 报告任务或设备故障。`],
    [/^Device (.+) entered restricted region (.+)\.$/, (m) => `设备 ${m[1]} 进入禁行区域 ${m[2]}。`],
    [/^Devices (.+) and (.+) are ([\d.]+)m apart, below the ([\d.]+)m safety distance\.$/, (m) => `设备 ${m[1]} 与 ${m[2]} 间距 ${m[3]} 米，低于安全距离 ${m[4]} 米。`],
    [/^Device (.+) reported localization drift of ([\d.]+)m\.$/, (m) => `设备 ${m[1]} 报告定位漂移 ${m[2]} 米。`],
    [/^Device (.+) requires maintenance based on (.+)\.$/, (m) => `设备 ${m[1]} 已达到 ${m[2]} 维护条件。`],
  ];
  const matched = patterns.find(([pattern]) => pattern.test(message));
  if (matched) return matched[1](message.match(matched[0])!);
  return '系统运行消息';
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
