"""add password reset columns to users

Revision ID: 7f2c4a9d1e33
Revises: 1a3049d306a7
Create Date: 2026-09-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '7f2c4a9d1e33'
down_revision = '1a3049d306a7'
branch_labels = None
depends_on = None


def upgrade():
    # ### أعمدة جديدة لدعم ميزة "نسيت كلمة المرور" ###
    op.add_column('users', sa.Column('reset_token', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('reset_token_expires', sa.DateTime(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### end Alembic commands ###
    op.drop_column('users', 'reset_token_expires')
    op.drop_column('users', 'reset_token')
