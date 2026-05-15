from app import create_app
from app.extensions import db
from app.schema_bootstrap import POSTGRES_ENUMS

app = create_app()
with app.app_context():
    missing = []
    for name, values in POSTGRES_ENUMS.items():
        res = db.session.execute(db.text(f"SELECT enumlabel FROM pg_enum WHERE enumtypid = (SELECT oid FROM pg_type WHERE typname = '{name}')")).fetchall()
        db_vals = [r[0] for r in res]
        if not db_vals:
            missing.append(f'Type {name} missing')
            continue
        for val in values:
            if val not in db_vals:
                missing.append(f"ALTER TYPE {name} ADD VALUE '{val}';")
    for m in missing:
        print(m)
