import face_recognition
import numpy as np
import cv2
import os

def extract_face_embedding_from_image(image_path):
    img = face_recognition.load_image_file(image_path)
    encodings = face_recognition.face_encodings(img)
    return encodings[0] if encodings else None


def extract_best_frame_embedding(video_path):
    cap = cv2.VideoCapture(video_path)
    embeddings = []

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        enc = face_recognition.face_encodings(rgb)
        if enc:
            embeddings.append(enc[0])

    cap.release()

    return embeddings[0] if embeddings else None


def faces_match(img_embedding, video_embedding, threshold=0.6):
    if img_embedding is None or video_embedding is None:
        return False

    distance = np.linalg.norm(img_embedding - video_embedding)
    return distance < threshold
