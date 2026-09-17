# -*- coding: utf-8 -*-
"""
Blueprint مقدم الطلب: تقديم طلب جديد، طلباتي، مصفوفة التوزيع، تتبع اختبارات الشريحة.
"""

import logging

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from datetime import datetime
from sqlalchemy.exc import IntegrityError

from .models import db, Segment, Governorate, CourseCatalog, TrainingGroup, InsuranceRequest, generate_secure_request_code, COMPLETION_STATUSES
from .constants import ROLE_TO_SEGMENT_NAME
from .emails import send_new_request_notification
from .decorators import role_required
from .matrix import build_matrix_context
from .test_links import build_test_links_context
from app_package import mail

applicant_bp = Blueprint('applicant', __name__)

APPLICANT_ROLES = list(ROLE_TO_SEGMENT_NAME.keys())


@applicant_bp.route('/request/new', methods=['GET', 'POST'])
@role_required(APPLICANT_ROLES, check_password_change=True)
def request_form():
    locked_segment_name = session.get('user_segment', 'قادة الدولة')

    if request.method == 'POST':
        try:
            governorate = request.form.get('governorate')
            group_name = request.form.get('group_name')
            course_title = request.form.get('course_title')
            start_date_str = request.form.get('start_date')
            end_date_str = request.form.get('end_date')
            
            # قراءة القيم مع معالجة آمنة للأخطاء العددية
            try:
                days_count = int(request.form.get('days_count', 0))
                hours_count = int(request.form.get('hours_count', 0))
            except ValueError:
                flash('خطأ: عدد الأيام والساعات يجب أن يكون قيماً رقمية صحيحة.', 'danger')
                return redirect(url_for('applicant.request_form'))

            # 1. التحقق من وجود الحقول الأساسية
            if not governorate or not group_name or not course_title or not start_date_str or not end_date_str:
                flash('خطأ: يرجى تعبئة كافة الحقول الإجبارية.', 'danger')
                return redirect(url_for('applicant.request_form'))

            # تحويل التواريخ
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                flash('خطأ: صيغة التواريخ غير صحيحة.', 'danger')
                return redirect(url_for('applicant.request_form'))

            # 2. التحقق من منطقية التواريخ (تاريخ النهاية بعد البداية)
            if start_date >= end_date:
                flash('خطأ: تاريخ نهاية التدريب يجب أن يكون بعد تاريخ البداية حصراً.', 'danger')
                return redirect(url_for('applicant.request_form'))

            # 3. التحقق من القيم الرقمية (أكبر من الصفر)
            if days_count <= 0 or hours_count <= 0:
                flash('خطأ: عدد الأيام وعدد الساعات يجب أن يكون أكبر من الصفر.', 'danger')
                return redirect(url_for('applicant.request_form'))

            max_attempts = 3
            new_req = None
            for attempt in range(max_attempts):
                request_code = generate_secure_request_code()
                new_req = InsuranceRequest(
                    request_code=request_code,
                    applicant_id=session['user_id'],
                    applicant_email=session['user_email'],
                    target_category=locked_segment_name,
                    governorate=governorate,
                    group_name=group_name,
                    course_title=course_title,
                    start_date=start_date,
                    end_date=end_date,
                    days_count=days_count,
                    hours_count=hours_count,
                    status='طلب جديد'
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

            flash(f'تم إرسال طلبك بنجاح برمز: {request_code}', 'success')
            return redirect(url_for('applicant.my_requests'))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in request_form: {str(e)}", exc_info=True)
            flash('حدث خطأ غير متوقع أثناء حفظ الطلب. يرجى المحاولة لاحقاً.', 'danger')

    return render_template('request.html', locked_segment_name=locked_segment_name,
                            governorates=Governorate.query.all(), courses=CourseCatalog.query.order_by(CourseCatalog.code).all())


@applicant_bp.route('/request/my_requests')
@role_required(APPLICANT_ROLES, check_password_change=True)
def my_requests():
    user_requests = InsuranceRequest.query.filter_by(
        applicant_id=session['user_id'], is_deleted=False, is_archived_by_applicant=False
    ).order_by(InsuranceRequest.created_at.desc()).all()

    total_requests = len(user_requests)
    new_requests_count = sum(1 for r in user_requests if r.status == 'طلب جديد')
    in_progress_count = sum(1 for r in user_requests if r.status in ['جاري المعالجة', 'جاري تنفيذ التدريب'])
    completed_requests_count = sum(1 for r in user_requests if r.status in
                                    ['تم تنفيذ الطلب والتعاقد مع مدرب', 'تم الانتهاء من تنفيذ التدريب'])

    return render_template('my_requests.html',
                            requests=user_requests,
                            total_requests=total_requests,
                            new_requests_count=new_requests_count,
                            in_progress_count=in_progress_count,
                            completed_requests_count=completed_requests_count,
                            locked_segment_name=session.get('user_segment', 'قادة الدولة'))


@applicant_bp.route('/request/matrix')
@role_required(APPLICANT_ROLES, check_password_change=True)
def applicant_matrix():
    segment_name = session.get('user_segment', 'قادة الدولة')
    ctx = build_matrix_context(
        sel_gov_code=request.args.get('governorate_code'),
        locked_segment_name=segment_name,
    )
    ctx['locked_segment_name'] = segment_name
    return render_template('applicant_matrix.html', **ctx)


@applicant_bp.route('/request/test_links')
@role_required(APPLICANT_ROLES, check_password_change=True)
def applicant_test_links():
    """شاشة تتبع اختبارات خاصة بمقدم الطلب مقفلة تلقائياً على شريحة المستخدم."""
    segment_name = session.get('user_segment', 'قادة الدولة')
    ctx = build_test_links_context(locked_segment_name=segment_name)

    return render_template(
        'applicant_test_links.html',
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
        locked_segment_name=segment_name,
        sel_gov=request.args.get('governorate', 'ALL'),
        sel_group=request.args.get('group', 'ALL'),
        sel_course=request.args.get('course', 'ALL'),
        sel_test_type=request.args.get('test_type', 'ALL'),
        sel_completion=request.args.get('completion_status', 'ALL'),
        date_from=ctx['selected_date_from'],
        date_to=ctx['selected_date_to'],
    )


@applicant_bp.route('/request/archive/<int:req_id>', methods=['POST'])
@role_required(APPLICANT_ROLES, check_password_change=True)
def archive_my_request(req_id):
    req_item = InsuranceRequest.query.get_or_404(req_id)

    if req_item.applicant_id != session.get('user_id'):
        flash('لا يمكنك أرشفة طلب لا يخصك.', 'danger')
        return redirect(url_for('applicant.my_requests'))

    # أرشفة مقدم الطلب مستقلة تماماً عن أرشفة الإدارة (is_archived).
    req_item.is_archived_by_applicant = True
    db.session.commit()
    flash(f'تم أرشفة الطلب {req_item.request_code} بنجاح.', 'success')
    return redirect(url_for('applicant.my_requests'))


@applicant_bp.route('/request/archive')
@role_required(APPLICANT_ROLES, check_password_change=True)
def my_archive():
    """أرشيف الطلبات الخاص بمقدم الطلب الحالي فقط (بيانات دائمة من قاعدة البيانات،
    ومستقلة تماماً عن أرشفة الإدارة)."""
    archived_requests = InsuranceRequest.query.filter_by(
        applicant_id=session['user_id'], is_deleted=False, is_archived_by_applicant=True
    ).order_by(InsuranceRequest.created_at.desc()).all()

    return render_template('my_archive.html', archived_requests=archived_requests)


@applicant_bp.route('/request/restore/<int:req_id>', methods=['POST'])
@role_required(APPLICANT_ROLES, check_password_change=True)
def restore_my_request(req_id):
    req_item = InsuranceRequest.query.get_or_404(req_id)

    if req_item.applicant_id != session.get('user_id'):
        flash('لا يمكنك استعادة طلب لا يخصك.', 'danger')
        return redirect(url_for('applicant.my_archive'))

    req_item.is_archived_by_applicant = False
    db.session.commit()
    flash(f'تمت استعادة الطلب {req_item.request_code} إلى قائمة طلباتي بنجاح.', 'success')
    return redirect(url_for('applicant.my_archive'))


@applicant_bp.route('/api/get_groups')
@role_required(APPLICANT_ROLES)
def get_groups():
    seg_obj = Segment.query.filter_by(name=request.args.get('category')).first()
    gov_obj = Governorate.query.filter_by(name=request.args.get('governorate')).first()
    groups_list = []
    if seg_obj and gov_obj:
        groups = TrainingGroup.query.filter_by(slice_code=seg_obj.code, governorate_code=gov_obj.code).all()
        groups_list = [{"code": g.code, "name": g.name} for g in groups]
    return jsonify({"groups": groups_list})