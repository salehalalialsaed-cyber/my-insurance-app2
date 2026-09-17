# -*- coding: utf-8 -*-
import pytest
from app_package import create_app
from app_package.models import db

@pytest.fixture
def app():
    # تمرير وضع الاختبار مباشرة عند إنشاء التطبيق
    app = create_app(testing=True)

    with app.app_context():
        # --- حارس أمان مستقل ثاني ---
        actual_db_url = str(db.engine.url)
        if 'sqlite' not in actual_db_url:
            raise RuntimeError(f"🚨 توقف فوري! القاعدة المتصلة فعلياً: {actual_db_url} — هذي مش sqlite!")

        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture
def client(app):
    return app.test_client()
