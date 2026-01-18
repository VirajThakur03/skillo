import re
import os
from PIL import Image
import pytesseract
from pdf2image import convert_from_path
import cv2
import numpy as np

def extract_text(file_path):
    if not os.path.exists(file_path):
        raise Exception("File does not exist")

    text = ""

    if file_path.lower().endswith(".pdf"):
        pages = convert_from_path(file_path, dpi=300)
        if not pages:
            raise Exception("PDF conversion failed")

        for p in pages[:2]:
            text += pytesseract.image_to_string(p)

    else:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img)

    if not text.strip():
        raise Exception("No readable text found")

    return text.lower()


def validate_document(text, doc_type):
    doc_type = doc_type.lower()

    if doc_type == "aadhaar":
        return bool(re.search(r"\b\d{4}\s?\d{4}\s?\d{4}\b", text))

    if doc_type == "driving":
        return bool(re.search(r"[A-Z]{2}\d{2}\s?\d{11}", text))

    if doc_type == "passport":
        return bool(re.search(r"[A-Z]\d{7}", text))

    return True


def is_blurry(file_path, threshold=100):
    # File does not exist
    if not os.path.exists(file_path):
        return False

    img = cv2.imread(file_path)

    # 🚨 CRITICAL FIX
    if img is None:
        # Not an image (PDF / corrupted / unsupported)
        return False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()

    return variance < threshold


def is_screenshot(file_path):
    if not os.path.exists(file_path):
        return False

    img = cv2.imread(file_path)

    # ✅ VERY IMPORTANT CHECK
    if img is None:
        # Not an image (PDF / unsupported / corrupted)
        return False

    h, w = img.shape[:2]

    # Screenshot heuristic (example)
    aspect_ratio = w / h if h else 0

    if aspect_ratio > 1.6 and w > 800:
        return True

    return False