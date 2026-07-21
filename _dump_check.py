# -*- coding: utf-8 -*-
from docx import Document
doc = Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
lines = []
for p in doc.paragraphs:
    if p.text.strip():
        lines.append(p.text)
t = doc.tables[0]
for row in t.rows:
    for c in row.cells:
        if c.text.strip():
            lines.append(c.text)
full = "\n".join(lines)
# check for doubled-character artifacts
patterns = ["渲染渲染", "工作站站", "））", "且且", "实时时", "OSPFF", "2.5G G",
            "冗余余", "；；", "余量量", "扩展余量量", "留1口冗余余", "关键使能项项"]
print("== doubled-char scan ==")
found_any = False
for pat in patterns:
    if pat in full:
        found_any = True
        print("FOUND:", pat)
if not found_any:
    print("NONE of the 12 reported artifacts present in docx.")
# also dump a few suspicious lines verbatim
print("\n== verbatim check of suspected lines ==")
for seg in ["点云渲", "工作站", "对接）", "且相邻", "实时呈现", "OSPF", "2.5G SFP", "留 1 口冗余", "切换区", "覆盖与冗余", "扩展余量"]:
    idx = full.find(seg)
    if idx >= 0:
        print(repr(full[idx:idx+24]))
