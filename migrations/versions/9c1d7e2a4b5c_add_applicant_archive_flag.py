"""add is_archived_by_applicant column to training_requests

Revision ID: 9c1d7e2a4b5c
Revises: 452bd3fb2ff8
Create Date: 2026-09-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9c1d7e2a4b5c'
down_revision = '452bd3fb2ff8'
branch_labels = None
depends_on = None


def upgrade():
    # ### عمود جديد: أرشفة مقدم الطلب مستقلة تماماً عن أرشفة الإدارة (is_archived) ###
    op.add_column(
        'training_requests',
        sa.Column('is_archived_by_applicant', sa.Boolean(), nullable=False,
                   server_default=sa.false())
    )
    # ### end Alembic commands ###


def downgrade():
    # ### end Alembic commands ###
    op.drop_column('training_requests', 'is_archived_by_applicant')
