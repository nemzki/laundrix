"""Central configuration. All secrets come from environment variables (.env)."""
import os
from datetime import timedelta

from dotenv import load_dotenv
from sqlalchemy.engine import URL

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _database_uri() -> str:
    # URL.create safely escapes special characters in passwords.
    return URL.create(
        drivername="mysql+pymysql",
        username=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME", "laundrix_db"),
        query={"charset": "utf8mb4"},
    ).render_as_string(hide_password=False)


class BaseConfig:
    ENV_NAME = "development"

    # --- Core ---
    SECRET_KEY = os.getenv("SECRET_KEY")
    BEHIND_PROXY = _bool("BEHIND_PROXY")
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # reject request bodies > 2 MB (webhooks are small)

    # --- Database ---
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True, "pool_recycle": 280}

    # --- Google OAuth (admins) ---
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_ALLOWED_DOMAIN = (os.getenv("GOOGLE_ALLOWED_DOMAIN") or "").strip().lower() or None

    # --- Staff portal (email + Staff ID + face check by Didit Biometric Authentication) ---
    STAFF_GOOGLE_LOGIN_ALLOWED = _bool("STAFF_GOOGLE_LOGIN_ALLOWED", False)
    STAFF_MAX_FAILED_ATTEMPTS = int(os.getenv("STAFF_MAX_FAILED_ATTEMPTS", "5"))
    STAFF_LOCKOUT_MINUTES = int(os.getenv("STAFF_LOCKOUT_MINUTES", "15"))
    STAFF_LOGIN_WINDOW_SECONDS = int(os.getenv("STAFF_LOGIN_WINDOW_SECONDS", "600"))
    STAFF_ENROLL_TOKEN_HOURS = int(os.getenv("STAFF_ENROLL_TOKEN_HOURS", "24"))

    # --- Identity verification (ID + liveness + face match via Didit hosted flow) ---
    # Disabled by default so the app boots without any provider credentials.
    IDV_ENABLED = _bool("IDV_ENABLED", False)
    IDV_PROVIDER = os.getenv("IDV_PROVIDER", "didit").lower()
    DIDIT_API_KEY = os.getenv("DIDIT_API_KEY")
    DIDIT_WORKFLOW_ID = os.getenv("DIDIT_WORKFLOW_ID")
    DIDIT_WEBHOOK_SECRET = os.getenv("DIDIT_WEBHOOK_SECRET")
    DIDIT_BASE_URL = os.getenv("DIDIT_BASE_URL", "https://verification.didit.me").rstrip("/")
    # Which Didit application mode this deployment expects: its webhooks carry
    # "environment": "sandbox" | "live". Mismatching events are ignored.
    DIDIT_ENVIRONMENT = os.getenv("DIDIT_ENVIRONMENT", "sandbox").lower()
    DIDIT_SANDBOX_SCENARIO = (os.getenv("DIDIT_SANDBOX_SCENARIO") or "").strip() or None
    IDV_MAX_ATTEMPTS = int(os.getenv("IDV_MAX_ATTEMPTS", "3"))
    IDV_ATTEMPT_WINDOW_HOURS = int(os.getenv("IDV_ATTEMPT_WINDOW_HOURS", "24"))
    IDV_RETENTION_DAYS = int(os.getenv("IDV_RETENTION_DAYS", "365"))
    IDV_POLL_COOLDOWN_SECONDS = int(os.getenv("IDV_POLL_COOLDOWN_SECONDS", "15"))
    IDV_HTTP_CONNECT_TIMEOUT = float(os.getenv("IDV_HTTP_CONNECT_TIMEOUT", "3.05"))
    IDV_HTTP_READ_TIMEOUT = float(os.getenv("IDV_HTTP_READ_TIMEOUT", "10"))
    IDV_PRIVACY_CONTACT_EMAIL = (os.getenv("IDV_PRIVACY_CONTACT_EMAIL") or "").strip() or None

    # Staff sign-in: a Didit "Biometric Authentication" workflow re-checks a returning person's face
    # (liveness + match against the portrait Didit stored during their ID verification).
    DIDIT_BIOMETRIC_WORKFLOW_ID = (os.getenv("DIDIT_BIOMETRIC_WORKFLOW_ID") or "").strip() or None
    IDV_BIOMETRIC_MAX_PER_HOUR = int(os.getenv("IDV_BIOMETRIC_MAX_PER_HOUR", "6"))      # caps cost abuse
    IDV_BIOMETRIC_POLL_COOLDOWN_SECONDS = int(os.getenv("IDV_BIOMETRIC_POLL_COOLDOWN_SECONDS", "3"))
    IDV_BIOMETRIC_RETENTION_DAYS = int(os.getenv("IDV_BIOMETRIC_RETENTION_DAYS", "90"))

    # --- Sessions / cookies ---
    PERMANENT_SESSION_LIFETIME = timedelta(
        minutes=int(os.getenv("SESSION_LIFETIME_MINUTES", "480"))
    )
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"  # Lax is required for the OAuth redirect back
    SESSION_COOKIE_SECURE = False

    # --- Security ---
    WTF_CSRF_TIME_LIMIT = 3600
    FORCE_HTTPS = False
    RATELIMIT_STORAGE_URI = os.getenv("RATELIMIT_STORAGE_URI", "memory://")

    REQUIRED_ENV = ("SECRET_KEY", "DB_USER", "DB_PASSWORD")

    @classmethod
    def validate(cls):
        missing = [k for k in cls.REQUIRED_ENV if os.getenv(k) is None]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill them in."
            )
        cls._validate_identity_verification()

    @classmethod
    def _validate_identity_verification(cls):
        if not cls.IDV_ENABLED:
            return
        if cls.IDV_PROVIDER != "didit":
            raise RuntimeError("IDV_PROVIDER must be 'didit'.")
        missing = [
            name for name in ("DIDIT_API_KEY", "DIDIT_WORKFLOW_ID", "DIDIT_WEBHOOK_SECRET")
            if not getattr(cls, name)
        ]
        if missing:
            raise RuntimeError(
                f"IDV_ENABLED=true but these are not set: {', '.join(missing)}."
            )
        if cls.DIDIT_ENVIRONMENT not in {"sandbox", "live"}:
            raise RuntimeError("DIDIT_ENVIRONMENT must be 'sandbox' or 'live'.")
        if not cls.DIDIT_BASE_URL.startswith("https://"):
            raise RuntimeError("DIDIT_BASE_URL must be an https:// URL.")


