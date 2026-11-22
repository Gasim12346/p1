"""
بوابة الامتحانات الخاصة: امتحانات تحديد المستوى (Placement Exams Views).
تشمل:
1. شاشة قائمة امتحانات تحديد المستوى (عرض البطاقات والعرض الجدولي مع البحث والفلترة).
2. شاشة رصد الدرجات وإجراءات المرشحين (حضور، نقل نتائج سابقة، تقييم نظري وعملي).
3. كشف النتيجة الرسمي القابل للطباعة بحجم A4 والتجزئة التلقائية للصفحات.
"""

from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q

from apps.core.models import Institute, SystemSettings
from apps.documents.models import CertificateSettings
from apps.core.permissions import is_instructor_user, is_admin_user
from apps.academic.models import Instructor
from apps.trainees.models import Trainee
from .models import (
    PlacementExamOrder,
    PlacementExamCandidate,
    PlacementExamStatus,
    AssessmentType,
    CandidateClassification,
    AttendanceStatus,
    CandidateActionType,
)


def get_sample_placement_exams():
    """بيانات تجريبية موحدة لامتحانات تحديد المستوى وفق النموذج السوداني المعتمد:
    - عينتان تجريبية نظيفة (طلب #001 و طلب #002)
    - مادة واحدة فقط (حاسوب)
    - الغرض من الطلب وبنده الفرعي والجهة الطالبة
    - موعد الانعقاد وقائمة المشاركين
    """
    sample_exams = [
        {
            'id': 'sample-sd-001',
            'request_internal_id': 'طلب #001',
            'exam_number': 'طلب #001',
            'code': 'طلب #001',
            'signal_number': '00452',
            'source_entity': 'قيادة سلاح المدرعات (الشجرة)',
            'host_entity': 'قيادة سلاح المدرعات (الشجرة)',
            'destination_country': 'جمهورية مصر العربية',
            'purpose': 'آلية',
            'sub_purpose': 'آمر آلية',
            'classification': 'officers',
            'classification_label': 'ضباط',
            'receipt_date': '2026-11-10',
            'exam_date': '2026-12-05',
            'exam_time': '09:00',
            'exam_day_name': 'السبت',
            'subject': 'حاسوب',
            'title': 'امتحان تحديد المستوى (حاسوب)',
            'target_course': 'آلية — آمر آلية',
            'supervising_teacher': 'مقدم / قاسم ابوه',
            'supervisor': 'مقدم / قاسم ابوه',
            'assessment_type': 'theory_and_practical',
            'theory_max_grade': 50,
            'practical_max_grade': 50,
            'total_max_grade': 100,
            'status': 'in_progress',
            'status_label': 'قيد التنفيذ',
            'status_badge_class': 'badge-status-in-progress',
            'is_confirmed': False,
            'official_request_image': True,
            'trainees_count': 3,
            'subjects_count': 1,
            'subjects': [{
                'name': 'حاسوب',
                'status': 'pending',
                'assessment_type': 'theory_and_practical',
                'total_max_grade': 100,
                'theory_max_grade': 50,
                'practical_max_grade': 50
            }],
            'trainees': [
                {'military_number': '482910', 'name': 'عثمان البشير فضل المولى', 'rank': 'نقيب', 'force': 'القوات البرية السودانية', 'unit': 'سلاح المدرعات (الشجرة)', 'attendance_status': 'unrecorded'},
                {'military_number': '519203', 'name': 'طارق أحمد البدوي', 'rank': 'ملازم أول', 'force': 'القوات البرية السودانية', 'unit': 'سلاح المدرعات (الشجرة)', 'attendance_status': 'unrecorded'},
                {'military_number': '620194', 'name': 'محمد عبد الله إدريس', 'rank': 'مساعد', 'force': 'القوات البرية السودانية', 'unit': 'سلاح المدرعات (الشجرة)', 'attendance_status': 'unrecorded'}
            ],
            'created_at': '2026-11-10'
        },
        {
            'id': 'sample-sd-002',
            'request_internal_id': 'طلب #002',
            'exam_number': 'طلب #002',
            'code': 'طلب #002',
            'signal_number': '00819',
            'source_entity': 'إدارة الملحقيات العسكرية (الخرطوم)',
            'host_entity': 'إدارة الملحقيات العسكرية (الخرطوم)',
            'destination_country': 'جمهورية تركيا',
            'purpose': 'ملحق',
            'sub_purpose': 'مساعد ملحق عسكري',
            'classification': 'officers',
            'classification_label': 'ضباط',
            'receipt_date': '2026-11-12',
            'exam_date': '2026-12-10',
            'exam_time': '10:30',
            'exam_day_name': 'الخميس',
            'subject': 'حاسوب',
            'title': 'امتحان تحديد المستوى (حاسوب)',
            'target_course': 'ملحق — مساعد ملحق عسكري',
            'supervising_teacher': 'رائد / لبنى عبد الرحمن',
            'supervisor': 'رائد / لبنى عبد الرحمن',
            'assessment_type': 'theory_and_practical',
            'theory_max_grade': 60,
            'practical_max_grade': 40,
            'total_max_grade': 100,
            'status': 'in_progress',
            'status_label': 'قيد التنفيذ',
            'status_badge_class': 'badge-status-in-progress',
            'is_confirmed': False,
            'official_request_image': True,
            'trainees_count': 2,
            'subjects_count': 1,
            'subjects': [{
                'name': 'حاسوب',
                'status': 'pending',
                'assessment_type': 'theory_and_practical',
                'total_max_grade': 100,
                'theory_max_grade': 60,
                'practical_max_grade': 40
            }],
            'trainees': [
                {'military_number': '710492', 'name': 'عاصم تاج السر الفكي', 'rank': 'نقيب', 'force': 'القوات البرية السودانية', 'unit': 'إدارة الملحقيات العسكرية (الخرطوم)', 'attendance_status': 'unrecorded'},
                {'military_number': '739104', 'name': 'وليد كمال الدين مصطفى', 'rank': 'ملازم أول', 'force': 'القوات البرية السودانية', 'unit': 'إدارة الملحقيات العسكرية (الخرطوم)', 'attendance_status': 'unrecorded'}
            ],
            'created_at': '2026-11-12'
        }
    ]
    return sample_exams


