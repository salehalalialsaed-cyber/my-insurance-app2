# -*- coding: utf-8 -*-
"""
Blueprint الإدارة: سجل الطلبات، تحديث الحالة، الأرشفة، إدارة المستخدمين، المصفوفة، التصدير.
"""

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, Response
from datetime import datetime
from sqlalchemy.exc import IntegrityError
import pandas as pd
import io
import logging
import re

EMAIL_REGEX = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def is_valid_email(email):
    """تحقق بسيط بدون مكتبات خارجية من صيغة الإيميل (فيه @ ونطاق صحيح)."""
    return bool(email) and bool(EMAIL_REGEX.match(email.strip()))

from .models import (
    db, User, Segment, Governorate, CourseCatalog, TrainingGroup, InsuranceRequest,
    generate_secure_request_code, LinkRequest, COMPLETION_STATUSES, COMPLETION_STATUS_PENDING,
    COMPLETION_STATUS_NO_ENTRY, COMPLETION_STATUS_PARTIAL, COMPLETION_STATUS_COMPLETED,
)
from .constants import ROLE_TO_SEGMENT_NAME, VALID_STATUSES, OTHER_ROLE_DISPLAY_NAMES
from .emails import send_new_request_notification, send_status_update_notification
from .decorators import role_required
from .matrix import build_matrix_context
from .test_links import refresh_completion_statuses, build_test_links_context
from app_package import mail

admin_bp = Blueprint('admin', __name__)

# --- أدوار القراءة (تشمل المراقب) وأدوار الكتابة (بدون المراقب) ---
READ_ROLES = ['system_admin', 'request_processor', 'observer']
WRITE_ROLES = ['system_admin', 'request_processor']
OBSERVER_DENIED_MESSAGE = 'دائرة البرامج التدريبية: حساب مراقب للقراءة فقط.'

# --- خريطة أسماء عرض مُجمّعة (شرائح + أدوار مستقلة) لشاشات إدارة
# المستخدمين فقط. ROLE_TO_SEGMENT_NAME وحدها مرجع أي تحقق من الشريحة. ---
DISPLAY_ROLE_MAPPING = {**ROLE_TO_SEGMENT_NAME, **OTHER_ROLE_DISPLAY_NAMES}


# --- سجل الطلبات وإدارته ---

@admin_bp.route('/admin/requests')
@role_required(READ_ROLES)
def admin_requests():
    sel_segment = request.args.get('segment', 'ALL')
    sel_gov = request.args.get('governorate', 'ALL')
    sel_group = request.args.get('group', 'ALL')
    sel_status = request.args.get('status', 'ALL')

    query = InsuranceRequest.query.filter_by(is_deleted=False, is_archived=False)

    if sel_segment != 'ALL':
        seg_obj = Segment.query.filter_by(code=sel_segment).first()
        if seg_obj:
            query = query.filter_by(target_category=seg_obj.name)

    if sel_gov != 'ALL':
        gov_obj = Governorate.query.filter_by(code=sel_gov).first()
        if gov_obj:
            query = query.filter_by(governorate=gov_obj.name)

    if sel_group != 'ALL':
        query = query.filter_by(group_name=sel_group)

    if sel_status != 'ALL':
        query = query.filter_by(status=sel_status)

    filtered_requests = query.all()

    sel_kpi_segment = request.args.get('kpi_segment', 'ALL')
    kpi_query = InsuranceRequest.query.filter_by(is_deleted=False, is_archived=False)
    if sel_kpi_segment != 'ALL':
        kpi_seg_obj = Segment.query.filter_by(code=sel_kpi_segment).first()
        if kpi_seg_obj:
            kpi_query = kpi_query.filter_by(target_category=kpi_seg_obj.name)

    kpi_all = kpi_query.all()
    kpis = {
        'total': len(kpi_all),
        'new': sum(1 for r in kpi_all if r.status == 'طلب جديد'),
        'in_progress': sum(1 for r in kpi_all if r.status == 'جاري المعالجة'),
        'completed': sum(1 for r in kpi_all if r.status in
                          ['تم تنفيذ الطلب والتعاقد مع مدرب', 'تم الانتهاء من تنفيذ التدريب'])
    }

    return render_template('admin.html',
                            requests=filtered_requests,
                            kpis=kpis,
                            segments=Segment.query.all(),
                            governorates=Governorate.query.all(),
                            groups=TrainingGroup.query.all(),
                            sel_segment=sel_segment,
                            sel_gov=sel_gov,
                            sel_group=sel_group,
                            sel_status=sel_status,
                            sel_kpi_segment=sel_kpi_segment,
                            valid_statuses=VALID_STATUSES)


