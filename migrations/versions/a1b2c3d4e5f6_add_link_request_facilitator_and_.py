"""add link_request facilitator name, segment, governorate and group columns

Revision ID: a1b2c3d4e5f6
Revises: d6ca2826acf8
Create Date: 2026-09-16 09:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'd6ca2826acf8'
branch_labels = None
depends_on = None


def upgrade():
    # server_default='' فقط عشان أي سطر موجود مسبقاً بالجدول (لو تم اختباره
    # قبل هالتعديل) ما يفشل الترحيل بسبب NOT NULL. القيمة الافتراضية ما
    # بتُستخدم لأي إدخال جديد لأن الكود دايماً بيبعتها صراحة.
    with op.batch_alter_table('link_requests', schema=None) as batch_op:
        batch_op.add_column(sa.Column('facilitator_full_name', sa.String(length=150),
                                       nullable=False, server_default=''))
        batch_op.add_column(sa.Column('segment_name', sa.String(length=100),
                                       nullable=False, server_default=''))
        batch_op.add_column(sa.Column('governorate_name', sa.String(length=100),
                                       nullable=False, server_default=''))
        batch_op.add_column(sa.Column('group_name', sa.String(length=100),
                                       nullable=False, server_default=''))


def downgrade():
    with op.batch_alter_table('link_requests', schema=None) as batch_op:
        batch_op.drop_column('group_name')
        batch_op.drop_column('governorate_name')
        batch_op.drop_column('segment_name')
        batch_op.drop_column('facilitator_full_name')
