import json
from decimal import Decimal
from datetime import datetime, date, timedelta
from functools import wraps
from urllib.parse import quote
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, Count, Avg, Sum, Max, Min, ProtectedError

from apps.core.permissions import (
    is_super_admin_user, super_admin_required,
    is_admin_user, admin_access_required, admin_required,
    is_registrar_user, registrar_required,
    is_supervisor_user, is_instructor_user, get_user_instructor
)
from training.models import (
    Institute, Instructor, SessionSubjectInstructor,
    Trainee, TraineeCategory, CourseCategory, Course, Subject,
    CourseSession, CourseEnrollment, TraineeSubjectGrade, DisciplineInfraction,
    CertificateSettings, MovementOrderSettings, SystemSettings, UserProfile, UserRole,
    has_trainee_passed_course,
    ActivityLog, ActivityAction, ActivityCategory, log_activity
)
from training.forms import (
    InstructorForm, TraineeForm, CourseForm, SubjectForm, CourseSessionForm,
    UserLoginForm, CourseCategoryForm, CertificateSettingsForm,
    MovementOrderSettingsForm, OFFICER_RANKS,
    SystemSettingsForm, UserCreateForm, UserEditForm, AdminLoginForm
)
from apps.reports.reports import (
    get_report_data, export_report_to_excel, get_default_date_range, get_sessions_subjects_summary
)
from apps.core.services import initialize_new_institute


