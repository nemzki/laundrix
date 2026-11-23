"""Central configuration. All secrets come from environment variables (.env)."""
import math
import os
from datetime import timedelta

from dotenv import load_dotenv
from sqlalchemy.engine import URL

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _bool(name: str, default: bool = False) -> bool:
    """Read an environment variable as True/False.

    Returns True when the value is 1, true, yes or on (any letter case); anything else
    (or a missing variable) falls back to `default`."""
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    """Numeric env var; anything missing, non-numeric or not positive falls back to the default."""
    try:
        value = float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _database_uri() -> str:
    """Build the MySQL connection URL from the DB_* environment variables.

    Uses SQLAlchemy's URL.create so special characters in the password are escaped safely
    instead of breaking the URL."""
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


def _database_engine_options() -> dict:
    """Build the extra options SQLAlchemy uses when it connects to the database.

    pool_pre_ping tests a connection before using it, and pool_recycle replaces connections
    before the server closes them. If DB_SSL_CA is set, the SSL (TLS) options are added too."""
    options = {
        "pool_pre_ping": True,
        "pool_recycle": 280,
    }

    ssl_ca = (os.getenv("DB_SSL_CA") or "").strip()

    if ssl_ca:
        options["connect_args"] = {
            "ssl_ca": ssl_ca,
            "ssl_verify_cert": _bool("DB_SSL_VERIFY_CERT", True),
            "ssl_verify_identity": _bool("DB_SSL_VERIFY_IDENTITY", True),
        }

    return options


class BaseConfig:
    """Settings shared by every environment.

    Each value is read from an environment variable (your .env file), so secrets stay out
    of the code. The Development, Production and Testing classes below extend this one."""
    ENV_NAME = "development"

    # --- Core ---
    SECRET_KEY = os.getenv("SECRET_KEY")
    BEHIND_PROXY = _bool("BEHIND_PROXY")
    APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # reject request bodies > 2 MB (webhooks are small)

    # --- File storage ---
    PROFILE_AVATAR_DIR = os.getenv("PROFILE_AVATAR_DIR") or None
    PAYMENT_UPLOAD_DIR = os.getenv("PAYMENT_UPLOAD_DIR") or None

    # --- Database ---
    SQLALCHEMY_DATABASE_URI = _database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = _database_engine_options()

    # --- Google OAuth (admins) ---
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_ALLOWED_DOMAIN = (os.getenv("GOOGLE_ALLOWED_DOMAIN") or "").strip().lower() or None

    # --- Initial administrator (read ONLY by `flask bootstrap-admin`; remove the password afterwards) ---
    INITIAL_ADMIN_USERNAME = (os.getenv("INITIAL_ADMIN_USERNAME") or "").strip().lower() or None
    INITIAL_ADMIN_PASSWORD = os.getenv("INITIAL_ADMIN_PASSWORD") or None
    INITIAL_ADMIN_EMAIL = (os.getenv("INITIAL_ADMIN_EMAIL") or "").strip().lower() or None

    # --- Administrator password sign-in ---
    # --- Administrator password sign-in (Google OAuth remains available separately) ---
    # Read by app/auth/credentials.py; default on so username/email + password works locally.
    ADMIN_PASSWORD_LOGIN_ENABLED = _bool("ADMIN_PASSWORD_LOGIN_ENABLED", True)

    # --- Staff portal (email + password, Google, or Face Login against Didit-verified staff) ---
    STAFF_GOOGLE_LOGIN_ALLOWED = _bool("STAFF_GOOGLE_LOGIN_ALLOWED", True)
    # Face Login matching (Didit Face Search, 0-100). Calibrate from the diagnostic log lines.
    FACE_LOGIN_MIN_SIMILARITY = float(os.getenv("FACE_LOGIN_MIN_SIMILARITY", "90"))
    FACE_LOGIN_MIN_MARGIN = float(os.getenv("FACE_LOGIN_MIN_MARGIN", "5"))
    STAFF_MAX_FAILED_ATTEMPTS = int(os.getenv("STAFF_MAX_FAILED_ATTEMPTS", "5"))
    STAFF_LOCKOUT_MINUTES = int(os.getenv("STAFF_LOCKOUT_MINUTES", "15"))
    STAFF_LOGIN_WINDOW_SECONDS = int(os.getenv("STAFF_LOGIN_WINDOW_SECONDS", "600"))
    STAFF_ENROLL_TOKEN_HOURS = int(os.getenv("STAFF_ENROLL_TOKEN_HOURS", "24"))

    # --- SMS notifications (UniSMS). Off by default; the secret is read only on the server. ---
    SMS_ENABLED = _bool("SMS_ENABLED", False)
    UNISMS_API_BASE_URL = (os.getenv("UNISMS_API_BASE_URL") or "https://unismsapi.com/api").strip().rstrip("/")
    UNISMS_API_SECRET_KEY = (os.getenv("UNISMS_API_SECRET_KEY") or "").strip() or None
    UNISMS_SENDER_ID = (os.getenv("UNISMS_SENDER_ID") or "Unisoft").strip()
    SMS_CONNECT_TIMEOUT = _float("SMS_CONNECT_TIMEOUT", 3.05)
    SMS_READ_TIMEOUT = _float("SMS_READ_TIMEOUT", 10.0)

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
        """Stop the app at startup if required settings are missing.

        Raises a clear error listing every missing environment variable, then runs the extra
        identity-verification and SMS checks."""
        missing = [k for k in cls.REQUIRED_ENV if os.getenv(k) is None]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}. "
                "Copy .env.example to .env and fill them in."
            )
        cls._validate_identity_verification()
        cls._validate_sms()

    @classmethod
    def _validate_sms(cls):
        """Fail fast on a half-configured SMS setup. Never echoes the secret."""
        if not cls.SMS_ENABLED:
            return
        if not cls.UNISMS_API_SECRET_KEY:
            raise RuntimeError("SMS_ENABLED=true but UNISMS_API_SECRET_KEY is not set.")
        if not cls.UNISMS_API_BASE_URL.startswith("https://"):
            raise RuntimeError("UNISMS_API_BASE_URL must be an https:// URL.")

    @classmethod
    def _validate_identity_verification(cls):
        """Check the Didit identity-verification settings.

        Only runs when IDV_ENABLED is on. It makes sure the API key, workflow id and webhook
        secret exist, the environment is 'sandbox' or 'live', and the base URL uses https."""
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
    """Settings for working on your own computer (debug mode on)."""
    DEBUG = True


