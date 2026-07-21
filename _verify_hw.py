# -*- coding: utf-8 -*-
from docx import Document
doc = Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
spec = "\n".join(c.text for row in doc.tables[0].rows for c in row.cells)

# 1) 不应出现的"功能/场景"措辞
forbidden = ["调度引擎","DAG","PostgreSQL","Redis","遥测","渲染","点云","双 4K","4K 大屏",
             "沙盘","机器人","VLAN","QoS","漫游","时延","录像","回放","AI 识别","跨镜头",
             "无盲区","演示","场景","RTSP 拉流","对接大屏","大屏实时","控制网","急停",
             "≥ 30 台","三维","WebGL","CUDA","微缩","轨迹","融合","GSMA"]
hits = [w for w in forbidden if w in spec]
print("FORBIDDEN-TERM HITS:", hits if hits else "NONE")

# 2) 基础下限硬指标应存在
required = ["≥ 4 物理核心","≥ 16GB DDR4",">= 16GB","显存 ≥ 4GB","≥ 1920×1080",
            "≥ 1/2.8","CMOS","2.8mm","RJ45","H.264","PoE（IEEE 802.3af）","DC 12V",
            "≥ IP66","−10℃","≥ 15.4W","≥ 120W","802.3af","WiFi 6","≥ 24 英寸","IPS",
            "9–12U","Cat6"]
miss = [w for w in required if w not in spec]
print("MISSING HARD-SPEC:", miss if miss else "NONE")

# 3) ▲ 数量与位置（应在编号后文字前）
import re
ast_items = re.findall(r'▲\d+\.\d+', spec)
print("▲ PARAM COUNT:", len(ast_items), ast_items)
# 错误位置：出现 "数字.▲" (▲在编号前) 应为 0
bad_ast = re.findall(r'\d+\.\d+ ▲', spec)
print("BAD ▲ POSITION (▲after space):", bad_ast if bad_ast else "NONE")

# 4) 统一编号 1.1 .. 7.x 是否齐全无跳号
nums = re.findall(r'(?<!▲)(\d+)\.(\d+) ', spec)
from collections import defaultdict
bydev = defaultdict(list)
for d, n in nums:
    bydev[int(d)].append(int(n))
print("DEVICE COUNT:", len(bydev))
for d in sorted(bydev):
    seq = sorted(bydev[d])
    expect = list(range(1, max(seq)+1))
    ok = seq == expect
    print(f"  dev {d}: items={seq} contiguous={ok}")

# 5) 空行：spec 单元格段落数 vs 非空段数，验证有空段
cell = doc.tables[0].rows[2].cells[2]
paras = cell.paragraphs
nonempty = [p for p in paras if p.text.strip()]
print("SPEC paragraphs total:", len(paras), "| nonempty:", len(nonempty),
      "| blank separators:", len(paras)-len(nonempty))

# 6) 无"推荐/建议/可选/可省去"
soft = [w for w in ["推荐","建议","可选","可省去"] if w in spec]
print("SOFT-LANG:", soft if soft else "NONE")
print("\nALL CHECKS DONE")
