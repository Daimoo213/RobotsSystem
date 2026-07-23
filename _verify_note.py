# -*- coding: utf-8 -*-
from docx import Document
doc = Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
paras = [p.text for p in doc.paragraphs]
t = doc.tables[0]
rows_text = ["\n".join(c.text for c in row.cells) for row in t.rows[2:]]

checks = {
 "说明含一次性备注": any("表中各标的参数为基础硬件规格下限" in p for p in paras),
 "行内不再含备注句": not any("以上参数为各设备基础硬件规格下限" in r for r in rows_text),
 "核心产品措辞新": any('本项目核心产品为“调度一体工作站”（对应标的序号 1）' in p for p in paras),
 "温度半角负号": "工作温度范围：-10℃ ~ +50℃" in "\n".join(rows_text),
 "无全角负号U+2212": "−" not in "\n".join(rows_text),
}
for k,v in checks.items(): print(("OK  " if v else "FAIL ")+k)
print("\n说明段落:")
for p in paras:
    if p.startswith("1.") or p.startswith("2.") or p.startswith("说明") or p.startswith("采购预算"):
        print("  ", p)