@login_required
def admin_report_print_view(request):
    """
    التقرير الإحصائي والتحليلي العام لمؤشرات التدريب والنتائج - جاهز للطباعة الرسمية
    يدعم الفلترة اللحظية وفق النطاق الزمني والخيارات المحددة في قسم التقارير الشاملة
    """
    if not (is_admin_user(request.user) or is_supervisor_user(request.user) or is_registrar_user(request.user)):
        messages.error(request, 'عذراً، هذا التقرير مخصص للإدارة وهيئة القيادة والتسجيل فقط.')
        return redirect('training:home')

    cert_settings = CertificateSettings.get_settings(institute=request.institute)
    system_settings = SystemSettings.get_settings(institute=request.institute)

    params = request.GET

    # معالجة تقرير امتحانات تحديد المستوى المخصص للطباعة الرسمية
    if params.get('report_type') == 'placement_exams':
        report_data = get_report_data(params, institute=request.institute)
        return render(request, 'training/admin_report_print.html', {
            'is_placement_report': True,
            'report_data': report_data,
            'filters_summary': report_data.get('filters_summary', ''),
            'cert_settings': cert_settings,
            'system_settings': system_settings,
        })

    has_filters = any(k in params for k in [
        'start_date', 'end_date', 'all_dates', 'force', 'unit',
        'course_id', 'category_id', 'session_id', 'status',
        'session_status', 'trainee_category', 'instructor_id', 'q'
    ])

    def calc_pct(part, whole):
        if not whole or not part:
            return 0
        v = round((part / whole * 100), 1)
        return int(v) if v.is_integer() else v

    def format_avg(val):
        if val is None:
            return 0
        v = round(float(val), 1)
        return int(v) if v.is_integer() else v

    report_sub_header = ''
    report_category_name = ''
    report_course_name = ''
    report_batch_code = ''
    is_single_course = False

    if has_filters:
        use_all_dates = params.get('all_dates') == '1'
        start_date_str = str(params.get('start_date') or '').strip()
        end_date_str = str(params.get('end_date') or '').strip()

        if use_all_dates:
            start_date = None
            end_date = None
        else:
            def_start, def_end = get_default_date_range()
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else def_start
            except ValueError:
                start_date = def_start
            try:
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else def_end
            except ValueError:
                end_date = def_end

        session_status = str(params.get('session_status') or 'completed').strip()
        if session_status not in ['completed', 'active', 'all']:
            session_status = 'completed'

        category_id = str(params.get('category_id') or '').strip()
        course_id = str(params.get('course_id') or '').strip()
        session_id = str(params.get('session_id') or '').strip()
        force = str(params.get('force') or '').strip()
        unit = str(params.get('unit') or '').strip()
        trainee_category = str(params.get('trainee_category') or '').strip()
        status = str(params.get('status') or 'all').strip()
        instructor_id = str(params.get('instructor_id') or '').strip()
        q = str(params.get('q') or '').strip()

        enrollments_qs = CourseEnrollment.objects.select_related(
            'trainee', 'session', 'session__course', 'session__course__category'
        )
        if request.institute:
            enrollments_qs = enrollments_qs.filter(session__institute=request.institute)

        if session_status == 'completed':
            enrollments_qs = enrollments_qs.filter(session__status='completed')
        elif session_status == 'active':
            enrollments_qs = enrollments_qs.filter(session__status='active')
        elif session_status == 'all':
            enrollments_qs = enrollments_qs.filter(session__status__in=['completed', 'active'])

        if start_date and end_date:
            enrollments_qs = enrollments_qs.filter(
                Q(session__start_date__lte=end_date, session__end_date__gte=start_date) |
                Q(session__start_date__range=(start_date, end_date)) |
                Q(session__end_date__range=(start_date, end_date))
            )

        if category_id:
            enrollments_qs = enrollments_qs.filter(session__course__category_id=category_id)
        if course_id:
            enrollments_qs = enrollments_qs.filter(session__course_id=course_id)
        if session_id:
            enrollments_qs = enrollments_qs.filter(session_id=session_id)
        if force:
            enrollments_qs = enrollments_qs.filter(Q(current_force=force) | Q(trainee__force=force))
        if unit:
            enrollments_qs = enrollments_qs.filter(Q(current_unit__icontains=unit) | Q(trainee__unit__icontains=unit))
        if trainee_category:
            enrollments_qs = enrollments_qs.filter(trainee__category=trainee_category)
        if instructor_id:
            enrollments_qs = enrollments_qs.filter(
                Q(session__supervisor_id=instructor_id) |
                Q(session__subject_instructors__instructor_id=instructor_id)
            ).distinct()

        if status == 'passed':
            enrollments_qs = enrollments_qs.filter(is_dropped=False, is_graded=True, percentage__gte=50)
        elif status == 'failed':
            enrollments_qs = enrollments_qs.filter(is_dropped=False, is_graded=True, percentage__lt=50)
        elif status == 'dropped':
            enrollments_qs = enrollments_qs.filter(is_dropped=True)
        elif status == 'active':
            enrollments_qs = enrollments_qs.filter(is_dropped=False)

        if q:
            enrollments_qs = enrollments_qs.filter(
                Q(trainee__name__icontains=q) |
                Q(trainee__military_number__icontains=q) |
                Q(current_rank__icontains=q) |
                Q(current_unit__icontains=q) |
                Q(session__course__name__icontains=q) |
                Q(session__session_code__icontains=q)
            )

        # تجهيز نص ملخص الفلترة للطباعة
        filter_desc_items = []
        if use_all_dates:
            filter_desc_items.append("كامل السجلات")
        elif start_date and end_date:
            filter_desc_items.append(f"الفترة من: {start_date.strftime('%Y-%m-%d')} إلى: {end_date.strftime('%Y-%m-%d')}")
        if force:
            filter_desc_items.append(f"القوة: {force}")
        if unit:
            filter_desc_items.append(f"الوحدة: {unit}")
        if category_id:
            cat_obj = CourseCategory.objects.filter(pk=category_id).first()
            if cat_obj: filter_desc_items.append(f"التصنيف: {cat_obj.name}")
        if course_id:
            course_obj = Course.objects.filter(pk=course_id).first()
            if course_obj: filter_desc_items.append(f"الدورة: {course_obj.name}")
        if session_id:
            sess_obj = CourseSession.objects.filter(pk=session_id).first()
            if sess_obj: filter_desc_items.append(f"الدفعة: {sess_obj.session_code}")

        filters_summary = " • ".join(filter_desc_items) if filter_desc_items else "كافة السجلات"

        # استخراج وتجهيز تصنيف الدورة واسم الدورة والدفعة لوضعهم أسفل العنوان الرئيسي مباشرة
        cat_name = ''
        c_name = ''
        b_code = ''

        if session_id:
            s_item = CourseSession.objects.filter(pk=session_id).select_related('course', 'course__category').first()
            if s_item:
                b_code = s_item.session_code or f"{s_item.id}"
                if s_item.course:
                    c_name = s_item.course.name
                    if s_item.course.category:
                        cat_name = s_item.course.category.name

        if course_id and not c_name:
            c_item = Course.objects.filter(pk=course_id).select_related('category').first()
            if c_item:
                c_name = c_item.name
                if c_item.category and not cat_name:
                    cat_name = c_item.category.name

        if category_id and not cat_name:
            cat_item = CourseCategory.objects.filter(pk=category_id).first()
            if cat_item:
                cat_name = cat_item.name

        # إذا لم يتم التحديد الصريح، فحص إذا كانت السجلات المفلترة تخص دورة أو دفعة أو تصنيف موحد
        if not b_code:
            unique_sessions = list(enrollments_qs.values_list('session__session_code', flat=True).distinct()[:2])
            if len(unique_sessions) == 1 and unique_sessions[0]:
                b_code = unique_sessions[0]
        if not c_name:
            unique_courses = list(enrollments_qs.values_list('session__course__name', flat=True).distinct()[:2])
            if len(unique_courses) == 1 and unique_courses[0]:
                c_name = unique_courses[0]
        if not cat_name:
            unique_cats = list(enrollments_qs.values_list('session__course__category__name', flat=True).distinct()[:2])
            if len(unique_cats) == 1 and unique_cats[0]:
                cat_name = unique_cats[0]

        # تنظيف رقم الدفعة
        b_code_display = ''
        if b_code:
            b_clean = b_code.strip()
            if b_clean.startswith('الدفعة'):
                b_clean = b_clean[len('الدفعة'):].strip()
            b_code_display = f"الدفعة: {b_clean}"

        header_parts = []
        if cat_name:
            header_parts.append(f"التصنيف: {cat_name}")
        if c_name:
            header_parts.append(f"الدورة: {c_name}")
        if b_code_display:
            header_parts.append(b_code_display)

        report_sub_header = " • ".join(header_parts)
        report_category_name = cat_name
        report_course_name = c_name
        report_batch_code = b_code

        # 1. إحصائيات KPIs المفلترة
        trainees_total = enrollments_qs.values('trainee_id').distinct().count()
        trainees_officers = enrollments_qs.filter(trainee__category=TraineeCategory.OFFICER).values('trainee_id').distinct().count()
        trainees_ncos = enrollments_qs.filter(trainee__category=TraineeCategory.NCO).values('trainee_id').distinct().count()
        trainees_civilians = enrollments_qs.filter(trainee__category=TraineeCategory.CIVILIAN).values('trainee_id').distinct().count()

        courses_total = enrollments_qs.values('session__course_id').distinct().count()
        sessions_count = enrollments_qs.values('session_id').distinct().count()

        # تحديد ما إذا كان التقرير يخص دورة تدريبية واحدة فقط لعرض كافة تفاصيلها
        is_single_course = bool(session_id) or (sessions_count == 1) or (courses_total == 1 and sessions_count <= 1)

        # المعتمد نجاحهم: الذين تم رصد درجاتهم واجتازوا بنجاح (percentage >= 50 وغير مقطوعين)
        enrollments_graded = enrollments_qs.filter(is_graded=True, is_dropped=False, percentage__gte=50).count()

        # متوسط التحصيل العام
        avg_score_res = enrollments_qs.filter(is_graded=True, is_dropped=False).aggregate(avg_score=Avg('percentage'))
        avg_score = format_avg(avg_score_res['avg_score'])

        # 2. التوزيع التكراري للتقديرات
        graded_qs = enrollments_qs.filter(is_graded=True, is_dropped=False)
        total_eval = graded_qs.count()

        grade_a = graded_qs.filter(percentage__gte=85).count()
        grade_b = graded_qs.filter(percentage__gte=75, percentage__lt=85).count()
        grade_c = graded_qs.filter(percentage__gte=65, percentage__lt=75).count()
        grade_d = graded_qs.filter(percentage__gte=50, percentage__lt=65).count()
        grade_f = graded_qs.filter(percentage__lt=50).count() + enrollments_qs.filter(is_dropped=True).count()

        grade_a_pct = calc_pct(grade_a, total_eval)
        grade_b_pct = calc_pct(grade_b, total_eval)
        grade_c_pct = calc_pct(grade_c, total_eval)
        grade_d_pct = calc_pct(grade_d, total_eval)
        grade_f_pct = calc_pct(grade_f, total_eval)

        # 3. توزيع القوات
        from collections import Counter
        force_counts = Counter()
        for en in enrollments_qs:
            f_name = (en.current_force or (en.trainee.force if en.trainee else '') or '').strip()
            force_counts[f_name if f_name else 'غير محدد'] += 1

        total_force_en = sum(force_counts.values()) or 1
        forces_stats = [
            {'force': f, 'count': c, 'pct': round((c / total_force_en * 100), 1)}
            for f, c in force_counts.most_common()
        ]

    else:
        filters_summary = "كامل السجلات الإحصائية للنظام"
        if request.institute:
            inst_sessions = CourseSession.objects.filter(institute=request.institute)
            inst_enrollments = CourseEnrollment.objects.filter(session__institute=request.institute)
            trainees_total = inst_enrollments.values('trainee_id').distinct().count()
            trainees_officers = inst_enrollments.filter(trainee__category=TraineeCategory.OFFICER).values('trainee_id').distinct().count()
            trainees_ncos = inst_enrollments.filter(trainee__category=TraineeCategory.NCO).values('trainee_id').distinct().count()
            trainees_civilians = inst_enrollments.filter(trainee__category=TraineeCategory.CIVILIAN).values('trainee_id').distinct().count()

            courses_total = Course.objects.filter(institute=request.institute).count()
            sessions_count = inst_sessions.count()

            enrollments_graded = inst_enrollments.filter(is_graded=True, is_dropped=False, percentage__gte=50).count()
            avg_score_res = inst_enrollments.filter(is_graded=True, is_dropped=False).aggregate(avg_score=Avg('percentage'))
            avg_score = format_avg(avg_score_res['avg_score'])

            graded_qs = inst_enrollments.filter(is_graded=True, is_dropped=False)
            total_eval = graded_qs.count()

            grade_a = graded_qs.filter(percentage__gte=85).count()
            grade_b = graded_qs.filter(percentage__gte=75, percentage__lt=85).count()
            grade_c = graded_qs.filter(percentage__gte=65, percentage__lt=75).count()
            grade_d = graded_qs.filter(percentage__gte=50, percentage__lt=65).count()
            grade_f = graded_qs.filter(percentage__lt=50).count() + inst_enrollments.filter(is_dropped=True).count()

            grade_a_pct = calc_pct(grade_a, total_eval)
            grade_b_pct = calc_pct(grade_b, total_eval)
            grade_c_pct = calc_pct(grade_c, total_eval)
            grade_d_pct = calc_pct(grade_d, total_eval)
            grade_f_pct = calc_pct(grade_f, total_eval)

            raw_forces = inst_enrollments.exclude(current_force__isnull=True).exclude(current_force='').values('current_force').annotate(count=Count('id')).order_by('-count')
            total_trainees = trainees_total or 1
            forces_stats = [
                {'force': f['current_force'], 'count': f['count'], 'pct': calc_pct(f['count'], total_trainees)}
                for f in raw_forces
            ]
        else:
            trainees_total = Trainee.objects.count()
            trainees_officers = Trainee.objects.filter(category=TraineeCategory.OFFICER).count()
            trainees_ncos = Trainee.objects.filter(category=TraineeCategory.NCO).count()
            trainees_civilians = Trainee.objects.filter(category=TraineeCategory.CIVILIAN).count()

            courses_total = Course.objects.count()
            sessions_count = CourseSession.objects.count()

            enrollments_graded = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False, percentage__gte=50).count()
            avg_score_res = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False).aggregate(avg_score=Avg('percentage'))
            avg_score = format_avg(avg_score_res['avg_score'])

            graded_qs = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False)
            total_eval = graded_qs.count()

            grade_a = graded_qs.filter(percentage__gte=85).count()
            grade_b = graded_qs.filter(percentage__gte=75, percentage__lt=85).count()
            grade_c = graded_qs.filter(percentage__gte=65, percentage__lt=75).count()
            grade_d = graded_qs.filter(percentage__gte=50, percentage__lt=65).count()
            grade_f = graded_qs.filter(percentage__lt=50).count() + CourseEnrollment.objects.filter(is_dropped=True).count()

            grade_a_pct = calc_pct(grade_a, total_eval)
            grade_b_pct = calc_pct(grade_b, total_eval)
            grade_c_pct = calc_pct(grade_c, total_eval)
            grade_d_pct = calc_pct(grade_d, total_eval)
            grade_f_pct = calc_pct(grade_f, total_eval)

            raw_forces = Trainee.objects.values('force').annotate(count=Count('military_number')).order_by('-count')
            total_trainees = trainees_total or 1
            forces_stats = [
                {'force': f['force'] if f['force'] else 'غير محدد', 'count': f['count'], 'pct': round((f['count'] / total_trainees * 100), 1)}
                for f in raw_forces
            ]

    # استخراج بيان المواد وهيئة التدريس ومعدلات النجاح للطباعة الرسمية
    subjects_summary = []
    if has_filters:
        if session_id:
            sessions_for_summary = CourseSession.objects.filter(id=session_id).select_related('course', 'course__category', 'supervisor')
        elif course_id:
            sessions_for_summary = CourseSession.objects.filter(course_id=course_id).select_related('course', 'course__category', 'supervisor')
        else:
            sessions_for_summary = CourseSession.objects.filter(
                id__in=enrollments_qs.values_list('session_id', flat=True).distinct()
            ).select_related('course', 'course__category', 'supervisor')
        if request.institute:
            sessions_for_summary = sessions_for_summary.filter(institute=request.institute)

        if sessions_for_summary.exists():
            subjects_summary = get_sessions_subjects_summary(sessions_for_summary[:5])
    else:
        recent_sessions = CourseSession.objects.all()
        if request.institute:
            recent_sessions = recent_sessions.filter(institute=request.institute)
        recent_sessions = recent_sessions.order_by('-start_date')[:3]
        subjects_summary = get_sessions_subjects_summary(recent_sessions)

    return render(request, 'training/admin_report_print.html', {
        'trainees_total': trainees_total,
        'trainees_officers': trainees_officers,
        'trainees_ncos': trainees_ncos,
        'trainees_civilians': trainees_civilians,
        'courses_total': courses_total,
        'sessions_count': sessions_count,
        'enrollments_graded': enrollments_graded,
        'avg_score': avg_score,
        'grade_a': grade_a,
        'grade_b': grade_b,
        'grade_c': grade_c,
        'grade_d': grade_d,
        'grade_f': grade_f,
        'grade_a_pct': grade_a_pct,
        'grade_b_pct': grade_b_pct,
        'grade_c_pct': grade_c_pct,
        'grade_d_pct': grade_d_pct,
        'grade_f_pct': grade_f_pct,
        'forces_stats': forces_stats,
        'filters_summary': filters_summary,
        'report_sub_header': report_sub_header,
        'report_category_name': report_category_name,
        'report_course_name': report_course_name,
        'report_batch_code': report_batch_code,
        'is_single_course': is_single_course,
        'subjects_summary': subjects_summary,
        'cert_settings': cert_settings,
        'system_settings': system_settings,
    })


