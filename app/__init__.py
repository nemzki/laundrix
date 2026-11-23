"""Laundrix application factory."""
import logging

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import get_config
from app.extensions import csrf, db, limiter, login_manager, migrate, oauth, talisman

CSP = {
    "default-src": "'self'",
    "script-src": "'self'",
    "style-src": "'self'",
    "font-src": "'self'",
    "img-src": ["'self'", "data:", "https://lh3.googleusercontent.com"],  # Google avatars
    "object-src": "'none'",
    "base-uri": "'self'",
    "frame-ancestors": "'none'",
}


def create_app(config_class=None):
    """Application factory: build and return a fully configured Flask app.

    Steps: load and validate the config, set up proxy support, connect the extensions,
    add the account-status check to every request, register the blueprints and CLI
    commands, then set up logging."""
    app = Flask(__name__)
    config_class = config_class or get_config()
    config_class.validate()
    app.config.from_object(config_class)

    if app.config["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _init_extensions(app)
    from app.core.account_gate import enforce_account_status

    app.before_request(enforce_account_status)   # default-deny account-state check on every request
    _register_blueprints(app)
    _register_cli(app)
    _configure_logging(app)
    return app


def _init_extensions(app):
    """Connect every extension (database, CSRF, limiter, login, security headers, Google OAuth) to the app.

    Also sets the security headers (HTTPS, CSP, camera permission) and tells Flask-Login how to
    load a user from the id stored in the session."""
    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    talisman.init_app(
        app,
        force_https=app.config["FORCE_HTTPS"],
        session_cookie_secure=app.config["SESSION_COOKIE_SECURE"],
        content_security_policy=CSP,
        frame_options="DENY",
        referrer_policy="strict-origin-when-cross-origin",
        permissions_policy={
            "camera": "(self)",
            "microphone": "()",
            "geolocation": "()",
        },
    )

    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    if not app.config["GOOGLE_CLIENT_ID"] or not app.config["GOOGLE_CLIENT_SECRET"]:
        app.logger.warning("Google OAuth credentials are not set; sign-in will not work.")

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        """Flask-Login callback: load the User row for the id saved in the session cookie."""
        return db.session.get(User, int(user_id))


def _register_blueprints(app):
    """Register every feature blueprint and give each one its URL prefix.

    For example the orders blueprint is served under /orders and analytics under /admin/analytics."""
    from app.audit import bp as audit_bp
    from app.analytics import bp as analytics_bp
    from app.auth import bp as auth_bp
    from app.catalog import bp as catalog_bp
    from app.core import bp as core_bp
    from app.dashboard import bp as dashboard_bp
    from app.identity import bp as identity_bp
    from app.landing import bp as landing_bp
    from app.orders import bp as orders_bp
    from app.payments import bp as payments_bp
    from app.staff_admin import bp as staff_admin_bp
    from app.staff_auth import bp as staff_bp
    from app.tracking import bp as tracking_bp

    app.register_blueprint(core_bp)
    app.register_blueprint(landing_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(staff_bp, url_prefix="/staff")
    app.register_blueprint(identity_bp, url_prefix="/identity")
    app.register_blueprint(dashboard_bp, url_prefix="/dashboard")
    app.register_blueprint(catalog_bp, url_prefix="/admin/services")
    app.register_blueprint(orders_bp, url_prefix="/orders")
    app.register_blueprint(payments_bp, url_prefix="/payments")
    app.register_blueprint(staff_admin_bp, url_prefix="/admin/staff")
    app.register_blueprint(audit_bp, url_prefix="/admin/audit-logs")
    app.register_blueprint(analytics_bp, url_prefix="/admin/analytics")
    app.register_blueprint(tracking_bp)

def _register_cli(app):
    """Register the custom `flask ...` commands defined in app/cli.py."""
    from app.cli import register_commands

    register_commands(app)



def _configure_logging(app):
    """Send log messages to the console at INFO level.

    Skipped in debug and testing modes, where Flask's own logging is enough."""
    if app.debug or app.testing:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(name)s] %(message)s"
        )
    )
    handler.setLevel(logging.INFO)

    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)