from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, BiometricVerification, Participant
from app.main import app
from app.schemas import CreateEventRequest, CreateRegistrationRequest
from app.services import RegistrationService, VerificationStatus


@pytest.fixture
async def memory_service():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = RegistrationService(session_factory)
    await service.seed_default_events()
    yield service
    await service.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_complete_relational_schema_and_biometric_consent(
    memory_service: RegistrationService,
):
    # 1. Create registration with participant details
    request = CreateRegistrationRequest(
        event_id="EVT-2026-001",
        full_name="Dr. Katherine Johnson",
        email="katherine@nasa.gov",
        mobile="+15559876543",
        participant_type="Speaker",
        organization="NASA Research",
        consent_agreed=True,
    )
    reg = await memory_service.create_registration(request)

    assert reg.status == VerificationStatus.OTP_PENDING
    assert reg.participant_id.startswith("PART-")
    assert reg.registration_id.startswith("REG-")

    # Verify Participant record was properly created in Participants table
    session = await memory_service._get_session()
    part_res = await session.execute(
        select(Participant).where(Participant.participant_id == reg.participant_id)
    )
    participant = part_res.scalar_one_or_none()
    assert participant is not None
    assert participant.full_name == "Dr. Katherine Johnson"
    assert participant.email == "katherine@nasa.gov"
    assert participant.mobile == "+15559876543"
    assert participant.participant_type == "Speaker"
    assert participant.organization == "NASA Research"
    assert participant.created_at is not None

    # 2. Email + Mobile OTP verification
    await memory_service.verify_otp(reg.id, reg.otp_code)
    assert reg.status == VerificationStatus.FACE_PENDING

    # 3. Face verification
    await memory_service.verify_face(reg.id, "valid-face")
    assert reg.face_verified is True
    assert reg.status == VerificationStatus.LIVENESS_PENDING

    # 4. Liveness check
    await memory_service.verify_liveness(reg.id, "live")
    assert reg.liveness_verified is True
    assert reg.status == VerificationStatus.PAD_PENDING

    # 5. PAD check (Presentation Attack Detection)
    await memory_service.verify_pad(reg.id, "real-person")
    assert reg.pad_verified is True

    # Verify BiometricVerification record was persisted in biometric_verifications table
    bio_query = select(BiometricVerification).where(
        BiometricVerification.participant_id == reg.participant_id
    )
    bio_res = await session.execute(bio_query)
    bio_record = bio_res.scalar_one_or_none()
    assert bio_record is not None
    assert bio_record.verification_id.startswith("BIO-")
    assert bio_record.face_verified is True
    assert bio_record.liveness_verified is True
    assert bio_record.liveness_passed is True
    assert bio_record.pad_verified is True
    assert bio_record.consent_id.startswith("CNS-")
    assert bio_record.provider_reference.startswith("PRV-BIO-")
    assert bio_record.verified_at is not None
    assert bio_record.verification_date is not None

    # 6. Complete registration and issue QR token
    completed = await memory_service.complete_registration(reg.id)
    assert completed.status == VerificationStatus.REGISTERED
    assert completed.registered_at is not None
    assert completed.qr_token is not None
    assert completed.qr_token.startswith("event-registration:")

    # 7. Check Duplicate Event registration is blocked
    with pytest.raises(ValueError, match="already registered"):
        await memory_service.create_registration(request)

    # 8. Entry check-in by QR token with Live Gate Face verification
    checkin_result = await memory_service.check_in(
        qr_token=completed.qr_token,
        face_payload="valid-gate-face",
    )
    assert checkin_result.status == VerificationStatus.CHECKED_IN
    assert checkin_result.checked_in_at is not None

    # 9. Second check-in attempt is rejected (anti-passback / duplicate entry prevention)
    with pytest.raises(ValueError, match="already checked in"):
        await memory_service.check_in(
            qr_token=completed.qr_token,
            face_payload="valid-gate-face",
        )


