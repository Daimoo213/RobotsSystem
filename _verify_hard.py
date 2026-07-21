# -*- coding: utf-8 -*-
from docx import Document
doc = Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
spec = "\n".join(c.text for row in doc.tables[0].rows for c in row.cells)
softs = ["推荐", "建议", "可选", "可省去", "（IR）可选"]
print("=== soft-language scan (should all be OK/no) ===")
for s in softs:
    print(("FAIL " if s in spec else "OK   no ") + repr(s))
print("\n=== hard-indicator presence (should all be OK) ===")
checks = {
    "GPU显存>=12GB": "显存 ≥ 12GB" in spec,
    "摄像头>=3840x2160": "≥ 3840×2160" in spec,
    "夜视硬要求": "支持夜视（IR）" in spec,
    "特写可选已删": ("另增 1–2 台沙盘特写" not in spec) and ("可选：" not in spec),
    "NVR可选已删": "（可选）" not in spec,
    "PoE>=240W_参数": "整机 PoE 输出功率 ≥ 240W" in spec,
    "PoE>=240W_▲2": "整机 ≥ 240W" in spec,
    "AP带载硬": "单 AP 实际带载 ≤ 12 台机器人" in spec,
    "机柜不配配线架": "不配置独立配线架" in spec,
    "无210W残留": "≥ 210W" not in spec,
    "大屏>=3840x2160": "分辨率 ≥ 3840×2160" in spec,
}
allok = True
for k, v in checks.items():
    if not v:
        allok = False
    print(("OK " if v else "FAIL ") + k)
print("\nALL HARD-INDICATOR CHECKS PASS" if allok else "\nSOME FAILED")
