# app/utils.py
from flask import current_app
import logging

def setup_logging():
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("sklio")
    return logger
