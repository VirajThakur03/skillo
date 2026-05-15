"""merge migration heads after runtime fix

Revision ID: 9e0f1a2b3c4d
Revises: 8d9e0f1a2b3c, b7a1c2d3e4f5
Create Date: 2026-04-17 19:45:00.000000

"""


# revision identifiers, used by Alembic.
revision = "9e0f1a2b3c4d"  # pragma: allowlist secret
down_revision = ("8d9e0f1a2b3c", "b7a1c2d3e4f5")  # pragma: allowlist secret
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
