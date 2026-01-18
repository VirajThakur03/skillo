# app/utils.py
from flask import current_app
import logging

def setup_logging():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("sklio")
    return logger

def compute_badges(user):
    badges = []

    if user.trust_score >= 50:
        badges.append("Verified Provider")

    if user.trust_score >= 80:
        badges.append("Trusted Pro")

    if user.completed_jobs >= 10:
        badges.append("Top Performer")

    return badges
