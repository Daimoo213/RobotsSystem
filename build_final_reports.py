# -*- coding: utf-8 -*-
"""生成两份交付文档：
1) 实现进度对比分析报告.docx  —— 方案需求 vs 当前实现，差距 + 实现占比
2) 技术方案总览_功能维度_技术选型_技术路线.docx —— 前端/后端/数据库/机器人 四维度功能点 + 选型 + 路线
均使用 python-docx；CJK 字体微软雅黑。
"""
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

CJK = "Microsoft YaHei"
DARK = RGBColor(0x1F, 0x29, 0x37)
ACCENT = RGBColor(0x2F, 0x6F, 0xE0)
GREY = RGBColor(0x60, 0x6A, 0x78)


def set_cjk(run, size=10.5, bold=False, color=DARK):
    run.font.name = CJK
    run._element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.color.rgb = color


def style_doc(doc):
    # default font
    st = doc.styles["Normal"]
    st.font.name = CJK
    st._element.rPr.rFonts.set(qn("w:eastAsia"), CJK)
    st.font.size = Pt(10.5)
    st.font.color.rgb = DARK


def title(doc, text):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(text)
    set_cjk(r, 20, True, ACCENT)
    p.space_after = Pt(6)


def h1(doc, text):
    p = doc.add_heading(level=1)
    r = p.add_run(text)
    set_cjk(r, 15, True, ACCENT)
    return p


def h2(doc, text):
    p = doc.add_heading(level=2)
    r = p.add_run(text)
    set_cjk(r, 12.5, True, DARK)
    return p


def h3(doc, text):
    p = doc.add_heading(level=3)
    r = p.add_run(text)
    set_cjk(r, 11, True, DARK)
    return p


def para(doc, text, size=10.5, bold=False, color=DARK, italic=False):
    p = doc.add_paragraph()
    r = p.add_run(text)
    set_cjk(r, size, bold, color)
    r.font.italic = italic
    return p


def bullet(doc, text, lead=None):
    p = doc.add_paragraph(style="List Bullet")
    if lead:
        r = p.add_run(lead)
        set_cjk(r, 10.5, True, ACCENT)
        r2 = p.add_run(text)
        set_cjk(r2, 10.5)
    else:
        r = p.add_run(text)
        set_cjk(r, 10.5)
    return p


def table(doc, headers, rows, widths=None, header_fill="2F6FE0"):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Light Grid Accent 1"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    hdr = t.rows[0].cells
    for i, htext in enumerate(headers):
        hdr[i].text = ""
        rp = hdr[i].paragraphs[0].add_run(htext)
        set_cjk(rp, 10, True, RGBColor(0xFF, 0xFF, 0xFF))
        # fill
        tcPr = hdr[i]._tc.get_or_add_tcPr()
        from docx.oxml import OxmlElement
        shd = OxmlElement("w:shd")
        shd.set(qn("w:val"), "clear")
        shd.set(qn("w:fill"), header_fill)
        tcPr.append(shd)
    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            rr = cells[i].paragraphs[0].add_run(str(val))
            set_cjk(rr, 9.5)
    if widths:
        for i, w in enumerate(widths):
            for row in t.rows:
                row.cells[i].width = Inches(w)
    return t


