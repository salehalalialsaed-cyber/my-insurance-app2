# -*- coding: utf-8 -*-
"""
Blueprint طلب روابط الاختبار الموقّتة (قبلي/بعدي).
يحتوي على:
- /request/test_link : شاشة الميسّر لطلب رابط اختبار.
- /test-link/<token>  : البوابة العامة (بدون تسجيل دخول) التي تتحقق من الوقت
  وتحوّل لرابط Kobo الحقيقي فقط ضمن النافذة الزمنية المسموحة.
- /api/test_link/get_groups : جلب المجموعات التدريبية حسب الشريحة والمحافظة
- دالة السياق المشتركة build_test_links_context لدعم شاشات تتبع الاختبارات للأدمن ومقدم الطلب.
"""

import logging
import secrets
from datetime import datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify

from .models import (
    db, CourseCatalog, LinkRequest, Segment, Governorate, TrainingGroup,
    WINDOW_DURATION_MINUTES, COMPLETION_RATE_PERCENT, COMPLETION_STATUS_PENDING,
    COMPLETION_STATUS_NO_ENTRY, COMPLETION_STATUS_PARTIAL, COMPLETION_STATUS_COMPLETED,
)
from .constants import TEST_LINK_REQUESTER_ROLE
from .decorators import role_required
from .emails import send_test_link_success_email, send_test_link_failure_email
from app_package import mail

test_links_bp = Blueprint('test_links', __name__)

TEST_LINK_ROLES = [TEST_LINK_REQUESTER_ROLE]

TEST_TYPE_LABELS = {
    'pre': 'الاختبار القبلي',
    'post': 'الاختبار البعدي',
}


def _is_three_part_name(name):
    """تحقق بسيط أن الاسم يتكون من 3 أجزاء على الأقل مفصولة بمسافات."""
    return len([part for part in name.strip().split() if part]) >= 3


def _arabic_count(n, singular, dual, plural_few, plural_many):
    """صياغة عدد بالعربي حسب قواعد الجمع (مفرد/مثنى/جمع قليل 3-10/جمع كثير)."""
    if n == 1:
        return singular
    if n == 2:
        return dual
    if 3 <= n <= 10:
        return f"{n} {plural_few}"
    return f"{n} {plural_many}"


def _format_window_duration(total_minutes):
    """
    يحوّل WINDOW_DURATION_MINUTES لنص عربي مقروء يُعرض بشاشة الطلب، حتى
    يبقى متزامناً تلقائياً مع الثابت الفعلي بدل نص ثابت بالقالب. لو الرقم
    ساعات كاملة (مضاعف 60) بيعرضها بالساعات، وإلا بالدقائق.
    """
    if total_minutes >= 60 and total_minutes % 60 == 0:
        hours = total_minutes // 60
        return _arabic_count(hours, 'ساعة واحدة', 'ساعتان', 'ساعات', 'ساعة')
    return _arabic_count(total_minutes, 'دقيقة واحدة', 'دقيقتان', 'دقائق', 'دقيقة')


def _render_form(form_data=None):
    """
    عرض نموذج طلب الرابط. form_data بتحافظ على القيم اللي عبّاها المستخدم
    لما يرجع النموذج برسالة خطأ، حتى ما يضطر يعيد تعبئة كل شي من الصفر.
    today بتمنع اختيار تاريخ ماضي من واجهة المتصفح نفسها (والتحقق الفعلي
    بيضل موجود بالسيرفر).
    """
    return render_template(
        'request_test_link.html',
        courses=CourseCatalog.query.order_by(CourseCatalog.title).all(),
        segments=Segment.query.order_by(Segment.name).all(),
        governorates=Governorate.query.order_by(Governorate.name).all(),
        form_data=form_data or {},
        window_duration_label=_format_window_duration(WINDOW_DURATION_MINUTES),
        today=datetime.now().strftime('%Y-%m-%d'),
    )


