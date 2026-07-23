from docx import Document
from docx.oxml.ns import qn
doc=Document(r"D:/MengWork/Web/RobotsSystem/采购需求_基础设施参数（30机器人）.docx")
t=doc.tables[0]
tbl=t._tbl
# count grid cols
grid=t.rows[0].cells
print("grid cols (row0 cells):", len(grid))
for ri,row in enumerate(t.rows):
    cells=row.cells
    print(f"\n=== ROW {ri} cell_count={len(cells)} ===")
    for ci,c in enumerate(cells):
        txt=c.text.strip().replace("\n"," / ")
        print(f"  col{ci}: {txt[:70]}")
# check TC merges via w:vMerge / gridSpan
print("\n===== XML MERGE CHECK =====")
for ri,tr in enumerate(tbl.tr_lst):
    for tc in tr.tc_lst:
        gs=tc.find(qn('w:tcPr')+'')
        gridspan=tc.find('.//'+qn('w:gridSpan'))
        vmerge=tc.find('.//'+qn('w:vMerge'))
        span=gridspan.get(qn('w:val')) if gridspan is not None else None
        vm=vmerge.get(qn('w:val')) if vmerge is not None else ('continue' if vmerge is not None else None)
        if span or vm:
            print(f"ROW{ri}: gridSpan={span} vMerge={vm}")