# ============================================================
# 文档 1：实现进度对比分析报告
# ============================================================
def build_comparison():
    doc = Document()
    style_doc(doc)
    title(doc, "机器人集群智能调度系统\n实现进度对比分析报告")
    para(doc, "（基于源码静态走查，对照《方案一_集群调度系统开发方案》与 CODEBUDDY.md 规划，"
              "未执行前端构建与后端集成测试）", size=9, color=GREY, italic=True)
    para(doc, "生成日期：2026-07-16", size=9, color=GREY)

    # 1 背景
    h1(doc, "一、项目背景与方案需求概述")
    para(doc, "本项目是某高校“智能建造”科研展示项目的“大脑”部分：调度 20–100 台异构施工机器人，"
              "在微缩工地沙盘上协同完成房地产建设全流程演示。我方交付范围为调度系统的前后端，"
              "以及提供给机器人硬件接入的标准化 API 接口（不涉及机器人硬件本身）。")
    para(doc, "系统规划为严格的四层架构（应用层 / 调度层 / 接入层 / 设备层），并由 8 大功能模块协作：")
    for m in [
        "设备接入与集群管理 —— 一机一档、适配器抽象、心跳遥测、分组管理",
        "工地地图与环境感知 —— 网格+高度层地图、区域划分、施工点位、动态障碍",
        "集群智能调度（核心）—— 29 项工序 DAG、集中式+分布式调度、市场机制派单、任务模板、优先级、人工干预",
        "集群协同作业控制 —— 批量操控、编队同步、碰撞联锁",
        "能耗与维保管控 —— 能耗模型、续航预测、错峰充能、维保提醒",
        "监控与告警中心 —— 数字孪生大屏数据源、单设备下钻、告警引擎",
        "施工数据与报表统计 —— 事件溯源时序库、多维聚合、PDF/Excel 导出",
        "施工现场安全管控 —— 人机避让、全局急停、分区管控（电子围栏）",
    ]:
        bullet(doc, m)
    para(doc, "两套前端：PM 端（施工进度指挥）与 O&M 端（设备集群 3D 调度），共用同一后端与机器人接入 API。")

    # 2 验证方法
    h1(doc, "二、验证方法与范围")
    bullet(doc, "后端走查：app/ 下全部 .py（adapters / api / core / models / scheduler / services / ws / pointcloud），重点阅读 scheduler/engine.py、adapters/simulated.py、services/runtime.py、api/alerts.py、core/database.py、core/redis.py、models/models.py、main.py。")
    bullet(doc, "前端走查：frontend/ 下 apps/pm、apps/om、packages/* 关键组件与 API 客户端。")
    bullet(doc, "判定口径：已实现=有真实逻辑且数据驱动；部分实现=核心数据结构/接口在但关键逻辑缺失或仅为仿真；未实现=无代码或仅占位/TODO。")
    bullet(doc, "局限：未运行集成测试，机器人层为仿真环境，真实 ROS2/MQTT/硬件未接线，占比为功能完整性估计。")

    # 3 逐模块验证
    h1(doc, "三、逐模块实现验证结果（后端 8 模块）")
    table(doc,
          ["模块", "规划核心内容", "已实现（证据）", "缺失 / 仅仿真", "状态", "占比"],
          [
              ["设备接入与集群管理", "一机一档、DeviceAgent、心跳遥测、分组",
               "Device 模型（code/type/capabilities/permissions/health）+ SimulatedAdapter（心跳→Redis、遥测→device_events、移动、任务执行、pause/resume/estop/reset/release）",
               "Ros2Adapter 不存在；MQTT 未接线；仅仿真设备", "部分", "60%"],
              ["工地地图与环境感知", "网格+高度层、区域/点位、动态障碍、版本快照",
               "MapRegion/MapPoint 模型 + map API（区域、点位 CRUD）",
               "动态障碍、SLAM/真实点云、进度版本快照缺失；点云仅仿真生成", "部分", "50%"],
              ["集群智能调度", "29 工序 DAG、集中式+分布式、市场机制、模板、优先级、干预",
               "SchedulerEngine 后台循环真实可用：DAG 加载、get_ready_tasks、MarketSchedulerStrategy 成本派单、完工检查、写库、WS 广播；Script 模板+reload；process→device 映射+优先级",
               "分布式协商无；人工干预 API（暂停/改派/插单）无；RL 策略接口无", "基本", "78%"],
              ["集群协同作业控制", "批量操控、编队同步、碰撞联锁",
               "send_command 批量指令（pause/resume/estop/reset/release）",
               "编队同步无；碰撞联锁无（device_safety_distance 配置已定义但零引用）", "部分", "25%"],
              ["能耗与维保管控", "能耗模型、续航预测、错峰充能、维保提醒",
               "SimulatedDevice 电量耗散/回充、<15 自动回停靠充电、<20 健康 warn",
               "续航预测无；错峰充能排程无；按里程/时长维保提醒无", "部分", "40%"],
              ["监控与告警中心", "大屏数据源、单设备下钻、告警引擎",
               "WebSocket+Redis 7 通道发布订阅、dashboard/device 下钻 API、DeviceEvent 时序",
               "告警引擎无产生逻辑（Alert 表仅 list/ack，无任何模块写入告警）→ 大屏告警恒为空", "部分", "55%"],
              ["施工数据与报表统计", "事件溯源、多维聚合、PDF/Excel 导出",
               "DeviceEvent 时序模型 + reports API 路由",
               "多维度聚合报表未完善；PDF/Excel 导出未实现（或仅占位）", "部分", "40%"],
              ["施工现场安全管控", "人机避让、全局急停、分区管控",
               "全局急停已实现（软件双通道：runtime.trigger_estop + adapter.set_estop + WS 广播）",
               "电子围栏越界拦截无（配置未引用）；人机避让无；分区授权无", "部分", "30%"],
          ],
          widths=[1.1, 1.5, 2.2, 1.9, 0.6, 0.5])

    # 4 分维度差距
    h1(doc, "四、分维度差距清单")
    h2(doc, "4.1 后端（业务模块）")
    bullet(doc, "告警引擎：规划为订阅各模块事件并产生分级告警，当前仅有查询接口，无任何产生逻辑 —— 演示阻断级缺口。")
    bullet(doc, "分布式调度协商、人工干预（改派/插单/暂停）API：调度核心强，但运行时不接收外部干预指令。")
    bullet(doc, "碰撞联锁、电子围栏拦截：配置项 device_safety_distance / 围栏数据已存在，但派单与移动逻辑均未消费。")
    h2(doc, "4.2 前端（PM / O&M 双端）")
    bullet(doc, "PM 端完成度高（甘特图数据驱动、KPI、左/右栏齐全）；O&M 端 3D 真实渲染（Three.js）、设备条/详情/拓扑齐全。")
    bullet(doc, "差距：三视图（调度/能耗/安全）仅标签页，未切换底层数据；摄像头 AI 识别为占位/仿真写入；历史轨迹/告警回放无；O&M 暂停/释放/重置按钮未接运行时命令。")
    h2(doc, "4.3 数据库")
    bullet(doc, "已实现：PostgreSQL + 异步 SQLAlchemy（10 张表，UUID/JSONB），Redis 7 通道发布订阅，DeviceEvent 时序落库。")
    bullet(doc, "差距：无 Alembic 迁移（生产靠 create_all 风险高）；device_events 为普通表而非专用时序库（规划称时序库）；无备份/读写分离策略。")
    h2(doc, "4.4 机器人（设备接入层）")
    bullet(doc, "仅 SimulatedAdapter 仿真；Ros2Adapter、MQTT 接线、标准接入协议契约均未实现；碰撞联锁/围栏/避障在设备侧无落地。这是与方案差距最大的一块。")

    # 5 实现占比
    h1(doc, "五、实现占比总览")
    table(doc,
          ["维度", "整体占比", "说明"],
          [
              ["后端（8 模块 + 基础设施）", "≈ 58%", "调度核心真实可用；接入/协同/能耗/告警/安全/报表/地图多数仅部分"],
              ["前端（PM + O&M）", "≈ 73%", "PM 80% / O&M 65%；数据驱动与真实 3D 渲染到位，视图切换与回放待补"],
              ["数据库", "≈ 70%", "模型与实时通道扎实；缺迁移工具与专用时序库"],
              ["机器人（设备接入层）", "≈ 8%", "仅仿真接入；真实 ROS2/MQTT/协议契约/安全响应未落地"],
              ["系统整体", "≈ 52%", "按 后端40%·前端35%·机器人25% 加权估算"],
          ],
          widths=[2.4, 1.4, 3.0])
    para(doc, "结论：系统“骨架与展示面”已成型（调度引擎、双端大屏、数据通道），但“真实设备接入、告警产生、"
              "安全拦截（碰撞/围栏）”三处为演示与验收阻断项，需优先补齐。", bold=True)

    # 6 P0
    h1(doc, "六、关键待补齐项（按优先级）")
    table(doc,
          ["优先级", "缺口", "影响"],
          [
              ["P0 演示阻断", "真实设备接入（Ros2Adapter + MQTT 接线 + 协议契约）", "无真实机器人即无演示本体"],
              ["P0 演示阻断", "告警引擎（产生逻辑 + 分级 + WS 推送）", "O&M 告警列表恒空，安全态势不可见"],
              ["P0 验收必查", "碰撞联锁 + 电子围栏越界拦截", "安全管控形同虚设，方案核心卖点缺失"],
              ["P1 重要", "人工干预 API（暂停/改派/插单）、分布式协商", "调度灵活性不足，演示可解释性差"],
              ["P1 重要", "Alembic 迁移 + 专用时序库", "生产可维护性与报表性能"],
              ["P2 增强", "维保提醒、续航预测、错峰充能、PDF/Excel 导出、历史回放", "完整度与汇报支撑"],
          ],
          widths=[1.3, 3.0, 2.5])
    doc.save("实现进度对比分析报告.docx")
    print("saved 实现进度对比分析报告.docx")


