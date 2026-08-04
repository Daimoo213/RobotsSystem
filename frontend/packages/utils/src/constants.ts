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
  agv: '自动运输车', excavator: '挖掘机', crane: '吊车',
  masonry: '砌筑机器人', inspect: '巡检机器人', inspection: '巡检机器人',
};

/** 设备状态标签 */
export const DEVICE_STATUS_LABELS: Record<string, string> = {
  idle: '待机', charging: '充电中', moving: '移动中',
  working: '作业中', paused: '已暂停', maintenance: '维护', occupancy: '维修占用', fault: '故障',
  pending: '待处理', assigned: '已分配', ready: '就绪', offline: '离线', planned_offline: '主动离线',
};

/** 任务状态标签；接口内部仍使用英文编码。 */
export const TASK_STATUS_LABELS: Record<string, string> = {
  pending: '待开始', assigned: '已分配', running: '进行中', paused: '已暂停',
  completed: '已完成', failed: '执行失败', cancel_requested: '取消请求中', cancelled: '已取消', reassign_pending: '等待改派',
};

export const DISPATCH_STATE_LABELS: Record<string, string> = {
  waiting_dependencies: '等待前置任务', waiting_schedule: '等待计划时间', waiting_device: '等待合适设备',
  waiting_planning_input: '等待补充规划条件', waiting_capacity: '等待产能资源',
  dispatched: '已派发', cancelling: '取消请求中', cancelled: '已取消', finished: '已闭环', failed: '派发失败',
};

export const DISPATCH_REASON_LABELS: Record<string, string> = {
  dependencies_incomplete: '前置任务尚未完成', planned_start_not_reached: '尚未到计划开始时间',
  awaiting_candidate: '正在匹配可用设备', no_enabled_device: '没有已启用设备',
  no_compatible_device: '没有能力和点位均匹配的设备', compatible_devices_offline: '匹配设备当前离线',
  compatible_devices_busy: '匹配设备正在执行其他任务', compatible_devices_low_battery: '匹配设备电量不足',
  waiting_previous_device_cancel: '等待原设备确认取消', waiting_reassignment_target: '等待改派设备可用',
  mission_cancelled: '上次执行已取消，等待重新派发', mission_start_rejected: '设备拒绝启动，等待重新派发',
  device_reported_failure: '设备报告执行失败',
  planning_input_required: '缺少交付量、计划窗口或资源需求', planning_window_required: '缺少计划开始或结束时间',
  planned_end_passed: '计划结束时间已过，无法承诺按期完成', no_available_working_time: '没有可用作业时间',
  insufficient_capacity: '当前真实设备产能不足', no_valid_capacity_device: '没有登记有效真实产能的匹配设备',
  allocation_replanning: '执行单元变化，正在按剩余工作量重新规划',
  waiting_device_cancel: '已下发取消命令，等待设备遥测确认', operator_cancelled: '任务已由操作员取消',
};

/** 任务执行状态标签。 */
export const MISSION_STATE_LABELS: Record<string, string> = {
  dispatched: '已下发', accepted: '已接受', running: '运行中', paused: '已暂停',
  completed: '已完成', failed: '执行失败', cancelled: '已取消',
  pause_requested: '暂停请求中', resume_requested: '恢复请求中', cancel_requested: '取消请求中',
};

export const MISSION_PHASE_LABELS: Record<string, string> = {
  preparing: '准备执行', navigating_to_target: '前往目标', arrived_at_target: '已到达目标',
  working: '正在作业', work_completed: '作业已完成', returning: '正在返回', returned: '已返回',
};

/** 告警级别和处理状态标签。 */
export const ALERT_LEVEL_LABELS: Record<string, string> = {
  critical: '严重', warning: '警告', info: '提示',
};
export const ALERT_STATUS_LABELS: Record<string, string> = {
  open: '未确认', ack: '已确认', resolved: '已解决',
};

/** 设备健康指标标签。 */
export const HEALTH_STATUS_LABELS: Record<string, string> = {
  ok: '正常', warn: '警告', fail: '故障', busy: '忙碌', planned_offline: '主动离线', unknown: '未知',
};

/** 实时事件类型标签。 */
export const EVENT_TYPE_LABELS: Record<string, string> = {
  alert: '告警', charging: '充电', sync: '同步', normal: '普通', update: '更新',
  completed: '已完成', task_created: '任务已创建', task_assigned: '任务已分配',
  task_completed: '任务已完成', task_reassigned: '任务已改派', task_paused: '任务已暂停',
  task_resumed: '任务已恢复', task_waiting: '任务等待调度', task_deleted: '任务已删除',
};

/** 控制命令显示标签。 */
export const COMMAND_LABELS: Record<string, string> = {
  pause: '暂停', resume: '恢复', estop: '急停', release: '释放', reset: '重置',
  reset_pose: '重置定位', mission_start: '开始任务', mission_pause: '暂停任务',
  mission_resume: '恢复任务', mission_cancel: '取消任务',
};

/** 施工阶段显示标签。 */
export const STAGE_LABELS: Record<string, string> = Object.fromEntries(
  STAGES.map((stage) => [stage.value, stage.label]),
);

/** 常用计量单位显示标签。 */
export const UNIT_LABELS: Record<string, string> = {
  'm³': '立方米', m3: '立方米', t: '吨', m: '米', km: '千米', '㎡': '平方米',
  '车次': '车次', '天': '天',
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
  occupancy: COLORS.purple, fault: COLORS.red, offline: COLORS.red, planned_offline: COLORS.amber,
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
  { id: 'offline', label: '离线', color: COLORS.red },
  { id: 'planned_offline', label: '主动离线', color: COLORS.amber },
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
