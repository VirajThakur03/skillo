import hashlib
import hmac
import os
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from flask import current_app

from ..extensions import db
from ..models import Booking


GST_STATE_CODES = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "27": "Maharashtra",
    "29": "Karnataka",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "36": "Telangana",
}


def _state_from_gstin(gstin: str | None) -> str | None:
    gstin = (gstin or "").strip().upper()
    if len(gstin) >= 2 and gstin[:2].isdigit():
        return GST_STATE_CODES.get(gstin[:2], gstin[:2])
    return None

def _get_client():
    import razorpay

    key_id = current_app.config.get("RAZORPAY_KEY_ID") or os.getenv("RAZORPAY_KEY_ID")
    key_secret = current_app.config.get("RAZORPAY_KEY_SECRET") or os.getenv("RAZORPAY_KEY_SECRET")
    if not key_id or not key_secret:
        raise RuntimeError("Razorpay credentials are not configured")
    return razorpay.Client(auth=(key_id, key_secret))


def create_order(amount_paise: int, currency: str, booking_id: str, notes: dict | None = None) -> dict:
    client = _get_client()
    payload = {
        "amount": int(amount_paise),
        "currency": currency,
        "receipt": str(booking_id),
        "payment_capture": 1,
    }
    if notes:
        payload["notes"] = notes
    return client.order.create(payload)


def verify_webhook_signature(payload_body: bytes, razorpay_signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)


def capture_payment(payment_id: str, amount_paise: int) -> dict:
    client = _get_client()
    return client.payment.capture(payment_id, int(amount_paise))


def initiate_refund(payment_id: str, amount_paise: int, reason: str) -> dict:
    client = _get_client()
    return client.payment.refund(
        payment_id,
        {"amount": int(amount_paise), "notes": {"reason": reason}},
    )


