from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.extensions import db
from app.models import Booking, BookingStatus, KycStatus, Review, Skill, User, VerificationStatus


def test_provider_kyc_status_endpoint_returns_checklist(app, client, register_user, auth_headers):
    provider, token = register_user(
        "provider",
        name="KYC Provider",
        email="kyc-status-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.rejected
        provider_record.kyc_rejection_reason = "Upload a clearer bank proof document."
        db.session.commit()

    response = client.get(
        "/api/kyc/status",
        headers=auth_headers(token),
    )

    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload["kyc_status"] == "rejected"
    assert "bank proof" in payload["status_description"].lower()
    assert "bank_proof" in payload["reupload_document_types"]
    assert payload["discoverability_blocked"] is True


def test_booking_timeline_endpoint_and_missing_relation_fallback(
    app,
    client,
    register_user,
    auth_headers,
    booking_with_missing_relations,
):
    seeker, token = register_user(
        "seeker",
        name="Timeline Seeker",
        email="timeline-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Timeline Provider",
        email="timeline-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.approved
        provider_record.is_verified = True

        skill = Skill(
            provider_id=provider_record.id,
            title="Painter",
            description="Wall painting",
            price=Decimal("1200.00"),
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        booking = Booking(
            seeker_id=seeker["id"],
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=60,
            price=Decimal("1200.00"),
            amount_payable=Decimal("1200.00"),
            currency="INR",
            status=BookingStatus.PENDING,
        )
        db.session.add(booking)
        db.session.commit()
        booking_id = booking.id

    pay_response = client.post(
        f"/api/bookings/{booking_id}/pay",
        headers=auth_headers(token),
        json={"payment_ref": f"timeline-{booking_id}"},
    )
    assert pay_response.status_code == 200, pay_response.get_json()

    timeline_response = client.get(
        f"/api/bookings/{booking_id}/timeline",
        headers=auth_headers(token),
    )
    assert timeline_response.status_code == 200, timeline_response.get_json()
    events = timeline_response.get_json()["events"]
    event_types = [event["event_type"] for event in events]
    assert "payment_captured" in event_types
    assert "confirmed" in event_types

    missing_relations_response = client.get(
        "/api/bookings/my",
        headers=auth_headers(booking_with_missing_relations["token"]),
    )
    assert missing_relations_response.status_code == 200, missing_relations_response.get_json()
    assert any(item["skill"] == "Service unavailable" for item in missing_relations_response.get_json())


def test_dashboard_pages_render_expected_containers(client):
    provider_page = client.get("/provider/dashboard")
    assert provider_page.status_code == 200
    provider_html = provider_page.get_data(as_text=True)
    assert "providerActionCenter" in provider_html

    seeker_page = client.get("/my-bookings")
    assert seeker_page.status_code == 200
    seeker_html = seeker_page.get_data(as_text=True)
    assert "bookingFilters" in seeker_html
    assert "bookingSearch" in seeker_html


def test_my_bookings_supports_pagination_and_invoice_review_combinations(
    app,
    client,
    register_user,
    auth_headers,
):
    seeker, seeker_token = register_user(
        "seeker",
        name="Paged Seeker",
        email="paged-seeker@example.com",
    )
    provider, _provider_token = register_user(
        "provider",
        name="Paged Provider",
        email="paged-provider@example.com",
    )

    with app.app_context():
        provider_record = db.session.get(User, provider["id"])
        provider_record.verification_status = VerificationStatus.completed
        provider_record.kyc_status = KycStatus.approved
        provider_record.is_verified = True

        skill = Skill(
            provider_id=provider_record.id,
            title="Deep Cleaning",
            description="House cleaning",
            price=Decimal("1500.00"),
            currency="INR",
            is_active=True,
        )
        db.session.add(skill)
        db.session.flush()

        completed = Booking(
            seeker_id=seeker["id"],
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None),
            duration_minutes=90,
            price=Decimal("1500.00"),
            amount_payable=Decimal("1500.00"),
            currency="INR",
            status=BookingStatus.COMPLETED,
            invoice_number="INV-1001",
            invoice_url="invoices/inv-1001.pdf",
            invoice_generated_at=datetime.now(timezone.utc).replace(tzinfo=None),
            platform_fee_amount=Decimal("75.00"),
            gst_amount=Decimal("13.50"),
            service_amount=Decimal("1411.50"),
        )
        cancelled = Booking(
            seeker_id=seeker["id"],
            provider_id=provider_record.id,
            skill_id=skill.id,
            scheduled_at=(datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None),
            duration_minutes=60,
            price=Decimal("800.00"),
            amount_payable=Decimal("800.00"),
            currency="INR",
            status=BookingStatus.CANCELLED,
            cancellation_reason="provider_unavailable",
        )
        db.session.add_all([completed, cancelled])
        db.session.flush()

        review = Review(
            booking_id=completed.id,
            seeker_id=seeker["id"],
            provider_id=provider_record.id,
            rating=4.5,
            comment="Great work",
            provider_reply="Thanks for the feedback!",
            provider_replied_at=datetime.now(timezone.utc),
        )
        db.session.add(review)
        db.session.commit()

    paged = client.get(
        "/api/bookings/my?limit=1&offset=0",
        headers=auth_headers(seeker_token),
    )
    assert paged.status_code == 200, paged.get_json()
    page_payload = paged.get_json()
    assert len(page_payload) == 1

    full = client.get("/api/bookings/my", headers=auth_headers(seeker_token))
    assert full.status_code == 200, full.get_json()
    payload = full.get_json()
    assert len(payload) == 2

    completed_row = next(item for item in payload if item["status"] == "COMPLETED")
    assert completed_row["invoice"]["url"] == "invoices/inv-1001.pdf"
    assert completed_row["review_rating"] == 4.5
    assert "Thanks for the feedback!" in completed_row["review_provider_reply"]

    cancelled_row = next(item for item in payload if item["status"] == "CANCELLED")
    assert cancelled_row["cancellation_reason"] == "provider_unavailable"
