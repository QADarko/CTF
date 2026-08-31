"""Add the durable runtime repository snapshot.

Revision ID: 0002_repository_snapshot
Revises: 0001_initial
"""

from alembic import op

from packages.ctf_domain.sqlalchemy_models import RepositorySnapshotRow

revision = "0002_repository_snapshot"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    RepositorySnapshotRow.__table__.create(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    RepositorySnapshotRow.__table__.drop(bind=op.get_bind(), checkfirst=True)