@admin_bp.route('/update_status/<int:req_id>', methods=['POST'])
@role_required(WRITE_ROLES, denied_redirect='admin.admin_requests', denied_message=OBSERVER_DENIED_MESSAGE)
def update_status(req_id):
    req_item = InsuranceRequest.query.get_or_404(req_id)
    new_status = request.form.get('status')

    if new_status in VALID_STATUSES:
        req_item.status = new_status
        req_item.trainer_name = request.form.get('trainer_name', '').strip() or None
        req_item.trainer_phone = request.form.get('trainer_phone', '').strip() or None

        rate_str = request.form.get('hourly_rate_usd', '').strip()
        req_item.hourly_rate_usd = float(rate_str) if rate_str else None

        req_item.trainer_notes = request.form.get('trainer_notes', '').strip() or None

        db.session.commit()
        send_status_update_notification(mail, req_item)

        flash(f'تم تحديث حالة الطلب {req_item.request_code} بنجاح وإرسال الإشعارات.', 'success')
    else:
        flash('الحالة المحددة غير صالحة.', 'danger')

    return redirect(request.referrer or url_for('admin.admin_requests'))


@admin_bp.route('/admin/requests/new', methods=['GET', 'POST'])
@role_required(WRITE_ROLES, denied_redirect='admin.admin_requests', denied_message=OBSERVER_DENIED_MESSAGE)
def admin_add_request():
    applicants = User.query.filter(User.role.in_(ROLE_TO_SEGMENT_NAME.keys())).order_by(User.full_name).all()

    if request.method == 'POST':
        try:
            applicant_id_str = request.form.get('applicant_id')
            if not applicant_id_str:
                flash('الرجاء اختيار مقدم الطلب.', 'danger')
                return render_template('admin_request_form.html', applicants=applicants,
                                       governorates=Governorate.query.all(),
                                       courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                                       valid_statuses=VALID_STATUSES, form=request.form)

            applicant_id = int(applicant_id_str)
            applicant_user = db.session.get(User, applicant_id)
            if not applicant_user or applicant_user.role not in ROLE_TO_SEGMENT_NAME:
                flash('الرجاء اختيار مقدم طلب صالح.', 'danger')
                return render_template('admin_request_form.html', applicants=applicants,
                                       governorates=Governorate.query.all(),
                                       courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                                       valid_statuses=VALID_STATUSES, form=request.form)

            target_category = ROLE_TO_SEGMENT_NAME[applicant_user.role]

            governorate = request.form.get('governorate')
            group_name = request.form.get('group_name')
            course_title = request.form.get('course_title')
            start_date_str = request.form.get('start_date')
            end_date_str = request.form.get('end_date')

            # التحقق من القيم العددية للأيام والساعات
            try:
                days_count = int(request.form.get('days_count', 0))
                hours_count = int(request.form.get('hours_count', 0))
            except ValueError:
                flash('خطأ: عدد الأيام والساعات يجب أن يكون قيماً رقمية صحيحة.', 'danger')
                return render_template('admin_request_form.html', applicants=applicants,
                                       governorates=Governorate.query.all(),
                                       courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                                       valid_statuses=VALID_STATUSES, form=request.form)

            # التحقق من الحقول الإجبارية
            if not governorate or not group_name or not course_title or not start_date_str or not end_date_str:
                flash('خطأ: يرجى تعبئة كافة الحقول الإجبارية.', 'danger')
                return render_template('admin_request_form.html', applicants=applicants,
                                       governorates=Governorate.query.all(),
                                       courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                                       valid_statuses=VALID_STATUSES, form=request.form)

            # التحقق من صيغة التواريخ
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('خطأ: صيغة التواريخ غير صحيحة.', 'danger')
                return render_template('admin_request_form.html', applicants=applicants,
                                       governorates=Governorate.query.all(),
                                       courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                                       valid_statuses=VALID_STATUSES, form=request.form)

            # التحقق من منطقية التواريخ (تاريخ النهاية بعد البداية حصراً)
            if start_date >= end_date:
                flash('خطأ: تاريخ نهاية التدريب يجب أن يكون بعد تاريخ البداية حصراً.', 'danger')
                return render_template('admin_request_form.html', applicants=applicants,
                                       governorates=Governorate.query.all(),
                                       courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                                       valid_statuses=VALID_STATUSES, form=request.form)

            # التحقق من أن الأيام والساعات أكبر من الصفر
            if days_count <= 0 or hours_count <= 0:
                flash('خطأ: عدد الأيام وعدد الساعات يجب أن يكون أكبر من الصفر.', 'danger')
                return render_template('admin_request_form.html', applicants=applicants,
                                       governorates=Governorate.query.all(),
                                       courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                                       valid_statuses=VALID_STATUSES, form=request.form)

            status = request.form.get('status') if request.form.get('status') in VALID_STATUSES else 'طلب جديد'

            rate_str = request.form.get('hourly_rate_usd', '').strip()
            hourly_rate = float(rate_str) if rate_str else None

            max_attempts = 3
            new_req = None
            for attempt in range(max_attempts):
                request_code = generate_secure_request_code()
                new_req = InsuranceRequest(
                    request_code=request_code,
                    applicant_id=applicant_user.id,
                    applicant_email=applicant_user.email,
                    target_category=target_category,
                    governorate=governorate,
                    group_name=group_name,
                    course_title=course_title,
                    start_date=start_date,
                    end_date=end_date,
                    days_count=days_count,
                    hours_count=hours_count,
                    status=status,
                    trainer_name=request.form.get('trainer_name', '').strip() or None,
                    trainer_phone=request.form.get('trainer_phone', '').strip() or None,
                    hourly_rate_usd=hourly_rate,
                    trainer_notes=request.form.get('trainer_notes', '').strip() or None,
                )
                db.session.add(new_req)
                try:
                    db.session.commit()
                    break
                except IntegrityError:
                    db.session.rollback()
                    if attempt == max_attempts - 1:
                        raise
            else:
                raise RuntimeError('تعذر توليد رمز طلب فريد بعد عدة محاولات.')

            send_new_request_notification(mail, new_req)

            flash(f'تمت إضافة الطلب برمز: {request_code}', 'success')
            return redirect(url_for('admin.admin_requests'))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in admin_add_request: {str(e)}", exc_info=True)
            flash('حدث خطأ غير متوقع أثناء حفظ الطلب. يرجى المحاولة لاحقاً.', 'danger')

    return render_template('admin_request_form.html', applicants=applicants,
                           governorates=Governorate.query.all(),
                           courses=CourseCatalog.query.order_by(CourseCatalog.code).all(),
                           valid_statuses=VALID_STATUSES, form={})


