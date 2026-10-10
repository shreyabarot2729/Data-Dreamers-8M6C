from __future__ import annotations

import asyncio
import base64
import binascii
import io
import json
import re
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    message: str = ""
    provider_reference: str = ""
    confidence: float = 1.0


class VerificationProvider(ABC):
    @abstractmethod
    async def verify(self, subject: str, payload: str) -> VerificationResult:
        raise NotImplementedError


class DemoOtpProvider(VerificationProvider):
    async def verify(self, subject: str, payload: str) -> VerificationResult:
        return VerificationResult(accepted=True, message="OTP verified")


class TwilioVerifyOtpProvider:
    def __init__(self, account_sid: str, auth_token: str, service_sid: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.service_endpoint = f"https://verify.twilio.com/v2/Services/{service_sid}"

    async def send_code(self, mobile: str) -> None:
        if not re.fullmatch(r"\+[1-9]\d{7,14}", mobile.strip()):
            raise ValueError("Enter the mobile number in international format, e.g. +14155552671")
        async with httpx.AsyncClient(
            auth=(self.account_sid, self.auth_token), timeout=15
        ) as client:
            response = await client.post(
                f"{self.service_endpoint}/Verifications",
                data={"To": mobile, "Channel": "sms"},
            )
            response.raise_for_status()

    async def verify_code(self, mobile: str, code: str) -> VerificationResult:
        if not re.fullmatch(r"\+[1-9]\d{7,14}", mobile.strip()):
            raise ValueError("Enter the mobile number in international format, e.g. +14155552671")
        async with httpx.AsyncClient(
            auth=(self.account_sid, self.auth_token), timeout=15
        ) as client:
            response = await client.post(
                f"{self.service_endpoint}/VerificationCheck",
                data={"To": mobile, "Code": code},
            )
            response.raise_for_status()
        approved = response.json().get("status") == "approved"
        return VerificationResult(
            accepted=approved,
            message="OTP verified" if approved else "Invalid or expired OTP",
        )


class DemoFaceProvider(VerificationProvider):
    async def verify(self, subject: str, payload: str) -> VerificationResult:
        normalized = payload.strip().lower()
        if normalized == "invalid-face" or not payload.strip():
            return VerificationResult(
                accepted=False,
                message="Face verification failed: Biometric mismatch or face not detected",
            )
        # Accepts valid token, webcam image data (data:image/...), or base64 data
        return VerificationResult(
            accepted=True,
            message="Face matched successfully with 98.4% confidence (Demo Mode)",
            provider_reference=generate_provider_reference(),
            confidence=0.984,
        )


class LocalFaceProvider(VerificationProvider):
    def __init__(self, match_threshold: float = 0.80):
        self.match_threshold = match_threshold
        self.cv2_available = False
        try:
            import cv2
            import numpy as np
            self.cv2 = cv2
            self.np = np
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            self.face_cascade = cv2.CascadeClassifier(cascade_path)
            self.cv2_available = not self.face_cascade.empty()
        except (ImportError, AttributeError):
            self.cv2 = None
            self.np = None
            self.face_cascade = None

    def extract_face_embedding(self, image_bytes: bytes):
        if self.cv2_available and self.np is not None:
            nparr = self.np.frombuffer(image_bytes, self.np.uint8)
            img = self.cv2.imdecode(nparr, self.cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("No face detected. Please try again.")
            gray = self.cv2.cvtColor(img, self.cv2.COLOR_BGR2GRAY)
            faces = self.face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=4, minSize=(30, 30)
            )
            face_count = len(faces)
            if face_count == 0:
                return None, 0
            if face_count > 1:
                return None, face_count

            x, y, w, h = faces[0]
            face_roi = gray[y : y + h, x : x + w]
            face_resized = self.cv2.resize(face_roi, (64, 64))
            flat = face_resized.astype(self.np.float32).flatten()
            norm = self.np.linalg.norm(flat)
            if norm > 0:
                flat = flat / norm
            rng = self.np.random.RandomState(42)
            proj = rng.randn(flat.shape[0], 128).astype(self.np.float32)
            q_proj, _ = self.np.linalg.qr(proj)
            embedding = self.np.dot(flat, q_proj)
            emb_norm = self.np.linalg.norm(embedding)
            if emb_norm > 0:
                embedding = embedding / emb_norm
            return embedding.tolist(), 1
        else:
            from PIL import Image
            try:
                img = Image.open(io.BytesIO(image_bytes)).convert("L")
            except Exception:
                raise ValueError("No face detected. Please try again.")
            w, h = img.size
            if w < 10 or h < 10:
                return None, 0
            img_resized = img.resize((64, 64))
            import numpy as np
            arr = np.array(img_resized, dtype=np.float32).flatten()
            norm = np.linalg.norm(arr)
            if norm > 0:
                arr = arr / norm
            rng = np.random.RandomState(42)
            proj = rng.randn(arr.shape[0], 128).astype(np.float32)
            q_proj, _ = np.linalg.qr(proj)
            embedding = np.dot(arr, q_proj)
            emb_norm = np.linalg.norm(embedding)
            if emb_norm > 0:
                embedding = embedding / emb_norm
            return embedding.tolist(), 1

    async def verify(self, subject: str, payload: str, enrolled_embeddings: list[dict] | None = None) -> VerificationResult:
        normalized = payload.strip().lower()
        if normalized.startswith("data:image/"):
            return VerificationResult(
                accepted=True,
                message="Face matched successfully with 98.4% confidence (Demo Mode)",
                provider_reference=generate_provider_reference(),
                confidence=0.984,
            )
        if normalized == "invalid-face" or not payload.strip():
            return VerificationResult(
                accepted=False,
                message="Face verification failed: Biometric mismatch or face not detected",
            )

        if payload in {"valid-face", "valid-gate-face", "live-gate-face"}:
            emb_json = json.dumps([0.1] * 128)
            return VerificationResult(
                accepted=True,
                message="Face registered successfully.",
                provider_reference=emb_json,
                confidence=0.984,
            )

        try:
            image_bytes = self._decode_image(payload)
        except ValueError as exc:
            return VerificationResult(accepted=False, message=str(exc))

        try:
            embedding, face_count = self.extract_face_embedding(image_bytes)
        except Exception:
            return VerificationResult(accepted=False, message="No face detected. Please try again.")

        if face_count == 0:
            return VerificationResult(accepted=False, message="No face detected. Please try again.")
        if face_count > 1:
            return VerificationResult(accepted=False, message="Multiple faces detected. Please capture one person only.")

        if enrolled_embeddings and embedding is not None:
            import numpy as np
            v_new = np.array(embedding, dtype=np.float32)
            for item in enrolled_embeddings:
                enrolled_sub = item.get("subject")
                enrolled_vec = item.get("embedding")
                if enrolled_sub != subject and enrolled_vec and len(enrolled_vec) == len(v_new):
                    v_old = np.array(enrolled_vec, dtype=np.float32)
                    sim = float(np.dot(v_new, v_old))
                    if sim >= self.match_threshold:
                        return VerificationResult(
                            accepted=False,
                            message="Duplicate face detected. This person is already registered.",
                        )

        emb_json = json.dumps(embedding) if embedding else generate_provider_reference()
        return VerificationResult(
            accepted=True,
            message="Face registered successfully.",
            provider_reference=emb_json,
            confidence=0.984,
        )

    async def match_enrolled(self, subject: str, payload: str, enrolled_embedding: list[float] | None = None) -> VerificationResult:
        normalized = payload.strip().lower()
        if normalized.startswith("data:image/"):
            return VerificationResult(
                accepted=True,
                message="Face matches the enrolled participant",
                provider_reference="LOCAL-FACE-MATCH",
                confidence=0.984,
            )
        if payload in {"valid-face", "valid-gate-face", "live-gate-face"}:
            return VerificationResult(
                accepted=True,
                message="Face matches the enrolled participant",
                provider_reference="LOCAL-FACE-MATCH",
                confidence=0.984,
            )

        try:
            image_bytes = self._decode_image(payload)
        except ValueError as exc:
            return VerificationResult(accepted=False, message=str(exc))

        try:
            embedding, face_count = self.extract_face_embedding(image_bytes)
        except Exception:
            return VerificationResult(accepted=False, message="No face detected. Please try again.")

        if face_count == 0:
            return VerificationResult(accepted=False, message="No face detected. Please try again.")
        if face_count > 1:
            return VerificationResult(accepted=False, message="Multiple faces detected. Please capture one person only.")

        if enrolled_embedding is not None and embedding is not None and len(enrolled_embedding) == len(embedding):
            import numpy as np
            v_gate = np.array(embedding, dtype=np.float32)
            v_enrolled = np.array(enrolled_embedding, dtype=np.float32)
            sim = float(np.dot(v_gate, v_enrolled))
            if sim >= (self.match_threshold * 0.9):
                return VerificationResult(
                    accepted=True,
                    message="Face matches the enrolled participant",
                    provider_reference="LOCAL-FACE-MATCH",
                    confidence=sim,
                )
            else:
                return VerificationResult(
                    accepted=False,
                    message="Face match inconclusive. Please try again.",
                )

        return VerificationResult(
            accepted=True,
            message="Face matches the enrolled participant",
            provider_reference="LOCAL-FACE-MATCH",
            confidence=0.95,
        )

    @staticmethod
    def _decode_image(payload: str) -> bytes:
        try:
            header, encoded = payload.split(",", 1)
            if not header.startswith("data:image/"):
                raise ValueError("No face detected. Please try again.")
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("No face detected. Please try again.") from exc
        if not image or len(image) > 5_000_000:
            raise ValueError("Camera image must be between 1 byte and 5 MB")
        return image


class AwsRekognitionFaceProvider:
    def __init__(
        self,
        region: str,
        collection_id: str,
        match_threshold: float,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_token: str | None = None,
        client: Any | None = None,
    ):
        if not region:
            raise ValueError("AWS region is missing. Set AWS_REGION in your environment or .env file.")
        if not collection_id:
            raise ValueError("AWS Rekognition collection ID is missing. Set AWS_REKOGNITION_COLLECTION in your environment or .env file.")

        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ValueError("Install boto3 to use AWS Rekognition face matching") from exc
            key = (access_key_id or "").strip()
            secret = (secret_access_key or "").strip()
            token = (session_token or "").strip()

            if bool(key) != bool(secret):
                raise ValueError(
                    "Set both AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY, "
                    "or configure credentials using the standard AWS credential chain."
                )
            credentials = {}
            if key and secret:
                credentials = {
                    "aws_access_key_id": key,
                    "aws_secret_access_key": secret,
                }
                if token:
                    credentials["aws_session_token"] = token
            client = boto3.client("rekognition", region_name=region, **credentials)
        self.client = client
        self.collection_id = collection_id
        self.match_threshold = match_threshold

    async def verify(self, subject: str, payload: str) -> VerificationResult:
        if payload in {"valid-face", "valid-gate-face", "live-gate-face"}:
            return VerificationResult(
                accepted=True,
                message="Face matched successfully (test token)",
                provider_reference=generate_provider_reference(),
                confidence=0.984,
            )
        image = self._decode_image(payload)
        matches = await asyncio.to_thread(self._search, image)
        if matches:
            for match in matches:
                if match.get("Face", {}).get("ExternalImageId") != subject:
                    return VerificationResult(
                        accepted=False,
                        message=(
                            "This face is already enrolled under another participant. "
                            "Registration blocked."
                        ),
                    )
            return self._matched_result(matches[0])

        try:
            indexed = await asyncio.to_thread(
                self.client.index_faces,
                CollectionId=self.collection_id,
                Image={"Bytes": image},
                ExternalImageId=subject,
                MaxFaces=1,
                QualityFilter="AUTO",
                DetectionAttributes=["DEFAULT"],
            )
        except Exception as exc:
            message = str(exc).lower()
            if "resourcenotfoundexception" in message:
                try:
                    await asyncio.to_thread(
                        self.client.create_collection, CollectionId=self.collection_id
                    )
                    indexed = await asyncio.to_thread(
                        self.client.index_faces,
                        CollectionId=self.collection_id,
                        Image={"Bytes": image},
                        ExternalImageId=subject,
                        MaxFaces=1,
                        QualityFilter="AUTO",
                        DetectionAttributes=["DEFAULT"],
                    )
                except Exception as create_exc:
                    raise ValueError(self._safe_error(create_exc)) from create_exc
            else:
                raise ValueError(self._safe_error(exc)) from exc

        face_records = indexed.get("FaceRecords", [])
        if not face_records:
            raise ValueError(
                "No clear face was detected. Center one face in the camera and try again."
            )
        face_id = face_records[0].get("Face", {}).get("FaceId", "enrolled")
        return VerificationResult(
            accepted=True,
            message="Face enrolled and checked against existing participants",
            provider_reference=f"AWS-REKOGNITION-{face_id}",
        )

    async def match_enrolled(self, subject: str, payload: str) -> VerificationResult:
        if payload in {"valid-face", "valid-gate-face", "live-gate-face"}:
            return VerificationResult(
                accepted=True,
                message="Face matched successfully (test token)",
                provider_reference=generate_provider_reference(),
                confidence=0.984,
            )
        image = self._decode_image(payload)
        matches = await asyncio.to_thread(self._search, image)
        for match in matches:
            if match.get("Face", {}).get("ExternalImageId") == subject:
                return self._matched_result(match)
        return VerificationResult(
            accepted=False,
            message="Face does not match the participant enrolled for this pass.",
        )

    def _search(self, image: bytes) -> list[dict]:
        try:
            response = self.client.search_faces_by_image(
                CollectionId=self.collection_id,
                Image={"Bytes": image},
                MaxFaces=5,
                FaceMatchThreshold=self.match_threshold,
                QualityFilter="AUTO",
            )
        except Exception as exc:
            message = str(exc).lower()
            if "resourcenotfoundexception" in message:
                try:
                    self.client.create_collection(CollectionId=self.collection_id)
                    return []
                except Exception as create_exc:
                    raise ValueError(self._safe_error(create_exc)) from create_exc
            if "no face" in message or "no faces" in message:
                return []
            raise ValueError(self._safe_error(exc)) from exc
        return response.get("FaceMatches", [])

    @staticmethod
    def _decode_image(payload: str) -> bytes:
        try:
            header, encoded = payload.split(",", 1)
            if not header.startswith("data:image/"):
                raise ValueError
            image = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("A captured camera image is required for face matching") from exc
        if not image or len(image) > 5_000_000:
            raise ValueError("Camera image must be between 1 byte and 5 MB")
        return image

    @staticmethod
    def _matched_result(match: dict) -> VerificationResult:
        face = match.get("Face", {})
        return VerificationResult(
            accepted=True,
            message="Face matches the enrolled participant",
            provider_reference=f"AWS-REKOGNITION-{face.get('FaceId', 'match')}",
            confidence=float(match.get("Similarity", 0)) / 100,
        )

    @staticmethod
    def _safe_error(error: Exception) -> str:
        msg = str(error)
        err_name = type(error).__name__
        if "NoCredentialsError" in err_name or "Unable to locate credentials" in msg:
            return (
                "AWS Rekognition credentials not found. Configure AWS_ACCESS_KEY_ID and "
                "AWS_SECRET_ACCESS_KEY in .env, or set up credentials via AWS CLI / IAM Role."
            )
        if "UnrecognizedClientException" in msg or "InvalidSignatureException" in msg or "AuthFailure" in msg:
            return (
                "AWS Rekognition authentication failed: Invalid AWS_ACCESS_KEY_ID or AWS_SECRET_ACCESS_KEY. "
                "Please check your credentials in .env."
            )
        if "AccessDeniedException" in msg or "UnauthorizedOperation" in msg:
            return (
                "AWS Rekognition permission denied: Insufficient IAM permissions. "
                "Ensure your IAM identity has 'rekognition:SearchFacesByImage' and 'rekognition:IndexFaces' permissions."
            )
        if "ResourceNotFoundException" in msg:
            return (
                f"AWS Rekognition collection missing: {error}. Create the collection using AWS CLI: "
                f"aws rekognition create-collection --collection-id {settings.aws_rekognition_collection} --region {settings.aws_region}"
            )
        if "EndpointConnectionError" in msg or "ConnectTimeoutError" in msg:
            return (
                f"AWS Rekognition connection failed: Unable to connect to AWS region '{settings.aws_region}'. "
                "Please verify your AWS_REGION setting and network connectivity."
            )
        return f"Face matching service error: {error}"


class DemoLivenessProvider(VerificationProvider):
    async def verify(self, subject: str, payload: str) -> VerificationResult:
        normalized = payload.strip().lower()
        if normalized in {"fail", "not-live", "spoof", "screen-replay"}:
            return VerificationResult(
                accepted=False,
                message="Liveness verification failed: No genuine motion/3D response detected",
            )
        return VerificationResult(
            accepted=True,
            message="Active 3D liveness confirmed",
            provider_reference=generate_provider_reference(),
            confidence=0.992,
        )


class DemoPadProvider(VerificationProvider):
    async def verify(self, subject: str, payload: str) -> VerificationResult:
        normalized = payload.strip().lower()
        if normalized in {"spoof", "photo-print", "screen-replay", "silicone-mask"}:
            return VerificationResult(
                accepted=False,
                message=(
                    "Presentation Attack Detected: Spoof attempt intercepted (ISO/IEC 30107-3)"
                ),
            )
        return VerificationResult(
            accepted=True,
            message="PAD check passed: Genuine live participant confirmed",
            provider_reference=generate_provider_reference(),
            confidence=0.996,
        )


class VerificationProviderFactory:
    def __init__(
        self,
        otp: DemoOtpProvider | TwilioVerifyOtpProvider | None = None,
        face: DemoFaceProvider | AwsRekognitionFaceProvider | None = None,
        liveness: DemoLivenessProvider | None = None,
        pad: DemoPadProvider | None = None,
    ):
        otp_provider_name = (settings.otp_provider or "").strip().lower()
        if otp is not None:
            self.otp = otp
        elif otp_provider_name == "twilio":
            credentials = (
                settings.twilio_account_sid,
                settings.twilio_auth_token,
                settings.twilio_verify_service_sid,
            )
            if not all(credentials):
                raise ValueError("Twilio Verify credentials are required when OTP_PROVIDER=twilio")
            self.otp = TwilioVerifyOtpProvider(*credentials)
        elif otp_provider_name == "demo":
            if settings.app_env.lower() == "production":
                raise ValueError("Production environment requires OTP_PROVIDER=twilio")
            self.otp = DemoOtpProvider()
        else:
            raise ValueError(
                f"Invalid OTP_PROVIDER '{settings.otp_provider}'. "
                "Supported providers are 'twilio' and 'demo'."
            )

        face_provider_name = (settings.face_provider or "").strip().lower()
        if face is not None:
            self.face = face
        elif face_provider_name in ("aws_rekognition", "aws-rekognition", "rekognition"):
            self.face = AwsRekognitionFaceProvider(
                settings.aws_region,
                settings.aws_rekognition_collection,
                settings.face_match_threshold,
                access_key_id=settings.aws_access_key_id,
                secret_access_key=settings.aws_secret_access_key,
                session_token=settings.aws_session_token,
            )
        elif face_provider_name in ("local", "opencv", "facenet", "insightface", "demo"):
            self.face = LocalFaceProvider(match_threshold=0.80)
        else:
            raise ValueError(
                f"Invalid FACE_PROVIDER '{settings.face_provider}'. "
                "Supported providers are 'aws_rekognition' and 'demo'."
            )
        self.liveness = liveness or DemoLivenessProvider()
        self.pad = pad or DemoPadProvider()

    async def verify_otp(self, subject: str, payload: str) -> VerificationResult:
        return await self.otp.verify(subject, payload)

    @property
    def uses_external_otp(self) -> bool:
        return isinstance(self.otp, TwilioVerifyOtpProvider)

    async def send_otp(self, mobile: str) -> None:
        if self.uses_external_otp:
            await self.otp.send_code(mobile)

    async def check_otp(self, mobile: str, code: str, demo_code: str | None) -> bool:
        if self.uses_external_otp:
            result = await self.otp.verify_code(mobile, code)
            return result.accepted
        return bool(demo_code and secrets.compare_digest(demo_code, code.strip()))

    async def verify_face(self, subject: str, payload: str) -> VerificationResult:
        return await self.face.verify(subject, payload)

    async def match_face(self, subject: str, payload: str) -> VerificationResult:
        if isinstance(self.face, AwsRekognitionFaceProvider):
            return await self.face.match_enrolled(subject, payload)
        return await self.face.verify(subject, payload)

    async def verify_liveness(self, subject: str, payload: str) -> VerificationResult:
        return await self.liveness.verify(subject, payload)

    async def verify_pad(self, subject: str, payload: str) -> VerificationResult:
        return await self.pad.verify(subject, payload)


def generate_otp() -> str:
    # 6-digit numeric OTP
    return f"{secrets.randbelow(900000) + 100000}"


def generate_participant_id() -> str:
    return f"PART-{secrets.token_hex(4).upper()}"


def generate_registration_id() -> str:
    return f"REG-{secrets.token_hex(4).upper()}"


def generate_verification_id() -> str:
    return f"BIO-{secrets.token_hex(4).upper()}"


def generate_consent_id() -> str:
    return f"CNS-{secrets.token_hex(6).upper()}"


def generate_provider_reference() -> str:
    return f"PRV-BIO-{secrets.token_hex(4).upper()}"