@login_required
def reports_hub_view(request):
    """
    قسم التقارير الشاملة:
    عرض وتخصيص واستخراج التقارير مع فلترة متقدمة ونطاق زمني (افتراضياً آخر 3 شهور)
    """
    if not (is_admin_user(request.user) or is_supervisor_user(request.user) or is_registrar_user(request.user)):
        messages.error(request, 'عذراً، هذا القسم مخصص للإدارة وهيئة القيادة والتسجيل فقط.')
        return redirect('training:home')

    # خيارات الفلترة المتاحة
    categories = CourseCategory.objects.all().order_by('name')
    courses = Course.objects.select_related('category').all().order_by('name')
    sessions = CourseSession.objects.select_related('course', 'course__category').all().order_by('-start_date')
    instructors = Instructor.objects.all().order_by('name')

    if request.institute:
        categories = categories.filter(institute=request.institute)
        courses = courses.filter(institute=request.institute)
        sessions = sessions.filter(institute=request.institute)
        instructors = instructors.filter(institute=request.institute)

    # القوى العسكرية القياسية ووحداتها المعيارية بالنظام
    DEFAULT_FORCE_UNITS = {
        'القوات البرية': [
            'سلاح المشاة', 'سلاح المدرعات', 'سلاح المدفعية', 'سلاح الإشارة',
            'سلاح المهندسين', 'سلاح الصيانة', 'سلاح النقل', 'الإدارة المالية',
            'إدارة نظم المعلومات', 'إدارة التدريب', 'هيئة الإمداد والتموين',
            'الشرطة العسكرية', 'شعبة الاستخبارات', 'لواء القوات الخاصة',
            'إدارة العمليات', 'قيادة القوات البرية'
        ],
        'القوات البحرية': [
            'قاعدة بورتسودان البحرية', 'قاعدة فلامنجو البحرية', 'أسطول الزوارق والسفن',
            'لواء المشاة البحرية', 'جناح الضفادع البشرية', 'ورش الصيانة البحرية',
            'إدارة نظم المعلومات البحرية', 'الإدارة المالية البحرية',
            'جناح الاتصالات الساحلية', 'مركز تدريب القوات البحرية', 'قيادة القوات البحرية'
        ],
        'القوات الجوية': [
            'قاعدة وادي سيدنا الجوية', 'قاعدة الشهيد مختار الجوية', 'قاعدة الأبيض الجوية',
            'قاعدة مروي الجوية', 'جناح المقاتلات', 'جناح النقل الجوي', 'جناح المروحيات',
            'مجمع صيانة الطيران', 'الملاحة والمراقبة الجوية', 'إدارة نظم المعلومات الجوية',
            'الإدارة المالية الجوية', 'كلية القوات الجوية', 'قيادة القوات الجوية'
        ],
        'قوات الدفاع الجوي': [
            'لواء الصواريخ م/ط', 'كتائب المدفعية م/ط', 'مراكز الرادارات والإنذار المبكر',
            'قيادة السيطرة والتوجيه', 'الحرب الإلكترونية', 'سلاح الإشارة للدفاع الجوي',
            'ورش الصيانة الفنية', 'مركز تدريب الدفاع الجوي', 'إدارة نظم المعلومات',
            'الإدارة المالية', 'قيادة قوات الدفاع الجوي'
        ]
    }

    # بناء خريطة الربط بين القوى والوحدات مع إدراج كافة القوى دائماً
    force_units_dict = {f: set(u_list) for f, u_list in DEFAULT_FORCE_UNITS.items()}
    all_units_set = set()
    for u_list in DEFAULT_FORCE_UNITS.values():
        all_units_set.update(u_list)

    # دمج القوى والوحدات المسجلة فعلياً في قاعدة البيانات للدارسين والتسجيلات والمعلمين
    trainee_pairs = Trainee.objects.exclude(force__isnull=True).exclude(force='').exclude(unit__isnull=True).exclude(unit='').values_list('force', 'unit')
    enrollment_pairs = CourseEnrollment.objects.exclude(current_force__isnull=True).exclude(current_force='').exclude(current_unit__isnull=True).exclude(current_unit='').values_list('current_force', 'current_unit')
    instructor_pairs = Instructor.objects.exclude(force__isnull=True).exclude(force='').exclude(unit__isnull=True).exclude(unit='').values_list('force', 'unit')

    for f_val, u_val in set(trainee_pairs).union(enrollment_pairs).union(instructor_pairs):
        f_clean = f_val.strip() if f_val else ''
        u_clean = u_val.strip() if u_val else ''
        if f_clean and u_clean:
            if f_clean not in force_units_dict:
                force_units_dict[f_clean] = set()
            force_units_dict[f_clean].add(u_clean)
            all_units_set.add(u_clean)

    # وحدات إضافية مسجلة بالنظام
    extra_units = set(Trainee.objects.exclude(unit__isnull=True).exclude(unit='').values_list('unit', flat=True)).union(
        CourseEnrollment.objects.exclude(current_unit__isnull=True).exclude(current_unit='').values_list('current_unit', flat=True)
    )
    for eu in extra_units:
        if eu and eu.strip():
            all_units_set.add(eu.strip())

    force_units_map = {f: sorted(list(u_set)) for f, u_set in sorted(force_units_dict.items())}
    forces = sorted(list(force_units_map.keys()))
    units = sorted(list(all_units_set))

    trainee_categories = TraineeCategory.choices

    # تجهيز هياكل البيانات الجاهزة للربط والفلترة اللحظية في المتصفح
    courses_data = [
        {'id': c.id, 'name': c.name, 'category_id': c.category_id}
        for c in courses
    ]
    sessions_data = []
    for s in sessions:
        code_str = str(s.session_code or '').strip()
        batch_text = code_str if code_str.startswith('الدفعة') else f"الدفعة {code_str}"
        target_display = s.get_target_category_display() or ''
        status_label = 'معتمدة ومحفوظة' if s.status == 'completed' else 'منعقدة'
        full_name = f"{s.course.name} ({batch_text} - {target_display}) - {status_label}"
        sessions_data.append({
            'id': s.id,
            'session_code': s.session_code,
            'name': full_name,
            'course_id': s.course_id,
            'category_id': s.course.category_id if s.course else None,
            'target_category': s.target_category or '',
            'status': s.status
        })

    # خيارات الفلترة الخاصة بامتحانات تحديد المستوى
    from apps.placement_exams.models import PlacementExamOrder
    placement_qs = PlacementExamOrder.objects.all()
    if request.institute:
        placement_qs = placement_qs.filter(institute=request.institute)

    placement_purposes = sorted([p for p in placement_qs.exclude(purpose='').values_list('purpose', flat=True).distinct() if p])
    placement_sources = sorted([s for s in placement_qs.exclude(source_entity='').values_list('source_entity', flat=True).distinct() if s])
    placement_years = sorted(list(placement_qs.values_list('year', flat=True).distinct()), reverse=True)

    # جلب بيانات التقرير المفلترة مع عزل بيانات المعهد
    report_data = get_report_data(request.GET, institute=request.institute)
    system_settings = SystemSettings.get_settings(institute=request.institute)

    context = {
        'report_data': report_data,
        'categories': categories,
        'courses': courses,
        'sessions': sessions,
        'instructors': instructors,
        'forces': forces,
        'units': units,
        'trainee_categories': trainee_categories,
        'placement_purposes': placement_purposes,
        'placement_sources': placement_sources,
        'placement_years': placement_years,
        'system_settings': system_settings,
        'current_filters': request.GET,
        'force_units_map_json': json.dumps(force_units_map, ensure_ascii=False),
        'all_units_json': json.dumps(units, ensure_ascii=False),
        'courses_json': json.dumps(courses_data, ensure_ascii=False),
        'sessions_json': json.dumps(sessions_data, ensure_ascii=False),
    }
    return render(request, 'training/reports_hub.html', context)


@login_required
def reports_export_excel_view(request):
    """
    تصدير التقرير المفلتر مباشرة كملف إكسل منسق بالكامل (Excel .xlsx)
    """
    if not (is_admin_user(request.user) or is_supervisor_user(request.user) or is_registrar_user(request.user)):
        messages.error(request, 'عذراً، غير مصرح لك بتصدير التقارير.')
        return redirect('training:home')

    try:
        report_data = get_report_data(request.GET, institute=request.institute)
        excel_bytes = export_report_to_excel(report_data)
    except ImportError:
        messages.error(request, 'حزمة openpyxl غير مثبتة على بيئة الخادم الحالية. يرجى تثبيتها عبر أمر: pip install openpyxl')
        return redirect('training:reports_hub')

    safe_title = report_data.get('report_title', 'تقرير')
    now_str = timezone.now().strftime('%Y%m%d_%H%M')
    filename = f"{safe_title}_{now_str}.xlsx"
    encoded_filename = quote(filename)

    response = HttpResponse(
        excel_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
    return response


# ==========================================================
# إدارة مخالفات ودرجات الضبط والربط للدارسين
# ==========================================================



