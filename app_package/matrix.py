# -*- coding: utf-8 -*-
"""
المنطق المشترك بين مصفوفة الأدمن (admin.admin_matrix) ومصفوفة مقدم الطلب
(applicant.applicant_matrix) — كانتا دالتين شبه متطابقتين، توحّدتا هون.
"""

from .models import Segment, Governorate, CourseCatalog, TrainingGroup, InsuranceRequest


def build_matrix_context(sel_seg_code=None, sel_gov_code=None, locked_segment_name=None):
    """
    يبني كل البيانات اللازمة لعرض مصفوفة التوزيع (حقائب تدريبية × مجموعات تدريبية).

    - لو انمرّر locked_segment_name (حالة مقدم الطلب): الشريحة تصير مقفلة عليه،
      ومنرجع segments=None (التمبلت تبع مقدم الطلب أصلاً ما بتستخدمها).
    - لو ما انمرّر locked_segment_name (حالة الأدمن): منسمح باختيار أي شريحة
      عبر sel_seg_code، ومنرجع القائمة الكاملة لل segments.
    """
    segments = None
    if locked_segment_name:
        current_segment = Segment.query.filter_by(name=locked_segment_name).first()
        sel_seg_code = current_segment.code if current_segment else ''
        segment_name = locked_segment_name
    else:
        segments = Segment.query.all()
        if not sel_seg_code and segments:
            sel_seg_code = segments[0].code
        current_segment = Segment.query.filter_by(code=sel_seg_code).first()
        segment_name = current_segment.name if current_segment else 'قادة الدولة'

    governorates = Governorate.query.all()
    if not sel_gov_code and governorates:
        sel_gov_code = governorates[0].code

    current_gov = Governorate.query.filter_by(code=sel_gov_code).first()
    governorate_name = current_gov.name if current_gov else ''

    groups = TrainingGroup.query.filter_by(governorate_code=sel_gov_code, slice_code=sel_seg_code).all()
    # الترتيب حسب كود الحقيبة (code) بشكل صريح، لأنه بدون ORDER BY فإن Postgres لا يضمن
    # ترتيب الإدخال، فأي حقيبة جديدة تُضاف مباشرة لقاعدة البيانات تظهر بمكان عشوائي
    # (غالباً بآخر القائمة) بدل مكانها الصحيح ضمن مسارها ومستواها.
    courses = CourseCatalog.query.order_by(CourseCatalog.code).all()

    requests_query = InsuranceRequest.query.filter_by(is_deleted=False, is_archived=False, target_category=segment_name)
    if governorate_name:
        requests_query = requests_query.filter_by(governorate=governorate_name)

    scoped_requests = requests_query.all()

    matrix_data = {(req.course_title, req.group_name): req for req in scoped_requests}

    kpis = {
        'total': len(scoped_requests),
        'new': sum(1 for r in scoped_requests if r.status == 'طلب جديد'),
        'in_progress': sum(1 for r in scoped_requests if r.status == 'جاري المعالجة'),
        'contracted': sum(1 for r in scoped_requests if r.status == 'تم تنفيذ الطلب والتعاقد مع مدرب'),
        'executing': sum(1 for r in scoped_requests if r.status == 'جاري تنفيذ التدريب'),
        'completed': sum(1 for r in scoped_requests if r.status == 'تم الانتهاء من تنفيذ التدريب'),
        'failed': sum(1 for r in scoped_requests if r.status == 'لم يتم تنفيذ الطلب لتعذر الحصول على مدرب'),
    }

    return {
        'segments': segments,
        'governorates': governorates,
        'sel_seg_code': sel_seg_code,
        'sel_gov_code': sel_gov_code,
        'current_segment': current_segment,
        'current_gov': current_gov,
        'courses': courses,
        'groups': groups,
        'matrix_data': matrix_data,
        'kpis': kpis,
    }
