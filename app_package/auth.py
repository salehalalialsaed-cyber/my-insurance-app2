# -*- coding: utf-8 -*-
"""
Blueprint المصادقة: تسجيل الدخول، الخروج، تغيير كلمة المرور.
"""

import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

from .models import db, User
from .constants import ROLE_TO_SEGMENT_NAME, TEST_LINK_REQUESTER_ROLE
from .emails import send_password_reset_email
from app_package import mail

auth_bp = Blueprint('auth', __name__)

RESET_TOKEN_VALIDITY_MINUTES = 30


def redirect_user_by_role(role):
    if role in ['system_admin', 'request_processor', 'observer']:
        return redirect(url_for('admin.admin_requests'))
    elif role in ROLE_TO_SEGMENT_NAME:
        return redirect(url_for('applicant.my_requests'))
    elif role == TEST_LINK_REQUESTER_ROLE:
        return redirect(url_for('test_links.request_test_link'))
    else:
        return redirect(url_for('auth.login'))


@auth_bp.route('/')
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_email' in session:
        user = db.session.get(User, session.get('user_id'))
        if user and user.must_change_password and user.role not in ['system_admin', 'observer']:
            return redirect(url_for('auth.change_password'))
        return redirect_user_by_role(session.get('user_role'))

    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and user.check_password(password):
            session['user_id'] = user.id
            session['user_email'] = user.email
            session['user_role'] = user.role
            session['user_name'] = user.full_name
            session['user_segment'] = ROLE_TO_SEGMENT_NAME.get(user.role, 'شريحة عامة')

            if user.must_change_password and user.role not in ['system_admin', 'observer']:
                flash('يرجى تغيير كلمة المرور المؤقتة الخاصة بك للمتابعة.', 'warning')
                return redirect(url_for('auth.change_password'))

            flash(f'مرحباً بك يا {user.full_name}', 'success')
            return redirect_user_by_role(user.role)
        else:
            flash('البريد الإلكتروني أو كلمة المرور غير صحيحة!', 'danger')

    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    session.clear()
    flash('تم تسجيل الخروج بنجاح.', 'info')
    return redirect(url_for('auth.login'))


@auth_bp.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_email' not in session:
        return redirect(url_for('auth.login'))

    user = db.session.get(User, session['user_id'])
    if not user:
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        current_password = request.form.get('current_password')
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not user.check_password(current_password):
            flash('كلمة المرور الحالية غير صحيحة!', 'danger')
        elif not new_password or len(new_password) < 6:
            flash('كلمة المرور الجديدة يجب ألا تقل عن 6 رموز!', 'danger')
        elif new_password != confirm_password:
            flash('كلمة المرور الجديدة غير مطابقة لتأكيد كلمة المرور!', 'danger')
        else:
            user.set_password(new_password)
            user.must_change_password = False
            db.session.commit()

            flash('تم تغيير كلمة المرور بنجاح! يمكنك الآن استخدام النظام.', 'success')
            return redirect_user_by_role(user.role)

    return render_template('change_password.html')


@auth_bp.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password_request():
    """
    يستقبل بريد المستخدم، وإن كان موجوداً يولّد توكن مؤقت (صالح لمدة
    محدودة) ويرسل رابط استعادة كلمة المرور عليه. لا نُفصح للزائر إن كان
    الإيميل موجوداً بالنظام أم لا، لتفادي كشف قائمة المستخدمين المسجّلين.
    """
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        user = User.query.filter_by(email=email).first()

        if user:
            user.reset_token = secrets.token_urlsafe(32)
            user.reset_token_expires = datetime.utcnow() + timedelta(minutes=RESET_TOKEN_VALIDITY_MINUTES)
            db.session.commit()

            reset_url = url_for('auth.reset_password', token=user.reset_token, _external=True)
            sent = send_password_reset_email(mail, user, reset_url)
            if not sent:
                logging.error(f"Failed to send password reset email to {email}")

        flash('إذا كان البريد الإلكتروني مسجلاً بالنظام، فستصلك رسالة تحتوي رابط استعادة كلمة المرور خلال دقائق.', 'info')
        return redirect(url_for('auth.login'))

    return render_template('forgot_password.html')


@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()

    token_valid = bool(
        user and user.reset_token_expires and user.reset_token_expires > datetime.utcnow()
    )

    if not token_valid:
        flash('رابط استعادة كلمة المرور غير صالح أو منتهي الصلاحية. يرجى طلب رابط جديد.', 'danger')
        return redirect(url_for('auth.forgot_password_request'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or len(new_password) < 6:
            flash('كلمة المرور الجديدة يجب ألا تقل عن 6 رموز!', 'danger')
        elif new_password != confirm_password:
            flash('كلمة المرور الجديدة غير مطابقة لتأكيد كلمة المرور!', 'danger')
        else:
            user.set_password(new_password)
            user.must_change_password = False
            user.reset_token = None
            user.reset_token_expires = None
            db.session.commit()

            flash('تم تعيين كلمة المرور الجديدة بنجاح! يمكنك الآن تسجيل الدخول.', 'success')
            return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)