class ProductionConfig(BaseConfig):
    """Settings for the live site (for example on Render).

    Debug is off, cookies are HTTPS-only and every request is forced onto HTTPS."""
    ENV_NAME = "production"
    DEBUG = False
    SESSION_COOKIE_SECURE = True
    FORCE_HTTPS = True
    PREFERRED_URL_SCHEME = "https"

    @classmethod
    def validate(cls):
        """Run the base checks plus extra production-only safety checks.

        Requires an https APP_BASE_URL, requires Didit to be in 'live' mode and refuses to start
        if a Didit sandbox test scenario is still set."""
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
    """Settings used by the automated tests.

    Uses an in-memory SQLite database, turns off CSRF, the rate limiter and real SMS, and
    pins fixed fake keys so a developer's .env can never change a test result."""
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
    SMS_ENABLED = False                 # tests never contact the SMS provider, whatever .env says
    FACE_LOGIN_MIN_SIMILARITY = 90.0    # pinned so a developer's .env calibration can't change test outcomes
    FACE_LOGIN_MIN_MARGIN = 5.0
    UNISMS_API_SECRET_KEY = None
    INITIAL_ADMIN_USERNAME = INITIAL_ADMIN_PASSWORD = INITIAL_ADMIN_EMAIL = None   # never taken from a developer .env

    @classmethod
    def validate(cls):
        """Skip the environment checks, because tests use the fake values defined above."""
        pass


CONFIGS = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}


def get_config():
    """Pick the config class that matches the APP_ENV environment variable.

    'production' and 'testing' map to their classes; anything else uses DevelopmentConfig."""
    return CONFIGS.get(os.getenv("APP_ENV", "development").lower(), DevelopmentConfig)