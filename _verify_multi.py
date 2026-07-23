# -*- coding: utf-8 -*-
from docx import Document
import re
doc = Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
t = doc.tables[0]
print("rows (incl title+hdr):", len(t.rows), "| cols:", len(t.columns))

# 数据行（跳过 title=row0, header=row1）
data_rows = t.rows[2:]
print("数据行数(标的):", len(data_rows))

# 期望 (序号, 标的名称, 数量, 单位)
expect = [
    ("1", "调度一体工作站（主机 / 显卡 / 存储）", "1", "台"),
    ("2", "显示系统（双屏）", "1", "套"),
    ("3", "监控摄像头系统（实时查看）", "1", "套"),
    ("4", "核心路由器", "1", "台"),
    ("5", "PoE 交换机", "1", "台"),
    ("6", "无线接入点 AP", "3", "台"),
    ("7", "网络机柜及综合布线", "1", "套"),
]
ok = True
for ri, row in enumerate(data_rows):
    cells = [c.text.strip() for c in row.cells]
    seq, name, spec, cnt, unit = cells[0], cells[1], cells[2], cells[3], cells[4]
    exp = expect[ri]
    match = (seq == exp[0] and name == exp[1] and cnt == exp[2] and unit == exp[3])
    if not match:
        ok = False
    print(f"row{ri+1}: seq={seq!r} name={name!r} cnt={cnt!r} unit={unit!r} -> {'OK' if match else 'MISMATCH exp='+str(exp)}")
    # 参数编号是否从 1 起、连续、▲ 在编号前
    nums = re.findall(r'(▲)?(\d+)\.\s', spec)
    param_nums = [int(n) for _, n in nums]
    ast_before = all(a == "▲" for a, _ in nums if a)  # all ▲ are prefix
    contiguous = param_nums == list(range(1, max(param_nums)+1)) if param_nums else False
    print(f"   参数编号: {param_nums} 连续={contiguous} ▲均在编号前={ast_before}")
    # 每行备注条数
    print(f"   投标备注数: {spec.count('（投标时提供')}")

# 功能/场景残留扫描（全表）
full = "\n".join(c.text for row in t.rows for c in row.cells)
bad = [w for w in ["渲染","调度引擎","数据库","遥测","点云","沙盘","VLAN","QoS","漫游","时延","录像","回放","AI 识别","跨镜头","无盲区","演示","场景","RTSP 拉流","对接大屏","控制网","急停","WebGL","CUDA","三维","微缩","轨迹","融合","3840×2160"] if w in full]
print("\n功能/场景/4K残留:", bad if bad else "NONE")
print("\nRESULT:", "ALL PASS" if (ok and not bad) else "CHECK")
