# app/verify/face_verify.py

import os

try:
    import cv2
except ModuleNotFoundError:  # pragma: no cover - depends on runtime env
    cv2 = None

try:
    import numpy as np
except ModuleNotFoundError:  # pragma: no cover - depends on runtime env
    np = None

# =========================
# FACE DETECTOR (HAAR)
# =========================
FACE_CASCADE = (
    cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cv2 is not None
    else None
)

# =========================
# LBPH RECOGNIZER FACTORY
# =========================
def create_recognizer():
    """
    LBPH is robust to:
    - beard / no beard
    - lighting
    - small age changes
    """
    if cv2 is None or not hasattr(cv2, "face"):
        return None
    return cv2.face.LBPHFaceRecognizer_create(
        radius=2,
        neighbors=8,
        grid_x=8,
        grid_y=8
    )

# =========================
# INTERNAL FACE DETECTOR
# =========================
def _detect_face(gray):
    """
    Detect face and return BEARD-SAFE crop (upper 65%)
    """
    if FACE_CASCADE is None:
        return None
    faces = FACE_CASCADE.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(80, 80)
    )

    if len(faces) == 0:
        return None

    x, y, w, h = faces[0]

    # 🔥 Beard-safe crop
    return gray[y : y + int(h * 0.65), x : x + w]

# =========================
# FACE DETECTOR
# =========================
def extract_face_from_image(image_path):
    """
    Extract a single face from an image file (selfie / document fallback)
    Returns grayscale face crop or None
    """
    if not image_path or not os.path.exists(image_path):
        return None
    if cv2 is None:
        return None

    img = cv2.imread(image_path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face = _detect_face(gray)

    return face


# =========================
# DOCUMENT FACE (SAVE ONCE)
# =========================
def extract_and_save_document_face(doc_path, output_path):
    if cv2 is None:
        return False
    img = cv2.imread(doc_path)
    if img is None:
        return False

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    face = _detect_face(gray)

    if face is None:
        return False

    cv2.imwrite(output_path, face)
    return True

# =========================
# LOAD SAVED FACE
# =========================
def load_document_face(face_path):
    if not face_path or not os.path.exists(face_path):
        return None
    if cv2 is None:
        return None

    return cv2.imread(face_path, cv2.IMREAD_GRAYSCALE)

# =========================
# VIDEO FACE EXTRACTION
# =========================
def extract_video_faces(video_path, max_faces=20, max_frames=120):
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        cap.release()
        return None
    faces = []
    frame_count = 0

    while cap.isOpened() and frame_count < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face = _detect_face(gray)

        if face is not None:
            faces.append(face)

        if len(faces) >= max_faces:
            break

        frame_count += 1

    cap.release()
    return faces

# =========================
# FACE MATCH (MULTI FRAME)
# =========================
def faces_match(reference_face, video_faces, threshold=85, min_matches=3):
    if reference_face is None or not video_faces:
        return False

    recognizer = create_recognizer()
    if recognizer is None or np is None:
        return False
    recognizer.train([reference_face], np.array([0]))

    good_matches = 0

    for vf in video_faces:
        try:
            _, confidence = recognizer.predict(vf)
        except Exception:
            continue

        if confidence < threshold:
            good_matches += 1

        if good_matches >= min_matches:
            return True

    return False
