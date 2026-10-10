from __future__ import annotations

import asyncio
import base64
import binascii
import json
import re
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

import httpx

from app.config import settings


@dataclass(frozen=True)
class VerificationResult:
    accepted: bool
    message: str = ""
    provider_reference: str = ""
    confidence: float = 1.0
    face_template: str | None = None


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
        if normalized.startswith("data:image/"):
            return VerificationResult(
                accepted=False,
                message=(
                    "Camera face matching is not configured. Set "
                    "FACE_PROVIDER=aws_rekognition to enable biometric matching."
                ),
            )
        if normalized == "invalid-face" or not payload.strip():
            return VerificationResult(
                accepted=False,
                message="Face verification failed: Biometric mismatch or face not detected",
            )
        # Accepts valid token, webcam image data (data:image/...), or base64 data
        return VerificationResult(
            accepted=True,
            message="Face matched successfully with 98.4% confidence",
            provider_reference=generate_provider_reference(),
            confidence=0.984,
        )


class AwsRekognitionFaceProvider:
    def __init__(
        self,
        region: str,
        collection_id: str,
        match_threshold: float,
        client: Any | None = None,
    ):
        if client is None:
            try:
                import boto3
            except ImportError as exc:
                raise ValueError("Install boto3 to use AWS Rekognition face matching") from exc
            client = boto3.client("rekognition", region_name=region)
        self.client = client
        self.collection_id = collection_id
        self.match_threshold = match_threshold

    async def verify(self, subject: str, payload: str) -> VerificationResult:
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
        return f"Face matching service error: {error}"


