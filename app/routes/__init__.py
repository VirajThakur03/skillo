# app/routes/__init__.py
from .auth import auth_bp
from .skills import skills_bp
from .bookings import bookings_bp
from .chat import chat_bp, socket_handlers
from .front import front_bp
from .provider import provider_bp

def register_routes(app):
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(skills_bp, url_prefix="/api/skills")
    app.register_blueprint(bookings_bp, url_prefix="/api/bookings")
    app.register_blueprint(chat_bp, url_prefix="/api/chat")
    app.register_blueprint(front_bp)  # no prefix; serves UI pages
    app.register_blueprint(provider_bp)

    # register socket handlers
    socket_handlers(app)
