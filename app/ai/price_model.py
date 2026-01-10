# app/ai/price_model.py
import os
import joblib

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "ml", "models", "price_model.joblib")
model = None

def load_model():
    global model
    try:
        model = joblib.load(MODEL_PATH)
    except Exception:
        model = None

def predict(features: dict):
    """
    features: dict containing numeric or encoded features.
    If model exists, call it; otherwise return a simple heuristic.
    """
    if model is None:
        # simple heuristic: base by skill category length + experience
        base = 300.0
        exp = float(features.get("experience_years", 1))
        demand = float(features.get("demand_score", 1))
        price = base * (1 + exp * 0.05) * demand
        return {"source": "heuristic", "price": round(price, 2)}
    else:
        # convert features to ordered vector required by model
        # NOTE: keep model training conventions consistent.
        X = [features.get(k, 0) for k in sorted(features.keys())]
        pred = model.predict([X])[0]
        return {"source": "model", "price": float(pred)}

# try to load on import
load_model()