class DevelopmentConfig(BaseConfig):
    DEBUG = True


class ProductionConfig(BaseConfig):
    ENV_NAME = "production"
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    FORCE_HTTPS = True
    PREFERRED_URL_SCHEME = "https"

    @classmethod
    def validate(cls):
        super().validate()
        if not cls.APP_BASE_URL.startswith("https://"):
            raise RuntimeError("APP_BASE_URL must be an https:// URL in production.")
        if cls.IDV_ENABLED and cls.DIDIT_ENVIRONMENT != "live":
            raise RuntimeError(
                "DIDIT_ENVIRONMENT must be 'live' in production: a sandbox application "
                "returns mocked results and must never verify real users."
            )
        if cls.DIDIT_SANDBOX_SCENARIO:
            raise RuntimeError("DIDIT_SANDBOX_SCENARIO must not be set in production.")


class TestingConfig(BaseConfig):
    ENV_NAME = "testing"
    TESTING = True
    SECRET_KEY = "test-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    SQLALCHEMY_ENGINE_OPTIONS = {}
    WTF_CSRF_ENABLED = False
    GOOGLE_CLIENT_ID = "test"
    GOOGLE_CLIENT_SECRET = "test"
    RATELIMIT_ENABLED = False
    DIDIT_BIOMETRIC_WORKFLOW_ID = "bio-workflow-id"
    IDV_ENABLED = True
    DIDIT_API_KEY = "test-api-key"
    DIDIT_WORKFLOW_ID = "11111111-2222-3333-4444-555555555555"
    DIDIT_WEBHOOK_SECRET = "test-webhook-secret"
    DIDIT_ENVIRONMENT = "sandbox"

    @classmethod
    def validate(cls):
        pass


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    return CONFIGS.get(os.getenv("APP_ENV", "development").lower(), DevelopmentConfig)