# ============================================================
# 文档 2：分维度技术方案（前端/后端/数据库/机器人）
# ============================================================
def fp(doc, name, status, selection, route, desc):
    """功能点块：标题 + 状态 + 选型表 + 路线 + 说明"""
    h3(doc, name)
    badge = {"已实现": "✅ 已实现", "部分实现": "🟡 部分实现", "未实现": "⚪ 未实现"}.get(status, status)
    p = doc.add_paragraph()
    r = p.add_run("状态：" + badge)
    set_cjk(r, 10, True, ACCENT if status == "已实现" else (RGBColor(0xB8,0x86,0x00) if status=="部分实现" else GREY))
    table(doc, ["维度", "内容"],
          [["技术选型 / 真实做法", selection],
           ["技术路线（落地步骤）", route]],
          widths=[1.6, 5.2])
    if desc:
        para(doc, desc, size=9.5, color=GREY, italic=True)


def rfp(doc, name, status, definition, split, selection, route, components):
    """机器人功能点块：功能定义 / 云-机分工 / 技术选型 / 技术路线 / 依赖部件。"""
    h3(doc, name)
    badge = {"已实现": "✅ 已实现", "部分实现": "🟡 部分实现（仿真）", "未实现": "⚪ 待自研"}.get(status, status)
    p = doc.add_paragraph()
    r = p.add_run("状态：" + badge)
    set_cjk(r, 10, True, ACCENT if status == "已实现" else (RGBColor(0xB8, 0x86, 0x00) if status == "部分实现" else GREY))
    table(doc, ["维度", "内容"],
          [["功能定义", definition],
           ["云端 / 机端分工", split],
           ["技术选型", selection],
           ["技术路线（怎么做）", route],
           ["依赖部件", components]],
          widths=[1.5, 5.3])