def _order_to_dict(order):
    """تحويل نموذج PlacementExamOrder إلى قاموس متوافق كلياً مع قوالب العرض"""
    code_display = order.order_code or f"طلب #{str(order.internal_order_number).zfill(3)}"
    target_course = f"{order.purpose} — {order.sub_purpose}" if order.sub_purpose else order.purpose
    teacher = order.supervisor_name_snapshot or (order.supervisor.name if order.supervisor else 'قيد التحديد')
    
    candidates_list = []
    for c in order.candidates.all():
        candidates_list.append({
            'military_number': c.military_number_snapshot,
            'name': c.name_snapshot,
            'rank': c.rank_snapshot,
            'force': c.force_snapshot,
            'unit': c.unit_snapshot,
            'attendance_status': c.attendance_status,
            'theory_score': float(c.theory_score) if c.theory_score is not None else None,
            'practical_score': float(c.practical_score) if c.practical_score is not None else None,
            'total_score': float(c.total_score) if c.total_score is not None else None,
            'notes': c.notes or '',
        })

    status_badge_map = {
        PlacementExamStatus.IN_PROGRESS: 'badge-status-in-progress',
        PlacementExamStatus.CONFIRMED: 'badge-status-confirmed',
        PlacementExamStatus.PENDING_APPROVAL: 'badge-status-pending-approval',
        PlacementExamStatus.APPROVED: 'badge-status-approved',
    }

    return {
        'id': str(order.id),
        'db_id': order.id,
        'request_internal_id': code_display,
        'exam_number': code_display,
        'code': code_display,
        'signal_number': order.signal_number,
        'source_entity': order.source_entity,
        'host_entity': order.host_entity or order.source_entity,
        'destination_country': order.destination_country,
        'purpose': order.purpose,
        'sub_purpose': order.sub_purpose,
        'classification': order.classification,
        'classification_label': order.get_classification_display(),
        'receipt_date': order.receipt_date.strftime('%Y-%m-%d') if order.receipt_date else '',
        'exam_date': order.exam_date.strftime('%Y-%m-%d') if order.exam_date else '',
        'exam_time': order.exam_time.strftime('%H:%M') if order.exam_time else '09:00',
        'exam_day_name': '',
        'subject': order.subject_name,
        'title': f"امتحان تحديد المستوى ({order.subject_name})",
        'target_course': target_course,
        'supervising_teacher': teacher,
        'supervisor': teacher,
        'assessment_type': order.assessment_type,
        'theory_max_grade': float(order.theory_max_score),
        'practical_max_grade': float(order.practical_max_score),
        'total_max_grade': float(order.total_max_score),
        'status': order.status,
        'status_label': order.get_status_display(),
        'status_badge_class': status_badge_map.get(order.status, 'badge-status-in-progress'),
        'is_confirmed': order.is_confirmed,
        'official_request_image': bool(order.official_signal_file),
        'trainees_count': order.candidates.count(),
        'subjects_count': 1,
        'subjects': [{
            'name': order.subject_name,
            'status': 'pending',
            'assessment_type': order.assessment_type,
            'total_max_grade': float(order.total_max_score),
            'theory_max_grade': float(order.theory_max_score),
            'practical_max_grade': float(order.practical_max_score)
        }],
        'trainees': candidates_list,
        'created_at': order.created_at.strftime('%Y-%m-%d') if order.created_at else ''
    }


