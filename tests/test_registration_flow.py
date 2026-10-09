from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.providers import AwsRekognitionFaceProvider
from app.schemas import CreateRegistrationRequest
from app.services import RegistrationService, VerificationStatus


@pytest.fixture
async def test_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    service = RegistrationService(session_factory)
    yield service
    await engine.dispose()


@pytest.mark.asyncio
async def test_registration_flow_requires_otp_face_liveness_and_pad(test_db: RegistrationService):
    request = CreateRegistrationRequest(
        event_id="evt-001",
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        mobile="+15550000001",
    )

    registration = await test_db.create_registration(request)

    assert registration.status == VerificationStatus.OTP_PENDING
    assert registration.participant_id is not None
    assert registration.otp_secret is not None

    with pytest.raises(ValueError, match="OTP"):
        await test_db.verify_otp(registration.id, "wrong-code")

    otp_code = registration.otp_code
    await test_db.verify_otp(registration.id, otp_code)
    assert registration.status == VerificationStatus.FACE_PENDING

    await test_db.verify_face(registration.id, "valid-face")
    await test_db.verify_liveness(registration.id, "live")
    await test_db.verify_pad(registration.id, "real-person")

    updated = await test_db.complete_registration(registration.id)
    assert updated.status == VerificationStatus.REGISTERED
    assert updated.qr_code is not None
    assert updated.qr_code.startswith("event-registration:")

    assert await test_db.is_duplicate_registration("evt-001", "ada@example.com") is True


@pytest.mark.asyncio
async def test_expired_otp_is_rejected(test_db: RegistrationService):
    request = CreateRegistrationRequest(
        event_id="evt-001",
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
        mobile="+15550000002",
    )
    registration = await test_db.create_registration(request)

    registration.otp_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await test_db.session.commit()

    with pytest.raises(ValueError, match="expired"):
        await test_db.verify_otp(registration.id, registration.otp_code)


@pytest.mark.asyncio
async def test_demo_provider_rejects_camera_images_instead_of_claiming_face_match(
    test_db: RegistrationService,
):
    registration = await test_db.create_registration(
        CreateRegistrationRequest(
            event_id="evt-face-demo",
            full_name="Face Test",
            email="face.test@example.com",
            mobile="+15550000006",
        )
    )
    await test_db.verify_otp(registration.id, registration.otp_code)

    with pytest.raises(ValueError, match="not configured"):
        await test_db.verify_face(registration.id, "data:image/jpeg;base64,YWJj")


@pytest.mark.asyncio
async def test_face_collection_blocks_duplicate_enrollment_and_requires_same_gate_face():
    class FakeRekognitionClient:
        def __init__(self, matches):
            self.matches = matches
            self.index_calls = 0

        def search_faces_by_image(self, **kwargs):
            return {"FaceMatches": self.matches}

        def index_faces(self, **kwargs):
            self.index_calls += 1
            return {"FaceRecords": [{"Face": {"FaceId": "new-face"}}]}

    captured_image = "data:image/jpeg;base64,YWJj"
    existing_face = {
        "Face": {"FaceId": "existing-face", "ExternalImageId": "PART-OTHER"},
        "Similarity": 97.2,
    }
    client = FakeRekognitionClient([existing_face])
    provider = AwsRekognitionFaceProvider("us-east-1", "faces", 90, client=client)

    duplicate = await provider.verify("PART-NEW", captured_image)
    wrong_gate_face = await provider.match_enrolled("PART-NEW", captured_image)
    correct_gate_face = await provider.match_enrolled("PART-OTHER", captured_image)

    assert duplicate.accepted is False
    assert wrong_gate_face.accepted is False
    assert correct_gate_face.accepted is True
    assert correct_gate_face.confidence == pytest.approx(0.972)
    assert client.index_calls == 0


@pytest.mark.asyncio
async def test_check_in_requires_valid_qr_and_face(test_db: RegistrationService):
    request = CreateRegistrationRequest(
        event_id="evt-002",
        first_name="Grace",
        last_name="Hopper",
        email="grace@example.com",
        mobile="+15550000003",
    )
    registration = await test_db.create_registration(request)
    await test_db.verify_otp(registration.id, registration.otp_code)
    await test_db.verify_face(registration.id, "valid-face")
    await test_db.verify_liveness(registration.id, "live")
    await test_db.verify_pad(registration.id, "real-person")
    await test_db.complete_registration(registration.id)

    with pytest.raises(ValueError, match="not configured"):
        await test_db.check_in(registration.id, "data:image/jpeg;base64,YWJj")

    check_in = await test_db.check_in(registration.id, "valid-face")
    assert check_in.status == VerificationStatus.CHECKED_IN

    with pytest.raises(ValueError, match="already checked in"):
        await test_db.check_in(registration.id, "valid-face")

    unregistered = await test_db.create_registration(
        CreateRegistrationRequest(
            event_id="evt-002",
            first_name="Margaret",
            last_name="Hamilton",
            email="margaret@example.com",
            mobile="+15550000005",
        )
    )
    await test_db.verify_otp(unregistered.id, unregistered.otp_code)
    await test_db.verify_face(unregistered.id, "valid-face")
    await test_db.verify_liveness(unregistered.id, "live")
    await test_db.verify_pad(unregistered.id, "real-person")
    await test_db.complete_registration(unregistered.id)

    with pytest.raises(ValueError, match="Face"):
        await test_db.check_in(unregistered.id, "invalid-face")


@pytest.mark.asyncio
async def test_duplicate_registration_is_rejected(test_db: RegistrationService):
    request = CreateRegistrationRequest(
        event_id="evt-003",
        first_name="Alan",
        last_name="Turing",
        email="alan@example.com",
        mobile="+15550000004",
    )
    first = await test_db.create_registration(request)
    await test_db.verify_otp(first.id, first.otp_code)
    await test_db.verify_face(first.id, "valid-face")
    await test_db.verify_liveness(first.id, "live")
    await test_db.verify_pad(first.id, "real-person")
    await test_db.complete_registration(first.id)

    duplicate = CreateRegistrationRequest(
        event_id="evt-003",
        first_name="Alan",
        last_name="Turing",
        email="alan@example.com",
        mobile="+15550000004",
    )

    with pytest.raises(ValueError, match="already registered"):
        await test_db.create_registration(duplicate)
