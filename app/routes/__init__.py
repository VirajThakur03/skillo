# app/routes/__init__.py
from .auth import auth_bp
from .skills import skills_bp
from .bookings import bookings_bp
from .chat import chat_bp, socket_handlers
from .front import front_bp
from .provider import provider_bp
from .webhooks import webhooks_bp
from .kyc import admin_bp, kyc_bp
from .account import account_bp
from .favorites import favorites_bp
from .promos import promos_bp
from .referrals import referrals_bp, wallet_bp
from .system import system_bp
from .payouts import payouts_bp
from .search import search_bp
from .availability import availability_bp
from .notifications import notifications_bp
from .quotes import quotes_bp
from .ops import ops_bp
from .jobs import jobs_bp
from .wallet import wallet_v2_bp
from .subscriptions import subscriptions_bp

def register_routes(app):
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(skills_bp, url_prefix="/api/skills")
    app.register_blueprint(bookings_bp, url_prefix="/api/bookings")
    app.register_blueprint(chat_bp, url_prefix="/api/chat")
    app.register_blueprint(jobs_bp)
    app.register_blueprint(front_bp)  # no prefix; serves UI pages
    app.register_blueprint(provider_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(kyc_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(favorites_bp)
    app.register_blueprint(promos_bp)
    app.register_blueprint(referrals_bp)
    app.register_blueprint(wallet_bp)
    app.register_blueprint(wallet_v2_bp)
    app.register_blueprint(subscriptions_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(payouts_bp)
    app.register_blueprint(search_bp)
    app.register_blueprint(availability_bp, url_prefix="/api/availability")
    app.register_blueprint(notifications_bp)
    app.register_blueprint(quotes_bp)
    app.register_blueprint(ops_bp)

    # register socket handlers
    socket_handlers(app)