@login_required
def placement_exams_list_view(request):
    """شاشة قائمة امتحانات تحديد المستوى (عرض البطاقات والعرض الجدولي مع البحث والفلترة)"""
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        messages.warning(request, 'صلاحيات حسابك محصورة في صفحة رصد نتائج المواد المكلف بها فقط.')
        return redirect('training:results_center')

    # جلب الأوامر المسجلة في قاعدة البيانات
    db_orders = PlacementExamOrder.objects.select_related('supervisor').prefetch_related('candidates').all()
    
    # دمج بيانات قاعدة البيانات مع العينات النموذجية إن وُجدت
    exams = []
    if db_orders.exists():
        for o in db_orders:
            exams.append(_order_to_dict(o))
    else:
        exams = get_sample_placement_exams()

    available_statuses = [
        ('all', 'جميع الحالات'),
        ('in_progress', 'قيد التنفيذ والرصد'),
        ('pending_approval', 'بانتظار اعتماد النتائج'),
        ('approved', 'النتائج معتمدة'),
    ]

    host_entities = sorted(list(set(e['host_entity'] for e in exams if e.get('host_entity'))))
    supervisors = sorted(list(set(e['supervisor'] for e in exams if e.get('supervisor') and e['supervisor'] != 'قيد التحديد')))
    exam_dates = sorted(list(set(e['exam_date'] for e in exams if e.get('exam_date'))), reverse=True)
    exam_years = sorted(list(set(e['exam_date'][:4] for e in exams if e.get('exam_date'))), reverse=True)

    # قائمة الدارسين المعتمدة
    trainees_qs = Trainee.objects.all()[:30]
    if trainees_qs.exists():
        registered_trainees = [
            {
                'military_number': str(t.military_number),
                'name': t.name,
                'rank': getattr(t, 'rank', '') or '',
                'force': getattr(t, 'force', '') or '',
                'unit': getattr(t, 'unit', '') or ''
            }
            for t in trainees_qs
        ]
    else:
        registered_trainees = [
            {'military_number': '11029481', 'name': 'محمد بن ناصر الشهري', 'rank': 'نقيب', 'force': 'القوات البرية', 'unit': 'سلاح المدرعات'},
            {'military_number': '10984723', 'name': 'تركي بن سعد القحطاني', 'rank': 'ملازم أول', 'force': 'القوات الجوية', 'unit': 'جناح الطيران'},
            {'military_number': '10847291', 'name': 'سلمان بن حمد الدوسري', 'rank': 'رئيس رقباء', 'force': 'القوات البحرية', 'unit': 'قاعدة البحر الأحمر'},
        ]

    # قائمة المعلمين المعتمدة بالنظام
    db_instructors = list(Instructor.objects.filter(is_active=True).values('military_number', 'rank', 'name', 'force', 'unit'))
    default_instructors = [
        {'military_number': '1122334455', 'rank': 'مقدم', 'name': 'قاسم ابوه', 'force': 'القوات البحرية', 'unit': 'قاعدة فلامنجو البحرية'},
        {'military_number': '12345678', 'rank': 'رائد', 'name': 'لبنى عبد الرحمن', 'force': 'القوات البرية', 'unit': 'إدارة نظم المعلومات'},
        {'military_number': '11002233', 'rank': 'عقيد', 'name': 'خالد بن سلطان العتيبي', 'force': 'القوات البرية', 'unit': 'جناح التعليم والتدريب'},
    ]

    seen_mils = set()
    registered_instructors = []
    for inst in db_instructors + default_instructors:
        mil = str(inst.get('military_number', ''))
        if mil and mil not in seen_mils:
            seen_mils.add(mil)
            registered_instructors.append(inst)

    return render(request, 'training/placement_exams_list.html', {
        'exams': exams,
        'total_exams': len(exams),
        'available_statuses': available_statuses,
        'host_entities': host_entities,
        'supervisors': supervisors,
        'exam_dates': exam_dates,
        'exam_years': exam_years,
        'registered_trainees': registered_trainees,
        'registered_instructors': registered_instructors,
    })


