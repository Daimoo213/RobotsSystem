from docx import Document
doc=Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
t=doc.tables[0]
for ri,row in enumerate(t.rows):
    print(f"--- ROW {ri} ---")
    for c in row.cells:
        if c.text.strip(): print(c.text)
