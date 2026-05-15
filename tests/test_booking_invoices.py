from datetime import datetime, timedelta, timezone

from app.extensions import db
from app.models import Booking, BookingStatus, PaymentStatus, RoleEnum, Skill, User, VerificationStatus
from app.services import payment_service


def test_completed_booking_detail_exposes_invoice_payload(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Invoice Detail Seeker",
        email="invoice-detail-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Invoice Detail Provider",
        email="invoice-detail-provider@example.com",
    )

    with app.app_context():
        seeker_record = db.session.get(User, seeker["id"])
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.is_verified = True

        skill = Skill(
            provider_id=provider_record.id,
            title="AC Service",
            description="Seasonal servicing",
            price=1599,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker_record.id,
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=2),
            duration_minutes=60,
            price=1599,
            currency="INR",
            status=BookingStatus.COMPLETED,
            payment_status=PaymentStatus.CAPTURED,
            platform_fee_pct=5,
            platform_fee_amount=80,
            gst_amount=14.4,
            service_amount=1504.6,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    response = client.get(
        f"/api/bookings/{booking_id}",
        headers=auth_headers(seeker_token),
    )

    assert response.status_code == 200
    payload = response.get_json()
    invoice = payload["invoice"]
    assert invoice["status"] == "generating"
    assert invoice["number"] is None
    assert invoice["service"] == 1504.6
    assert invoice["platform_fee"] == 80.0
    assert invoice["gst"] == 14.4
    assert invoice["total"] == 1599.0


def test_request_invoice_endpoint_returns_generating_status(app, client, register_user, auth_headers):
    seeker, seeker_token = register_user(
        "seeker",
        name="Invoice Request Seeker",
        email="invoice-request-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Invoice Request Provider",
        email="invoice-request-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.is_verified = True

        skill = Skill(
            provider_id=provider_record.id,
            title="Plumbing",
            description="Leak repair",
            price=999,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=3),
            duration_minutes=90,
            price=999,
            currency="INR",
            status=BookingStatus.COMPLETED,
            payment_status=PaymentStatus.CAPTURED,
            platform_fee_pct=5,
            platform_fee_amount=50,
            gst_amount=9,
            service_amount=940,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    response = client.post(
        f"/api/bookings/{booking_id}/invoice/generate",
        headers=auth_headers(seeker_token),
    )

    assert response.status_code == 202
    assert response.get_json() == {"invoice": {"status": "generating"}}


def test_generate_booking_invoice_includes_compliance_metadata(app, register_user, monkeypatch):
    seeker, _seeker_token = register_user(
        "seeker",
        name="Invoice Metadata Seeker",
        email="invoice-metadata-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Invoice Metadata Provider",
        email="invoice-metadata-provider@example.com",
    )

    captured = {}

    def fake_generate_pdf_invoice(invoice_data):
        captured.update(invoice_data)
        return "invoices/fake-invoice.pdf"

    monkeypatch.setattr(payment_service, "generate_pdf_invoice", fake_generate_pdf_invoice)

    with app.app_context():
        app.config["PLATFORM_GSTIN"] = "29ABCDE1234F1Z5"
        app.config["PLATFORM_SAC_CODE"] = "998599"
        app.config["LEGAL_ENTITY_NAME"] = "Sklio Marketplace Private Limited"
        app.config["LEGAL_ENTITY_ADDRESS"] = "Bengaluru, Karnataka"

        seeker_record = db.session.get(User, seeker["id"])
        provider_record = db.session.get(User, provider["id"])
        seeker_record.gstin = "29AAACS1234A1Z5"
        seeker_record.location = "Bengaluru, Karnataka"
        provider_record.gstin = "27AAACP1234P1Z5"
        provider_record.verification_status = VerificationStatus.completed
        provider_record.is_verified = True

        skill = Skill(
            provider_id=provider_record.id,
            title="Electrical Repair",
            description="Wiring fixes",
            price=2200,
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker_record.id,
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=datetime.now(timezone.utc) + timedelta(days=1),
            duration_minutes=90,
            price=2200,
            amount_payable=2200,
            currency="INR",
            status=BookingStatus.COMPLETED,
            payment_status=PaymentStatus.CAPTURED,
            platform_fee_pct=10,
            platform_fee_amount=220,
            gst_amount=39.6,
            cgst_amount=0,
            sgst_amount=0,
            igst_amount=39.6,
            service_amount=1940.4,
        )
        db.session.add(booking)
        db.session.commit()

        url = payment_service.generate_booking_invoice(str(booking.id))

    assert url == "invoices/fake-invoice.pdf"
    assert captured["platform_gstin"] == "29ABCDE1234F1Z5"
    assert captured["platform_sac_code"] == "998599"
    assert captured["legal_entity_name"] == "Sklio Marketplace Private Limited"
    assert captured["legal_entity_address"] == "Bengaluru, Karnataka"
    assert captured["provider_gstin"] == "27AAACP1234P1Z5"
    assert captured["tax_mode_label"] == "IGST"
    assert "SKLIO|" in captured["qr_payload"]
