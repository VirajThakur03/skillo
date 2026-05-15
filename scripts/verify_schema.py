import os

from sqlalchemy import create_engine, inspect


REQUIRED_BOOKING_COLUMNS = {
    "payment_provider",
    "payment_checkout_session_id",
    "payment_intent_id",
    "payment_ref",
    "promo_discount_amount",
    "amount_payable",
}


def main():
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise SystemExit("DATABASE_URL is required")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("bookings")}
    missing = sorted(REQUIRED_BOOKING_COLUMNS - columns)
    if missing:
        raise SystemExit(f"missing booking columns: {', '.join(missing)}")
    print("schema verification passed")


if __name__ == "__main__":
    main()
