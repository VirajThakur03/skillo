# app/integrations/whatsapp.py
import os

def send_whatsapp_message(phone: str, message: str):
    """
    Stub for WhatsApp integration.
    In production: integrate Twilio WhatsApp API or Meta WhatsApp Cloud API here.
    For now, we just print to logs so you see when it would trigger.
    """
    enabled = os.getenv("WHATSAPP_ENABLED", "false").lower() == "true"
    if not enabled:
        print(f"[WHATSAPP DISABLED] Would send to {phone}: {message}")
        return

    # Example skeleton (Twilio style) – not active!
    # from twilio.rest import Client
    # account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    # auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    # client = Client(account_sid, auth_token)
    # from_number = os.getenv("TWILIO_WHATSAPP_FROM")
    # client.messages.create(
    #     body=message,
    #     from_=f"whatsapp:{from_number}",
    #     to=f"whatsapp:{phone}"
    # )

    print(f"[WHATSAPP STUB] To {phone}: {message}")
