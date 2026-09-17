# -*- coding: utf-8 -*-
"""
دوال إرسال الإشعارات البريدية التلقائية (بتنسيق HTML ودعم RTL)
قوالب الإيميلات نفسها موجودة بـ templates/emails/*.html (منفصلة عن هذا الملف).

ربط الإيميلات ببعضها (Threading):
إيميل "الطلب الجديد" هو أول رسالة، ونحفظ Message-ID تبعه بعمود email_message_id
بجدول training_requests. كل إيميلات "تحديث الحالة" اللاحقة تُرسل بـ Header
In-Reply-To / References يشاور على نفس الـ Message-ID، فتظهر كـ "رد" على نفس
الإيميل الأول (Thread واحد) بدل ما تكون رسائل منفصلة بصندوق الوارد.
"""

import logging

from flask import render_template
from flask_mail import Message
from .models import db, User


def send_new_request_notification(mail, req_item):
    try:
        sys_admin = User.query.filter_by(role='system_admin').first()
        req_processor = User.query.filter_by(role='request_processor').first()
        observers = User.query.filter_by(role='observer').all()

        if not sys_admin or not sys_admin.email:
            return

        to_email = sys_admin.email
        cc_emails = []

        if req_processor and req_processor.email:
            cc_emails.append(req_processor.email)

        for obs in observers:
            if obs.email and obs.email not in cc_emails:
                cc_emails.append(obs.email)

        subject = f"طلب تدريبي جديد - مرجع رقم: {req_item.request_code}"
        html_body = render_template('emails/new_request.html', req=req_item)

        msg = Message(subject=subject, recipients=[to_email], cc=cc_emails, html=html_body)
        mail.send(msg)

        # نحفظ Message-ID تبع هذا الإيميل عشان نربط فيه كل تحديثات الحالة اللاحقة
        req_item.email_message_id = msg.msgId
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logging.error(f"Error sending new request notification: {e}", exc_info=True)


def send_status_update_notification(mail, req_item):
    if not req_item.applicant_email:
        return

    try:
        sys_admin = User.query.filter_by(role='system_admin').first()
        req_processor = User.query.filter_by(role='request_processor').first()
        observers = User.query.filter_by(role='observer').all()

        cc_emails = []
        if sys_admin and sys_admin.email and sys_admin.email != req_item.applicant_email:
            cc_emails.append(sys_admin.email)

        if req_processor and req_processor.email and req_processor.email != req_item.applicant_email:
            if req_processor.email not in cc_emails:
                cc_emails.append(req_processor.email)

        for obs in observers:
            if obs.email and obs.email != req_item.applicant_email and obs.email not in cc_emails:
                cc_emails.append(obs.email)

        original_subject = f"طلب تدريبي جديد - مرجع رقم: {req_item.request_code}"
        subject = f"Re: {original_subject}" if req_item.email_message_id else \
            f"تحديث حالة الطلب التدريبي - مرجع: {req_item.request_code}"

        html_body = render_template('emails/status_update.html', req=req_item)

        extra_headers = {}
        if req_item.email_message_id:
            extra_headers['In-Reply-To'] = req_item.email_message_id
            extra_headers['References'] = req_item.email_message_id

        msg = Message(
            subject=subject,
            recipients=[req_item.applicant_email],
            cc=cc_emails,
            html=html_body,
            extra_headers=extra_headers or None
        )
        mail.send(msg)
    except Exception as e:
        logging.error(f"SMTP Exception: {str(e)}", exc_info=True)


def send_test_link_success_email(mail, link_req, course, gateway_url):
    """يرسل للميسّر رابط البوابة وتفاصيل صلاحيته بعد نجاح طلب رابط الاختبار."""
    try:
        subject = f"رابط الاختبار جاهز - {course.title}"
        html_body = render_template(
            'emails/test_link_success.html',
            link_req=link_req, course=course, gateway_url=gateway_url
        )
        msg = Message(subject=subject, recipients=[link_req.facilitator_email], html=html_body)
        mail.send(msg)
    except Exception as e:
        logging.error(f"Error sending test link success email: {e}", exc_info=True)


def send_test_link_failure_email(mail, link_req, course):
    """يرسل للميسّر إشعار عدم توفر رابط اختبار لهذا الكورس."""
    try:
        subject = f"تعذر إصدار رابط الاختبار - {course.title}"
        html_body = render_template(
            'emails/test_link_failure.html',
            link_req=link_req, course=course
        )
        msg = Message(subject=subject, recipients=[link_req.facilitator_email], html=html_body)
        mail.send(msg)
    except Exception as e:
        logging.error(f"Error sending test link failure email: {e}", exc_info=True)


def send_password_reset_email(mail, user, reset_url):
    """
    يرسل إيميل استعادة كلمة المرور مع رابط يحتوي التوكن المؤقت.
    لا يرمي استثناء للخارج أبداً (نفس نمط باقي دوال هذا الملف) حتى
    لا ينهار طلب المستخدم لو فشل إرسال البريد لأي سبب.
    """
    try:
        subject = "طلب استعادة كلمة المرور - دائرة البرامج التدريبية"
        html_body = render_template('emails/password_reset.html', user=user, reset_url=reset_url)
        msg = Message(subject=subject, recipients=[user.email], html=html_body)
        mail.send(msg)
        return True
    except Exception as e:
        logging.error(f"Error sending password reset email: {e}", exc_info=True)
        return False
