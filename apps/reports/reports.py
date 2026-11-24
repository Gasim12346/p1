"""
خدمات ووظائف استخراج التقارير وتصديرها إلى إكسل
تتيح تخصيص واستخراج تقارير شاملة عن الدارسين، الدورات، الوحدات، القوى العسكرية، أوامر التحرك، وهيئة التعليم
مع إمكانية الفلترة بنطاق تواريخ مخصص (افتراضياً آخر 3 شهور) وحفظ التقرير بصيغة Excel مع تنسيقات كاملة.
"""
import io
from datetime import datetime, timedelta
from urllib.parse import quote
from django.utils import timezone
from django.db.models import Q, Count, Avg

try:
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False

from training.models import (
    CourseEnrollment,
    CourseSession,
    Course,
    CourseCategory,
    Trainee,
    TraineeCategory,
    Instructor,
    SessionSubjectInstructor,
    Subject,
    TraineeSubjectGrade,
)


def get_default_date_range():
    """الحصول على نطاق التواريخ الافتراضي (آخر 3 شهور حتى اليوم)"""
    end_date = timezone.now().date()
    start_date = end_date - timedelta(days=90)
    return start_date, end_date


def _format_report_result(res):
    """تجهيز مصفوفة الخلايا للعرض التلقائي والمباشر داخل القوالب دون الحاجة لفلاتر مخصصة"""
    records = res.get('records', [])
    columns = res.get('columns', [])
    for r_idx, rec in enumerate(records, start=1):
        cells = []
        for col in columns:
            k = col['key']
            val = r_idx if k == 'index' else rec.get(k, '')
            cells.append({
                'key': k,
                'title': col.get('title', ''),
                'value': val,
                'align': col.get('align', 'center'),
            })
        rec['cells'] = cells
    return res


def get_sessions_subjects_summary(sessions_qs):
    """
    حساب تفاصيل المواد الدراسية وهيئة التدريس ونسب ومتوسطات النجاح لكل دورة منعقدة
    يوفر بياناً إحصائياً دقيقاً بعدد المواد المنفذة في كل دورة والمعلم المكلف ومتوسط التحصيل ونسبة النجاح
    """
    summary = []
    for session in sessions_qs:
        subjects = session.get_subjects()
        if not subjects:
            continue

        active_enrollments = list(session.enrollments.filter(is_dropped=False))
        total_enrolled = len(active_enrollments)

        # خريطة المعلمين المسندين لمواد الدورة
        subject_instructors_map = {
            si.subject_id: si.instructor 
            for si in session.subject_instructors.select_related('instructor').all()
        }

        subjects_data = []
        for s_idx, sub in enumerate(subjects, start=1):
            instructor = subject_instructors_map.get(sub.id)
            if instructor:
                inst_name = f"{instructor.rank} / {instructor.name}" if instructor.rank else instructor.name
            elif session.supervisor:
                inst_name = f"{session.supervisor.name} (مشرف الدورة)"
            else:
                inst_name = 'لم يحدد بعد'

            # درجات المادة للدارسين النشطين
            grades = list(TraineeSubjectGrade.objects.filter(
                enrollment__in=active_enrollments,
                subject=sub,
                score__isnull=False
            ))
            total_graded = len(grades)
            max_grade_val = float(sub.max_grade or 100.0)
            pass_threshold = max_grade_val * 0.5

            if total_graded > 0:
                scores = [float(g.score) for g in grades]
                avg_score = round(sum(scores) / total_graded, 2)
                passed_count = sum(1 for s in scores if s >= pass_threshold)
                failed_count = total_graded - passed_count
                pass_rate = round((passed_count / total_graded) * 100, 1)
                avg_percentage = round((avg_score / max_grade_val) * 100, 1) if max_grade_val > 0 else 0.0
                highest_score = round(max(scores), 2)
                lowest_score = round(min(scores), 2)
            else:
                avg_score = 0.0
                passed_count = 0
                failed_count = 0
                pass_rate = 0.0
                avg_percentage = 0.0
                highest_score = 0.0
                lowest_score = 0.0

            if pass_rate >= 85:
                assessment = 'ممتاز (أ)'
                assessment_class = 'success'
            elif pass_rate >= 75:
                assessment = 'جيد جداً (ب)'
                assessment_class = 'primary'
            elif pass_rate >= 65:
                assessment = 'جيد (ج)'
                assessment_class = 'info'
            elif pass_rate >= 50:
                assessment = 'مقبول (د)'
                assessment_class = 'warning'
            else:
                assessment = 'دون المستوى'
                assessment_class = 'danger'

            subjects_data.append({
                'index': s_idx,
                'subject_id': sub.id,
                'subject_code': sub.code or f"SUB-{sub.id}",
                'subject_name': sub.name,
                'credit_hours': sub.credit_hours,
                'max_grade': max_grade_val,
                'instructor_name': inst_name,
                'total_enrolled': total_enrolled,
                'total_graded': total_graded,
                'passed_count': passed_count,
                'failed_count': failed_count,
                'avg_score': avg_score,
                'avg_percentage': avg_percentage,
                'pass_rate': pass_rate,
                'highest_score': highest_score,
                'lowest_score': lowest_score,
                'assessment': assessment,
                'assessment_class': assessment_class,
            })

        course_title = session.course.name if session.course else ''
        batch_title = session.session_code or f"الدفعة {session.id}"
        cat_title = session.course.category.name if session.course and session.course.category else 'عام'

        summary.append({
            'session_id': session.id,
            'session_code': batch_title,
            'course_name': course_title,
            'category_name': cat_title,
            'start_date': session.start_date.strftime('%Y-%m-%d') if session.start_date else '',
            'end_date': session.end_date.strftime('%Y-%m-%d') if session.end_date else '',
            'status_label': 'معتمدة ومحفوظة' if session.status == 'completed' else 'منعقدة حالياً',
            'status_class': 'success' if session.status == 'completed' else 'primary',
            'subjects_count': len(subjects),
            'total_enrolled': total_enrolled,
            'statement': f"لقد تم تدريس {len(subjects)} مواد في دورة {course_title} ({batch_title})",
            'subjects': subjects_data,
        })
    return summary