@test_links_bp.route('/request/test_link', methods=['GET', 'POST'])
@role_required(TEST_LINK_ROLES, check_password_change=True)
def request_test_link():
    if request.method == 'POST':
        try:
            facilitator_full_name = (request.form.get('facilitator_full_name') or '').strip()
            segment_name = request.form.get('segment_name')
            governorate_name = request.form.get('governorate_name')
            group_name = request.form.get('group_name')
            course_code = request.form.get('course_code')
            test_type = request.form.get('test_type')
            requested_date_str = request.form.get('requested_date')
            start_time_str = request.form.get('start_time')
            expected_trainees_count_str = (request.form.get('expected_trainees_count') or '').strip()

            submitted = {
                'facilitator_full_name': facilitator_full_name,
                'segment_name': segment_name,
                'governorate_name': governorate_name,
                'group_name': group_name,
                'course_code': course_code,
                'test_type': test_type,
                'requested_date': requested_date_str,
                'start_time': start_time_str,
                'expected_trainees_count': expected_trainees_count_str,
            }

            # 1. تحقق من الحقول الإجبارية
            if (not facilitator_full_name or not segment_name or not governorate_name
                    or not group_name or not course_code or test_type not in ('pre', 'post')
                    or not requested_date_str or not start_time_str or not expected_trainees_count_str):
                flash('خطأ: يرجى تعبئة كافة الحقول الإجبارية.', 'danger')
                return _render_form(submitted)

            # 2. الاسم الثلاثي
            if not _is_three_part_name(facilitator_full_name):
                flash('خطأ: يرجى إدخال الاسم الثلاثي كاملاً.', 'danger')
                return _render_form(submitted)

            # 2ب. العدد المتوقع للمتدربين يجب أن يكون رقماً صحيحاً موجباً
            try:
                expected_trainees_count = int(expected_trainees_count_str)
            except ValueError:
                expected_trainees_count = None
            if expected_trainees_count is None or expected_trainees_count <= 0:
                flash('خطأ: عدد المتدربين المتوقع يجب أن يكون رقماً صحيحاً أكبر من الصفر.', 'danger')
                return _render_form(submitted)

            course = db.session.get(CourseCatalog, course_code)
            if not course:
                flash('خطأ: الكورس المختار غير موجود.', 'danger')
                return _render_form(submitted)

            # 3. تحويل التاريخ والوقت لكائن datetime واحد
            try:
                requested_date = datetime.strptime(requested_date_str, '%Y-%m-%d').date()
                start_time = datetime.strptime(
                    f"{requested_date_str} {start_time_str}", '%Y-%m-%d %H:%M'
                )
            except ValueError:
                flash('خطأ: صيغة التاريخ أو الوقت غير صحيحة.', 'danger')
                return _render_form(submitted)

            # 4. رفض أي طلب بتاريخ/وقت في الماضي
            if start_time <= datetime.now():
                flash('خطأ: لا يمكن طلب رابط بتاريخ أو وقت سابق للحظة الحالية.', 'danger')
                return _render_form(submitted)

            window_end = start_time + timedelta(minutes=WINDOW_DURATION_MINUTES)

            # 5. هل يوجد رابط اختبار فعلي لهذا الكورس ولهذا النوع؟
            actual_link = course.pre_test_link if test_type == 'pre' else course.post_test_link
            link_exists = bool(actual_link and actual_link.strip())

            token = secrets.token_urlsafe(32)
            new_link_req = LinkRequest(
                facilitator_id=session['user_id'],
                facilitator_email=session['user_email'],
                facilitator_full_name=facilitator_full_name,
                segment_name=segment_name,
                governorate_name=governorate_name,
                group_name=group_name,
                course_code=course_code,
                test_type=test_type,
                requested_date=requested_date,
                start_time=start_time,
                window_end=window_end,
                token=token,
                status='تم التنفيذ' if link_exists else 'لم يتم التنفيذ',
                expected_trainees_count=expected_trainees_count if link_exists else None,
                completion_status=COMPLETION_STATUS_PENDING if link_exists else None,
            )
            db.session.add(new_link_req)
            db.session.commit()

            if link_exists:
                gateway_url = url_for('test_links.open_test_link', token=token, _external=True)
                send_test_link_success_email(mail, new_link_req, course, gateway_url)
                flash('تم إصدار رابط الاختبار بنجاح، تحقق من بريدك الإلكتروني.', 'success')
            else:
                send_test_link_failure_email(mail, new_link_req, course)
                flash(
                    'لا يوجد رابط اختبار مسجّل لهذا الكورس حالياً. تم توثيق طلبك، '
                    'يرجى التواصل مع دائرة البرامج التدريبية.',
                    'warning'
                )

            return redirect(url_for('test_links.request_test_link'))

        except Exception as e:
            db.session.rollback()
            logging.error(f"Error in request_test_link: {str(e)}", exc_info=True)
            flash('حدث خطأ غير متوقع أثناء معالجة الطلب. يرجى المحاولة لاحقاً.', 'danger')
            return _render_form(request.form.to_dict())

    return _render_form()


