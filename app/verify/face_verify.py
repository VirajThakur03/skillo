import cv2
import numpy as np
import os

# =========================
# FACE DETECTOR
# =========================
FACE_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)

# LBPH recognizer
def create_recognizer():
    return cv2.face.LBPHFaceRecognizer_create(
        radius=2,
        neighbors=8,
        grid_x=8,
        grid_y=8
    )


# =========================
# INTERNAL HELPERS
# =========================
def _detect_face(gray):
    faces = FACE_CASCADE.detectMultiScale(
    gray,
    scaleFactor=1.1,
    minNeighbors=4,
    minSize=(60, 60)
)

    if len(faces) == 0:
        return None

    x, y, w, h = faces[0]

    # 🔥 BEARD SAFE: upper 65% only
    return gray[y:y + int(h * 0.65), x:x + w]


# =========================
# DOCUMENT FACE (SAVE ONCE)
# =========================
def extract_and_save_document_face(doc_path, output_path):
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
# LOAD DOCUMENT FACE
# =========================
def load_document_face(face_path):
    if not os.path.exists(face_path):
        return None

    face = cv2.imread(face_path, cv2.IMREAD_GRAYSCALE)
    return face


# =========================
# VIDEO FACE FRAMES
# =========================
def extract_video_faces(video_path, max_frames=15):
    cap = cv2.VideoCapture(video_path)
    faces = []

    while cap.isOpened() and len(faces) < max_frames:
        ret, frame = cap.read()
        if not ret:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face = _detect_face(gray)
        if face is not None:
            faces.append(face)

    cap.release()
    return faces


# =========================
# FACE MATCH (MULTI FRAME)
# =========================
def faces_match(doc_face, video_faces, threshold=85):
    if doc_face is None or not video_faces:
        return False

    recognizer = create_recognizer()

    # Train once with document
    recognizer.train([doc_face], np.array([0]))

    good_matches = 0

    for vf in video_faces:
        label, confidence = recognizer.predict(vf)

        # 🔥 Lower confidence = better match
        if confidence < threshold:
            good_matches += 1

    # Require at least 3 matching frames
    return good_matches >= 3