@pytest.mark.asyncio
async def test_event_capacity_limit(memory_service: RegistrationService):
    # Create an event with capacity of 1
    new_event = await memory_service.create_event(
        CreateEventRequest(
            event_id="EVT-CAP-001",
            event_name="Exclusive Workshop",
            event_date=datetime.now(UTC) + timedelta(days=5),
            capacity=1,
        )
    )
    assert new_event.capacity == 1

    # First participant registers
    first = await memory_service.create_registration(
        CreateRegistrationRequest(
            event_id="EVT-CAP-001",
            full_name="User One",
            email="user1@example.com",
            mobile="+15551111111",
        )
    )
    await memory_service.verify_otp(first.id, first.otp_code)
    await memory_service.verify_face(first.id, "valid-face")
    await memory_service.verify_liveness(first.id, "live")
    await memory_service.verify_pad(first.id, "real-person")
    await memory_service.complete_registration(first.id)

    # Second participant should be rejected due to capacity limit
    with pytest.raises(ValueError, match="capacity .* reached"):
        await memory_service.create_registration(
            CreateRegistrationRequest(
                event_id="EVT-CAP-001",
                full_name="User Two",
                email="user2@example.com",
                mobile="+15552222222",
            )
        )


@pytest.mark.asyncio
async def test_fastapi_endpoints_end_to_end():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # Check health
        health_res = await client.get("/health")
        assert health_res.status_code == 200
        assert health_res.json() == {"status": "ok"}

        # List events
        events_res = await client.get("/api/events")
        assert events_res.status_code == 200
        events = events_res.json()
        assert len(events) >= 1

        # Register participant
        unique_id = secrets.token_hex(4)
        reg_payload = {
            "event_id": events[0]["event_id"],
            "full_name": "Alan Kay",
            "email": f"alan.kay.{unique_id}@smalltalk.org",
            "mobile": "+15553334444",
            "participant_type": "VIP",
            "organization": "Viewpoints Research",
        }
        create_res = await client.post("/api/registrations", json=reg_payload)
        assert create_res.status_code == 201
        reg_data = create_res.json()
        assert "otp_secret" not in reg_data
        assert reg_data["otp_code"]
        reg_id = reg_data["id"]
        otp_code = reg_data["otp_code"]

        # Verify OTP
        otp_res = await client.post(f"/api/registrations/{reg_id}/otp", json={"code": otp_code})
        assert otp_res.status_code == 200
        assert otp_res.json()["status"] == "face_pending"

        # Verify Face
        face_res = await client.post(
            f"/api/registrations/{reg_id}/face", json={"payload": "valid-face"}
        )
        assert face_res.status_code == 200
        assert face_res.json()["status"] == "liveness_pending"

        # Verify Liveness
        live_res = await client.post(
            f"/api/registrations/{reg_id}/liveness", json={"payload": "live"}
        )
        assert live_res.status_code == 200
        assert live_res.json()["status"] == "pad_pending"

        # Verify PAD
        pad_res = await client.post(
            f"/api/registrations/{reg_id}/pad", json={"payload": "real-person"}
        )
        assert pad_res.status_code == 200

        # Complete Registration
        comp_res = await client.post(f"/api/registrations/{reg_id}/complete")
        assert comp_res.status_code == 200
        completed_data = comp_res.json()
        assert completed_data["status"] == "registered"
        assert completed_data["qr_token"] is not None

        registrations_res = await client.get("/api/registrations")
        assert registrations_res.status_code == 200
        assert any(item["id"] == reg_id for item in registrations_res.json())

        # Fetch QR PNG image
        qr_img_res = await client.get(f"/api/registrations/{reg_id}/qr")
        assert qr_img_res.status_code == 200
        assert qr_img_res.headers["content-type"] == "image/png"
        assert len(qr_img_res.content) > 100

        # Check Biometrics audit log
        bio_url = f"/api/biometrics?participant_id={completed_data['participant_id']}"
        bio_audit = await client.get(bio_url)
        assert bio_audit.status_code == 200
        bios = bio_audit.json()
        assert len(bios) >= 1
        assert bios[0]["consent_id"] != ""

        # Perform Gate Check-In
        checkin_payload = {
            "qr_token": completed_data["qr_token"],
            "face_payload": "live-gate-face",
        }
        checkin_res = await client.post("/api/check-in", json=checkin_payload)
        assert checkin_res.status_code == 200
        checkin_body = checkin_res.json()
        assert checkin_body["success"] is True
        assert "Access Granted" in checkin_body["message"]
        assert checkin_body["status"] == "checked_in"
