# -*- coding: utf-8 -*-
"""
النماذج (Models) الخاصة بقاعدة البيانات.
هذا الملف يحتوي على كائن db وكل جداول التطبيق.
"""

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import func, cast, Integer

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    must_change_password = db.Column(db.Boolean, default=True, nullable=False)
    reset_token = db.Column(db.String(255), nullable=True)
    reset_token_expires = db.Column(db.DateTime, nullable=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Segment(db.Model):
    __tablename__ = 'segments'
    code = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), default='نشطة')


class Governorate(db.Model):
    __tablename__ = 'governorates'
    code = db.Column(db.String(20), primary_key=True)
    name = db.Column(db.String(100), nullable=False)


class CourseCatalog(db.Model):
    __tablename__ = 'course_catalog'
    code = db.Column(db.String(30), primary_key=True)
    track_name = db.Column(db.String(100), nullable=False)
    level_name = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    course_link = db.Column(db.Text, nullable=True)
    pre_test_link = db.Column(db.Text, nullable=True)
    post_test_link = db.Column(db.Text, nullable=True)


class TrainingGroup(db.Model):
    __tablename__ = 'training_groups'
    code = db.Column(db.String(30), primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    governorate_code = db.Column('governorate_code', db.String(20), db.ForeignKey('governorates.code'))
    slice_code = db.Column('slice_code', db.String(20), db.ForeignKey('segments.code'))
    status = db.Column(db.String(20), default='نشطة')


class InsuranceRequest(db.Model):
    __tablename__ = 'training_requests'

    id = db.Column(db.Integer, primary_key=True)
    request_code = db.Column(db.String(30), unique=True, nullable=False)
    applicant_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    applicant_email = db.Column(db.String(120), nullable=False)

    target_category = db.Column(db.String(50), nullable=False)
    governorate = db.Column(db.String(50), nullable=False)
    group_name = db.Column(db.String(100), nullable=False)
    course_title = db.Column(db.String(150), nullable=False)

    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    days_count = db.Column(db.Integer, nullable=False)
    hours_count = db.Column(db.Integer, nullable=False)

    status = db.Column(db.String(50), default='طلب جديد')
    trainer_name = db.Column(db.String(120), nullable=True)
    trainer_phone = db.Column(db.String(30), nullable=True)
    hourly_rate_usd = db.Column(db.Float, nullable=True)
    trainer_notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False)
    # أرشفة الإدارة (system_admin / request_processor) — مستقلة تماماً عن أرشفة مقدم الطلب.
    is_archived = db.Column(db.Boolean, nullable=False, default=False)
    # أرشفة مقدم الطلب نفسه — مستقلة تماماً عن أرشفة الإدارة. كل طرف له علمه الخاص.
    is_archived_by_applicant = db.Column(db.Boolean, nullable=False, default=False)
    email_message_id = db.Column(db.String(255), nullable=True)

    applicant = db.relationship('User', backref=db.backref('requests', lazy=True))


class LinkRequest(db.Model):
    __tablename__ = 'link_requests'

    id = db.Column(db.Integer, primary_key=True)
    facilitator_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    facilitator_email = db.Column(db.String(120), nullable=False)
    facilitator_full_name = db.Column(db.String(150), nullable=False)

    segment_name = db.Column(db.String(100), nullable=False)
    governorate_name = db.Column(db.String(100), nullable=False)
    group_name = db.Column(db.String(100), nullable=False)

    course_code = db.Column(db.String(30), db.ForeignKey('course_catalog.code'), nullable=False)
    test_type = db.Column(db.String(10), nullable=False)  # 'pre' أو 'post'

    requested_date = db.Column(db.Date, nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)   # تاريخ+وقت البداية مدموجين
    window_end = db.Column(db.DateTime, nullable=False)   # start_time + WINDOW_DURATION_MINUTES

    token = db.Column(db.String(64), unique=True, nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'تم التنفيذ' / 'لم يتم التنفيذ'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # العدد المتوقع لمتدربي هذه الجلسة بالذات، يُدخله الميسّر يدوياً بالنموذج.
    # إجباري فقط عندما status = 'تم التنفيذ' (يوجد بوابة فعلية)، وإلا يبقى NULL.
    expected_trainees_count = db.Column(db.Integer, nullable=True)
    # عدد مرات التحويل الناجح لرابط Kobo أثناء النافذة الفعالة. افتراضي 0.
    click_count = db.Column(db.Integer, nullable=False, default=0)
    # إحدى قيم COMPLETION_STATUSES، أو NULL لطلبات 'لم يتم التنفيذ' (غير منطبقة).
    completion_status = db.Column(db.String(60), nullable=True)

    facilitator = db.relationship('User', backref=db.backref('link_requests', lazy=True))
    course = db.relationship('CourseCatalog', backref=db.backref('link_requests', lazy=True))


# مدة صلاحية نافذة الرابط بالدقائق (مرنة أكثر من الساعات لضبط مدد قصيرة
# عند الحاجة، متل التجربة). القيمة الافتراضية 240 = 4 ساعات (نفس السلوك
# السابق بدون تغيير). لتغييرها: عدّل الرقم هون فقط.
WINDOW_DURATION_MINUTES = 240

# نسبة "الاكتمال الكامل" لاختبار جلسة معينة، كنسبة مئوية من
# expected_trainees_count. لتغييرها: عدّل الرقم هون فقط (متل
# WINDOW_DURATION_MINUTES) دون أي تعديل آخر بالكود.
COMPLETION_RATE_PERCENT = 50

# القيم الأربع الممكنة لعمود completion_status، كمرجع واحد يُستدعى من
# test_links.py (لحساب الحالة) و admin.py (لعرضها بالفلاتر والـKPIs)،
# حتى لا تتكرر هذه النصوص الحرفية بأكثر من مكان.
COMPLETION_STATUS_PENDING = 'بانتظار الاختبار'
COMPLETION_STATUS_NO_ENTRY = 'لم يدخل أي متدرب'
COMPLETION_STATUS_PARTIAL = 'دخول جزئي (أقل من النسبة المطلوبة)'
COMPLETION_STATUS_COMPLETED = 'مكتمل ومنفذ من قبل المتدربين'

COMPLETION_STATUSES = [
    COMPLETION_STATUS_PENDING,
    COMPLETION_STATUS_NO_ENTRY,
    COMPLETION_STATUS_PARTIAL,
    COMPLETION_STATUS_COMPLETED,
]


def generate_secure_request_code():
    """
    تولد رمز طلب فريد وآمن لمنع التضارب (Race Condition)
    بالشكل: REQ-YYYY-XXX
    """
    current_year = datetime.now().year
    prefix = f"REQ-{current_year}-"
    
    # استعلام قاعدة البيانات لجلب أعلى رقم تسلسلي حالي لنفس السنة بشكل آمن
    max_seq = db.session.query(
        func.max(cast(func.substr(InsuranceRequest.request_code, len(prefix) + 1), Integer))
    ).filter(InsuranceRequest.request_code.like(f"{prefix}%")).scalar()
    
    next_seq = (max_seq or 0) + 1
    return f"{prefix}{next_seq:03d}"