def get_report_data(params, institute=None):
    """
    تجميع وفلترة بيانات التقرير بحسب المعايير المحددة في الطلب وعزل بيانات المعهد إن وجد
    """
    report_type = str(params.get('report_type') or 'trainees').strip()
    if report_type not in ['trainees', 'sessions', 'units_forces', 'dropped_trainees', 'instructors', 'course_subjects', 'placement_exams']:
        report_type = 'trainees'

    # معالجة نطاق التواريخ
    use_all_dates = params.get('all_dates') in ['1', 'true', 'True']
    start_date_str = str(params.get('start_date') or '').strip()
    end_date_str = str(params.get('end_date') or '').strip()

    def_start, def_end = get_default_date_range()

    if use_all_dates:
        start_date = None
        end_date = None
        start_date_val = ''
        end_date_val = ''
    else:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date() if start_date_str else def_start
        except ValueError:
            start_date = def_start

        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date() if end_date_str else def_end
        except ValueError:
            end_date = def_end

        start_date_val = start_date.strftime('%Y-%m-%d')
        end_date_val = end_date.strftime('%Y-%m-%d')

    category_id = str(params.get('category_id') or '').strip()
    course_id = str(params.get('course_id') or '').strip()
    session_id = str(params.get('session_id') or '').strip()
    force = str(params.get('force') or '').strip()
    unit = str(params.get('unit') or '').strip()
    trainee_category = str(params.get('trainee_category') or '').strip()
    status = str(params.get('status') or 'all').strip()
    instructor_id = str(params.get('instructor_id') or '').strip()
    q = str(params.get('q') or '').strip()
    session_status = str(params.get('session_status') or 'completed').strip()
    if session_status not in ['completed', 'active', 'all']:
        session_status = 'completed'

    filter_desc_items = []

    session_status_map = {
        'completed': 'الدورات المعتمدة والمحفوظة',
        'active': 'الدورات المنعقدة (الجارية حالياً)',
        'all': 'كافة الدورات (المعتمدة والمنعقدة)',
    }
    filter_desc_items.append(f"حالة الدورة: {session_status_map.get(session_status)}")

    if use_all_dates:
        filter_desc_items.append("الفترة: كامل السجلات (كل الأوقات)")
    else:
        filter_desc_items.append(f"الفترة من: {start_date_val} إلى: {end_date_val}")

    if category_id:
        cat_obj = CourseCategory.objects.filter(pk=category_id).first()
        if cat_obj:
            filter_desc_items.append(f"التصنيف: {cat_obj.name}")

    if course_id:
        course_obj = Course.objects.filter(pk=course_id).first()
        if course_obj:
            filter_desc_items.append(f"الدورة: {course_obj.name}")

    if session_id:
        sess_obj = CourseSession.objects.filter(pk=session_id).first()
        if sess_obj:
            filter_desc_items.append(f"الدفعة: {sess_obj.session_code or f'دورة {sess_obj.id}'}")

    if force:
        filter_desc_items.append(f"القوة: {force}")

    if unit:
        filter_desc_items.append(f"الوحدة: {unit}")

    if trainee_category:
        cat_map = {'officer': 'ضباط', 'nco': 'ضباط صف', 'civilian': 'مدنيين'}
        filter_desc_items.append(f"تصنيف الدارس: {cat_map.get(trainee_category, trainee_category)}")

    if status and status != 'all':
        status_map = {
            'passed': 'الناجحون فقط',
            'failed': 'الراسبون فقط',
            'dropped': 'المقطوعون فقط',
            'active': 'المستمرون بالدورة فقط',
        }
        filter_desc_items.append(f"الحالة: {status_map.get(status, status)}")

    if instructor_id:
        inst_obj = Instructor.objects.filter(pk=instructor_id).first()
        if inst_obj:
            filter_desc_items.append(f"المعلم: {inst_obj.name}")

    if q:
        filter_desc_items.append(f"بحث نصي: \"{q}\"")

    filters_summary = " | ".join(filter_desc_items) if filter_desc_items else "كافة السجلات"

    # استعلام الدورات المنعقدة وفق معايير الفلترة لتحليل المواد وهيئة التدريس
    sessions_filter_qs = CourseSession.objects.select_related(
        'course', 'course__category', 'supervisor'
    ).prefetch_related('enrollments', 'subject_instructors__instructor')

    if institute:
        sessions_filter_qs = sessions_filter_qs.filter(institute=institute)

    if session_status == 'completed':
        sessions_filter_qs = sessions_filter_qs.filter(status='completed')
    elif session_status == 'active':
        sessions_filter_qs = sessions_filter_qs.filter(status='active')
    elif session_status == 'all':
        sessions_filter_qs = sessions_filter_qs.filter(status__in=['completed', 'active'])

    if start_date and end_date:
        sessions_filter_qs = sessions_filter_qs.filter(
            Q(start_date__lte=end_date, end_date__gte=start_date) |
            Q(start_date__range=(start_date, end_date))
        )

    if category_id:
        sessions_filter_qs = sessions_filter_qs.filter(course__category_id=category_id)
    if course_id:
        sessions_filter_qs = sessions_filter_qs.filter(course_id=course_id)
    if trainee_category:
        sessions_filter_qs = sessions_filter_qs.filter(
            Q(target_category=trainee_category) | Q(target_category='joint') | Q(enrollments__trainee__category=trainee_category)
        ).distinct()
    if session_id:
        filtered_by_session = sessions_filter_qs.filter(id=session_id)
        if filtered_by_session.exists():
            sessions_filter_qs = filtered_by_session
        else:
            fallback_session = CourseSession.objects.filter(id=session_id).select_related('course', 'course__category', 'supervisor').prefetch_related('enrollments', 'subject_instructors__instructor')
            if institute:
                fallback_session = fallback_session.filter(institute=institute)
            if fallback_session.exists():
                sessions_filter_qs = fallback_session
    if instructor_id:
        sessions_filter_qs = sessions_filter_qs.filter(
            Q(supervisor_id=instructor_id) |
            Q(subject_instructors__instructor_id=instructor_id)
        ).distinct()

    if q:
        sessions_filter_qs = sessions_filter_qs.filter(
            Q(course__name__icontains=q) |
            Q(session_code__icontains=q) |
            Q(course__category__name__icontains=q) |
            Q(supervisor__name__icontains=q)
        )

    sessions_filter_qs = sessions_filter_qs.order_by('-start_date', 'course__name')

    # احتساب بيان المواد وهيئة التدريس للدورات المشمولة
    target_sessions = []
    if session_id or course_id or report_type in ['sessions', 'course_subjects'] or sessions_filter_qs.count() <= 30:
        target_sessions = list(sessions_filter_qs[:50])
    sessions_subjects_summary = get_sessions_subjects_summary(target_sessions) if target_sessions else []

    # ========================================================
    # 1. تقرير الدارسين والنتائج التفصيلي (trainees)
    # ========================================================
    if report_type == 'trainees':
        qs = CourseEnrollment.objects.select_related(
            'trainee', 'session', 'session__course', 'session__course__category'
        )
        if institute:
            qs = qs.filter(session__institute=institute)

        # فلترة حالة الدورة التدريبية (معتمدة ومحفوظة، أو منعقدة حالياً، أو الكل)
        if session_status == 'completed':
            qs = qs.filter(session__status='completed')
        elif session_status == 'active':
            qs = qs.filter(session__status='active')
        elif session_status == 'all':
            qs = qs.filter(session__status__in=['completed', 'active'])

        # فلترة التاريخ (تاريخ انعقاد الدورة)
        if start_date and end_date:
            qs = qs.filter(
                Q(session__start_date__lte=end_date, session__end_date__gte=start_date) |
                Q(session__start_date__range=(start_date, end_date)) |
                Q(session__end_date__range=(start_date, end_date))
            )

        if category_id:
            qs = qs.filter(session__course__category_id=category_id)
        if course_id:
            qs = qs.filter(session__course_id=course_id)
        if session_id:
            qs = qs.filter(session_id=session_id)
        if force:
            qs = qs.filter(Q(current_force=force) | Q(trainee__force=force))
        if unit:
            qs = qs.filter(Q(current_unit__icontains=unit) | Q(trainee__unit__icontains=unit))
        if trainee_category:
            qs = qs.filter(trainee__category=trainee_category)
        if instructor_id:
            qs = qs.filter(
                Q(session__supervisor_id=instructor_id) |
                Q(session__subject_instructors__instructor_id=instructor_id)
            ).distinct()

        if status == 'passed':
            qs = qs.filter(is_dropped=False, is_graded=True, percentage__gte=50)
        elif status == 'failed':
            qs = qs.filter(is_dropped=False, is_graded=True, percentage__lt=50)
        elif status == 'dropped':
            qs = qs.filter(is_dropped=True)
        elif status == 'active':
            qs = qs.filter(is_dropped=False)

        if q:
            qs = qs.filter(
                Q(trainee__name__icontains=q) |
                Q(trainee__military_number__icontains=q) |
                Q(current_rank__icontains=q) |
                Q(current_unit__icontains=q) |
                Q(session__course__name__icontains=q) |
                Q(session__session_code__icontains=q)
            )

        qs = qs.order_by('-session__start_date', 'session__course__name', 'trainee__name')

        records = []
        stats = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'dropped': 0,
            'officers': 0,
            'nco': 0,
            'civilians': 0,
            'avg_percentage': 0.0,
        }

        total_percentages = []
        for en in qs:
            stats['total'] += 1
            if en.trainee.category == TraineeCategory.OFFICER:
                stats['officers'] += 1
            elif en.trainee.category == TraineeCategory.NCO:
                stats['nco'] += 1
            else:
                stats['civilians'] += 1

            if en.is_dropped:
                stats['dropped'] += 1
                result_status = 'مقطوع عن الدورة'
                status_class = 'danger'
            elif en.is_graded:
                if en.percentage and en.percentage >= 50:
                    stats['passed'] += 1
                    result_status = 'ناجح'
                    status_class = 'success'
                else:
                    stats['failed'] += 1
                    result_status = 'راسب'
                    status_class = 'danger'
            else:
                result_status = 'قيد الدراسة'
                status_class = 'warning'

            if en.percentage is not None and not en.is_dropped and en.is_graded:
                total_percentages.append(float(en.percentage))

            records.append({
                'id': en.id,
                'military_number': en.trainee.military_number,
                'name': en.trainee.name,
                'rank': en.current_rank or '---',
                'category_label': en.trainee.get_category_display(),
                'force': en.current_force or en.trainee.force or '---',
                'unit': en.current_unit or en.trainee.unit or '---',
                'course_name': en.session.course.name,
                'session_code': en.session.session_code or f"دورة {en.session.id}",
                'session_status_label': 'معتمدة ومحفوظة' if en.session.status == 'completed' else 'منعقدة حالياً',
                'session_status_class': 'success' if en.session.status == 'completed' else 'primary',
                'dates': f"{en.session.start_date.strftime('%Y-%m-%d')} إلى {en.session.end_date.strftime('%Y-%m-%d')}",
                'total_score': f"{en.total_score:.2f}" if en.total_score is not None else '---',
                'percentage': f"{en.percentage:.2f}%" if en.percentage is not None else '---',
                'percentage_num': float(en.percentage) if en.percentage is not None else None,
                'grade_label': en.grade_label or '---',
                'result_status': result_status,
                'status_class': status_class,
                'is_dropped': en.is_dropped,
                'drop_reason': en.drop_reason or '---',
            })

        stats['avg_percentage'] = round(sum(total_percentages) / len(total_percentages), 2) if total_percentages else 0.0

        # فحص تخصيص الدورة والدفعة والقوة وحالة الدورة لوضعهم في العنوان وحذفهم من التفاصيل
        selected_course_name = ''
        selected_batch_code = ''
        selected_session_status = ''
        selected_force = force.strip() if force else ''

        if session_id:
            sess_obj = CourseSession.objects.filter(pk=session_id).first()
            if sess_obj:
                selected_course_name = sess_obj.course.name if sess_obj.course else ''
                selected_batch_code = sess_obj.session_code or f"{sess_obj.id}"
                selected_session_status = 'معتمدة ومحفوظة' if sess_obj.status == 'completed' else 'منعقدة حالياً'
        elif course_id:
            c_obj = Course.objects.filter(pk=course_id).first()
            if c_obj:
                selected_course_name = c_obj.name
                if session_status in ['completed', 'active']:
                    selected_session_status = 'معتمدة ومحفوظة' if session_status == 'completed' else 'منعقدة حالياً'

        # التحقق من توحد الدورة أو الدفعة أو القوة أو الحالة في السجلات المعروضة
        if not selected_course_name and records:
            first_c = records[0]['course_name']
            if all(r['course_name'] == first_c for r in records) and first_c and first_c != '---':
                selected_course_name = first_c

        if selected_course_name and not selected_batch_code and records:
            first_b = records[0]['session_code']
            if all(r['session_code'] == first_b for r in records) and first_b and first_b != '---':
                selected_batch_code = first_b

        if not selected_session_status and records:
            first_s = records[0]['session_status_label']
            if all(r['session_status_label'] == first_s for r in records) and first_s and first_s != '---':
                selected_session_status = first_s

        if not selected_force and records:
            first_f = records[0]['force']
            if first_f and first_f != '---' and all(r['force'] == first_f for r in records):
                selected_force = first_f

        # بناء صيغة العنوان المخصص: الدورة معها رقم الدفعة والقوة وحالة الدورة
        course_batch_title = ''
        if selected_course_name:
            c_clean = selected_course_name.strip()
            c_name = c_clean if c_clean.startswith('دورة') else f"دورة {c_clean}"
            if selected_batch_code:
                b_clean = selected_batch_code.strip()
                b_str = b_clean if b_clean.startswith('الدفعة') else f"الدفعة {b_clean}"
                course_batch_title = f"{c_name} ({b_str})"
            else:
                course_batch_title = c_name

        title_parts = ['تقرير الدارسين والنتائج التفصيلي']
        if course_batch_title:
            title_parts.append(course_batch_title)
        if selected_force:
            title_parts.append(selected_force)
        if selected_session_status and (course_batch_title or selected_force):
            title_parts.append(f"({selected_session_status})")

        report_title = " - ".join(title_parts[:3])
        if len(title_parts) > 3:
            report_title += f" {title_parts[3]}"

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'military_number', 'title': 'النمرة', 'align': 'center', 'width': 14},
            {'key': 'rank', 'title': 'الرتبة', 'align': 'center', 'width': 15},
            {'key': 'name', 'title': 'اسم الدارس', 'align': 'right', 'width': 26},
            {'key': 'force', 'title': 'القوة', 'align': 'center', 'width': 18},
            {'key': 'unit', 'title': 'الوحدة', 'align': 'center', 'width': 22},
            {'key': 'course_name', 'title': 'الدورة', 'align': 'right', 'width': 26},
            {'key': 'session_code', 'title': 'الدفعة', 'align': 'center', 'width': 16},
            {'key': 'session_status_label', 'title': 'حالة الدورة', 'align': 'center', 'width': 16},
            {'key': 'percentage', 'title': 'النسبة', 'align': 'center', 'width': 12},
            {'key': 'grade_label', 'title': 'التقدير', 'align': 'center', 'width': 14},
            {'key': 'result_status', 'title': 'الحالة', 'align': 'center', 'width': 16},
        ]

        # حذف الدورة وحالة الدورة والدفعة والقوة من التفاصيل عند وضعها في العنوان
        keys_to_exclude = set()
        if selected_course_name:
            keys_to_exclude.add('course_name')
        if selected_batch_code:
            keys_to_exclude.add('session_code')
        if selected_session_status and (selected_course_name or selected_force):
            keys_to_exclude.add('session_status_label')
        if selected_force:
            keys_to_exclude.add('force')

        if keys_to_exclude:
            columns = [c for c in columns if c['key'] not in keys_to_exclude]

        return _format_report_result({
            'report_type': report_type,
            'report_title': report_title,
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
            'session_status': session_status,
            'subjects_summary': sessions_subjects_summary,
        })

    # ========================================================
    # 2. تقرير الدورات المنعقدة والإحصائيات (sessions)
    # ========================================================
    elif report_type == 'sessions':
        qs = CourseSession.objects.select_related('course', 'course__category', 'supervisor').prefetch_related('enrollments')
        if institute:
            qs = qs.filter(institute=institute)

        # فلترة حالة الدورة التدريبية (معتمدة ومحفوظة، أو منعقدة حالياً، أو الكل)
        if session_status == 'completed':
            qs = qs.filter(status='completed')
        elif session_status == 'active':
            qs = qs.filter(status='active')
        elif session_status == 'all':
            qs = qs.filter(status__in=['completed', 'active'])

        if start_date and end_date:
            qs = qs.filter(
                Q(start_date__lte=end_date, end_date__gte=start_date) |
                Q(start_date__range=(start_date, end_date))
            )

        if category_id:
            qs = qs.filter(course__category_id=category_id)
        if course_id:
            qs = qs.filter(course_id=course_id)
        if trainee_category:
            qs = qs.filter(
                Q(target_category=trainee_category) | Q(target_category='joint') | Q(enrollments__trainee__category=trainee_category)
            ).distinct()
        if session_id:
            qs = qs.filter(id=session_id)
        if instructor_id:
            qs = qs.filter(
                Q(supervisor_id=instructor_id) |
                Q(subject_instructors__instructor_id=instructor_id)
            ).distinct()

        if q:
            qs = qs.filter(
                Q(course__name__icontains=q) |
                Q(session_code__icontains=q) |
                Q(course__category__name__icontains=q) |
                Q(supervisor__name__icontains=q)
            )

        qs = qs.order_by('-start_date', 'course__name')

        records = []
        stats = {
            'total_sessions': 0,
            'completed_sessions': 0,
            'active_sessions': 0,
            'total_trainees': 0,
            'total_passed': 0,
            'total_dropped': 0,
            'avg_pass_rate': 0.0,
        }
        pass_rates = []

        for s in qs:
            all_en = list(s.enrollments.all())
            trainees_count = len(all_en)
            dropped_count = sum(1 for e in all_en if e.is_dropped)
            active_trainees = [e for e in all_en if not e.is_dropped]
            passed_count = sum(1 for e in active_trainees if e.is_graded and e.percentage and e.percentage >= 50)
            failed_count = sum(1 for e in active_trainees if e.is_graded and e.percentage and e.percentage < 50)

            graded_count = sum(1 for e in active_trainees if e.is_graded)
            pass_rate = round((passed_count / graded_count * 100), 1) if graded_count > 0 else 0.0
            if graded_count > 0:
                pass_rates.append(pass_rate)

            # المواد المعتمدة المنفذة في هذه الدورة
            subjects_list = s.get_subjects()
            subjects_count = len(subjects_list)

            stats['total_sessions'] += 1
            if s.status == 'completed' or getattr(s, 'is_completed', False):
                stats['completed_sessions'] += 1
            else:
                stats['active_sessions'] += 1

            stats['total_trainees'] += trainees_count
            stats['total_passed'] += passed_count
            stats['total_dropped'] += dropped_count

            records.append({
                'id': s.id,
                'session_code': s.session_code or f"دورة {s.id}",
                'course_name': s.course.name,
                'category_name': s.course.category.name if s.course.category else '---',
                'start_date': s.start_date.strftime('%Y-%m-%d'),
                'end_date': s.end_date.strftime('%Y-%m-%d'),
                'supervisor_name': s.supervisor.name if s.supervisor else '---',
                'subjects_count': f"{subjects_count} مواد" if subjects_count else "---",
                'subjects_count_num': subjects_count,
                'status_label': 'معتمدة ومحفوظة' if (s.status == 'completed' or getattr(s, 'is_completed', False)) else 'منعقدة حالياً',
                'status_class': 'success' if (s.status == 'completed' or getattr(s, 'is_completed', False)) else 'primary',
                'trainees_count': trainees_count,
                'passed_count': passed_count,
                'failed_count': failed_count,
                'dropped_count': dropped_count,
                'pass_rate': f"{pass_rate}%",
            })

        stats['total_trainees_enrolled'] = stats['total_trainees']
        stats['avg_pass_rate'] = round(sum(pass_rates) / len(pass_rates), 1) if pass_rates else 0.0

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'session_code', 'title': 'رقم/رمز الدورة', 'align': 'center', 'width': 18},
            {'key': 'course_name', 'title': 'اسم الدورة التدريبية', 'align': 'right', 'width': 28},
            {'key': 'category_name', 'title': 'التصنيف', 'align': 'center', 'width': 16},
            {'key': 'start_date', 'title': 'تاريخ البداية', 'align': 'center', 'width': 14},
            {'key': 'end_date', 'title': 'تاريخ النهاية', 'align': 'center', 'width': 14},
            {'key': 'supervisor_name', 'title': 'مشرف الدورة', 'align': 'right', 'width': 22},
            {'key': 'subjects_count', 'title': 'المواد المعتمدة', 'align': 'center', 'width': 14},
            {'key': 'trainees_count', 'title': 'الدارسين', 'align': 'center', 'width': 11},
            {'key': 'passed_count', 'title': 'الناجحين', 'align': 'center', 'width': 11},
            {'key': 'dropped_count', 'title': 'المقطوعين', 'align': 'center', 'width': 11},
            {'key': 'pass_rate', 'title': 'نسبة النجاح', 'align': 'center', 'width': 13},
            {'key': 'status_label', 'title': 'حالة الدورة', 'align': 'center', 'width': 15},
        ]

        return _format_report_result({
            'report_type': report_type,
            'report_title': 'تقرير الدورات المنعقدة ونسب النجاح',
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
            'session_status': session_status,
            'subjects_summary': sessions_subjects_summary,
        })

    # ========================================================
    # 3. تقرير الوحدات والقوى العسكرية (units_forces)
    # ========================================================
    elif report_type == 'units_forces':
        qs = CourseEnrollment.objects.select_related('trainee', 'session', 'session__course')
        if institute:
            qs = qs.filter(session__institute=institute)

        # فلترة حالة الدورة التدريبية
        if session_status == 'completed':
            qs = qs.filter(session__status='completed')
        elif session_status == 'active':
            qs = qs.filter(session__status='active')
        elif session_status == 'all':
            qs = qs.filter(session__status__in=['completed', 'active'])

        if start_date and end_date:
            qs = qs.filter(
                Q(session__start_date__lte=end_date, session__end_date__gte=start_date) |
                Q(session__start_date__range=(start_date, end_date))
            )

        if category_id:
            qs = qs.filter(session__course__category_id=category_id)
        if course_id:
            qs = qs.filter(session__course_id=course_id)
        if force:
            qs = qs.filter(Q(current_force=force) | Q(trainee__force=force))
        if unit:
            qs = qs.filter(Q(current_unit__icontains=unit) | Q(trainee__unit__icontains=unit))

        enrollments = list(qs)
        # تجميع حسب (الوحدة، القوة)
        grouped = {}
        for en in enrollments:
            u_name = (en.current_unit or en.trainee.unit or 'غير محددة').strip()
            f_name = (en.current_force or en.trainee.force or 'غير محددة').strip()
            key = (u_name, f_name)
            if key not in grouped:
                grouped[key] = {
                    'unit': u_name,
                    'force': f_name,
                    'total': 0,
                    'officers': 0,
                    'nco': 0,
                    'civilians': 0,
                    'passed': 0,
                    'dropped': 0,
                }
            item = grouped[key]
            item['total'] += 1
            if en.trainee.category == TraineeCategory.OFFICER:
                item['officers'] += 1
            elif en.trainee.category == TraineeCategory.NCO:
                item['nco'] += 1
            else:
                item['civilians'] += 1

            if en.is_dropped:
                item['dropped'] += 1
            elif en.is_graded and en.percentage and en.percentage >= 50:
                item['passed'] += 1

        records = sorted(grouped.values(), key=lambda x: x['total'], reverse=True)

        stats = {
            'total_units': len(records),
            'total_trainees': sum(r['total'] for r in records),
            'total_officers': sum(r['officers'] for r in records),
            'total_nco': sum(r['nco'] for r in records),
            'total_civilians': sum(r['civilians'] for r in records),
            'total_passed': sum(r['passed'] for r in records),
            'total_dropped': sum(r['dropped'] for r in records),
        }

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'unit', 'title': 'اسم الوحدة العسكرية', 'align': 'right', 'width': 28},
            {'key': 'force', 'title': 'القوة التابعة لها', 'align': 'center', 'width': 22},
            {'key': 'total', 'title': 'إجمالي المبتعثين', 'align': 'center', 'width': 15},
            {'key': 'officers', 'title': 'عدد الضباط', 'align': 'center', 'width': 13},
            {'key': 'nco', 'title': 'ضباط الصف', 'align': 'center', 'width': 13},
            {'key': 'civilians', 'title': 'المدنيين', 'align': 'center', 'width': 12},
            {'key': 'passed', 'title': 'الناجحين', 'align': 'center', 'width': 13},
            {'key': 'dropped', 'title': 'المقطوعين', 'align': 'center', 'width': 13},
        ]

        return _format_report_result({
            'report_type': report_type,
            'report_title': 'تقرير توزيع الوحدات والقوى العسكرية',
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
            'session_status': session_status,
            'subjects_summary': sessions_subjects_summary,
        })

    # ========================================================
    # 4. تقرير أوامر التحرك والدارسين المقطوعين (dropped_trainees)
    # ========================================================
    elif report_type == 'dropped_trainees':
        qs = CourseEnrollment.objects.filter(is_dropped=True).select_related(
            'trainee', 'session', 'session__course'
        )
        if institute:
            qs = qs.filter(session__institute=institute)

        # فلترة حالة الدورة التدريبية
        if session_status == 'completed':
            qs = qs.filter(session__status='completed')
        elif session_status == 'active':
            qs = qs.filter(session__status='active')
        elif session_status == 'all':
            qs = qs.filter(session__status__in=['completed', 'active'])

        if start_date and end_date:
            qs = qs.filter(
                Q(dropped_at__date__range=(start_date, end_date)) |
                Q(session__start_date__range=(start_date, end_date)) |
                Q(movement_order_date__range=(start_date, end_date))
            )

        if category_id:
            qs = qs.filter(session__course__category_id=category_id)
        if course_id:
            qs = qs.filter(session__course_id=course_id)
        if force:
            qs = qs.filter(Q(current_force=force) | Q(trainee__force=force))
        if unit:
            qs = qs.filter(Q(current_unit__icontains=unit) | Q(trainee__unit__icontains=unit))

        if q:
            qs = qs.filter(
                Q(trainee__name__icontains=q) |
                Q(trainee__military_number__icontains=q) |
                Q(current_unit__icontains=q) |
                Q(drop_reason__icontains=q) |
                Q(session__course__name__icontains=q)
            )

        qs = qs.order_by('-dropped_at', '-id')

        records = []
        for en in qs:
            records.append({
                'id': en.id,
                'military_number': en.trainee.military_number,
                'name': en.trainee.name,
                'rank': en.current_rank or '---',
                'category_label': en.trainee.get_category_display(),
                'unit': en.current_unit or en.trainee.unit or '---',
                'force': en.current_force or en.trainee.force or '---',
                'course_name': en.session.course.name,
                'session_code': en.session.session_code or f"دورة {en.session.id}",
                'drop_date': en.dropped_at.strftime('%Y-%m-%d') if en.dropped_at else (en.movement_order_date.strftime('%Y-%m-%d') if en.movement_order_date else '---'),
                'drop_reason': en.drop_reason or 'لم يحدد',
                'has_movement_scan': 'نعم' if en.movement_order_file else 'لا',
            })

        stats = {
            'total_dropped': len(records),
            'officers': sum(1 for r in records if r['category_label'] == 'ضابط'),
            'nco': sum(1 for r in records if r['category_label'] == 'ضابط صف'),
            'civilians': sum(1 for r in records if r['category_label'] == 'مدني'),
        }

        # فحص تخصيص الدورة والدفعة والقوة لوضعهم في العنوان وحذفهم من التفاصيل
        selected_course_name = ''
        selected_batch_code = ''
        selected_force = force.strip() if force else ''

        if session_id:
            sess_obj = CourseSession.objects.filter(pk=session_id).first()
            if sess_obj:
                selected_course_name = sess_obj.course.name if sess_obj.course else ''
                selected_batch_code = sess_obj.session_code or f"{sess_obj.id}"
        elif course_id:
            c_obj = Course.objects.filter(pk=course_id).first()
            if c_obj:
                selected_course_name = c_obj.name

        if not selected_course_name and records:
            first_c = records[0]['course_name']
            if all(r['course_name'] == first_c for r in records) and first_c and first_c != '---':
                selected_course_name = first_c

        if selected_course_name and not selected_batch_code and records:
            first_b = records[0]['session_code']
            if all(r['session_code'] == first_b for r in records) and first_b and first_b != '---':
                selected_batch_code = first_b

        if not selected_force and records:
            first_f = records[0]['force']
            if first_f and first_f != '---' and all(r['force'] == first_f for r in records):
                selected_force = first_f

        course_batch_title = ''
        if selected_course_name:
            c_clean = selected_course_name.strip()
            c_name = c_clean if c_clean.startswith('دورة') else f"دورة {c_clean}"
            if selected_batch_code:
                b_clean = selected_batch_code.strip()
                b_str = b_clean if b_clean.startswith('الدفعة') else f"الدفعة {b_clean}"
                course_batch_title = f"{c_name} ({b_str})"
            else:
                course_batch_title = c_name

        title_parts = ['تقرير الدارسين المقطوعة دوراتهم وأوامر التحرك']
        if course_batch_title:
            title_parts.append(course_batch_title)
        if selected_force:
            title_parts.append(selected_force)

        report_title = " - ".join(title_parts)

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'military_number', 'title': 'النمرة', 'align': 'center', 'width': 14},
            {'key': 'rank', 'title': 'الرتبة', 'align': 'center', 'width': 15},
            {'key': 'name', 'title': 'اسم الدارس', 'align': 'right', 'width': 26},
            {'key': 'unit', 'title': 'الوحدة المسجل بها', 'align': 'center', 'width': 22},
            {'key': 'force', 'title': 'القوة', 'align': 'center', 'width': 18},
            {'key': 'course_name', 'title': 'الدورة', 'align': 'right', 'width': 26},
            {'key': 'session_code', 'title': 'الدفعة', 'align': 'center', 'width': 16},
            {'key': 'drop_date', 'title': 'تاريخ القطع / التحرك', 'align': 'center', 'width': 18},
            {'key': 'drop_reason', 'title': 'سبب القطع', 'align': 'right', 'width': 28},
        ]

        keys_to_exclude = set()
        if selected_course_name:
            keys_to_exclude.add('course_name')
        if selected_batch_code:
            keys_to_exclude.add('session_code')
        if selected_force:
            keys_to_exclude.add('force')

        if keys_to_exclude:
            columns = [c for c in columns if c['key'] not in keys_to_exclude]

        return _format_report_result({
            'report_type': report_type,
            'report_title': report_title,
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
            'session_status': session_status,
            'subjects_summary': sessions_subjects_summary,
        })

    # ========================================================
    # 5. تقرير هيئة التعليم والمعلمين (instructors)
    # ========================================================
    elif report_type == 'instructors':
        qs = Instructor.objects.all()
        if institute:
            qs = qs.filter(institute=institute)
        if instructor_id:
            qs = qs.filter(pk=instructor_id)
        if q:
            qs = qs.filter(
                Q(name__icontains=q) |
                Q(military_number__icontains=q) |
                Q(rank__icontains=q) |
                Q(unit__icontains=q) |
                Q(force__icontains=q)
            )

        instructors = list(qs.order_by('name'))
        records = []

        for inst in instructors:
            # الدورات التي يشرف عليها بحسب حالة الدورة
            supervised_qs = CourseSession.objects.filter(supervisor=inst)
            if institute:
                supervised_qs = supervised_qs.filter(institute=institute)
            if session_status == 'completed':
                supervised_qs = supervised_qs.filter(status='completed')
            elif session_status == 'active':
                supervised_qs = supervised_qs.filter(status='active')
            elif session_status == 'all':
                supervised_qs = supervised_qs.filter(status__in=['completed', 'active'])

            if start_date and end_date:
                supervised_qs = supervised_qs.filter(
                    Q(start_date__lte=end_date, end_date__gte=start_date) |
                    Q(start_date__range=(start_date, end_date))
                )
            supervised_count = supervised_qs.count()

            # المواد المكلف بها بحسب حالة الدورة
            assigned_qs = SessionSubjectInstructor.objects.filter(instructor=inst)
            if institute:
                assigned_qs = assigned_qs.filter(session__institute=institute)
            if session_status == 'completed':
                assigned_qs = assigned_qs.filter(session__status='completed')
            elif session_status == 'active':
                assigned_qs = assigned_qs.filter(session__status='active')
            elif session_status == 'all':
                assigned_qs = assigned_qs.filter(session__status__in=['completed', 'active'])

            if start_date and end_date:
                assigned_qs = assigned_qs.filter(
                    Q(session__start_date__lte=end_date, session__end_date__gte=start_date) |
                    Q(session__start_date__range=(start_date, end_date))
                )
            assigned_count = assigned_qs.count()

            records.append({
                'id': inst.pk,
                'name': inst.name,
                'military_number': inst.military_number or '---',
                'rank': inst.rank or '---',
                'unit': inst.unit or '---',
                'force': inst.force or '---',
                'supervised_sessions_count': supervised_count,
                'assigned_subjects_count': assigned_count,
                'total_courses_involved': supervised_count + assigned_count,
            })

        stats = {
            'total_instructors': len(records),
            'total_supervisions': sum(r['supervised_sessions_count'] for r in records),
            'total_subject_assignments': sum(r['assigned_subjects_count'] for r in records),
        }

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'name', 'title': 'اسم المعلم', 'align': 'right', 'width': 28},
            {'key': 'military_number', 'title': 'النمرة العسكرية', 'align': 'center', 'width': 16},
            {'key': 'rank', 'title': 'الرتبة', 'align': 'center', 'width': 16},
            {'key': 'unit', 'title': 'الوحدة', 'align': 'center', 'width': 22},
            {'key': 'force', 'title': 'القوة', 'align': 'center', 'width': 18},
            {'key': 'supervised_sessions_count', 'title': 'الدورات المشرف عليها', 'align': 'center', 'width': 20},
            {'key': 'assigned_subjects_count', 'title': 'المواد المكلف بتدريسها', 'align': 'center', 'width': 20},
        ]

        return _format_report_result({
            'report_type': report_type,
            'report_title': 'تقرير هيئة التعليم وتكليفات المعلمين',
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
            'session_status': session_status,
            'subjects_summary': sessions_subjects_summary,
        })

    # ========================================================
    # 6. تقرير المواد الدراسية وهيئة التدريس ونسب النجاح (course_subjects)
    # ========================================================
    elif report_type == 'course_subjects':
        records = []
        all_instructors = set()
        all_pass_rates = []
        total_graded_exams = 0

        for s_summary in sessions_subjects_summary:
            for sub in s_summary['subjects']:
                records.append({
                    'category_name': s_summary['category_name'],
                    'course_name': s_summary['course_name'],
                    'session_code': s_summary['session_code'],
                    'subject_name': sub['subject_name'],
                    'subject_code': sub['subject_code'],
                    'instructor_name': sub['instructor_name'],
                    'credit_hours': f"{sub['credit_hours']} س",
                    'max_grade': f"{sub['max_grade']:.0f}",
                    'total_graded': sub['total_graded'],
                    'passed_count': sub['passed_count'],
                    'avg_score': f"{sub['avg_score']:.2f}",
                    'pass_rate': f"{sub['pass_rate']}%",
                    'assessment': sub['assessment'],
                    'assessment_class': sub['assessment_class'],
                })
                if sub['instructor_name'] not in ['لم يحدد بعد', 'لم يحدد'] and not sub['instructor_name'].endswith('(مشرف الدورة)'):
                    all_instructors.add(sub['instructor_name'])
                if sub['total_graded'] > 0:
                    all_pass_rates.append(sub['pass_rate'])
                total_graded_exams += sub['total_graded']

        stats = {
            'total_subjects_taught': len(records),
            'total_instructors_involved': len(all_instructors),
            'overall_avg_pass_rate': round(sum(all_pass_rates) / len(all_pass_rates), 1) if all_pass_rates else 0.0,
            'total_graded_exams': total_graded_exams,
        }

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'category_name', 'title': 'تصنيف الدورة', 'align': 'center', 'width': 16},
            {'key': 'course_name', 'title': 'اسم الدورة التدريبية', 'align': 'right', 'width': 26},
            {'key': 'session_code', 'title': 'الدفعة', 'align': 'center', 'width': 14},
            {'key': 'subject_name', 'title': 'المادة الدراسية', 'align': 'right', 'width': 24},
            {'key': 'instructor_name', 'title': 'الأستاذ / المعلم المكلف', 'align': 'right', 'width': 24},
            {'key': 'credit_hours', 'title': 'الساعات', 'align': 'center', 'width': 10},
            {'key': 'max_grade', 'title': 'الدرجة العظمى', 'align': 'center', 'width': 12},
            {'key': 'total_graded', 'title': 'الممتحنون', 'align': 'center', 'width': 11},
            {'key': 'passed_count', 'title': 'الناجحون', 'align': 'center', 'width': 11},
            {'key': 'avg_score', 'title': 'متوسط الدرجات', 'align': 'center', 'width': 14},
            {'key': 'pass_rate', 'title': 'متوسط النجاح', 'align': 'center', 'width': 14},
            {'key': 'assessment', 'title': 'مستوى الإنجاز', 'align': 'center', 'width': 14},
        ]

        return _format_report_result({
            'report_type': report_type,
            'report_title': 'تقرير المواد الدراسية وهيئة التدريس ومعدلات النجاح',
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
            'session_status': session_status,
            'subjects_summary': sessions_subjects_summary,
        })

    # ========================================================
    # 7. تقرير امتحانات تحديد المستوى (placement_exams)
    # ========================================================
    elif report_type == 'placement_exams':
        from apps.placement_exams.models import PlacementExamOrder, PlacementExamCandidate, PlacementExamStatus, CandidateClassification

        placement_qs = PlacementExamOrder.objects.select_related('supervisor', 'institute').prefetch_related('candidates')
        if institute:
            placement_qs = placement_qs.filter(institute=institute)

        placement_desc_items = []
        if use_all_dates:
            placement_desc_items.append("الفترة: كامل السجلات (كل الأوقات)")
        else:
            if start_date and end_date:
                placement_qs = placement_qs.filter(exam_date__range=(start_date, end_date))
            placement_desc_items.append(f"الفترة من: {start_date_val} إلى: {end_date_val}")

        # غرض الامتحان
        placement_purpose = str(params.get('placement_purpose') or '').strip()
        if placement_purpose:
            placement_qs = placement_qs.filter(purpose=placement_purpose)
            placement_desc_items.append(f"الغرض: {placement_purpose}")

        # الجهة الطالبة / المصدر
        placement_source = str(params.get('placement_source_entity') or '').strip()
        if placement_source:
            placement_qs = placement_qs.filter(source_entity=placement_source)
            placement_desc_items.append(f"الجهة الطالبة: {placement_source}")

        # سنة الطلب
        placement_year = str(params.get('placement_year') or '').strip()
        if placement_year and placement_year.isdigit():
            placement_qs = placement_qs.filter(year=int(placement_year))
            placement_desc_items.append(f"السنة: {placement_year}")

        # فئة الممتحنين
        placement_target_cat = str(params.get('placement_target_cat') or '').strip()
        if placement_target_cat and placement_target_cat != 'all':
            placement_qs = placement_qs.filter(classification=placement_target_cat)
            class_map = {
                CandidateClassification.OFFICERS: 'ضباط',
                CandidateClassification.NCOS: 'ضباط صف',
                CandidateClassification.CIVILIANS: 'مدنيين',
                CandidateClassification.MIXED: 'مشترك'
            }
            placement_desc_items.append(f"الفئة: {class_map.get(placement_target_cat, placement_target_cat)}")

        # حالة الامتحان
        placement_status = str(params.get('placement_status') or '').strip()
        if placement_status and placement_status != 'all':
            placement_qs = placement_qs.filter(status=placement_status)
            status_map_labels = {
                PlacementExamStatus.APPROVED: 'معتمد نهائياً',
                PlacementExamStatus.PENDING_APPROVAL: 'بانتظار الاعتماد',
                PlacementExamStatus.CONFIRMED: 'تم تأكيد الانعقاد',
                PlacementExamStatus.IN_PROGRESS: 'قيد التنفيذ'
            }
            placement_desc_items.append(f"الحالة: {status_map_labels.get(placement_status, placement_status)}")

        # حالة النتيجة أو الاعتماد
        placement_result_status = str(params.get('placement_result_status') or '').strip()
        if placement_result_status == 'passed':
            placement_qs = placement_qs.filter(candidates__is_passed=True).distinct()
            placement_desc_items.append("النتيجة: الناجحون فقط")
        elif placement_result_status == 'failed':
            placement_qs = placement_qs.filter(candidates__is_passed=False, candidates__attendance_status='present').distinct()
            placement_desc_items.append("النتيجة: الراسبون فقط")
        elif placement_result_status == 'absent':
            placement_qs = placement_qs.filter(candidates__attendance_status='absent').distinct()
            placement_desc_items.append("النتيجة: الغائبون فقط")
        elif placement_result_status == 'approved_only':
            placement_qs = placement_qs.filter(status=PlacementExamStatus.APPROVED)
            placement_desc_items.append("الاعتماد: معتمد فقط")

        # بحث نصي
        if q:
            placement_qs = placement_qs.filter(
                Q(order_code__icontains=q) |
                Q(signal_number__icontains=q) |
                Q(source_entity__icontains=q) |
                Q(host_entity__icontains=q) |
                Q(purpose__icontains=q) |
                Q(sub_purpose__icontains=q) |
                Q(candidates__candidate_name__icontains=q) |
                Q(candidates__military_number__icontains=q)
            ).distinct()
            placement_desc_items.append(f"بحث نصي: \"{q}\"")

        placement_filters_summary = " | ".join(placement_desc_items) if placement_desc_items else "كافة سجلات امتحانات تحديد المستوى"

        orders = list(placement_qs.order_by('-exam_date', '-id'))
        records = []

        total_candidates_count = 0
        total_passed_count = 0
        total_failed_count = 0
        total_absent_count = 0

        status_class_map = {
            PlacementExamStatus.APPROVED: 'success',
            PlacementExamStatus.PENDING_APPROVAL: 'info',
            PlacementExamStatus.CONFIRMED: 'primary',
            PlacementExamStatus.IN_PROGRESS: 'warning',
        }
        status_label_map = {
            PlacementExamStatus.APPROVED: 'معتمد نهائياً',
            PlacementExamStatus.PENDING_APPROVAL: 'بانتظار الاعتماد',
            PlacementExamStatus.CONFIRMED: 'تم تأكيد الانعقاد',
            PlacementExamStatus.IN_PROGRESS: 'قيد التنفيذ',
        }

        for order in orders:
            all_cands = list(order.candidates.all())
            c_count = len(all_cands)
            passed_cands = [c for c in all_cands if c.is_passed]
            p_count = len(passed_cands)
            attended_cands = [c for c in all_cands if c.attendance_status == 'present']
            att_count = len(attended_cands)
            failed_cands = [c for c in attended_cands if not c.is_passed]
            f_count = len(failed_cands)
            absent_cands = [c for c in all_cands if c.attendance_status == 'absent']
            ab_count = len(absent_cands)

            total_candidates_count += c_count
            total_passed_count += p_count
            total_failed_count += f_count
            total_absent_count += ab_count

            pass_pct = round((p_count / att_count * 100), 1) if att_count > 0 else (100.0 if p_count > 0 else 0.0)

            sup_name = order.supervisor.name if order.supervisor else (order.supervisor_name_snapshot or 'لم يحدد')
            if order.supervisor and order.supervisor.rank:
                sup_name = f"{order.supervisor.rank} / {sup_name}"

            records.append({
                'id': order.id,
                'order_code': order.order_code or f"#{order.id}",
                'signal_number': order.signal_number or '---',
                'source_entity': order.source_entity,
                'purpose': f"{order.purpose} ({order.sub_purpose})" if order.sub_purpose else order.purpose,
                'classification': order.get_classification_display(),
                'exam_date': order.exam_date.strftime('%Y-%m-%d') if order.exam_date else '---',
                'candidates_count': c_count,
                'passed_count': p_count,
                'failed_count': f_count,
                'absent_count': ab_count,
                'pass_rate': f"{pass_pct:.1f}%" if att_count > 0 else '---',
                'pass_rate_num': pass_pct,
                'status_label': status_label_map.get(order.status, order.status),
                'status_class': status_class_map.get(order.status, 'secondary'),
                'supervisor': sup_name,
                'is_approved': order.status == PlacementExamStatus.APPROVED,
                'is_confirmed': order.status in [PlacementExamStatus.CONFIRMED, PlacementExamStatus.PENDING_APPROVAL, PlacementExamStatus.APPROVED],
            })

        approved_exams_count = sum(1 for r in records if r['is_approved'])
        active_exams_count = len(records) - approved_exams_count
        evaluated_candidates = total_passed_count + total_failed_count
        overall_pass_rate = round((total_passed_count / evaluated_candidates * 100), 1) if evaluated_candidates > 0 else 0.0

        stats = {
            'total_exams': len(records),
            'approved_exams': approved_exams_count,
            'active_exams': active_exams_count,
            'total_candidates': total_candidates_count,
            'total_passed': total_passed_count,
            'total_failed': total_failed_count,
            'total_absent': total_absent_count,
            'overall_pass_rate': overall_pass_rate,
            'officers': sum(1 for o in orders if o.classification == CandidateClassification.OFFICERS),
            'ncos': sum(1 for o in orders if o.classification == CandidateClassification.NCOS),
            'civilians': sum(1 for o in orders if o.classification == CandidateClassification.CIVILIANS),
            'mixed': sum(1 for o in orders if o.classification == CandidateClassification.MIXED),
        }

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'order_code', 'title': 'كود الطلب', 'align': 'center', 'width': 14},
            {'key': 'signal_number', 'title': 'رقم الإشارة', 'align': 'center', 'width': 16},
            {'key': 'source_entity', 'title': 'الجهة الطالبة / الراسلة', 'align': 'right', 'width': 26},
            {'key': 'purpose', 'title': 'غرض الامتحان', 'align': 'right', 'width': 22},
            {'key': 'classification', 'title': 'الفئة', 'align': 'center', 'width': 12},
            {'key': 'exam_date', 'title': 'تاريخ الانعقاد', 'align': 'center', 'width': 14},
            {'key': 'candidates_count', 'title': 'الممتحنون', 'align': 'center', 'width': 11},
            {'key': 'passed_count', 'title': 'الناجحون', 'align': 'center', 'width': 11},
            {'key': 'pass_rate', 'title': 'نسبة النجاح', 'align': 'center', 'width': 13},
            {'key': 'status_label', 'title': 'حالة الطلب والاعتماد', 'align': 'center', 'width': 18},
            {'key': 'supervisor', 'title': 'المعلم المشرف', 'align': 'right', 'width': 22},
        ]

        return _format_report_result({
            'report_type': report_type,
            'report_title': 'تقرير امتحانات تحديد المستوى',
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': placement_filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
            'session_status': session_status,
            'subjects_summary': [],
        })