@login_required
def placement_results_entry_view(request, exam_id):
    """شاشة رصد درجات امتحانات تحديد المستوى وإجراءات المرشحين"""
    selected_exam = None
    
    # محاولة جلب الطلب من قاعدة البيانات أولاً
    if str(exam_id).isdigit():
        order = PlacementExamOrder.objects.filter(id=int(exam_id)).first()
        if order:
            selected_exam = _order_to_dict(order)

    if not selected_exam:
        sample_exams = get_sample_placement_exams()
        for ex in sample_exams:
            if str(ex.get('id')) == str(exam_id) or str(ex.get('exam_number')) == str(exam_id) or str(ex.get('code')) == str(exam_id):
                selected_exam = dict(ex)
                break

    if not selected_exam:
        selected_exam = {
            'id': exam_id,
            'exam_number': 'طلب #001',
            'code': 'طلب #001',
            'request_internal_id': 'طلب #001',
            'subject': 'حاسوب',
            'title': 'امتحان تحديد المستوى (حاسوب)',
            'target_course': 'دورة تأهيلية متقدمة',
            'host_entity': 'قيادة سلاح المدرعات (الشجرة)',
            'exam_date': '2026-12-05',
            'official_request_date': '2026-11-10',
            'supervising_teacher': 'مقدم / قاسم ابوه',
            'assessment_type': 'theory_and_practical',
            'total_max_grade': 100,
            'theory_max_grade': 50,
            'practical_max_grade': 50,
            'status': 'in_progress',
            'status_label': 'قيد التنفيذ',
            'is_confirmed': False,
        }

    raw_trainees = selected_exam.get('trainees', [])
    officer_ranks = {'ملازم', 'ملازم أول', 'نقيب', 'رائد', 'مقدم', 'عقيد', 'عميد', 'لواء', 'فريق'}

    all_trainees = []
    for idx, t in enumerate(raw_trainees):
        rank = t.get('rank', '').strip()
        is_officer = any(o in rank for o in officer_ranks)
        category = 'officer' if is_officer else 'nco'
        
        mod = idx % 4
        if mod == 0:
            prev_status = 'valid'
            prev_status_label = 'صالحة (أقل من 6 أشهر)'
            prev_status_badge = 'bg-success-subtle text-success border border-success-subtle'
            prev_date = '2026-09-10'
            prev_source = f"{selected_exam.get('target_course', 'دورة متقدمة')} - 18"
            prev_has_breakdown = True
            prev_theory = 55.0
            prev_practical = 37.0
            prev_total = 92.0
            action = 'retain'
            current_theory = 55.0
            current_practical = 37.0
            current_total = 92.0
            current_percentage = 92.0
            current_grade_label = 'ممتاز (أ)'
            current_grade_badge = 'badge-grade-a'
            is_graded = True
            notes = ''
        elif mod == 1:
            prev_status = 'valid'
            prev_status_label = 'صالحة (أقل من 6 أشهر)'
            prev_status_badge = 'bg-success-subtle text-success border border-success-subtle'
            prev_date = '2026-08-15'
            prev_source = f"{selected_exam.get('target_course', 'دورة تأهيلية')} - 12"
            prev_has_breakdown = False
            prev_theory = None
            prev_practical = None
            prev_total = 76.0
            action = 'retake'
            current_theory = 52.0
            current_practical = 34.0
            current_total = 86.0
            current_percentage = 86.0
            current_grade_label = 'ممتاز (أ)'
            current_grade_badge = 'badge-grade-a'
            is_graded = True
            notes = ''
        elif mod == 2:
            prev_status = 'expired'
            prev_status_label = 'انتهت صلاحية النتيجة'
            prev_status_badge = 'bg-warning-subtle text-warning-emphasis border border-warning-subtle'
            prev_date = '2026-01-20'
            prev_source = f"{selected_exam.get('target_course', 'دورة فنية')} - 09"
            prev_has_breakdown = True
            prev_theory = 50.0
            prev_practical = 34.0
            prev_total = 84.0
            action = 'mandatory'
            current_theory = None
            current_practical = None
            current_total = None
            current_percentage = None
            current_grade_label = None
            current_grade_badge = None
            is_graded = False
            notes = ''
        else:
            prev_status = 'none'
            prev_status_label = 'لا توجد نتيجة سابقة'
            prev_status_badge = 'bg-secondary-subtle text-secondary border border-secondary-subtle'
            prev_date = None
            prev_source = None
            prev_has_breakdown = False
            prev_theory = None
            prev_practical = None
            prev_total = None
            action = 'mandatory'
            current_theory = 48.0 if (idx == 3 and len(raw_trainees) > 3) else None
            current_practical = 32.0 if (idx == 3 and len(raw_trainees) > 3) else None
            current_total = 80.0 if (idx == 3 and len(raw_trainees) > 3) else None
            current_percentage = 80.0 if (idx == 3 and len(raw_trainees) > 3) else None
            current_grade_label = 'جيد جداً (ب)' if (idx == 3 and len(raw_trainees) > 3) else None
            current_grade_badge = 'badge-grade-b' if (idx == 3 and len(raw_trainees) > 3) else None
            is_graded = bool(idx == 3 and len(raw_trainees) > 3)
            notes = ''

        all_trainees.append({
            'id': idx + 1,
            'military_number': t.get('military_number', f"1000{idx}"),
            'name': t.get('name', ''),
            'rank': rank,
            'unit': t.get('unit', ''),
            'force': t.get('force', ''),
            'category': category,
            'prev_status': prev_status,
            'prev_status_label': prev_status_label,
            'prev_status_badge': prev_status_badge,
            'prev_date': prev_date,
            'prev_source': prev_source,
            'prev_has_breakdown': prev_has_breakdown,
            'prev_theory': prev_theory,
            'prev_practical': prev_practical,
            'prev_total': prev_total,
            'action': action,
            'current_theory': current_theory,
            'current_practical': current_practical,
            'current_total': current_total,
            'current_percentage': current_percentage,
            'current_grade_label': current_grade_label,
            'current_grade_badge': current_grade_badge,
            'is_graded': is_graded,
            'notes': notes,
        })

    officers = [t for t in all_trainees if t['category'] == 'officer']
    ncos = [t for t in all_trainees if t['category'] == 'nco']

    context = {
        'exam': selected_exam,
        'officers': officers,
        'ncos': ncos,
        'all_trainees': all_trainees,
        'total_participants': len(all_trainees),
        'from_source': request.GET.get('from', '').strip(),
        'from_tab': request.GET.get('from', 'sessions').strip(),
    }
    return render(request, 'training/placement_results_entry.html', context)


