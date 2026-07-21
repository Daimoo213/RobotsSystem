/** 施工阶段定义 */
export const STAGES = [
  { value: 'earthwork', label: '土方开发', order: 1 },
  { value: 'foundation', label: '基础施工', order: 2 },
  { value: 'main', label: '主体施工', order: 3 },
  { value: 'mep', label: '机电安装', order: 4 },
  { value: 'finishing', label: '装修施工', order: 5 },
  { value: 'landscape', label: '室外景观', order: 6 },
  { value: 'completion', label: '竣工', order: 7 },
] as const;

/** 设备类型标签 */
export const DEVICE_TYPE_LABELS: Record<string, string> = {
  agv: 'AGV运输车', excavator: '挖掘机', crane: '吊车',
  masonry: '砌筑机器人', inspect: '巡检机器人',
};

/** 设备状态标签 */
export const DEVICE_STATUS_LABELS: Record<string, string> = {
  idle: '待机', charging: '充电中', moving: '移动中',
  working: '作业中', paused: '已暂停', maintenance: '维护', occupancy: '维修占用', fault: '故障',
};

/** 设计系统颜色 */
export const COLORS = {
  cyan: '#2FD7FF', blue: '#3D8CFF', green: '#34DF9A',
  amber: '#FFB33D', red: '#FF5C6D', purple: '#B56CFF', gray: '#687988',
  bg: '#050B13', bgPanel: 'rgba(9,25,41,0.86)',
  text: '#E6F6FF', textMuted: '#79A3BF', textWeak: '#5A7A92',
  border: 'rgba(91,183,255,0.22)',
};

/** 设备状态颜色映射 */
export const STATUS_COLORS: Record<string, string> = {
  idle: COLORS.gray, charging: COLORS.blue, moving: COLORS.cyan,
  working: COLORS.green, paused: COLORS.amber, maintenance: COLORS.amber,
  occupancy: COLORS.purple, fault: COLORS.red,
};

/** 告警级别颜色 */
export const ALERT_LEVEL_COLORS: Record<string, string> = {
  critical: COLORS.red, warning: COLORS.amber, info: COLORS.blue,
};

/** 告警状态颜色 */
export const ALERT_STATUS_COLORS: Record<string, string> = {
  open: COLORS.red, ack: COLORS.gray, resolved: COLORS.green,
};

/** 体检指标颜色 */
export const HEALTH_COLORS: Record<string, string> = {
  ok: COLORS.green, warn: COLORS.amber, fail: COLORS.red, busy: COLORS.blue,
};

/** 29项工序 */
export const PROCESSES: Record<string, { name: string; stage: string }> = {
  site_prep: { name: '场地平整', stage: 'earthwork' },
  pit_excavation: { name: '基坑土方清运', stage: 'earthwork' },
  spoil_export: { name: '渣土外运', stage: 'earthwork' },
  pile_foundation: { name: '桩基施工', stage: 'foundation' },
  rebar_binding: { name: '钢筋绑扎', stage: 'main' },
  formwork: { name: '模板安装', stage: 'main' },
  concrete_pouring: { name: '混凝土浇筑', stage: 'main' },
  concrete_curing: { name: '混凝土养护', stage: 'main' },
  precast_hoisting: { name: '预制构件吊装', stage: 'main' },
  rebar_processing: { name: '钢筋加工配送', stage: 'main' },
  masonry_wall: { name: '楼层砌筑', stage: 'main' },
  vertical_transport: { name: '楼层垂直运输', stage: 'main' },
  pipe_install: { name: '管线安装', stage: 'mep' },
  cable_tray: { name: '桥架安装', stage: 'mep' },
  cable_laying: { name: '电缆敷设', stage: 'mep' },
  plastering: { name: '内墙抹灰', stage: 'finishing' },
  wall_spray: { name: '墙面喷涂', stage: 'finishing' },
  floor_grinding: { name: '地坪打磨找平', stage: 'finishing' },
  wall_grinding: { name: '墙面打磨', stage: 'finishing' },
  tile_paving: { name: '瓷砖铺贴', stage: 'finishing' },
  ceiling_install: { name: '吊顶安装', stage: 'finishing' },
  material_transport: { name: '建材辅料转运', stage: 'earthwork' },
  waste_removal: { name: '施工垃圾清运', stage: 'earthwork' },
  site_tidy: { name: '场地文明规整', stage: 'earthwork' },
  safety_inspect: { name: '现场安全巡检', stage: 'earthwork' },
  edge_guard: { name: '临边看护巡查', stage: 'earthwork' },
  emergency_supply: { name: '应急抢险补给', stage: 'earthwork' },
  surveying: { name: '测量放线', stage: 'earthwork' },
  quality_check: { name: '质量检测', stage: 'earthwork' },
};

/** 运维快捷指令 */
export const OPS_COMMANDS = [
  { id: 'self_check', label: '设备自检', icon: 'stethoscope' },
  { id: 'force_charge', label: '强制充电', icon: 'battery-charging' },
  { id: 'mode_switch', label: '模式切换', icon: 'toggle-right' },
  { id: 'diagnostics', label: '系统诊断', icon: 'cpu' },
  { id: 'backup', label: '数据备份', icon: 'database-backup' },
  { id: 'firmware_upgrade', label: '固件升级', icon: 'download-cloud' },
  { id: 'network_check', label: '网络检测', icon: 'wifi' },
  { id: 'safety_inspect', label: '安全巡检', icon: 'shield-check' },
] as const;

/** 3D场景工具栏命令 */
export const SCENE_COMMANDS = [
  { id: 'estop', label: '急停', color: COLORS.red },
  { id: 'pause', label: '暂停', color: COLORS.amber },
  { id: 'release', label: '释放', color: COLORS.blue },
  { id: 'reset', label: '重置', color: COLORS.purple },
  { id: 'resume', label: '恢复', color: COLORS.green },
] as const;

/** 设备筛选芯片 */
export const FILTER_CHIPS = [
  { id: 'working', label: '作业', color: COLORS.green },
  { id: 'moving', label: '移动', color: COLORS.cyan },
  { id: 'idle', label: '待机', color: COLORS.gray },
  { id: 'charging', label: '充电', color: COLORS.blue },
  { id: 'fault', label: '故障', color: COLORS.red },
  { id: 'occupancy', label: '维修占用', color: COLORS.purple },
] as const;

/** 体检指标项 */
export const HEALTH_KEYS = [
  { key: 'connection', label: '连' },
  { key: 'location', label: '定' },
  { key: 'battery', label: '电' },
  { key: 'task', label: '任' },
  { key: 'safety', label: '安' },
] as const;