def _write_invoice_pdf(invoice_data: dict) -> bytes:
    """Professional PDF generation using ReportLab."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=2*cm, leftMargin=2*cm, topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    
    elements = []

    # Title
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=20,
        textColor=colors.HexColor("#000000")
    )
    elements.append(Paragraph("INVOICE", title_style))

    # Header Info (Company vs Seeker)
    header_data = [
        [
            Paragraph(
                f"<b>From:</b><br/>{invoice_data.get('legal_entity_name', 'Sklio Marketplace')}<br/>{invoice_data.get('legal_entity_address', '')}<br/>GSTIN: {invoice_data.get('platform_gstin', 'N/A')}<br/>SAC: {invoice_data.get('platform_sac_code', '998599')}",
                styles['Normal'],
            ),
            Paragraph(f"<b>To:</b><br/>{invoice_data['seeker_name']}<br/>{invoice_data.get('seeker_email', '')}", styles['Normal'])
        ],
        [
            Paragraph(f"<b>Invoice #:</b> {invoice_data['invoice_number']}", styles['Normal']),
            Paragraph(f"<b>Date:</b> {invoice_data['date']}", styles['Normal'])
        ]
    ]
    header_table = Table(header_data, colWidths=[9*cm, 9*cm])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('BOTTOMPADDING', (0,0), (-1,-1), 10),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 20))

    qr_payload = invoice_data.get("qr_payload")
    if qr_payload:
        try:
            from reportlab.graphics.barcode.qr import QrCodeWidget
            from reportlab.graphics.shapes import Drawing

            qr_code = QrCodeWidget(qr_payload)
            bounds = qr_code.getBounds()
            width = bounds[2] - bounds[0]
            height = bounds[3] - bounds[1]
            drawing = Drawing(90, 90, transform=[90 / width, 0, 0, 90 / height, 0, 0])
            drawing.add(qr_code)
            elements.append(drawing)
            elements.append(Spacer(1, 12))
        except Exception:
            pass

    # Service Detail
    elements.append(Paragraph(f"<b>Service:</b> {invoice_data['service_title']}", styles['Normal']))
    elements.append(Paragraph(f"<b>Provider:</b> {invoice_data['provider_name']}", styles['Normal']))
    if invoice_data.get("provider_gstin"):
        elements.append(Paragraph(f"<b>Provider GSTIN:</b> {invoice_data['provider_gstin']}", styles['Normal']))
    if invoice_data.get("place_of_supply"):
        elements.append(Paragraph(f"<b>Place of Supply:</b> {invoice_data['place_of_supply']}", styles['Normal']))
    if invoice_data.get("tax_mode_label"):
        elements.append(Paragraph(f"<b>Tax Mode:</b> {invoice_data['tax_mode_label']}", styles['Normal']))
    elements.append(Spacer(1, 20))

    # Items Table
    data = [
        ["Description", "Amount (INR)"],
        ["Service Charge", f"{invoice_data['service_amount']:.2f}"],
        ["Platform Fee", f"{invoice_data['platform_fee']:.2f}"],
    ]
    
    # GST Breakdown
    if invoice_data.get('cgst_amount'):
        data.append(["CGST (9%)", f"{invoice_data['cgst_amount']:.2f}"])
    if invoice_data.get('sgst_amount'):
        data.append(["SGST (9%)", f"{invoice_data['sgst_amount']:.2f}"])
    if invoice_data.get('igst_amount'):
        data.append(["IGST (18%)", f"{invoice_data['igst_amount']:.2f}"])
    
    data.append([Paragraph("<b>Total</b>", styles['Normal']), Paragraph(f"<b>{invoice_data['total']:.2f}</b>", styles['Normal'])])

    table = Table(data, colWidths=[13*cm, 4*cm])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#f3f4f6")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -2), 0.5, colors.grey),
        ('LINEBELOW', (0, -1), (-1, -1), 1, colors.black),
        ('TOPPADDING', (0, -1), (-1, -1), 12),
    ]))
    elements.append(table)
    
    # Footer
    elements.append(Spacer(1, 40))
    footer_text = "Thank you for using Sklio! For support, contact help@sklio.in"
    elements.append(Paragraph(footer_text, styles['Italic']))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def generate_pdf_invoice(invoice_data: dict) -> str:
    filename = f"{invoice_data['invoice_number']}.pdf"
    payload = _write_invoice_pdf(invoice_data)
    backend = (current_app.config.get("STORAGE_BACKEND") or "local").lower()

    if backend == "s3":
        import boto3

        bucket = current_app.config.get("S3_BUCKET_NAME") or os.getenv("S3_BUCKET_NAME")
        key = f"invoices/{filename}"
        client = boto3.client(
            "s3",
            aws_access_key_id=current_app.config.get("AWS_ACCESS_KEY_ID") or os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=current_app.config.get("AWS_SECRET_ACCESS_KEY") or os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=current_app.config.get("AWS_REGION") or os.getenv("AWS_REGION", "ap-south-1"),
        )
        client.put_object(Bucket=bucket, Key=key, Body=payload, ContentType="application/pdf")
        return f"https://{bucket}.s3.amazonaws.com/{key}"

    upload_root = Path(current_app.config.get("UPLOAD_FOLDER", "/app/uploads/documents"))
    invoice_dir = upload_root / "invoices"
    invoice_dir.mkdir(parents=True, exist_ok=True)
    file_path = invoice_dir / filename
    file_path.write_bytes(payload)
    return str(file_path.relative_to(upload_root)).replace("\\", "/")


def generate_booking_invoice(booking_id: str) -> str:
    booking = db.session.get(Booking, booking_id)
    if not booking:
        raise ValueError("booking not found")

    service_amount = Decimal(booking.service_amount or booking.price or 0)
    platform_fee_amount = Decimal(booking.platform_fee_amount or 0)
    gst_amount = Decimal(booking.gst_amount or 0)
    total_paid = Decimal(getattr(booking, "amount_payable", None) or booking.price or 0)
    
    invoice_number = booking.invoice_number or f"INV-{str(booking_id).zfill(8)}"
    service_title = "Service"
    if booking.skill:
        service_title = booking.skill.title
    elif getattr(booking, 'job_post', None):
        service_title = booking.job_post.title

    invoice_data = {
        "invoice_number": invoice_number,
        "date": date.today().isoformat(),
        "seeker_name": getattr(booking.seeker, "name", "Customer"),
        "seeker_email": getattr(booking.seeker, "email", ""),
        "provider_name": getattr(booking.provider, "name", "Provider"),
        "service_title": service_title,
        "provider_gstin": getattr(booking.provider, "gstin", None),
        "platform_gstin": current_app.config.get("PLATFORM_GSTIN") or os.getenv("PLATFORM_GSTIN", ""),
        "platform_sac_code": current_app.config.get("PLATFORM_SAC_CODE") or os.getenv("PLATFORM_SAC_CODE", "998599"),
        "legal_entity_name": current_app.config.get("LEGAL_ENTITY_NAME") or os.getenv("LEGAL_ENTITY_NAME", "Sklio Marketplace"),
        "legal_entity_address": current_app.config.get("LEGAL_ENTITY_ADDRESS") or os.getenv("LEGAL_ENTITY_ADDRESS", ""),
        "place_of_supply": _state_from_gstin(getattr(booking.seeker, "gstin", None)) or getattr(booking.seeker, "location", None),
        "tax_mode_label": "IGST" if float(getattr(booking, "igst_amount", 0) or 0) > 0 else "CGST + SGST",
        "qr_payload": f"SKLIO|{invoice_number}|{float(total_paid):.2f}|{service_title}",
        "service_amount": float(service_amount),
        "platform_fee": float(platform_fee_amount),
        "cgst_amount": float(getattr(booking, "cgst_amount", 0) or 0),
        "sgst_amount": float(getattr(booking, "sgst_amount", 0) or 0),
        "igst_amount": float(getattr(booking, "igst_amount", 0) or 0),
        "gst_amount": float(gst_amount),
        "total": float(total_paid),
    }
    
    url = generate_pdf_invoice(invoice_data)
    booking.invoice_number = invoice_number
    booking.invoice_url = url
    booking.invoice_generated_at = datetime.now(timezone.utc)
    db.session.commit()
    return url


def generate_commission_invoice(booking_id: str) -> str:
    # In this context, it's the same as booking invoice for now
    return generate_booking_invoice(booking_id)
