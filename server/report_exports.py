"""Role-gated pharmacy report PDF formatting; no files stored on the server."""
from datetime import datetime, timezone
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether

INK = colors.HexColor("#16352C")
LIGHT = colors.HexColor("#EAF1ED")

def _money(n):
    return "PHP {:,.2f}".format(float(n or 0))

def _paragraph(value, style):
    return Paragraph(escape(str(value if value is not None else "")), style)

def _styles():
    s = getSampleStyleSheet()
    s.add(ParagraphStyle(name="P360Title", parent=s["Heading1"], fontSize=18, leading=22, textColor=INK, spaceAfter=12))
    s.add(ParagraphStyle(name="P360Body", parent=s["Normal"], fontSize=8, leading=11))
    s.add(ParagraphStyle(name="P360Small", parent=s["Normal"], fontSize=7, leading=9))
    return s

def _build(title, description, metrics, headers, records, landscape_page=False, extra=None):
    s = _styles()
    buf = BytesIO()
    page = landscape(A4) if landscape_page else A4
    doc = SimpleDocTemplate(buf, pagesize=page, leftMargin=32, rightMargin=32, topMargin=32, bottomMargin=36, title=title)
    story = [_paragraph(title, s["P360Title"]), _paragraph(description, s["P360Body"]), Spacer(1, 15)]
    if metrics:
        metric_rows = [[_paragraph(label, s["P360Body"]), _paragraph(value, s["P360Body"])] for label, value in metrics]
        mt = Table(metric_rows, colWidths=[210, 180], hAlign="LEFT")
        mt.setStyle(TableStyle([("BACKGROUND", (0,0),(-1,-1), LIGHT), ("BOTTOMPADDING", (0,0),(-1,-1), 8), ("TOPPADDING", (0,0),(-1,-1), 8), ("LINEBELOW",(0,0),(-1,-2),0.25,colors.lightgrey)]))
        story.extend([mt, Spacer(1,20)])
    if records:
        available = page[0]-64
        widths = [available/len(headers)]*len(headers)
        table_data = [[_paragraph(x, s["P360Small"]) for x in headers]]
        table_data += [[_paragraph(x, s["P360Small"]) for x in row] for row in records]
        tbl = Table(table_data, colWidths=widths, repeatRows=1, hAlign="LEFT")
        tbl.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),INK),("TEXTCOLOR",(0,0),(-1,0),colors.white),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white, LIGHT]),("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
        # Header text is contained in Paragraphs, so define an alternate white header style.
        for col, head in enumerate(headers):
            tbl._cellvalues[0][col] = Paragraph(escape(str(head)), ParagraphStyle(name=f"Header_{col}", parent=s["P360Small"], textColor=colors.white, fontName="Helvetica-Bold"))
        story.append(tbl)
    else:
        story.append(_paragraph("No records for this period.", s["P360Body"]))
    if extra:
        story.append(Spacer(1, 22))
        story.append(_paragraph("Batches and expiration", s["Heading2"]))
        extra_headers = ["Medicine", "Branch", "Batch", "Expiration", "Remaining"]
        extra_width = [available/5]*5
        batch_rows = [[_paragraph(x, s["P360Small"]) for x in row] for row in extra]
        header_style = ParagraphStyle(name="ExtraHeader", parent=s["P360Small"], textColor=colors.white, fontName="Helvetica-Bold")
        batch_table = Table([[ _paragraph(x, header_style) for x in extra_headers]] + batch_rows,
                            colWidths=extra_width, repeatRows=1, hAlign="LEFT")
        batch_table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),INK),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,LIGHT]),("VALIGN",(0,0),(-1,-1),"TOP"),
            ("TOPPADDING",(0,0),(-1,-1),7),("BOTTOMPADDING",(0,0),(-1,-1),7)]))
        story.append(batch_table)
    def footer(canvas, doc):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#687C72"))
        canvas.drawString(32, 20, "Pharmacy360  |  Generated " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"))
        canvas.drawRightString(page[0]-32,20,f"Page {doc.page}")
    doc.build(story, onFirstPage=footer,onLaterPages=footer)
    return buf.getvalue()

def financial_pdf(data):
    metrics = [("Sales income",_money(data.get("income"))), ("Cost of goods sold",_money(data.get("cogs"))),
      ("Gross profit",_money(data.get("grossProfit"))), ("Stock purchases",_money(data.get("stockPurchases"))),
      ("Operating expenses",_money(data.get("operatingExpenses"))), ("Employee wages",_money(data.get("wages"))),
      ("Cash outflow",_money(data.get("cashOutflow"))), ("Operating result",_money(data.get("operatingResult"))),
      ("Paid sales", str(data.get("salesCount",0)))]
    orders = [[r.get("order_number",""), str(r.get("created_at", ""))[:16], r.get("status",""),
      r.get("payment_status",""), _money(r.get("total_amount"))] for r in data.get("orders", [])]
    return _build("Financial Report", f"{str(data.get('period', '')).title()} period  |  {data.get('referenceDate', '')}  |  Recent orders (up to 20)",
        metrics, ["Order", "Date", "Status", "Payment", "Total"],orders)

def inventory_pdf(data):
    inv = data.get("inventory", [])
    batches = data.get("batches", [])
    low = sum(1 for i in inv if int(i.get("on_hand") or 0)-int(i.get("reserved") or 0)<=int(i.get("reorder_level") or 0))
    records = [[i.get("product",{}).get("name") if isinstance(i.get("product"),dict) else i.get("product_id", ""),
      i.get("branch",{}).get("name") if isinstance(i.get("branch"),dict) else "",
      str(i.get("on_hand",0)),str(i.get("reserved",0)),
      str(int(i.get("on_hand") or 0)-int(i.get("reserved") or 0)),str(i.get("reorder_level",0))] for i in inv]
    batch_rows = [[b.get("product", {}).get("name", "") if isinstance(b.get("product"), dict) else str(b.get("product_id", "")),
      b.get("branch", {}).get("name", "") if isinstance(b.get("branch"), dict) else "",
      str(b.get("batch_number") or ""),str(b.get("expiration_date") or "No expiry"),
      str(b.get("quantity_remaining", 0))] for b in batches]
    return _build("Branch Inventory Report", "Current inventory by branch. Generated on demand.",
      [("Stock records",str(len(inv))),("Low stock records",str(low)),("Tracked batches",str(len(batches)))],
      ["Medicine","Branch","On hand","Reserved","Available","Reorder at"],records,landscape_page=True,
      extra=batch_rows)
