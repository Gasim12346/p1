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

from .models import (
    CourseEnrollment,
    CourseSession,
    Course,
    CourseCategory,
    Trainee,
    TraineeCategory,
    Instructor,
    SessionSubjectInstructor,
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


def get_report_data(params):
    """
    تجميع وفلترة بيانات التقرير بحسب المعايير المحددة في الطلب
    """
    report_type = params.get('report_type', 'trainees').strip()
    if report_type not in ['trainees', 'sessions', 'units_forces', 'dropped_trainees', 'instructors']:
        report_type = 'trainees'

    # معالجة نطاق التواريخ
    use_all_dates = params.get('all_dates') in ['1', 'true', 'True']
    start_date_str = params.get('start_date', '').strip()
    end_date_str = params.get('end_date', '').strip()

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

    category_id = params.get('category_id', '').strip()
    course_id = params.get('course_id', '').strip()
    session_id = params.get('session_id', '').strip()
    force = params.get('force', '').strip()
    unit = params.get('unit', '').strip()
    trainee_category = params.get('trainee_category', '').strip()
    status = params.get('status', 'all').strip()
    instructor_id = params.get('instructor_id', '').strip()
    q = params.get('q', '').strip()

    filter_desc_items = []
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
        filter_desc_items.append(f"الفئة: {cat_map.get(trainee_category, trainee_category)}")

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

    # ========================================================
    # 1. تقرير الدارسين والنتائج التفصيلي (trainees)
    # ========================================================
    if report_type == 'trainees':
        qs = CourseEnrollment.objects.select_related(
            'trainee', 'session', 'session__course', 'session__course__category'
        )

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
                Q(session__instructors_assignments__instructor_id=instructor_id)
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

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'military_number', 'title': 'النمرة', 'align': 'center', 'width': 14},
            {'key': 'name', 'title': 'اسم الدارس', 'align': 'right', 'width': 26},
            {'key': 'rank', 'title': 'الرتبة', 'align': 'center', 'width': 15},
            {'key': 'category_label', 'title': 'التصنيف', 'align': 'center', 'width': 12},
            {'key': 'force', 'title': 'القوة', 'align': 'center', 'width': 18},
            {'key': 'unit', 'title': 'الوحدة', 'align': 'center', 'width': 22},
            {'key': 'course_name', 'title': 'الدورة', 'align': 'right', 'width': 26},
            {'key': 'session_code', 'title': 'الدفعة', 'align': 'center', 'width': 16},
            {'key': 'percentage', 'title': 'النسبة', 'align': 'center', 'width': 12},
            {'key': 'grade_label', 'title': 'التقدير', 'align': 'center', 'width': 14},
            {'key': 'result_status', 'title': 'الحالة', 'align': 'center', 'width': 16},
        ]

        return _format_report_result({
            'report_type': report_type,
            'report_title': 'تقرير الدارسين والنتائج التفصيلي',
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
        })

    # ========================================================
    # 2. تقرير الدورات المنعقدة والإحصائيات (sessions)
    # ========================================================
    elif report_type == 'sessions':
        qs = CourseSession.objects.select_related('course', 'course__category', 'supervisor').prefetch_related('enrollments')

        if start_date and end_date:
            qs = qs.filter(
                Q(start_date__lte=end_date, end_date__gte=start_date) |
                Q(start_date__range=(start_date, end_date))
            )

        if category_id:
            qs = qs.filter(course__category_id=category_id)
        if course_id:
            qs = qs.filter(course_id=course_id)
        if session_id:
            qs = qs.filter(id=session_id)
        if instructor_id:
            qs = qs.filter(
                Q(supervisor_id=instructor_id) |
                Q(instructors_assignments__instructor_id=instructor_id)
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
                'status_label': 'معتمدة ومكتملة' if (s.status == 'completed' or getattr(s, 'is_completed', False)) else 'جارية حالياً',
                'status_class': 'success' if (s.status == 'completed' or getattr(s, 'is_completed', False)) else 'primary',
                'trainees_count': trainees_count,
                'passed_count': passed_count,
                'failed_count': failed_count,
                'dropped_count': dropped_count,
                'pass_rate': f"{pass_rate}%",
            })

        stats['avg_pass_rate'] = round(sum(pass_rates) / len(pass_rates), 1) if pass_rates else 0.0

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'session_code', 'title': 'رقم/رمز الدورة', 'align': 'center', 'width': 18},
            {'key': 'course_name', 'title': 'اسم الدورة التدريبية', 'align': 'right', 'width': 28},
            {'key': 'category_name', 'title': 'التصنيف', 'align': 'center', 'width': 16},
            {'key': 'start_date', 'title': 'تاريخ البداية', 'align': 'center', 'width': 14},
            {'key': 'end_date', 'title': 'تاريخ النهاية', 'align': 'center', 'width': 14},
            {'key': 'supervisor_name', 'title': 'مشرف الدورة', 'align': 'right', 'width': 22},
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
        })

    # ========================================================
    # 3. تقرير الوحدات والقوى العسكرية (units_forces)
    # ========================================================
    elif report_type == 'units_forces':
        qs = CourseEnrollment.objects.select_related('trainee', 'session', 'session__course')

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
        })

    # ========================================================
    # 4. تقرير أوامر التحرك والدارسين المقطوعين (dropped_trainees)
    # ========================================================
    elif report_type == 'dropped_trainees':
        qs = CourseEnrollment.objects.filter(is_dropped=True).select_related(
            'trainee', 'session', 'session__course'
        )

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

        columns = [
            {'key': 'index', 'title': '#', 'align': 'center', 'width': 6},
            {'key': 'military_number', 'title': 'النمرة', 'align': 'center', 'width': 14},
            {'key': 'name', 'title': 'اسم الدارس', 'align': 'right', 'width': 26},
            {'key': 'rank', 'title': 'الرتبة', 'align': 'center', 'width': 15},
            {'key': 'unit', 'title': 'الوحدة المسجل بها', 'align': 'center', 'width': 22},
            {'key': 'force', 'title': 'القوة', 'align': 'center', 'width': 18},
            {'key': 'course_name', 'title': 'الدورة', 'align': 'right', 'width': 26},
            {'key': 'session_code', 'title': 'الدفعة', 'align': 'center', 'width': 16},
            {'key': 'drop_date', 'title': 'تاريخ القطع / التحرك', 'align': 'center', 'width': 18},
            {'key': 'drop_reason', 'title': 'سبب القطع', 'align': 'right', 'width': 28},
        ]

        return _format_report_result({
            'report_type': report_type,
            'report_title': 'تقرير الدارسين المقطوعة دوراتهم وأوامر التحرك',
            'records': records,
            'stats': stats,
            'columns': columns,
            'filters_summary': filters_summary,
            'start_date': start_date_val,
            'end_date': end_date_val,
            'use_all_dates': use_all_dates,
        })

    # ========================================================
    # 5. تقرير هيئة التعليم والمعلمين (instructors)
    # ========================================================
    elif report_type == 'instructors':
        qs = Instructor.objects.all()
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
            # الدورات التي يشرف عليها
            supervised_qs = CourseSession.objects.filter(supervisor=inst)
            if start_date and end_date:
                supervised_qs = supervised_qs.filter(
                    Q(start_date__lte=end_date, end_date__gte=start_date) |
                    Q(start_date__range=(start_date, end_date))
                )
            supervised_count = supervised_qs.count()

            # المواد المكلف بها
            assigned_qs = SessionSubjectInstructor.objects.filter(instructor=inst)
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

    # حفظ في الذاكرة وإرجاع الحزم
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()
