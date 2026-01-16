import re
import os
from PIL import Image
import pytesseract
from pdf2image import convert_from_path


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
