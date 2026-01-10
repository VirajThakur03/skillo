# app/ai/profile_gen.py
import os

OPENAI_AVAILABLE = False
try:
    import openai
    OPENAI_AVAILABLE = True
except Exception:
    OPENAI_AVAILABLE = False

from ..config import Config

def generate_profile(provider_name, skill, experience_years=1, city=""):
    """
    Generates a short professional profile for a provider.
    If OPENAI_API_KEY is set and openai package available, use it; otherwise return a templated string.
    """
    api_key = os.getenv("OPENAI_API_KEY") or Config.OPENAI_API_KEY
    prompt = f"Write a 2-3 sentence professional bio for {provider_name}, a {skill} with {experience_years} years experience based in {city}. " \
             f"Make it friendly, concise, and include 1 sentence about services offered."

    if api_key and OPENAI_AVAILABLE:
        openai.api_key = api_key
        try:
            resp = openai.Completion.create(
                model="text-davinci-003",
                prompt=prompt,
                max_tokens=120,
                temperature=0.6
            )
            text = resp.choices[0].text.strip()
            return {"source": "openai", "text": text}
        except Exception as e:
            return {"source": "error", "text": f"Error calling OpenAI: {str(e)}"}
    else:
        # fallback templated response
        text = f"{provider_name} is a skilled {skill} with {experience_years} year(s) of experience in {city}. " \
               f"They provide reliable, friendly service for both small jobs and larger projects. Contact to discuss availability and pricing."
        return {"source": "template", "text": text}
