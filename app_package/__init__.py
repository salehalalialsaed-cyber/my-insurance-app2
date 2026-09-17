# -*- coding: utf-8 -*-
"""
مصنع التطبيق (Application Factory).
هذا الملف مسؤول عن بناء تطبيق Flask وربطه بقاعدة البيانات والبريد.
"""

import os
from flask import Flask
from flask_mail import Mail
from flask_migrate import Migrate
from flask_wtf import CSRFProtect
from dotenv import load_dotenv

from .models import db

load_dotenv()

mail = Mail()
migrate = Migrate()
csrf = CSRFProtect()


def create_app(testing=False):
    app = Flask(__name__, template_folder='../templates')

    # --- الإعدادات الأساسية ---
    app.secret_key = os.environ.get('SECRET_KEY', 'test-secret-key-not-for-production')

    if testing:
        # وضع الاختبار: قاعدة وهمية بالذاكرة حصرياً، ولا نقرأ .env للقاعدة نهائياً
        db_url = 'sqlite:///:memory:'
        # تعطيل التحقق من CSRF بوضع الاختبار فقط، لأن pytest يرسل نماذج
        # POST مباشرة بدون توكن حقيقي من صفحة HTML مُصيَّرة فعلياً
        app.config['WTF_CSRF_ENABLED'] = False
    else:
        db_url = os.environ.get('DATABASE_URL')
        if not db_url:
            raise RuntimeError("DATABASE_URL غير موجود. تأكد من ملف .env")
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)

    # --- حارس أمان صريح أول ---
    if testing and 'sqlite' not in db_url:
        raise RuntimeError("🚨 خطأ أمان: وضع الاختبار لازم يستخدم sqlite فقط، تم رفض التشغيل!")
    if not testing and 'sqlite' in db_url:
        raise RuntimeError("🚨 خطأ أمان: التشغيل العادي وصله رابط sqlite بالغلط، تم رفض التشغيل!")

    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # --- إعدادات البريد ---
    app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER')
    app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS'] = os.environ.get('MAIL_USE_TLS', 'True').lower() in ['true', 'on', '1']
    app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
    app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
    app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_DEFAULT_SENDER')

    # --- ربط الإضافات بالتطبيق ---
    db.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)

    from .auth import auth_bp
    from .applicant import applicant_bp
    from .admin import admin_bp
    from .test_links import test_links_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(applicant_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(test_links_bp)

    return app