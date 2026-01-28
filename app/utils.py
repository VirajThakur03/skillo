# app/utils.py
from flask import current_app
import logging
from math import radians, sin, cos, sqrt, atan2
 
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

def haversine(lat1, lon1, lat2, lon2):
    """
    Calculate distance between two lat/lon points in KM
    """
    R = 6371  # Earth radius in km

    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)

    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1))
        * cos(radians(lat2))
        * sin(dlon / 2) ** 2
    )

    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c