# seeds/seed_data.py
import os
import sys
import traceback

# ensure project root (/app) is on sys.path so `import app` works when run from container
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app import create_app

# create and push app context BEFORE importing extensions/models that may rely on current_app
app = create_app()
app.app_context().push()

# now import extensions and models while the app context is active
from app.extensions import db, bcrypt
from app.models import User, Skill

def seed():
    try:
        if User.query.filter_by(email="provider@sklio.test").first():
            print("Seed appears to exist already. Skipping.")
            return

        provider = User(
            name="Rohit Sharma",
            email="provider@sklio.test",
            phone="9999999999",
            role="PROVIDER",
            bio="Experienced handyman and electrician.",
            location="Pune"
        )

        # If your User model has a set_password method that uses bcrypt, this is fine.
        # If it expects only the plaintext, adjust accordingly.
        if hasattr(provider, "set_password"):
            provider.set_password("password123", bcrypt)
        else:
            # fallback: if your User model expects password field directly
            provider.password = "password123"

        db.session.add(provider)
        db.session.commit()

        skill = Skill(
            provider_id=provider.id,
            title="Electrician - Home Repair",
            description="Wiring, fan install, switch repair, minor electrical fixes.",
            price=500.00,
            currency="INR",
            location="Pune",
            tags="electrician,home,repair"
        )

        db.session.add(skill)
        db.session.commit()
        print("Seeded provider and skill.")

    except Exception as e:
        print("Error during seeding:")
        traceback.print_exc()
        # optionally rollback if something failed
        try:
            db.session.rollback()
        except Exception:
            pass
        raise

if __name__ == "__main__":
    seed()