@test_links_bp.route('/api/test_link/get_groups')
@role_required(TEST_LINK_ROLES)
def get_groups_for_test_link():
    """نفس منطق /api/get_groups بـ applicant.py، بس متاح لدور الميسّر."""
    seg_obj = Segment.query.filter_by(name=request.args.get('segment')).first()
    gov_obj = Governorate.query.filter_by(name=request.args.get('governorate')).first()
    groups_list = []
    if seg_obj and gov_obj:
        groups = TrainingGroup.query.filter_by(slice_code=seg_obj.code, governorate_code=gov_obj.code).all()
        groups_list = [{"code": g.code, "name": g.name} for g in groups]
    return jsonify({"groups": groups_list})


@test_links_bp.route('/test-link/<token>')
def open_test_link(token):
    """
    البوابة العامة: لا تتطلب تسجيل دخول (المتدربون ليسوا مستخدمين بالنظام).
    تتحقق من الوقت الحالي مقابل نافذة الطلب، وتحوّل لرابط Kobo الحقيقي فقط
    ضمن النافذة المسموحة.
    """
    link_req = LinkRequest.query.filter_by(token=token).first()

    if not link_req:
        return render_template('test_link_status.html', state='not_found'), 404

    now = datetime.now()

    if now < link_req.start_time:
        return render_template(
            'test_link_status.html', state='not_started',
            start_time=link_req.start_time
        )

    if now > link_req.window_end:
        return render_template(
            'test_link_status.html', state='expired',
            window_end=link_req.window_end
        )

    course = db.session.get(CourseCatalog, link_req.course_code)
    actual_link = course.pre_test_link if link_req.test_type == 'pre' else course.post_test_link

    if not actual_link:
        return render_template('test_link_status.html', state='link_missing'), 404

    link_req.click_count = (link_req.click_count or 0) + 1
    db.session.commit()

    return redirect(actual_link)


def refresh_completion_statuses():
    """
    تحديث كسول (lazy) لحالة completion_status لكل طلبات الروابط اللي فيها
    بوابة فعلية (status='تم التنفيذ'), انتهت نافذتها الزمنية، ولسا مسجّلة
    'بانتظار الاختبار'.
    """
    now = datetime.now()
    pending_rows = LinkRequest.query.filter(
        LinkRequest.status == 'تم التنفيذ',
        LinkRequest.window_end < now,
        db.or_(
            LinkRequest.completion_status == COMPLETION_STATUS_PENDING,
            LinkRequest.completion_status.is_(None),
        ),
    ).all()

    if not pending_rows:
        return

    for row in pending_rows:
        clicks = row.click_count or 0
        expected = row.expected_trainees_count or 0

        if clicks == 0:
            row.completion_status = COMPLETION_STATUS_NO_ENTRY
        elif expected > 0 and clicks >= (COMPLETION_RATE_PERCENT / 100) * expected:
            row.completion_status = COMPLETION_STATUS_COMPLETED
        else:
            row.completion_status = COMPLETION_STATUS_PARTIAL

    db.session.commit()


