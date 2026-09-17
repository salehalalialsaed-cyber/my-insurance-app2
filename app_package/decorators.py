# -*- coding: utf-8 -*-
"""
Decorator موحّد للتحقق من صلاحية الوصول حسب الدور.
يجمع منطق _check_admin_access و _check_applicant_access (اللي كانا مكررين
بـ admin.py و applicant.py) بمكان واحد.
"""

from functools import wraps
from flask import session, redirect, url_for, flash

from .models import db, User


def role_required(allowed_roles, denied_redirect=None, denied_message=None,
                   check_password_change=False):
    """
    allowed_roles: قائمة الأدوار المسموح لها بالدخول للـ route.

    denied_redirect + denied_message: اختياريان معاً — تُستخدمان لما بدنا نرجّع
    مستخدم مسجّل دخول (بس دوره مو ضمن allowed_roles) لصفحة معينة برسالة واضحة،
    بدل ما نرميه لصفحة تسجيل الدخول (مثلاً: مراقب حاول يعمل تعديل).

    check_password_change: لو True، بيتحقق كمان إذا المستخدم لسا لازم يغيّر
    كلمة مروره المؤقتة، ولو هيك بيرجعه لصفحة change_password (يُستخدم حالياً
    فقط لـ routes مقدم الطلب، متل ما كان الوضع بـ _check_applicant_access).
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if 'user_email' not in session:
                return redirect(url_for('auth.login'))

            user_role = session.get('user_role')

            if user_role not in allowed_roles:
                if denied_redirect and denied_message:
                    flash(denied_message, 'danger')
                    return redirect(url_for(denied_redirect))
                return redirect(url_for('auth.login'))

            if check_password_change:
                user = db.session.get(User, session['user_id'])
                if user and user.must_change_password:
                    return redirect(url_for('auth.change_password'))

            return f(*args, **kwargs)
        return wrapper
    return decorator
