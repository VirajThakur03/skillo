import re
from collections import Counter


DANGER_KEYWORDS = {
    "gas leak",
    "sparking",
    "fire",
    "burning smell",
    "smoke",
    "shock",
}

SERVICE_HINTS = {
    "electrician": ["switch", "wire", "wiring", "power", "socket", "light", "fan"],
    "plumber": ["leak", "pipe", "tap", "drain", "toilet", "faucet"],
    "ac repair": ["ac", "cooling", "compressor", "air conditioner", "not cooling"],
    "cleaning": ["clean", "deep clean", "sofa", "bathroom", "kitchen"],
    "carpenter": ["wood", "door", "cabinet", "shelf", "hinge"],
}


def infer_job_intake(text, selected_category=None):
    lowered = (text or "").strip().lower()
    recommended_category = selected_category or ""
    best_score = 0
    for category, hints in SERVICE_HINTS.items():
        score = sum(1 for hint in hints if hint in lowered)
        if score > best_score:
            best_score = score
            recommended_category = category

    request_mode = "quote_request" if any(
        word in lowered for word in ["inspect", "inspection", "diagnose", "quote", "estimate", "custom"]
    ) else "instant_booking"
    if any(word in lowered for word in ["replace", "multiple", "renovation", "unknown"]):
        request_mode = "quote_request"

    safety_flag = any(keyword in lowered for keyword in DANGER_KEYWORDS)
    missing_fields = []
    if not recommended_category:
        missing_fields.append("category")
    if not re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)?\b", lowered):
        missing_fields.append("preferred_time")
    if not re.search(r"\b(home|office|flat|street|road|near|address)\b", lowered):
        missing_fields.append("address")

    clean_title = " ".join((text or "").strip().split())[:80] or "Service request"
    clean_summary = clean_title
    urgency = "high" if safety_flag else "medium" if "urgent" in lowered else "low"

    confidence = 0.35 + min(best_score * 0.15, 0.45)
    if selected_category:
        confidence += 0.1
    confidence = min(confidence, 0.95)

    return {
        "recommended_category": recommended_category,
        "request_mode": request_mode,
        "clean_title": clean_title,
        "clean_summary": clean_summary,
        "urgency": urgency,
        "missing_fields": missing_fields,
        "safety_flag": safety_flag,
        "safety_reason": "Potentially hazardous issue detected." if safety_flag else "",
        "suggested_tags": [recommended_category] if recommended_category else [],
        "confidence": round(confidence, 2),
    }


def rank_provider_match(query_text, candidates):
    lowered = (query_text or "").lower()
    ranked = []
    for candidate in candidates:
        text_score = 0
        haystack = " ".join(
            [
                candidate.get("service_title", ""),
                candidate.get("description", ""),
                " ".join(candidate.get("badges", []) or []),
            ]
        ).lower()
        for token in set(lowered.split()):
            if token and token in haystack:
                text_score += 8

        rating_score = float(candidate.get("rating") or 0) * 10
        distance_score = max(0, 30 - float(candidate.get("distance_km") or 30))
        availability_score = 12 if candidate.get("open_now") else 6 if candidate.get("next_available_at") else 0
        trust_score = 4 * len(candidate.get("badges", []) or [])
        overall = round(text_score + rating_score + distance_score + availability_score + trust_score, 2)
        ranked.append(
            {
                "provider_id": candidate.get("provider_id"),
                "overall_score": overall,
                "reason": (
                    "Strong fit on trust, availability, and service match."
                    if overall >= 55
                    else "Relevant option with usable availability."
                ),
            }
        )

    ranked.sort(key=lambda item: item["overall_score"], reverse=True)
    return ranked


def summarize_chat(messages):
    cleaned = [message.strip() for message in messages if message and message.strip()]
    if not cleaned:
        return {
            "reply_suggestions": [],
            "summary": "No conversation yet.",
            "extracted": {
                "mentioned_time": "",
                "mentioned_address": "",
                "action_items": [],
            },
        }

    last_message = cleaned[-1]
    lowered = " ".join(cleaned).lower()
    mentioned_time_match = re.search(r"\b\d{1,2}(:\d{2})?\s*(am|pm)?\b", lowered)
    mentioned_address_match = re.search(r"(near [a-z0-9 ,.-]+|flat [a-z0-9 ,.-]+|address[: ]+[a-z0-9 ,.-]+)", lowered)

    quick_replies = [
        "I'm on the way.",
        "Please share a landmark.",
        "Confirmed. See you soon.",
    ]
    if "price" in lowered or "cost" in lowered:
        quick_replies[1] = "I'll confirm the cost after inspection."
    if "late" in lowered or "delay" in lowered:
        quick_replies[0] = "I'm delayed but heading there now."

    action_items = []
    if "call" in lowered:
        action_items.append("Call before arrival")
    if "gate" in lowered or "landmark" in lowered:
        action_items.append("Check landmark or gate instructions")

    return {
        "reply_suggestions": quick_replies,
        "summary": last_message[:180],
        "extracted": {
            "mentioned_time": mentioned_time_match.group(0) if mentioned_time_match else "",
            "mentioned_address": mentioned_address_match.group(0) if mentioned_address_match else "",
            "action_items": action_items,
        },
    }


def summarize_reviews(reviews):
    if not reviews:
        return {
            "trust_signals": {
                "punctuality": "insufficient_data",
                "quality": "insufficient_data",
                "communication": "insufficient_data",
                "value": "insufficient_data",
            },
            "summary": "",
            "evidence_phrases": [],
        }

    def bucket(values):
        if not values:
            return "insufficient_data"
        avg = sum(values) / len(values)
        if avg >= 4.4:
            return "strong"
        if avg >= 3.2:
            return "mixed"
        return "weak"

    evidence_terms = []
    for review in reviews:
        if review.get("comment"):
            evidence_terms.extend(re.findall(r"[a-zA-Z]{4,}", review["comment"].lower()))
    common_terms = [item for item, _ in Counter(evidence_terms).most_common(3)]

    return {
        "trust_signals": {
            "punctuality": bucket([item.get("punctuality_rating") for item in reviews if item.get("punctuality_rating") is not None]),
            "quality": bucket([item.get("quality_rating") for item in reviews if item.get("quality_rating") is not None]),
            "communication": bucket([item.get("communication_rating") for item in reviews if item.get("communication_rating") is not None]),
            "value": bucket([item.get("value_rating") for item in reviews if item.get("value_rating") is not None]),
        },
        "summary": "Common themes: " + ", ".join(common_terms) if common_terms else "Ratings are available but written themes are limited.",
        "evidence_phrases": common_terms,
    }