def build_test_links_context(locked_segment_name=None):
    """
    دالة مشتركة لاستخراج واستعلام بيانات تتبع روابط الاختبارات والـ 7 KPIs.
    تستُخدم من الأدمن (مع إمكانية اختيار أي شريحة) ومن مقدم الطلب (مع قفل الشريحة تلقائياً).
    """
    refresh_completion_statuses()

    # جلب الفلاتر من GET parameters
    segment_filter = locked_segment_name or request.args.get('segment', '').strip()
    governorate_filter = request.args.get('governorate', '').strip()
    group_filter = request.args.get('group', '').strip()
    course_filter = request.args.get('course', '').strip()
    test_type_filter = request.args.get('test_type', '').strip()
    completion_filter = request.args.get('completion_status', '').strip()
    date_from_str = request.args.get('date_from', '').strip()
    date_to_str = request.args.get('date_to', '').strip()

    query = LinkRequest.query

    if locked_segment_name:
        query = query.filter_by(segment_name=locked_segment_name)
    elif segment_filter:
        query = query.filter_by(segment_name=segment_filter)

    if governorate_filter:
        query = query.filter_by(governorate_name=governorate_filter)
    if group_filter:
        query = query.filter_by(group_name=group_filter)
    if course_filter:
        query = query.filter_by(course_code=course_filter)
    if test_type_filter:
        query = query.filter_by(test_type=test_type_filter)
    if completion_filter:
        query = query.filter_by(completion_status=completion_filter)

    if date_from_str:
        try:
            d_from = datetime.strptime(date_from_str, '%Y-%m-%d').date()
            query = query.filter(LinkRequest.requested_date >= d_from)
        except ValueError:
            pass

    if date_to_str:
        try:
            d_to = datetime.strptime(date_to_str, '%Y-%m-%d').date()
            query = query.filter(LinkRequest.requested_date <= d_to)
        except ValueError:
            pass

    requests_list = query.order_by(LinkRequest.start_time.desc()).all()

    # حساب الـ 7 KPIs للنتائج المفلترة الحالية
    total_count = len(requests_list)
    executed_count = sum(1 for r in requests_list if r.status == 'تم التنفيذ')
    not_executed_count = sum(1 for r in requests_list if r.status == 'لم يتم التنفيذ')
    pending_count = sum(1 for r in requests_list if r.completion_status == COMPLETION_STATUS_PENDING)
    fully_completed_count = sum(1 for r in requests_list if r.completion_status == COMPLETION_STATUS_COMPLETED)
    partial_count = sum(1 for r in requests_list if r.completion_status == COMPLETION_STATUS_PARTIAL)
    no_entry_count = sum(1 for r in requests_list if r.completion_status == COMPLETION_STATUS_NO_ENTRY)

    # جلب قوائم القوائم المنسدلة للفلاتر
    segments = Segment.query.order_by(Segment.name).all()
    governorates = Governorate.query.order_by(Governorate.name).all()
    courses = CourseCatalog.query.order_by(CourseCatalog.title).all()

    # جلب المجموعات بناءً على الشريحة والمحافظة المختارة إن وجدت
    groups_query = TrainingGroup.query
    if segment_filter:
        seg_obj = Segment.query.filter_by(name=segment_filter).first()
        if seg_obj:
            groups_query = groups_query.filter_by(slice_code=seg_obj.code)
    if governorate_filter:
        gov_obj = Governorate.query.filter_by(name=governorate_filter).first()
        if gov_obj:
            groups_query = groups_query.filter_by(governorate_code=gov_obj.code)
    groups = groups_query.order_by(TrainingGroup.name).all()

    # ربط الكورسات بأساميها لتسهيل العرض بالقالب
    courses_map = {c.code: c.title for c in courses}

    return {
        'requests': requests_list,
        'total_count': total_count,
        'executed_count': executed_count,
        'not_executed_count': not_executed_count,
        'pending_count': pending_count,
        'fully_completed_count': fully_completed_count,
        'partial_count': partial_count,
        'no_entry_count': no_entry_count,
        'segments': segments,
        'governorates': governorates,
        'courses': courses,
        'courses_map': courses_map,
        'groups': groups,
        'locked_segment_name': locked_segment_name,
        # الاحتفاظ بالقيم المختارة للفلاتر
        'selected_segment': segment_filter,
        'selected_governorate': governorate_filter,
        'selected_group': group_filter,
        'selected_course': course_filter,
        'selected_test_type': test_type_filter,
        'selected_completion': completion_filter,
        'selected_date_from': date_from_str,
        'selected_date_to': date_to_str,
    }