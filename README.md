# Data-Dreamers-8M6C
# EventSecure: Biometric Event Registration & Check-In System

A production-grade Python event registration and gate admission security platform built with **FastAPI**, **SQLAlchemy (Async)**, **Alembic**, and a responsive frontend interface.

---

## Architecture Flow

```
                 EVENT REGISTRATION
                         ↓
                  Participant
                         ↓
              Mobile SMS OTP
                         ↓
                Face Verification
                         ↓
              Liveness + PAD Check
                         ↓
                 Participant ID
                         ↓
              Check duplicate event
                         ↓
                 Registration
                         ↓
                  QR Pass
                         ↓
                  EVENT ENTRY
                         ↓
             QR + Face Verification
                         ↓
                    CHECK-IN
```

---

## Relational Database Schema

### 1. `Events`
| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Internal primary key |
| `event_id` | Text (Unique, Indexed) | Unique event code, e.g. `EVT-2026-001` |
| `event_name` | Text | Name of the event |
| `event_date` | DateTime (UTC) | Date and time of the event |
| `capacity` | Integer | Maximum participant capacity |
| `created_at` | DateTime (UTC) | Timestamp created |

### 2. `Participants`
| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Internal primary key |
| `participant_id` | Text (Unique, Indexed) | Unique ID code, e.g. `PART-A8F291B0` |
| `full_name` | Text | Attendee full name |
| `email` | Text (Indexed) | Attendee email address |
| `mobile` | Text | Mobile contact number |
| `participant_type` | Text | Attendee, Speaker, VIP, Organizer, Delegate |
| `organization` | Text | Company, institution, or organization |
| `created_at` | DateTime (UTC) | Registration profile creation timestamp |

### 3. `BiometricVerification` (`biometric_verifications`)
| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Internal primary key |
| `verification_id` | Text (Unique, Indexed) | Unique verification reference (`BIO-XXXX`) |
| `participant_id` | Text (FK: `participants`) | Foreign key linking to participant |
| `provider_reference` | Text | External biometric vendor audit reference |
| `face_verified` | Boolean | Facial recognition match status |
| `liveness_verified` | Boolean | 3D motion / micro-movement confirmation (`liveness_passed`) |
| `pad_verified` | Boolean | Presentation Attack Detection (anti-spoofing) |
| `iris_verified` | Boolean | Iris biometric status (default: False) |
| `fingerprint_verified` | Boolean | Fingerprint biometric status (default: False) |
| `consent_id` | Text (Indexed) | Biometric data processing consent receipt (`CNS-XXXX`) |
| `verified_at` | DateTime (UTC) | Verification audit timestamp (`verification_date`) |