@login_required
def placement_results_sheet_view(request, exam_id):
    """كشف النتيجة الرسمي لامتحان تحديد المستوى وفق النموذج الأصلي المعتمد بحجم A4 والتجزئة التلقائية"""
    selected_exam = None
    if str(exam_id).isdigit():
        order = PlacementExamOrder.objects.filter(id=int(exam_id)).first()
        if order:
            selected_exam = _order_to_dict(order)

    if not selected_exam:
        sample_exams = get_sample_placement_exams()
        for ex in sample_exams:
            if str(ex.get('id')) == str(exam_id) or str(ex.get('exam_number')) == str(exam_id) or str(ex.get('code')) == str(exam_id):
                selected_exam = dict(ex)
                break

    if not selected_exam:
        selected_exam = {
            'id': exam_id,
            'exam_number': '002-26',
            'code': '002-26',
            'subject': 'اللغة الإنجليزية العسكرية',
            'title': 'امتحان تحديد المستوى في اللغة الإنجليزية العسكرية',
            'target_course': 'دورة القيادة والأركان المشتركة',
            'host_entity': 'جناح التدريب والتعليم الميداني',
            'exam_date': '2026-11-28',
            'official_request_date': '2026-11-05',
            'supervising_teacher': 'العقيد / خالد بن سلطان العتيبي',
            'assessment_type': 'theory_and_practical',
            'total_max_grade': 100,
            'theory_max_grade': 60,
            'practical_max_grade': 40,
            'status': 'completed',
            'status_label': 'مكتمل ومعتمد',
        }

    # استمداد بيانات المسؤول المعتمد والتوقيع من CertificateSettings
    cert_settings = CertificateSettings.objects.first()
    if cert_settings:
        official_rank = (cert_settings.left_signer_rank or 'عقيد مهندس').strip()
        official_name = (cert_settings.left_signer_name or 'المعز علي محمد خير').strip()
        official_title = (cert_settings.left_signer_title or 'قائد معهد نظم المعلومات والإحصاء').strip()
        station_name = (cert_settings.station_text or 'الخرطوم').strip()
        dept_name = (cert_settings.header_line_1 or 'إدارة نظم المعلومات والإحصاء').strip()
        institute_name = (cert_settings.header_line_2 or 'معهد نظم المعلومات والإحصاء').strip()
    else:
        official_rank = 'عقيد مهندس'
        official_name = 'المعز علي محمد خير'
        official_title = 'قائد معهد نظم المعلومات والإحصاء'
        station_name = 'الخرطوم'
        dept_name = 'إدارة نظم المعلومات والإحصاء'
        institute_name = 'معهد نظم المعلومات والإحصاء'

    arabic_months = {
        1: 'يناير', 2: 'فبراير', 3: 'مارس', 4: 'أبريل',
        5: 'مايو', 6: 'يونيو', 7: 'يوليو', 8: 'أغسطس',
        9: 'سبتمبر', 10: 'أكتوبر', 11: 'نوفمبر', 12: 'ديسمبر'
    }
    
    approval_date_raw = selected_exam.get('approval_date') or request.GET.get('approval_date', '').strip()
    if not approval_date_raw:
        approval_date_raw = timezone.now().strftime('%Y-%m-%d')

    approval_date_formatted = 'نوفمبر 2026م'
    try:
        parts = str(approval_date_raw).split('-')
        if len(parts) >= 2:
            y = parts[0]
            m = int(parts[1])
            approval_date_formatted = f"{arabic_months.get(m, 'نوفمبر')} {y}م"
    except Exception:
        approval_date_formatted = 'نوفمبر 2026م'

    raw_trainees = selected_exam.get('trainees', [])
    assessment_type = selected_exam.get('assessment_type', 'theory_and_practical')
    is_theory_only = (assessment_type == 'theory_only')

    all_trainees = []
    for idx, t in enumerate(raw_trainees):
        rank = (t.get('rank') or '').strip()
        name = (t.get('name') or '').strip()
        mod = idx % 4
        if mod == 0:
            c_total = 92.0
        elif mod == 1:
            c_total = 86.0
        elif mod == 2:
            c_total = 84.0
        else:
            c_total = 80.0

        notes = (t.get('notes') or '').strip()

        if is_theory_only:
            c_theory = c_total
            c_practical = '-'
        else:
            c_theory = round(c_total * 0.6, 1)
            c_practical = round(c_total * 0.4, 1)

        all_trainees.append({
            'military_number': t.get('military_number', f"1000{idx}"),
            'name': name,
            'rank': rank,
            'theory': f"{c_theory:.1f}" if isinstance(c_theory, (int, float)) else str(c_theory),
            'practical': f"{c_practical:.1f}" if isinstance(c_practical, (int, float)) else str(c_practical),
            'total': f"{c_total:.1f}",
            'percentage': f"{c_total:.1f}%",
            'notes': notes,
        })

    ROWS_PER_PAGE = 10
    total_participants = len(all_trainees)
    pages = []

    if total_participants == 0:
        pages.append({
            'page_number': 1,
            'total_pages': 1,
            'rows': [],
            'has_trainees': False,
        })
    else:
        total_pages = (total_participants + ROWS_PER_PAGE - 1) // ROWS_PER_PAGE
        for p_idx in range(total_pages):
            page_slice = all_trainees[p_idx * ROWS_PER_PAGE : (p_idx + 1) * ROWS_PER_PAGE]
            page_rows = []
            for r_idx, tr in enumerate(page_slice):
                serial = p_idx * ROWS_PER_PAGE + r_idx + 1
                page_rows.append({
                    'serial': serial,
                    'military_number': tr['military_number'],
                    'rank': tr['rank'],
                    'name': tr['name'],
                    'theory': tr['theory'],
                    'practical': tr['practical'],
                    'total': tr['total'],
                    'percentage': tr['percentage'],
                    'notes': tr['notes'],
                })
            pages.append({
                'page_number': p_idx + 1,
                'total_pages': total_pages,
                'rows': page_rows,
                'has_trainees': True,
            })

    context = {
        'exam': selected_exam,
        'pages': pages,
        'total_participants': total_participants,
        'approval_date_formatted': approval_date_formatted,
        'official_rank': official_rank,
        'official_name': official_name,
        'official_title': official_title,
        'station_name': station_name,
        'dept_name': dept_name,
        'institute_name': institute_name,
    }
    return render(request, 'training/placement_results_sheet.html', context)
