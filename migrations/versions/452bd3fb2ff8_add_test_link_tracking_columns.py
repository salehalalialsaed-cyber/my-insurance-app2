"""add test link tracking columns (expected_trainees_count, click_count, completion_status)

Revision ID: 452bd3fb2ff8
Revises: a1b2c3d4e5f6
Create Date: 2026-09-16 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '452bd3fb2ff8'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    # expected_trainees_count و completion_status تبقى NULL-able لأنها غير
    # منطبقة أصلاً على طلبات 'لم يتم التنفيذ' (ما في بوابة حقيقية). click_count
    # لازم NOT NULL بقيمة افتراضية 0 لأنه عدّاد يُستخدم بمقارنات حسابية مباشرة.
    with op.batch_alter_table('link_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('expected_trainees_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('click_count', sa.Integer(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('completion_status', sa.String(length=60), nullable=True))


def downgrade():
    with op.batch_alter_table('link_requests', schema=None) as batch_op:
        batch_op.drop_column('completion_status')
        batch_op.drop_column('click_count')
        batch_op.drop_column('expected_trainees_count')
