import os
from datetime import datetime
from config import Config
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable

def generate_pdf_invoice(booking, invoice):
    """
    Generates a professional PDF invoice using ReportLab and returns the file path.
    """
    os.makedirs(Config.INVOICE_FOLDER, exist_ok=True)
    filename = f"{invoice.invoice_number}.pdf"
    pdf_path = os.path.join(Config.INVOICE_FOLDER, filename)
    
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    
    story = []
    styles = getSampleStyleSheet()
    
    # Custom styles
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=24,
        leading=28,
        textColor=colors.HexColor('#0f172a')
    )
    
    subtitle_style = ParagraphStyle(
        'InvoiceSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#64748b')
    )
    
    header_right_style = ParagraphStyle(
        'HeaderRight',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=14,
        leading=18,
        alignment=2, # Right align
        textColor=colors.HexColor('#2563eb')
    )
    
    normal_style = ParagraphStyle(
        'InvoiceNormal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#334155')
    )
    
    bold_style = ParagraphStyle(
        'InvoiceBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#0f172a')
    )
    
    # Header Table
    header_data = [
        [
            Paragraph("<b>SMARTPARK</b><br/><font size=9 color='#64748b'>AI-Powered Smart Parking Management System</font>", title_style),
            Paragraph(f"INVOICE<br/><font size=10 color='#64748b'>#{invoice.invoice_number}</font>", header_right_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[350, 190])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    story.append(header_table)
    story.append(Spacer(1, 15))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#e2e8f0'), spaceAfter=15))
    
    # Details Grid (Bill To & Booking Overview)
    details_data = [
        [
            Paragraph("<b>CUSTOMER DETAILS</b>", bold_style),
            Paragraph("<b>PARKING DETAILS</b>", bold_style)
        ],
        [
            Paragraph(f"""
            <b>Name:</b> {booking.user.full_name}<br/>
            <b>Email:</b> {booking.user.email}<br/>
            <b>Mobile:</b> {booking.user.phone or 'N/A'}<br/>
            <b>Vehicle No:</b> {booking.vehicle.vehicle_number}<br/>
            <b>Vehicle Type:</b> {booking.vehicle.vehicle_type} ({booking.vehicle.model or ''})
            """, normal_style),
            Paragraph(f"""
            <b>Booking Ref:</b> {booking.booking_reference}<br/>
            <b>Location:</b> {booking.location.name}<br/>
            <b>Address:</b> {booking.location.address}<br/>
            <b>Slot Assigned:</b> <font color='#2563eb'><b>{booking.slot.slot_number}</b></font><br/>
            <b>Date:</b> {booking.start_time.strftime('%b %d, %Y')}<br/>
            <b>Gate Entry:</b> {booking.entry_time.strftime('%I:%M:%S %p') if booking.entry_time else 'N/A'}<br/>
            <b>Gate Exit:</b> {booking.exit_time.strftime('%I:%M:%S %p') if booking.exit_time else 'Active'}
            """, normal_style)
        ]
    ]
    
    details_table = Table(details_data, colWidths=[270, 270])
    details_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('PADDING', (0,0), (-1,-1), 10),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(details_table)
    story.append(Spacer(1, 20))
    
    # Line Item Table
    items_header = [
        Paragraph("<b>Description</b>", bold_style),
        Paragraph("<b>Start Time</b>", bold_style),
        Paragraph("<b>End Time</b>", bold_style),
        Paragraph("<b>Duration</b>", bold_style),
        Paragraph("<b>Rate/Hr</b>", bold_style),
        Paragraph("<b>Amount</b>", bold_style)
    ]
    
    items_row = [
        Paragraph(f"Parking Reservation - {booking.slot.slot_number}", normal_style),
        Paragraph(booking.start_time.strftime('%I:%M %p'), normal_style),
        Paragraph(booking.end_time.strftime('%I:%M %p'), normal_style),
        Paragraph(f"{booking.duration_hours} hrs", normal_style),
        Paragraph(f"₹{booking.hourly_rate:.2f}", normal_style),
        Paragraph(f"₹{invoice.subtotal:.2f}", bold_style)
    ]
    
    items_data = [items_header, items_row]
    items_table = Table(items_data, colWidths=[150, 75, 75, 70, 80, 90])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#1e293b')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('ALIGN', (3,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('PADDING', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 15))
    
    # Summary Table
    summary_data = [
        [Paragraph("Subtotal:", normal_style), Paragraph(f"₹{invoice.subtotal:.2f}", normal_style)],
        [Paragraph("Taxes & Fees:", normal_style), Paragraph(f"₹{invoice.tax:.2f}", normal_style)],
        [Paragraph("<b>TOTAL AMOUNT:</b>", bold_style), Paragraph(f"<b>₹{invoice.total_amount:.2f}</b>", ParagraphStyle('GreenText', parent=bold_style, textColor=colors.HexColor('#059669'), fontSize=12))],
        [Paragraph("Payment Status:", normal_style), Paragraph(f"<b>{invoice.payment_status}</b>", ParagraphStyle('StatusText', parent=bold_style, textColor=colors.HexColor('#d97706')))]
    ]
    summary_table = Table(summary_data, colWidths=[400, 140])
    summary_table.setStyle(TableStyle([
        ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
        ('PADDING', (0,0), (-1,-1), 4),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 30))
    
    # Footer Notice
    footer_text = Paragraph("""
    <font color='#64748b' size=8>
    <b>Terms & Conditions:</b> Please present this invoice or show your digital booking reference (QR code) at the parking entry gate. 
    Cancellation policy applies. Generated automatically by SmartPark Platform. Contact support@smartpark.com for queries.
    </font>
    """, normal_style)
    story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#cbd5e1'), spaceAfter=10))
    story.append(footer_text)
    
    doc.build(story)
    
    # Save relative path in database
    invoice.pdf_path = f"/static/uploads/invoices/{filename}"
    return pdf_path
