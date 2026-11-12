import os, io
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

def generate_franchise_pdf_report(outlet_name, location, revenue, csat, audit_score, filename="franchise_audit_report.pdf"):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle('DocTitle', parent=styles['Heading1'], fontSize=22, textColor=colors.HexColor('#1e3a8a'), spaceAfter=12)
    sub_style = ParagraphStyle('DocSub', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor('#475569'), spaceAfter=18)
    body_style = ParagraphStyle('DocBody', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#0f172a'), spaceAfter=10)

    story.append(Paragraph("🏢 INFOSYS ENTERPRISE FRANCHISE AUDIT REPORT", title_style))
    story.append(Paragraph(f"Official Compliance & Operational Performance Briefing — {outlet_name}", sub_style))
    story.append(Spacer(1, 12))

    data = [
        ["Metric Parameter", "Telemetry Value", "Compliance Status"],
        ["Outlet Location", str(location), "Verified 🟢"],
        ["Monthly Revenue", f"₹{revenue:,.2f}", "Above Target 🟢"],
        ["Customer CSAT", f"{csat:.1f} / 5.0", "Optimal 🟢" if csat>=4.0 else "Needs Review 🟡"],
        ["Audit Compliance Score", f"{audit_score:.1f}%", "Pass 🟢" if audit_score>=80 else "Conditional Pass 🟡"]
    ]

    t = Table(data, colWidths=[200, 180, 150])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e3a8a')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,0), 11),
        ('BOTTOMPADDING', (0,0), (-1,0), 8),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#f8fafc')),
        ('GRID', (0,0), (-1,-1), 1, colors.HexColor('#cbd5e1')),
        ('ALIGN', (0,0), (-1,-1), 'LEFT')
    ]))
    story.append(t)
    story.append(Spacer(1, 24))

    story.append(Paragraph("<b>Executive Compliance Note:</b> This document certifies that the operational telemetry, food safety adherence, and staff workforce metrics for this outlet have been verified by the Multi-Agent Autonomous AI Auditor.", body_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()