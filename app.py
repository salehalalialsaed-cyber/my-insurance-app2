# -*- coding: utf-8 -*-
"""
نقطة تشغيل التطبيق.
كل المنطق الفعلي أصبح داخل app_package/ (Application Factory + Blueprints).
"""

import click
from app_package import create_app, db
from app_package.models import User

app = create_app()


@app.cli.command('seed-db')
def seed_db():
    """
    تهيئة قاعدة البيانات لأول مرة: إنشاء الجداول وحساب مدير نظام واحد.

    ⚠️ يُشغَّل فقط من الطرفية (Shell على Render أو محلياً)، وليس عبر أي
    رابط بالمتصفح — لا يوجد أي مسار HTTP عام يقوم بهذه العملية:

        flask --app app seed-db

    يرفض العمل تلقائياً إذا كان يوجد مستخدم واحد على الأقل بقاعدة
    البيانات، لحماية الحسابات الموجودة من إعادة التصفير بالغلط أو
    بسوء نية.
    """
    db.create_all()

    if User.query.count() > 0:
        click.echo('⚠️  يوجد مستخدمون بالفعل بقاعدة البيانات. تم إيقاف العملية لحمايتهم.')
        click.echo('    إذا كنت تريد فعلاً إنشاء مستخدم جديد، استخدم شاشة "إدارة المستخدمين" داخل النظام بعد تسجيل الدخول.')
        return

    click.echo('🆕 لا يوجد أي مستخدم بعد. لنُنشئ حساب مدير النظام الأول:')
    email = click.prompt('البريد الإلكتروني لحساب المدير')
    full_name = click.prompt('الاسم الكامل', default='مدير النظام العام')
    password = click.prompt('كلمة السر', hide_input=True, confirmation_prompt=True)

    admin = User(
        email=email,
        full_name=full_name,
        role='system_admin',
        must_change_password=False,
    )
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()

    click.echo(f'✅ تم إنشاء حساب المدير بنجاح: {email}')


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5001))
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() in ['true', '1', 'on']
    app.run(host='0.0.0.0', port=port, debug=debug_mode)