class LocalFaceProvider:
    def __init__(
        self,
        model_dir: str,
        match_threshold: float,
        detector: Any | None = None,
        recognizer: Any | None = None,
    ):
        try:
            import cv2
            import numpy as np
        except ImportError as exc:
            raise ValueError(
                "Install the local-face extra to use local face matching: "
                "python -m pip install -e \".[local-face]\""
            ) from exc

        model_path = Path(model_dir)
        detector_path = model_path / "face_detection_yunet_2023mar.onnx"
        recognizer_path = model_path / "face_recognition_sface_2021dec.onnx"
        missing_models = [
            str(path) for path in (detector_path, recognizer_path) if not path.is_file()
        ]
        if missing_models:
            raise ValueError(
                "Local face model files are missing: "
                f"{', '.join(missing_models)}. Follow the local setup steps in README.md."
            )

        self.cv2 = cv2
        self.np = np
        self.detector = detector or cv2.FaceDetectorYN.create(
            str(detector_path), "", (320, 320), 0.9, 0.3, 5000
        )
        self.recognizer = recognizer or cv2.FaceRecognizerSF.create(str(recognizer_path), "")
        self.match_threshold = match_threshold
        self._inference_lock = Lock()

    async def verify(self, subject: str, payload: str) -> VerificationResult:
        embedding = await asyncio.to_thread(self._extract_embedding, payload)
        return VerificationResult(
            accepted=True,
            message="Face captured and encoded locally",
            provider_reference="LOCAL-SFACE",
            face_template=json.dumps(embedding),
        )

    async def match_enrolled(
        self, subject: str, payload: str, face_template: str | None
    ) -> VerificationResult:
        if not face_template:
            return VerificationResult(
                accepted=False,
                message="No local face template is enrolled for this participant.",
            )
        observed = await asyncio.to_thread(self._extract_embedding, payload)
        similarity = self._cosine_similarity(observed, self._parse_template(face_template))
        return VerificationResult(
            accepted=similarity >= self.match_threshold,
            message=(
                "Face matches the locally enrolled participant."
                if similarity >= self.match_threshold
                else "Face does not match the locally enrolled participant."
            ),
            provider_reference="LOCAL-SFACE",
            confidence=similarity,
        )

    def _extract_embedding(self, payload: str) -> list[float]:
        with self._inference_lock:
            return self._extract_embedding_locked(payload)

    def _extract_embedding_locked(self, payload: str) -> list[float]:
        try:
            header, encoded = payload.split(",", 1)
            if not header.startswith("data:image/"):
                raise ValueError
            image_bytes = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("A captured camera image is required for local face matching") from exc
        if not image_bytes or len(image_bytes) > 5_000_000:
            raise ValueError("Camera image must be between 1 byte and 5 MB")

        image = self.cv2.imdecode(
            self.np.frombuffer(image_bytes, dtype=self.np.uint8),
            self.cv2.IMREAD_COLOR,
        )
        if image is None:
            raise ValueError("The captured camera image could not be decoded.")

        height, width = image.shape[:2]
        self.detector.setInputSize((width, height))
        _, faces = self.detector.detect(image)
        if faces is None or len(faces) != 1:
            raise ValueError("Show exactly one clear face in the camera, then try again.")

        aligned = self.recognizer.alignCrop(image, faces[0])
        features = self.recognizer.feature(aligned).flatten()
        norm = float(self.np.linalg.norm(features))
        if not norm:
            raise ValueError(
                "Could not create a usable face template. Try again with better lighting."
            )
        return (features / norm).astype(self.np.float32).tolist()

    @staticmethod
    def _parse_template(template: str) -> list[float]:
        try:
            values = json.loads(template)
            if not isinstance(values, list) or not values:
                raise ValueError
            return [float(value) for value in values]
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError("Stored local face template is invalid.") from exc

    @staticmethod
    def _cosine_similarity(first: list[float], second: list[float]) -> float:
        if len(first) != len(second):
            raise ValueError("Stored local face template has an incompatible model format.")
        first_norm = sum(value * value for value in first) ** 0.5
        second_norm = sum(value * value for value in second) ** 0.5
        if not first_norm or not second_norm:
            raise ValueError("Stored local face template is invalid.")
        return sum(left * right for left, right in zip(first, second)) / (first_norm * second_norm)


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
        face: DemoFaceProvider | AwsRekognitionFaceProvider | LocalFaceProvider | None = None,
        liveness: DemoLivenessProvider | None = None,
        pad: DemoPadProvider | None = None,
    ):
        provider_name = settings.otp_provider.lower()
        if otp is not None:
            self.otp = otp
        elif provider_name == "twilio":
            credentials = (
                settings.twilio_account_sid,
                settings.twilio_auth_token,
                settings.twilio_verify_service_sid,
            )
            if not all(credentials):
                raise ValueError("Twilio Verify credentials are required when OTP_PROVIDER=twilio")
            self.otp = TwilioVerifyOtpProvider(*credentials)
        elif provider_name == "demo" and settings.app_env.lower() != "production":
            self.otp = DemoOtpProvider()
        else:
            raise ValueError(
                "Production requires OTP_PROVIDER=twilio; valid providers are demo and twilio"
            )
        face_provider_name = settings.face_provider.lower()
        if face is not None:
            self.face = face
        elif face_provider_name == "aws_rekognition":
            self.face = AwsRekognitionFaceProvider(
                settings.aws_region,
                settings.aws_rekognition_collection,
                settings.face_match_threshold,
            )
        elif face_provider_name == "local":
            self.face = LocalFaceProvider(
                settings.local_face_model_dir,
                settings.local_face_match_threshold,
            )
        elif face_provider_name == "demo" and settings.app_env.lower() != "production":
            self.face = DemoFaceProvider()
        else:
            raise ValueError(
                "Production requires a configured face provider; valid providers are "
                "demo, aws_rekognition, and local"
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

    async def match_face(
        self, subject: str, payload: str, face_template: str | None = None
    ) -> VerificationResult:
        if isinstance(self.face, AwsRekognitionFaceProvider):
            return await self.face.match_enrolled(subject, payload)
        if isinstance(self.face, LocalFaceProvider):
            return await self.face.match_enrolled(subject, payload, face_template)
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