def export_report_to_excel(report_data):
    """
    إنشاء ملف إكسل احترافي منسق بالكامل من بيانات التقرير
    مجهز لدعم اللغة العربية واتجاه اليمين لليسار (RTL) مع ترويسة أنيقة وألوان رسمية
    """
    if not HAS_OPENPYXL:
        raise ImportError("حزمة openpyxl غير مثبتة. يرجى تثبيتها عبر أمر: pip install openpyxl")

    wb = openpyxl.Workbook()
    ws = wb.active

    # ضبط اسم الورقة واتجاهها لليمين (RTL)
    sheet_title = report_data.get('report_title', 'تقرير')[:31]
    ws.title = sheet_title
    ws.views.sheetView[0].rightToLeft = True

    # تعريف الأنماط والألوان والخطوط
    navy_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    gold_fill = PatternFill(start_color="D97706", end_color="D97706", fill_type="solid")
    header_fill = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    sub_header_fill = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid")
    table_header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
    zebra_fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
    totals_fill = PatternFill(start_color="E2E8F0", end_color="E2E8F0", fill_type="solid")

    font_title = Font(name="Arial", size=15, bold=True, color="FFFFFF")
    font_sub_title = Font(name="Arial", size=12, bold=True, color="F8FAFC")
    font_filter = Font(name="Arial", size=10, italic=True, color="CBD5E1")
    font_table_header = Font(name="Arial", size=11, bold=True, color="FFFFFF")
    font_data = Font(name="Arial", size=10, bold=False, color="000000")
    font_data_bold = Font(name="Arial", size=10, bold=True, color="000000")
    font_totals = Font(name="Arial", size=11, bold=True, color="0F172A")

    thin_border_side = Side(border_style="thin", color="CBD5E1")
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    thick_bottom = Side(border_style="double", color="1E3A8A")
    totals_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thick_bottom)

    align_center = Alignment(horizontal="center", vertical="center", wrap_text=True)
    align_right = Alignment(horizontal="right", vertical="center", wrap_text=True)
    align_left = Alignment(horizontal="left", vertical="center", wrap_text=True)

    columns = report_data.get('columns', [])
    col_count = len(columns)
    if col_count == 0:
        col_count = 5

    # 1. الترويسة العليا: اسم المنظومة
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=col_count)
    cell_top = ws.cell(row=1, column=1, value="القوات المسلحة - معهد نظم المعلومات والإحصاء")
    cell_top.font = font_title
    cell_top.fill = header_fill
    cell_top.alignment = align_center
    ws.row_dimensions[1].height = 34

    # 2. عنوان التقرير
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=col_count)
    cell_name = ws.cell(row=2, column=1, value=report_data.get('report_title', 'تقرير النظام'))
    cell_name.font = font_sub_title
    cell_name.fill = sub_header_fill
    cell_name.alignment = align_center
    ws.row_dimensions[2].height = 28

    # 3. ملخص الفلاتر وتاريخ الاستخراج
    export_time_str = timezone.now().strftime('%Y-%m-%d %H:%M')
    filters_text = f"{report_data.get('filters_summary', '')} | تاريخ الاستخراج: {export_time_str}"
    ws.merge_cells(start_row=3, start_column=1, end_row=3, end_column=col_count)
    cell_filter = ws.cell(row=3, column=1, value=filters_text)
    cell_filter.font = font_filter
    cell_filter.fill = sub_header_fill
    cell_filter.alignment = align_center
    ws.row_dimensions[3].height = 22

    # سطر فاصل فارغ
    ws.row_dimensions[4].height = 10

    # 4. عناوين الأعمدة
    header_row_idx = 5
    ws.row_dimensions[header_row_idx].height = 26
    for c_idx, col_def in enumerate(columns, start=1):
        c = ws.cell(row=header_row_idx, column=c_idx, value=col_def['title'])
        c.font = font_table_header
        c.fill = table_header_fill
        c.alignment = align_center
        c.border = cell_border

    # 5. صفوف البيانات
    current_row = 6
    records = report_data.get('records', [])
    for r_idx, rec in enumerate(records, start=1):
        ws.row_dimensions[current_row].height = 22
        is_zebra = (r_idx % 2 == 0)

        for c_idx, col_def in enumerate(columns, start=1):
            key = col_def['key']
            val = r_idx if key == 'index' else rec.get(key, '')

            cell = ws.cell(row=current_row, column=c_idx, value=val)
            cell.font = font_data
            cell.border = cell_border

            align_type = col_def.get('align', 'center')
            if align_type == 'right':
                cell.alignment = align_right
            elif align_type == 'left':
                cell.alignment = align_left
            else:
                cell.alignment = align_center

            if is_zebra:
                cell.fill = zebra_fill

        current_row += 1

    # 6. صف المجاميع والإحصائيات الختامية
    ws.row_dimensions[current_row].height = 25
    ws.merge_cells(start_row=current_row, start_column=1, end_row=current_row, end_column=2)
    tot_label = ws.cell(row=current_row, column=1, value="الإجمالي الكلي")
    tot_label.font = font_totals
    tot_label.fill = totals_fill
    tot_label.alignment = align_center
    tot_label.border = totals_border

    ws.cell(row=current_row, column=2).border = totals_border

    count_cell = ws.cell(row=current_row, column=3, value=f"{len(records)} سجل")
    count_cell.font = font_totals
    count_cell.fill = totals_fill
    count_cell.alignment = align_center
    count_cell.border = totals_border

    for c_idx in range(4, col_count + 1):
        empty_tot = ws.cell(row=current_row, column=c_idx, value="")
        empty_tot.fill = totals_fill
        empty_tot.border = totals_border

    # 7. ضبط عرض الأعمدة تلقائياً
    for c_idx, col_def in enumerate(columns, start=1):
        col_letter = get_column_letter(c_idx)
        desired_width = col_def.get('width', 18)
        ws.column_dimensions[col_letter].width = desired_width

    # 8. إضافة ورقة منفصلة لتحليل المواد وهيئة التدريس إذا كانت متوفرة
    subjects_summary = report_data.get('subjects_summary', [])
    if subjects_summary and report_data.get('report_type') != 'course_subjects':
        ws_sub = wb.create_sheet(title="المواد وهيئة التدريس")
        ws_sub.views.sheetView[0].rightToLeft = True

        ws_sub.merge_cells('A1:J1')
        c_top = ws_sub.cell(row=1, column=1, value="القوات المسلحة - معهد نظم المعلومات والإحصاء | بيان المواد وهيئة التدريس ومعدلات النجاح")
        c_top.font = font_title
        c_top.fill = header_fill
        c_top.alignment = align_center
        ws_sub.row_dimensions[1].height = 32

        sub_row = 3
        for sess in subjects_summary:
            ws_sub.merge_cells(start_row=sub_row, start_column=1, end_row=sub_row, end_column=10)
            c_banner = ws_sub.cell(row=sub_row, column=1, value=f"{sess['statement']} | الدورة: {sess['course_name']} | الدفعة: {sess['session_code']} ({sess['status_label']})")
            c_banner.font = font_sub_title
            c_banner.fill = gold_fill
            c_banner.alignment = align_center
            ws_sub.row_dimensions[sub_row].height = 26
            sub_row += 1

            sub_headers = [
                ('#', 6),
                ('اسم المادة الدراسية', 26),
                ('كود المادة', 14),
                ('الأستاذ / المعلم المكلف', 26),
                ('الساعات', 10),
                ('الدرجة العظمى', 14),
                ('الممتحنون', 12),
                ('الناجحون', 12),
                ('متوسط الدرجات', 14),
                ('متوسط النجاح (%)', 16),
            ]
            ws_sub.row_dimensions[sub_row].height = 24
            for col_idx, (h_title, h_width) in enumerate(sub_headers, start=1):
                ch = ws_sub.cell(row=sub_row, column=col_idx, value=h_title)
                ch.font = font_table_header
                ch.fill = table_header_fill
                ch.alignment = align_center
                ch.border = cell_border
                col_letter = get_column_letter(col_idx)
                ws_sub.column_dimensions[col_letter].width = h_width
            sub_row += 1

            for s_idx, sub in enumerate(sess['subjects'], start=1):
                ws_sub.row_dimensions[sub_row].height = 22
                vals = [
                    s_idx,
                    sub['subject_name'],
                    sub['subject_code'],
                    sub['instructor_name'],
                    f"{sub['credit_hours']} س",
                    f"{sub['max_grade']:.0f}",
                    sub['total_graded'],
                    sub['passed_count'],
                    f"{sub['avg_score']:.2f}",
                    f"{sub['pass_rate']}%",
                ]
                for col_idx, val in enumerate(vals, start=1):
                    cell = ws_sub.cell(row=sub_row, column=col_idx, value=val)
                    cell.font = font_data
                    cell.border = cell_border
                    if col_idx in [2, 4]:
                        cell.alignment = align_right
                    else:
                        cell.alignment = align_center
                    if s_idx % 2 == 0:
                        cell.fill = zebra_fill
                sub_row += 1
            sub_row += 2

    # حفظ في الذاكرة وإرجاع الحزم
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