@admin_bp.route('/admin/delete_request/<int:req_id>', methods=['POST'])
@role_required(WRITE_ROLES, denied_redirect='admin.admin_requests', denied_message=OBSERVER_DENIED_MESSAGE)
def delete_request(req_id):
    req_item = InsuranceRequest.query.get_or_404(req_id)
    req_item.is_deleted = True
    db.session.commit()
    flash(f'تم حذف الطلب {req_item.request_code}.', 'info')
    return redirect(request.referrer or url_for('admin.admin_requests'))


# --- إدارة المستخدمين الشاملة (لصلاحية system_admin فقط) ---

@admin_bp.route('/admin/users')
@role_required(['system_admin'], denied_redirect='admin.admin_requests',
                denied_message='عذراً، هذه الصفحة خاصة بمدير النظام العام فقط.')
def admin_users():
    users = User.query.all()
    return render_template('admin_users.html', users=users, role_mapping=DISPLAY_ROLE_MAPPING)


@admin_bp.route('/admin/users/new', methods=['GET', 'POST'])
@role_required(['system_admin'], denied_redirect='admin.admin_requests',
                denied_message='عذراً، هذه الصلاحية لمدير النظام فقط.')
def admin_add_user():
    if request.method == 'POST':
        try:
            email = request.form.get('email').strip().lower()
            full_name = request.form.get('full_name').strip()
            password = request.form.get('password')
            role = request.form.get('role')

            if not is_valid_email(email):
                flash('صيغة البريد الإلكتروني غير صحيحة.', 'danger')
                return render_template('admin_user_form.html', role_mapping=DISPLAY_ROLE_MAPPING)

            if User.query.filter_by(email=email).first():
                flash('البريد الإلكتروني مستخدم مسبقاً لشخص آخر!', 'danger')
                return render_template('admin_user_form.html', role_mapping=DISPLAY_ROLE_MAPPING)

            new_user = User(
                email=email,
                full_name=full_name,
                role=role,
                must_change_password=True
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            flash(f'تم إنشاء المستخدم {full_name} بنجاح.', 'success')
            return redirect(url_for('admin.admin_users'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in admin_add_user: {str(e)}", exc_info=True)
            flash('حدث خطأ غير متوقع أثناء إضافة المستخدم. يرجى المحاولة لاحقاً.', 'danger')

    return render_template('admin_user_form.html', role_mapping=DISPLAY_ROLE_MAPPING)


@admin_bp.route('/admin/users/edit/<int:user_id>', methods=['GET', 'POST'])
@role_required(['system_admin'], denied_redirect='admin.admin_requests',
                denied_message='عذراً، هذه الصلاحية لمدير النظام فقط.')
def admin_edit_user(user_id):
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        try:
            new_email = request.form.get('email').strip().lower()
            if not is_valid_email(new_email):
                flash('صيغة البريد الإلكتروني غير صحيحة.', 'danger')
                return render_template('admin_user_form.html', edit_user=user, role_mapping=DISPLAY_ROLE_MAPPING)

            user.full_name = request.form.get('full_name').strip()
            user.email = new_email
            user.role = request.form.get('role')

            new_password = request.form.get('password')
            if new_password and len(new_password.strip()) > 0:
                user.set_password(new_password.strip())
                user.must_change_password = True

            db.session.commit()
            flash(f'تم تحديث بيانات المستخدم {user.full_name} بنجاح.', 'success')
            return redirect(url_for('admin.admin_users'))
        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in admin_edit_user: {str(e)}", exc_info=True)
            flash('حدث خطأ غير متوقع أثناء تحديث بيانات المستخدم. يرجى المحاولة لاحقاً.', 'danger')

    return render_template('admin_user_form.html', edit_user=user, role_mapping=DISPLAY_ROLE_MAPPING)


@admin_bp.route('/admin/users/delete/<int:user_id>', methods=['POST'])
@role_required(['system_admin'], denied_redirect='admin.admin_requests',
                denied_message='عذراً، هذه الصلاحية لمدير النظام فقط.')
def admin_delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == session.get('user_id'):
        flash('لا يمكنك حذف حسابك الحالي أثناء تسجيل الدخول به!', 'danger')
        return redirect(url_for('admin.admin_users'))

    db.session.delete(user)
    db.session.commit()
    flash('تم حذف المستخدم بنجاح.', 'info')
    return redirect(url_for('admin.admin_users'))


# --- الأرشفة ---

@admin_bp.route('/admin/archive')
@role_required(READ_ROLES)
def admin_archive():
    archived_requests = InsuranceRequest.query.filter_by(
        is_deleted=False, is_archived=True
    ).order_by(InsuranceRequest.created_at.desc()).all()
    return render_template('archive.html', archived_requests=archived_requests)


@admin_bp.route('/admin/archive_request/<int:req_id>', methods=['POST'])
@role_required(WRITE_ROLES, denied_redirect='admin.admin_requests', denied_message=OBSERVER_DENIED_MESSAGE)
def archive_request(req_id):
    req_item = InsuranceRequest.query.get_or_404(req_id)
    req_item.is_archived = True
    db.session.commit()
    flash(f'تم أرشفة الطلب {req_item.request_code} بنجاح.', 'success')
    return redirect(request.referrer or url_for('admin.admin_requests'))


@admin_bp.route('/admin/restore/<int:req_id>', methods=['POST'])
@role_required(WRITE_ROLES, denied_redirect='admin.admin_requests', denied_message=OBSERVER_DENIED_MESSAGE)
def restore_request(req_id):
    req = InsuranceRequest.query.get_or_404(req_id)
    req.is_archived = False
    db.session.commit()
    flash(f'تمت استعادة الطلب {req.request_code} بنجاح.', 'success')
    return redirect(url_for('admin.admin_archive'))


@admin_bp.route('/admin/delete_archived/<int:req_id>', methods=['POST'])
@role_required(WRITE_ROLES, denied_redirect='admin.admin_requests', denied_message=OBSERVER_DENIED_MESSAGE)
def delete_archived_request(req_id):
    req = InsuranceRequest.query.get_or_404(req_id)
    db.session.delete(req)
    db.session.commit()
    flash(f'تم حذف الطلب {req.request_code} نهائياً.', 'danger')
    return redirect(url_for('admin.admin_archive'))


# --- مصفوفة التوزيع الإدارية ---

@admin_bp.route('/admin/matrix')
@role_required(READ_ROLES)
def admin_matrix():
    ctx = build_matrix_context(
        sel_seg_code=request.args.get('segment_code'),
        sel_gov_code=request.args.get('governorate_code'),
    )
    return render_template('admin_matrix.html', **ctx)


# --- شاشة تتبع الاختبارات (روابط الاختبار الموقّتة) ---

@admin_bp.route('/admin/test_links')
@role_required(READ_ROLES)
def admin_test_links():
    # استخدام الدالة المشتركة لتوليد السياق والـ KPIs بالكامل
    ctx = build_test_links_context(locked_segment_name=None)
    
    # تحويل المتغيرات لتتطابق مع الأسماء المتوقعة بقالب admin_test_links.html الأصلي
    return render_template(
        'admin_test_links.html',
        link_requests=ctx['requests'],
        kpis={
            'total': ctx['total_count'],
            'executed': ctx['executed_count'],
            'not_executed': ctx['not_executed_count'],
            'pending': ctx['pending_count'],
            'completed': ctx['fully_completed_count'],
            'partial': ctx['partial_count'],
            'no_entry': ctx['no_entry_count'],
        },
        segments=ctx['segments'],
        governorates=ctx['governorates'],
        groups=[g.name for g in ctx['groups']] if ctx['groups'] else [],
        courses=ctx['courses'],
        completion_statuses=COMPLETION_STATUSES,
        sel_segment=request.args.get('segment', 'ALL'),
        sel_gov=request.args.get('governorate', 'ALL'),
        sel_group=request.args.get('group', 'ALL'),
        sel_course=request.args.get('course', 'ALL'),
        sel_test_type=request.args.get('test_type', 'ALL'),
        sel_completion=request.args.get('completion_status', 'ALL'),
        date_from=ctx['selected_date_from'],
        date_to=ctx['selected_date_to'],
    )


# --- تصدير Excel ---

@admin_bp.route('/admin/export_excel')
@role_required(READ_ROLES)
def export_excel():
    sel_segment = request.args.get('segment', 'ALL')
    sel_gov = request.args.get('governorate', 'ALL')
    sel_group = request.args.get('group', 'ALL')
    sel_status = request.args.get('status', 'ALL')

    query = InsuranceRequest.query.filter_by(is_deleted=False, is_archived=False)
    if sel_segment != 'ALL':
        seg_obj = Segment.query.filter_by(code=sel_segment).first()
        if seg_obj: query = query.filter_by(target_category=seg_obj.name)
    if sel_gov != 'ALL':
        gov_obj = Governorate.query.filter_by(code=sel_gov).first()
        if gov_obj: query = query.filter_by(governorate=gov_obj.name)
    if sel_group != 'ALL':
        query = query.filter_by(group_name=sel_group)
    if sel_status != 'ALL':
        query = query.filter_by(status=sel_status)

    data = []
    for r in query.all():
        data.append({
            'رمز الطلب': r.request_code,
            'مقدم الطلب': r.applicant_email,
            'الشريحة': r.target_category,
            'المحافظة': r.governorate,
            'المجموعة التدريبية': r.group_name,
            'الحقيبة التدريبية': r.course_title,
            'تاريخ البداية': str(r.start_date),
            'تاريخ النهاية': str(r.end_date),
            'عدد الأيام': r.days_count,
            'عدد الساعات': r.hours_count,
            'الحالة': r.status,
            'اسم المدرب': r.trainer_name or '',
            'هاتف المدرب': r.trainer_phone or '',
            'الأجر بالساعة ($)': r.hourly_rate_usd or '',
            'ملاحظات': r.trainer_notes or ''
        })

    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='الطلبات التدريبية')
    output.seek(0)

    return Response(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment;filename=training_requests_export.xlsx"}
    )