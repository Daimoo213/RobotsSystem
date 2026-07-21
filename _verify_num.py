# -*- coding: utf-8 -*-
from docx import Document
import re
from collections import defaultdict
doc = Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
spec = "\n".join(c.text for row in doc.tables[0].rows for c in row.cells)
nums = re.findall(r'(\d+)\.(\d+) ', spec)
bydev = defaultdict(list)
for d, n in nums:
    bydev[int(d)].append(int(n))
for d in sorted(bydev):
    seq = sorted(bydev[d])
    print(f"dev {d}: {seq} contiguous={seq == list(range(1, max(seq)+1))}")
print("---- sample device 3 (camera) ----")
for line in spec.split("\n"):
    if line.strip().startswith("3."):
        print("  " + line.strip()[:95])
print("---- sample device 1 (workstation) ----")
for line in spec.split("\n"):
    if line.strip().startswith("1."):
        print("  " + line.strip()[:95])
