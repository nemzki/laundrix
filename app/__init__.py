"""Laundrix application factory."""
import logging
import os
from logging.handlers import RotatingFileHandler

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from config import BASE_DIR, get_config
from app.extensions import csrf, db, limiter, login_manager, migrate, oauth, talisman

CSP = {
    "default-src": "'self'",
    "script-src": "'self'",
    "style-src": "'self'",
    "img-src": ["'self'", "data:", "https://lh3.googleusercontent.com"],  # Google avatars
    "object-src": "'none'",
    "base-uri": "'self'",
    "frame-ancestors": "'none'",
}


def create_app(config_class=None):
    app = Flask(__name__)
    config_class = config_class or get_config()
    config_class.validate()
    app.config.from_object(config_class)

    if app.config["BEHIND_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    _init_extensions(app)
    _register_blueprints(app)
    _register_cli(app)
    _configure_logging(app)
    return app


def _init_extensions(app):
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
        permissions_policy={"camera": "()", "microphone": "()", "geolocation": "()"},
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
        return db.session.get(User, int(user_id))


def _register_blueprints(app):
    from app.auth import bp as auth_bp
    from app.catalog import bp as catalog_bp
    from app.core import bp as core_bp
    from app.dashboard import bp as dashboard_bp
    from app.identity import bp as identity_bp
    from app.landing import bp as landing_bp
    from app.orders import bp as orders_bp
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
    app.register_blueprint(tracking_bp)

def _register_cli(app):
    from app.cli import register_commands

    register_commands(app)


def _configure_logging(app):
    if app.debug or app.testing:
        return
    log_dir = os.path.join(BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(log_dir, "laundrix.log"), maxBytes=1_000_000, backupCount=5
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
