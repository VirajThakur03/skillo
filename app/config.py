# app/config.py
import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret")
    SQLALCHEMY_DATABASE_URI = os.getenv("DATABASE_URL", "sqlite:///dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "jwt-secret")
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

    REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "/app/uploads/documents")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB per file

    ALLOWED_DOCUMENT_EXTENSIONS = {"png", "jpg", "jpeg", "pdf"}

    # 💸 Referral + monetization defaults
    REFERRAL_BONUS_SEEKER = 50.0      # ₹50
    REFERRAL_BONUS_PROVIDER = 50.0    # ₹50 (tune as needed)
    PLATFORM_FEE_DEFAULT = 5.0        # %

    # 📲 WhatsApp integration toggle
    WHATSAPP_ENABLED = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
