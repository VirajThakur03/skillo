# app/__init__.py
from flask import Flask
from .config import Config
from .extensions import socketio, db, migrate, bcrypt, jwt
from .routes import register_routes
import logging


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class)

    # Basic logging setup
    logging.basicConfig(level=logging.INFO)
    app.logger.info("Sklio backend starting…")

    # Init extensions
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")

    # Register blueprints / routes
    register_routes(app)

    @app.route("/ping")
    def ping():
        return {"status": "ok", "service": "sklio-backend"}

    return app