def build_techplan():
    doc = Document()
    style_doc(doc)
    title(doc, "机器人集群智能调度系统\n技术方案总览（功能维度 · 技术选型 · 技术路线）")
    para(doc, "按 前端 / 后端 / 数据库 / 机器人 四个维度划分功能点。"
              "已实现功能如实记录真实采用的方法；未实现 / 部分实现功能给出宏观技术选型与落地路线，"
              "确保方案功能在四层架构中正常流通。", size=9.5, color=GREY, italic=True)
    para(doc, "生成日期：2026-07-16", size=9, color=GREY)

    # ---------- 维度一：后端 ----------
    h1(doc, "维度一：后端（调度核心与业务模块）")
    para(doc, "现状底座：FastAPI（异步）+ SQLAlchemy（异步）+ PostgreSQL + Redis（发布订阅）+ WebSocket + JWT 鉴权 + Docker，已真实落地。", bold=True)
    fp(doc, "B1 设备接入与集群管理 API", "部分实现",
       "已实现：Device 模型（一机一档：code/type/capabilities/section_tags/permissions/health）+ 适配器模式（DeviceAdapter 抽象）+ SimulatedAdapter（心跳→Redis、遥测→device_events、移动、任务执行、pause/resume/estop/reset/release）。"
       "待选型：真实接入采用 ROS2（rclpy）适配 + MQTT（aiomqtt）轻量节点双协议，统一抽象为 DeviceAgent。",
       "1) 定义统一 JSON 接入契约（注册/心跳/遥测/指令/事件）；2) 实现 Ros2Adapter 对接 /device_state、/cmd_vel 等话题；3) 实现 MqttAdapter 对接遥测与指令主题；4) 在 RuntimeContext 中按配置选择适配器；5) 20 台压测（连接≤2s、定位≤15cm、心跳超时判定离线）。",
       "当前仅有仿真设备，真实 ROS2/MQTT 未接线。")
    fp(doc, "B2 集群智能调度引擎", "已实现",
       "已实现：SchedulerEngine 后台循环真实可用——DAG 加载（29 工序）、get_ready_tasks 依赖解锁、MarketSchedulerStrategy 成本派单（距离×0.5+电量×0.3+负载）、完工检查（设备回 idle 置 100%）、写库、WS 广播；Script 任务模板 + reload；process→device 映射 + priority 字段。",
       "维持现状并增强：1) 暴露人工干预 API（暂停/改派/插单），在 _tick 前消费干预队列；2) 增加分布式协商桩（局部资源争用协商接口）；3) 预留 RL 分配策略接口（Strategy 可插拔）。",
       "调度核心是当前最成熟模块，无需重写，补干预与协商即可。")
    fp(doc, "B3 工地地图与环境感知", "部分实现",
       "已实现：MapRegion/MapPoint 模型 + map API（区域、点位 CRUD）。"
       "待选型：地图存储用 PostgreSQL + 网格+高度层扩展（或 PostGIS 几何）；动态障碍用传感器/SLAM 融合写入 obstacle 层；点云用 ROS2 sensor_msgs/PointCloud2 订阅。",
       "1) 增加 dynamic_obstacle 表与版本化快照；2) PointCloudManager 接入真实 ROS2 点云主题（替换 simulated 分支）；3) 地图编辑器支持进度快照导出。",
       "点云当前为仿真生成，真实源为占位。")
    fp(doc, "B4 集群协同作业控制", "部分实现",
       "已实现：send_command 批量指令（pause/resume/estop/reset/release）下发同标段/同型设备。"
       "待选型：编队同步用群组指令 + 节拍对齐；碰撞联锁新建独立服务 services/interlock.py，消费位姿流计算距离矩阵，分级降速/停车。",
       "1) 实现 interlock 服务（消费 device_events 位姿，距离< device_safety_distance 触发减速/停车，广播联锁事件）；2) 编队同步：群组指令 + 多机节拍对齐；3) 联锁事件上报监控告警与安全管控。",
       "碰撞联锁当前零实现，device_safety_distance 配置已定义未引用——P0。")
    fp(doc, "B5 能耗与维保管控", "部分实现",
       "已实现：SimulatedDevice 电量耗散/回充、<15 自动回停靠、<20 健康 warn。"
       "待选型：能耗模型（按类型/负载估算）+ 续航预测 + 错峰充能排程（空闲/低优间隙调度）+ 维保提醒（运行时长/里程阈值工单）。",
       "1) 能耗模型服务估算剩余续航；2) 错峰充能：在调度空隙下发 charge 指令（复用 force_charge）；3) 维保提醒：定时扫描里程/时长生成保养工单写入 Alert/工单表。",
       "当前仅电量仿真，预测与提醒缺失。")
    fp(doc, "B6 监控与告警中心", "部分实现",
       "已实现：WebSocket + Redis 7 通道（devices/tasks/events/alerts/pointcloud/estop/script）发布订阅；dashboard/device 下钻 API；DeviceEvent 时序。"
       "待选型：告警引擎=规则引擎（阈值 + 状态机），订阅各模块事件，分级（critical/warning/info）落 Alert 表并 WS 推送。",
       "1) 新建 services/alert_engine.py，订阅离线/超时/低电量/路径冲突/越界事件；2) 分级写入 Alert + 推 CHANNEL_ALERTS；3) 前端告警列表即由真实数据驱动。",
       "告警产生逻辑当前完全缺失，大屏告警恒空——P0。")
    fp(doc, "B7 施工数据与报表统计", "部分实现",
       "已实现：DeviceEvent 时序模型 + reports API 路由。"
       "待选型：时序库（TimescaleDB 或分区表）支撑高吞吐；多维聚合（标段/日期/工序/车型/班组）；导出用后端生成 PDF（ReportLab）/Excel（openpyxl）。",
       "1) 报表聚合接口补全；2) 接入导出（PDF/Excel）；3) 事件溯源反哺调度策略优化。",
       "导出与多维聚合待完善。")
    fp(doc, "B8 施工现场安全管控", "部分实现",
       "已实现：全局急停（软件双通道：runtime.trigger_estop + adapter.set_estop + WS 广播）。"
       "待选型：急停双通道（软件+硬件继电器）；围栏校验服务 core/geofence.py（is_point_allowed/is_path_allowed 射线法）；人机避让基于实时位姿 + 电子围栏；分区授权（标段围栏 + 跨区作业授权）。",
       "1) 派单前调用 geofence 拦截禁行区（接入已定义配置）；2) 设备移动中实时校验越界→降速/停机；3) 分区授权校验；4) 人机避让：位姿接近危险区触发降速。",
       "围栏与避让当前未落地，仅急停可用——P0/P1。")

    # ---------- 维度二：前端 ----------
    h1(doc, "维度二：前端（PM 端 / O&M 端）")
    para(doc, "现状底座：React + TypeScript + Vite，pnpm monorepo（apps/pm、apps/om、packages/api-client、packages/ui、packages/shared-types），"
              "图表用 ECharts/Recharts，O&M 3D 用 Three.js（@react-three/fiber），实时数据用 WebSocket 客户端。", bold=True)
    fp(doc, "F1 PM 端甘特图（核心）", "已实现",
       "已实现：GanttColumn 数据驱动，支持日/周/月/季度切换、依赖线、里程碑菱形、今日线、任务详情弹窗，数据来自后端 tasks API + WS。",
       "维持并增强：接入人工干预（新增/改派）回写后端；里程碑与实际进度联动。",
       "PM 端最完整面板。")
    fp(doc, "F2 PM 端 KPI / 左栏 / 右栏", "已实现",
       "已实现：TopBar（在线率/扬尘/工期健康分/用户）、8 项 KPI、左栏（机器人数量环形图、土方资源负载、7 阶段进度）、右栏（待办+新增、摄像头视角、完成趋势三线、实时事件闭环），全部数据驱动。",
       "维持；摄像头 AI 识别接真实源后替换仿真写入。", "")
    fp(doc, "F3 O&M 端 3D 土方调度视角", "已实现",
       "已实现：Scene3D 基于 Three.js 真实渲染半透明空间方块（坑底/放坡/楼栋/道路/堆场）、机器人红点/红标、HUD 网格、设备名牌、场景工具栏（急停/暂停/释放/重置/恢复）、状态筛选芯片，数据来自 WS 位姿流。",
       "维持；补充透明方块模型层（真实点云叠加）；工具栏命令接 runtime 命令。",
       "3D 渲染真实可用。")
    fp(doc, "F4 O&M 端设备条 / 详情 / 拓扑", "已实现",
       "已实现：DeviceDeck（18 张卡片 + 5 项体检 连/定/电/任/安）、DeviceDetailPanel 下钻、RightColumn（集群协同拓扑 20 节点、设备类型分布、实时告警、系统概览），均数据驱动。",
       "维持；告警改为真实告警引擎数据。", "")
    fp(doc, "F5 双端实时数据层", "已实现",
       "已实现：packages/api-client（REST + WS 客户端），订阅 Redis 转发通道，store（pmStore/omStore）驱动 UI。",
       "维持；增加断线重连与心跳保活。", "")
    fp(doc, "F6 三视图切换（调度/能耗/安全）", "部分实现",
       "已实现：顶部标签页（调度/能耗/安全）。"
       "待选型：视图切换即切换同一 WS 数据的聚合维度（能耗=电量/充能分布；安全=围栏/越界/急停状态）。",
       "1) 后端补充能耗视图、安全视图聚合接口；2) 前端按 tab 切换数据源与图层。",
       "当前仅标签，未切换底层数据。")
    fp(doc, "F7 摄像头 AI 识别真实源", "未实现",
       "待选型：摄像头 RTSP/WebRTC 拉流 + 视觉模型推理（或后端 CameraDetection 真实写入），前端 CCTV 组件叠加 AI 浮窗。",
       "1) 接入真实摄像头流；2) 推理结果写入 CameraDetection；3) 前端浮窗读取最新识别。",
       "当前为 runtime 定时仿真写入。")
    fp(doc, "F8 历史轨迹 / 告警回放", "未实现",
       "待选型：基于 DeviceEvent 时序做轨迹/告警时间轴回放（前端时间轴 + 后端区间查询）。",
       "1) 后端区间查询接口；2) 前端时间轴控件驱动 3D/卡片回放。", "")

    # ---------- 维度三：数据库 ----------
    h1(doc, "维度三：数据库")
    para(doc, "现状底座：PostgreSQL（生产）+ 异步 SQLAlchemy；Redis（发布订阅 + 设备状态缓存）。", bold=True)
    fp(doc, "D1 关系数据模型", "已实现",
       "已实现：10 张表（User/Device/Task/Script/Alert/MapRegion/MapPoint/Camera/CameraDetection/DeviceEvent），UUID 主键、JSONB 扩展字段、外键关联、派生指标实时计算不冗余存储。",
       "维持；随模块演进补充字段（如维保工单、围栏）。", "")
    fp(doc, "D2 实时缓存与发布订阅", "已实现",
       "已实现：Redis 7 通道（ws:broadcast:*）发布订阅，设备状态 setex 5s 缓存；WS 网关订阅 Redis 推前端。",
       "维持；增加频道鉴权与消息大小限制。", "")
    fp(doc, "D3 时序数据存储", "部分实现",
       "已实现：DeviceEvent 以（time, device_id）复合主键落库，承载遥测/状态/任务/环境事件。"
       "待选型：高并发下改用 TimescaleDB 超表（或 PostgreSQL 分区表 + 降采样），保证回放与聚合性能。",
       "1) 评估 TimescaleDB；2) 建超表/分区；3) 聚合查询下推。",
       "当前为普通表，规划称“时序库”。")
    fp(doc, "D4 数据库迁移", "未实现",
       "待选型：Alembic 管理版本化迁移（生产禁用 create_all）。",
       "1) 初始化 Alembic；2) 由当前模型生成首版迁移；3) 纳入 CI，模型变更必出迁移。",
       "当前生产靠 debug 模式 create_all，风险高——P1。")
    fp(doc, "D5 备份与高可用", "未实现",
       "待选型：PostgreSQL 定时逻辑备份（pg_dump / WAL 归档）+ Redis AOF 持久化；可选读写分离。",
       "1) 备份脚本 + 定时任务；2) 容灾演练。", "")

    # ---------- 维度四：机器人（本体系统搭建 + 功能自研） ----------
    h1(doc, "维度四：机器人（本体系统搭建与功能自研）")
    para(doc, "定位澄清：我方不生产机器人硬件“零部件”，但需要——(1) 选型采购部件与系统，"
              "在微缩沙盘尺度上搭建整机；(2) 自研机器人本体的全部智能功能（视觉识别、点云建图、定位、"
              "路径规划、导航移动、避障、多机碰撞预测与避让、作业执行等）；(3) 通过标准接口把机器人接入调度大脑。"
              "因此本维度分两部分：A 整机搭建选型，B 本体功能自研技术路线。", bold=True)
    para(doc, "总体软件底座：Ubuntu 22.04 + ROS2 Humble（DDS 通信、多智能体节点组织），MCU 侧用 micro-ROS 打通；"
              "感知/AI 在边缘计算单元（Jetson）上跑，运动控制在 MCU 上跑，二者经 micro-ROS/串口桥接。"
              "云-机分工原则：全局派单与工序约束在云端（后端调度大脑），本体感知/定位/局部规划/避障/作业执行在机端自治，"
              "断网时机端可完成“最后一段”安全动作。", italic=True, size=9.5, color=GREY)

    # ── A 整机搭建选型 ──
    h2(doc, "A. 机器人整机搭建选型（微缩沙盘尺度）")
    para(doc, "沙盘为微缩工地，机器人为小型化整机（分米级）。按“计算 / 运动 / 感知 / 执行 / 通信 / 供电”六大子系统选型，"
              "五类机型（AGV 运输车、土方/挖掘机器人、吊装机器人、砌筑机器人、巡检机器人）共用主控与软件栈，差异在底盘与末端执行机构。")
    table(doc,
          ["子系统", "选型方向", "推荐器件（沙盘尺度）", "选择理由"],
          [
              ["主控计算单元", "边缘 AI 计算 + ROS2 主节点",
               "NVIDIA Jetson Orin Nano / NX（跑视觉+SLAM）",
               "GPU 算力支撑 YOLO 推理与点云处理，原生 Ubuntu+ROS2，功耗适合车载"],
              ["运动控制 MCU", "实时电机/舵机控制",
               "STM32F4 / ESP32（micro-ROS）",
               "硬实时闭环控制，与 Jetson 分层解耦；micro-ROS 无缝接入 ROS2"],
              ["底盘运动", "差速 / 麦克纳姆 / 履带",
               "AGV=麦克纳姆全向轮；土方=履带；巡检=差速",
               "全向便于窄道对位，履带贴合土方越障，差速结构简单"],
              ["激光雷达", "点云建图与 SLAM",
               "2D：RPLIDAR A1/A2；3D：Livox Mid-360 固态",
               "2D 满足平面 SLAM 低成本，3D 固态雷达提供稠密点云做三维建图"],
              ["深度/彩色相机", "视觉识别 + 障碍感知",
               "Intel RealSense D435i / Orbbec Astra",
               "RGB-D 同时给视觉识别与近距障碍深度，内置 IMU 便于视觉惯性里程计"],
              ["定位辅助", "IMU + 轮式里程计 + 二维码",
               "9 轴 IMU + 电机编码器 + 下视相机读 ArUco/二维码",
               "多源融合（EKF）提升沙盘尺度定位精度，二维码提供绝对位置校正"],
              ["执行机构", "作业末端",
               "舵机机械臂/铲斗/夹爪/吊钩（按机型）",
               "沙盘尺度用舵机即可完成挖/吊/砌/夹动作，MCU 直控"],
              ["通信", "无线组网",
               "WiFi6 车载模块（ROS2 DDS over WiFi）",
               "满足 20–100 台并发遥测与指令下发，DDS 自动发现"],
              ["供电与充电", "锂电 + 自主回充",
               "锂电池 + 接触式/无线充电桩 + 电量计",
               "支撑长时演示，配合能耗模块做错峰自主回充"],
          ],
          widths=[1.1, 1.5, 2.1, 2.1])
    para(doc, "整机软件分层：Jetson（ROS2：感知/定位/建图/规划/导航/避障/接入节点）── micro-ROS ──"
              " MCU（电机闭环、舵机作业、硬件急停继电器）。这样“想（AI）”与“动（实时控制）”解耦，任一层可独立调试。",
         size=9.5, color=GREY, italic=True)

    # ── B 本体功能自研 ──
    h2(doc, "B. 机器人本体功能自研技术路线")
    para(doc, "以下 11 个功能点覆盖方案要求的全部机器人本体能力，逐个给出：功能定义 / 云-机分工 / 技术选型 / 技术路线 / 依赖部件。", bold=True)

    rfp(doc, "R1 环境感知与视觉识别", "未实现",
        "识别沙盘环境中的目标：施工点位标志、物料、障碍物、人员（微缩模型/标记）、二维码路标，输出类别+位置，供导航与作业与后端摄像头 AI 浮窗使用。",
        "机端：相机采集+目标检测推理，输出检测结果上报；云端：汇总识别结果驱动 PM 端 CCTV AI 浮窗（挖机数/渣土车数/人员数/合规率）。",
        "目标检测 YOLOv8/v10（TensorRT 加速）；二维码/基准标 ArUco/AprilTag（OpenCV）；语义分割可选（作业面识别用 segmentation）。",
        "1) 采集沙盘图像做小样本数据集并标注；2) 训练/微调 YOLO 识别本项目类别；3) Jetson 上 TensorRT 量化部署为 ROS2 感知节点，发布 /detections；4) 二维码识别节点发布位姿校正；5) 检测结果经接入层上报后端写 CameraDetection。",
        "RealSense/Orbbec 相机 + Jetson GPU。")

    rfp(doc, "R2 点云建图（SLAM 建图）", "未实现",
        "用激光雷达/深度相机扫描沙盘，构建工地三维/二维栅格地图与点云，作为路径规划与数字孪生大屏的空间底座；随施工进度做版本快照。",
        "机端：实时 SLAM 建图与定位（前端里程计+后端优化）；云端：接收/融合各机地图、做全局地图版本管理，推送大屏渲染。",
        "3D：LIO-SAM / FAST-LIO2（激光惯性里程计）或 RTAB-Map（RGB-D）；2D：Cartographer / slam_toolbox；点云处理 PCL；回环检测降漂移。",
        "1) 传感器标定（雷达-IMU-相机外参）；2) 机端跑 FAST-LIO2 输出实时点云与位姿；3) 回环+位姿图优化生成一致地图；4) 点云降采样（体素滤波）后经 ROS2/后端推大屏；5) 按施工阶段保存地图快照对接后端地图版本。",
        "3D 固态雷达 Livox / 2D RPLIDAR + IMU + Jetson。")

    rfp(doc, "R3 定位（SLAM / 二维码融合）", "部分实现",
        "在已知地图内实时估计每台机器人的位姿（x,y,θ），为导航、避障、多机协同提供统一坐标；方案指定 SLAM/二维码定位。",
        "机端：多源传感器融合实时定位；云端：接收位姿聚合为全局态势（3D 大屏红点/名牌来源）。",
        "AMCL（粒子滤波，2D）或 SLAM 里程计（3D）；EKF 融合（robot_localization 包）IMU+轮速+视觉里程计；二维码/AprilTag 做绝对位置校正消除累积漂移。",
        "1) 部署 robot_localization EKF 融合 odom+IMU+视觉；2) 地面/立柱铺设二维码路标，下视相机检测做绝对校正；3) 输出 /odom→/map 的 TF；4) 位姿经接入层上报后端（当前仿真已产出位姿，替换为真实源）。",
        "IMU + 编码器 + 下视相机 + 雷达。")

    rfp(doc, "R4 路径规划（全局）", "未实现",
        "在地图上为“当前位置→任务点位”规划一条无碰撞、代价最优的全局路径，支撑方案“路径规划与避碰”。",
        "云端：可做跨设备的全局路由与工序约束（避免多机抢道）；机端：Nav2 全局规划器算本车最优路径。二者可协同（云给航点，机算细路径）。",
        "Nav2 全局规划器：A* / Dijkstra / Hybrid-A*（考虑车体转弯半径）；代价地图 costmap_2d（静态层+膨胀层）；多机层面用时间窗/优先级路由避免冲突。",
        "1) 由 R2 地图生成 costmap；2) 配置 Nav2 global_planner（差速用 NavFn/Smac，阿克曼用 Hybrid-A*）；3) 接收后端派单目标点位求全局路径；4) 全局路径与云端多机路由校验，冲突则重规划。",
        "地图（R2）+ Jetson（Nav2）。")

    rfp(doc, "R5 导航移动（局部规划与运动控制）", "部分实现",
        "驱动机器人沿全局路径实际行驶到目标点，实时跟踪路径、控制底盘速度与转向，完成“接单→到位”。",
        "机端全自治：局部规划+底盘运动学控制；云端只下发目标与监控进度。",
        "Nav2 局部规划器 DWB / TEB（Timed-Elastic-Band，适合狭窄沙盘）；底盘差速/全向运动学解算；micro-ROS 下发 PWM 到电机闭环（PID）。",
        "1) 配置 Nav2 controller（TEB 参数按沙盘尺度整定）；2) 局部规划器输出 /cmd_vel；3) 运动控制节点做运动学逆解→轮速；4) micro-ROS 传 MCU 做电机 PID 闭环；5) 到位判定回传 task_event（对接后端调度完工闭环）。",
        "底盘电机+编码器+MCU+Jetson。")

    rfp(doc, "R6 避障（动态避障）", "未实现",
        "行驶中实时发现并绕开地图上没有的动态/临时障碍（人员模型、临时堆放、其他机器人），保证不碰撞，支撑方案“动态障碍识别”。",
        "机端实时自治（毫秒级反应）；越障事件上报云端告警。",
        "costmap 动态障碍层（障碍点云/深度实时写入）+ 膨胀层；局部规划器 TEB/DWB 在动态代价图上实时重规划；近距紧急停障用深度相机/雷达阈值触发。",
        "1) 障碍感知节点把雷达/深度点云写入 costmap obstacle 层；2) 局部规划器基于更新后代价图实时避让；3) 设最小安全距离，突现障碍触发紧急减速/停车；4) 频繁受阻则请求全局重规划并上报告警。",
        "雷达 + 深度相机 + Jetson。")

    rfp(doc, "R7 路线碰撞预测与多机避让", "未实现",
        "预测多台机器人未来轨迹，提前发现潜在碰撞/拥堵并协商避让（谁让谁、谁减速），实现方案“集群碰撞联锁 + 多机不打架”。",
        "机端：实时交换位姿、执行联锁减速/停车；云端：全局层面做时空冲突预测与优先级仲裁（分布式协商+集中式兜底）。",
        "多机位姿共享（ROS2 DDS / 后端广播）；时空轨迹预测（恒速/多项式外推）；冲突消解=优先级让行 + 预约式路口（时间窗）+ 安全距离联锁；后端 services/interlock.py 做集中兜底。",
        "1) 各机周期广播位姿+意图轨迹；2) 预测未来 N 秒轨迹，算最近距离；3) 小于安全阈值→按优先级（土方>转运>巡检）让行/减速；4) 后端 interlock 服务消费位姿流做全局距离矩阵，分级降速/停车并广播联锁事件；5) 接入 device_safety_distance 配置（当前定义未引用，P0）。",
        "位姿共享链路 + 后端 interlock + 各机运动控制。")

    rfp(doc, "R8 作业执行（施工动作）", "部分实现",
        "到达点位后执行本机型的施工动作：挖掘/装土、吊装、砌筑、夹取转运、巡检拍摄，并量化进度回传（对接 completed_qty/deliverable_qty）。",
        "机端：末端执行机构动作序列控制；云端：下发作业参数、按进度解锁 DAG 下游工序。",
        "动作序列状态机（接单→对位→作业→完成）；末端舵机/步进闭环（MCU）；作业进度按动作节拍或视觉确认量化；ROS2 action 做长任务反馈。",
        "1) 为每机型定义作业动作序列；2) MCU 控制舵机臂/铲斗/吊钩执行；3) 视觉/行程开关确认作业完成；4) 进度经遥测回传后端 tasks 表（复用现有 completed_qty 逻辑）。",
        "舵机执行机构 + MCU + 相机确认。")

    rfp(doc, "R9 设备接入与遥测（对接调度大脑）", "部分实现",
        "把机器人接入后端调度系统：注册一机一档、周期上报心跳/位姿/电量/状态、接收并应答（ACK/NACK）派单与控制指令。",
        "机端：接入节点做协议转换与上报；云端：Ros2Adapter/MqttAdapter 接收，写设备注册表与 device_events。",
        "接入层适配器模式（DeviceAdapter 抽象已在）：真实用 Ros2Adapter（rclpy 订阅 /device_state、发 /cmd）+ MqttAdapter（aiomqtt）；统一 JSON 接入契约。",
        "1) 定义统一 JSON 契约（注册/心跳/遥测/指令/任务事件/告警）+ JSON Schema；2) 机端接入节点按契约上报；3) 后端实现 Ros2Adapter/MqttAdapter 替换 SimulatedAdapter；4) 心跳超时判离线并写 Alert；5) 指令 ACK 超时重传。",
        "WiFi + Jetson 接入节点 + 后端适配器。")

    rfp(doc, "R10 本体安全响应（急停 / 电子围栏 / 人机避让）", "部分实现",
        "机器人本体的安全兜底：接收全局急停立即停机、越出电子围栏自动停、检测到人员/危险区降速停机。",
        "机端：硬件+软件双通道急停、本地围栏与人机距离判定；云端：全局急停广播、围栏配置下发、越界事件汇总告警。",
        "硬件急停继电器（MCU 直断电机，不依赖软件）+ 软件急停（ROS2 广播）；电子围栏本地校验（点在多边形/射线法）；人机避让基于视觉识别+深度距离触发降速停车。",
        "1) MCU 集成硬件急停继电器（收到 estop 或断连即断电）；2) 软件急停订阅后端广播（现有 CHANNEL_ESTOP）；3) 机端加载围栏多边形，越界即停并上报；4) R1 识别人员→按距离分级降速/停机；5) 后端 geofence 派单前拦截配合。",
        "急停继电器 + MCU + 相机/雷达 + Jetson。")

    rfp(doc, "R11 本体能耗与自主回充", "部分实现",
        "监测本机电量与能耗，低电量时自主导航回充电桩充电，配合云端错峰充能调度，保障长时演示不断电。",
        "机端：电量监测+自主回充导航；云端：错峰充能排程（空闲/低优间隙调度）与续航预测。",
        "电量计采样；低电量阈值触发回充状态；回充导航复用 R4/R5（目标=充电桩点位）；对接式/无线充电对位用二维码精定位。",
        "1) MCU 采电压/电流估算 SOC 上报；2) 低于阈值切回充状态请求充电桩点位；3) 导航到桩用二维码精对位；4) 充满恢复待命；5) 后端能耗模块做错峰排程与续航预测（当前仅仿真电量，待补真实模型）。",
        "电量计 + 充电桩 + 二维码 + 底盘导航。")

    para(doc, "云-机能力边界一句话：后端调度大脑负责“派谁去、按什么工序、全局别撞”；机器人本体负责“看得懂、定得准、走得到、"
              "躲得开、干得成、停得下”。二者经统一 JSON 接入契约（R9）解耦。", bold=True, color=ACCENT)

    # 路线总结
    h1(doc, "技术路线总览（里程碑）")
    para(doc, "里程碑对齐方案第八章 M1–M5，并显式纳入机器人本体自研主线（整机搭建 → 单机自治 → 多机协同）。", size=9.5, color=GREY, italic=True)
    table(doc,
          ["里程碑", "目标", "云端关键交付", "机器人本体关键交付"],
          [
              ["M1 接入与地图", "单机可接入、地图可建",
               "Ros2Adapter/MQTT + 协议契约 + 一机一档 + 地图服务",
               "整机搭建（Jetson+MCU+传感器）+ SLAM 点云建图(R2) + 定位(R3)"],
              ["M2 调度内核", "单机能自主到位、大屏有真实数据",
               "调度引擎 + 告警引擎 + 实时遥测/位姿",
               "视觉识别(R1) + 全局路径规划(R4) + 导航移动(R5) + 接入遥测(R9)"],
              ["M3 协同与安全", "多机不打架、安全可控",
               "碰撞联锁 interlock + 电子围栏拦截 + 分区管控",
               "动态避障(R6) + 多机碰撞预测避让(R7) + 本体安全响应(R10)"],
              ["M4 作业与能耗", "能真正干活、可持续演示",
               "人工干预 API + 分布式协商 + 能耗错峰 + 维保",
               "作业执行(R8) + 自主回充(R11)"],
              ["M5 联调演示", "系统可演示、可维护、可汇报",
               "Alembic 迁移 + 时序库 + 报表导出 + 历史回放",
               "整机稳定性联调 + 演示剧本适配 + 全套文档"],
          ],
          widths=[1.2, 1.5, 2.1, 2.2])
    doc.save("技术方案总览_功能维度_技术选型_技术路线.docx")
    print("saved 技术方案总览_功能维度_技术选型_技术路线.docx")


if __name__ == "__main__":
    build_comparison()
    build_techplan()