### 4. `Registrations`
| Column | Type | Description |
|---|---|---|
| `id` | Integer (PK) | Internal primary key |
| `registration_id` | Text (Unique, Indexed) | Unique code, e.g. `REG-XXXX` |
| `participant_id` | Text (FK: `participants`) | Linked participant |
| `event_id` | Text (FK: `events`) | Linked event |
| `status` | Text | `otp_pending`, `face_pending`, `liveness_pending`, `pad_pending`, `registered`, `checked_in` |
| `registered_at` | DateTime (UTC) | Registration confirmation timestamp |
| `qr_token` | Text (Unique, Indexed) | Cryptographically signed pass token |
| `checked_in_at` | DateTime (UTC) | Gate entry timestamp |
| `otp_code` | Text | 6-digit authentication code |
| `otp_expires_at` | DateTime (UTC) | OTP expiration timestamp |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/` | Web UI Dashboard |
| `GET` | `/api/events` | List all events with live registration count vs capacity |
| `POST` | `/api/events` | Create a new event |
| `GET` | `/api/participants` | List registered participants |
| `GET` | `/api/biometrics` | Audit log of biometric verifications with consent receipts |
| `POST` | `/api/registrations` | Initiate registration, duplicate event check, and issue OTP |
| `GET` | `/api/registrations/{id}` | Retrieve registration state |
| `POST` | `/api/registrations/{id}/otp` | Verify Email & Mobile OTP |
| `POST` | `/api/registrations/{id}/face` | Perform facial biometric match |
| `POST` | `/api/registrations/{id}/liveness` | Run active 3D liveness probe |
| `POST` | `/api/registrations/{id}/pad` | Run ISO/IEC 30107 Presentation Attack Detection & log Consent |
| `POST` | `/api/registrations/{id}/complete` | Finalize registration and generate QR Pass Token |
| `GET` | `/api/registrations/{id}/qr` | Generate crisp PNG QR Code for admission pass |
| `POST` | `/api/check-in` | Gate entry check-in via QR Pass & live Gate Face matching |
| `GET` | `/health` | Health check endpoint |

---

## Quick Start

### 1. Install Dependencies
```bash
python -m pip install -e ".[dev]"
```

## Vercel Deployment

The repository includes a Vercel Python function entry point at `api/index.py`. Import the repository into Vercel and configure these project environment variables before deploying:

```ini
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DATABASE
APP_ENV=production
SECRET_KEY=<long-random-secret>
OTP_PROVIDER=twilio
TWILIO_ACCOUNT_SID=<account-sid>
TWILIO_AUTH_TOKEN=<auth-token>
TWILIO_VERIFY_SERVICE_SID=<verify-service-sid>
FACE_PROVIDER=aws_rekognition
AWS_REGION=us-east-1
AWS_REKOGNITION_COLLECTION=eventsecure-participants
FACE_MATCH_THRESHOLD=90
AWS_ACCESS_KEY_ID=<aws-access-key>
AWS_SECRET_ACCESS_KEY=<aws-secret-key>
```

Use a managed PostgreSQL database; Vercel's function filesystem and the app's in-memory SQLite default are not durable across requests or deployments. Run `alembic upgrade head` against the configured production database before using the app. Create a Twilio Verify service with SMS enabled and use its Verify Service SID. Store credentials only in Vercel project environment settings, never in source control.

For local setup, copy `.env.example` to `.env`. It uses demo OTP and AWS Rekognition for face matching. Configure AWS credentials either with `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` in the ignored local `.env` file (add `AWS_SESSION_TOKEN` when using temporary credentials), or through the standard AWS credential chain such as an AWS CLI profile. Create the Rekognition collection in the configured region and grant the identity `rekognition:SearchFacesByImage` and `rekognition:IndexFaces` permissions. Restart Uvicorn after changing `.env`. Never commit or share AWS credentials.

For local real-SMS testing, set `OTP_PROVIDER=twilio` and configure the Twilio account and Verify service credentials in `.env`. Enter the recipient number in E.164 format (for example, `+14155552671`); Twilio trial accounts may only send to verified recipient numbers. Without these settings, development uses demo OTP and does not send SMS.

### Same-Face Duplicate Prevention

Camera matching uses AWS Rekognition when `FACE_PROVIDER=aws_rekognition`. Create the collection in the configured region before starting the app:

```powershell
aws rekognition create-collection --collection-id eventsecure-participants --region us-east-1
```

Give the app's AWS identity `rekognition:SearchFacesByImage` and `rekognition:IndexFaces` permissions for that collection, then configure `AWS_REGION`, `AWS_REKOGNITION_COLLECTION`, `FACE_MATCH_THRESHOLD`, and AWS credentials through local environment settings or Vercel secrets. New camera enrollment searches existing faces before indexing; gate check-in must match the participant ID associated with the scanned pass. Existing registrations have no stored face template and must enroll again. Demo mode deliberately rejects camera images and never claims a biometric match. Liveness and PAD are still demo providers and need a real provider before production access control.

Camera access is available only in secure browser contexts (HTTPS on Vercel or `localhost` during development). The default face provider is a demo; AWS Rekognition enables face matching when configured. Liveness and presentation-attack detection remain demo checks, so live camera capture does not make the complete flow production-ready for real identity or access decisions. Use qualified liveness and PAD providers before deploying for real access control.

### 2. Configure Environment
Copy `.env.example` to `.env` and configure AWS credentials for real camera face matching. `.env` is ignored by Git. For demo mode without AWS, set `FACE_PROVIDER=demo`; demo mode intentionally rejects camera images and is not real biometric verification. SQLite is used locally:
```ini
DATABASE_URL=sqlite+aiosqlite:///./event_registration.db
DATABASE_ECHO=false
SECRET_KEY=change-this-to-a-long-random-secret
OTP_TTL_SECONDS=300
```
*(Or configure PostgreSQL for production: `postgresql+asyncpg://user:pass@localhost:5432/dbname`)*

### 3. Run Migrations
```bash
alembic upgrade head
```
For existing local SQLite databases, startup also adds the currently required event and biometric columns without deleting existing records. Continue to use Alembic for PostgreSQL and other deployed databases.

### 4. Run the API and Web UI
```bash
uvicorn app.main:app --reload
```
Open **`http://127.0.0.1:8000`** in your browser.

The standalone, authenticated admin application is available at **`http://127.0.0.1:8000/admin/login`**. It uses the same backend and database as the participant site, while keeping its interface separate. Admin sign-in is served by `/api/admin/login`; subsequent admin operations use bearer-token authorization and server-side role checks. Admin management actions are recorded in the audit log where supported. Set a unique `ADMIN_PASSWORD` in your ignored local `.env` before the first startup; no shared default admin password is included in the repository. Admin account creation supports built-in roles; newly created accounts must use a password of at least 12 characters. Some requested functions (such as sending/re-sending notifications, editable provider secrets, MFA enrollment, and PDF/XLSX exports) are not exposed by the current backend and are not simulated by the panel. Enabling the MFA-required setting currently blocks login until an MFA provider is configured rather than accepting a static shared code.

### 5. Run the Automated Tests
```bash
pytest -v
```
