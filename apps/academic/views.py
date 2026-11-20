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
def courses_catalog_view(request):
    """دليل الدورات ومفرداتها والمواد"""
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        messages.warning(request, 'حسابك مخصص لمعلم / هيئة التدريس، وصلاحياتك محصورة في صفحة رصد نتائج المواد المكلف بها فقط.')
        return redirect('training:results_center')

    categories = CourseCategory.objects.annotate(courses_count=Count('courses')).all()
    if request.institute:
        categories = categories.filter(Q(institute=request.institute) | Q(institute__isnull=True))

    cat_id = request.GET.get('category_id')
    selected_category = None
    if cat_id:
        selected_category = CourseCategory.objects.filter(pk=cat_id).first()
    if not selected_category and categories.exists():
        selected_category = categories.first()

    courses = Course.objects.none()
    if selected_category:
        courses = selected_category.courses.annotate(
            subjects_count=Count('subjects', filter=Q(subjects__session__isnull=True))
        ).all()

    course_id = request.GET.get('course_id')
    selected_course = None
    if course_id:
        selected_course = Course.objects.filter(pk=course_id).first()
    if not selected_course and courses.exists():
        selected_course = courses.first()

    subjects = Subject.objects.none()
    if selected_course:
        subjects = selected_course.subjects.filter(session__isnull=True)

    if request.method == 'POST' and 'add_course' in request.POST:
        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، إضافة دورة جديدة محصورة بمسجل البيانات أو مدير النظام.')
            return redirect(request.path)

        course_form = CourseForm(request.POST)
        if course_form.is_valid():
            new_course = course_form.save(commit=False)
            if request.institute:
                new_course.institute = request.institute
            new_course.save()
            log_activity(
                request=request,
                action_type=ActivityAction.CREATE,
                action_category=ActivityCategory.COURSES,
                description=f"إضافة دورة تدريبية جديدة: {new_course.name} (رمز: {new_course.course_number}) بمواظبة {new_course.attendance_max_grade}",
                target_model="Course",
                target_id=new_course.id
            )
            messages.success(request, f'تم إضافة الدورة "{new_course.name}" (الرمز: {new_course.course_number}) بنجاح.')
            return redirect(f"{request.path}?category_id={new_course.category_id}&course_id={new_course.id}")
        else:
            for field, errors in course_form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        initial_cat = selected_category if selected_category else None
        course_form = CourseForm(initial={'category': initial_cat})

    if request.method == 'POST' and 'add_subject' in request.POST:
        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، إضافة مادة دراسية جديدة محصورة بمسجل البيانات أو مدير النظام.')
            return redirect(request.path)

        target_course_id = request.POST.get('target_course_id')
        target_course = get_object_or_404(Course, pk=target_course_id)
        subject_form = SubjectForm(request.POST)
        if subject_form.is_valid():
            new_subject = subject_form.save(commit=False)
            new_subject.course = target_course
            if not new_subject.code:
                new_subject.code = Subject.generate_unique_code(target_course)
            new_subject.save()
            log_activity(
                request=request,
                action_type=ActivityAction.CREATE,
                action_category=ActivityCategory.COURSES,
                description=f"إضافة مادة دراسية: {new_subject.name} (كود: {new_subject.code} - عظمى: {new_subject.max_grade}) لدورة {target_course.name}",
                target_model="Subject",
                target_id=new_subject.id
            )
            messages.success(request, f'تم إضافة المادة "{new_subject.name}" وتوليد كودها التلقائي ({new_subject.code}) بنجاح.')
            return redirect(f"{request.path}?category_id={target_course.category_id}&course_id={target_course.id}")
        else:
            for field, errors in subject_form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        subject_form = SubjectForm()

    context = {
        'categories': categories,
        'selected_category': selected_category,
        'courses': courses,
        'selected_course': selected_course,
        'subjects': subjects,
        'course_form': course_form,
        'subject_form': subject_form,
    }
    return render(request, 'training/courses_catalog.html', context)


@registrar_required
def course_edit_view(request, course_id):
    """تعديل دورة موجودة"""
    course = get_object_or_404(Course, pk=course_id)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.COURSES,
                description=f"تعديل بيانات الدورة التدريبية: {course.name} (رمز: {course.course_number})",
                target_model="Course",
                target_id=course.id
            )
            messages.success(request, f'تم تحديث بيانات الدورة "{course.name}" بنجاح.')
            return redirect(f"/courses/?category_id={course.category_id}&course_id={course.id}")
        else:
            messages.error(request, 'حدث خطأ في البيانات المدخلة.')
    else:
        form = CourseForm(instance=course)

    return render(request, 'training/course_edit.html', {
        'form': form,
        'course': course,
    })


@registrar_required
def course_delete_view(request, course_id):
    """حذف دورة مع حماية الانعقادات والشهادات التاريخية"""
    course = get_object_or_404(Course, pk=course_id)
    category_id = course.category_id
    has_sessions = course.sessions.exists()
    sessions_count = course.sessions.count()

    if request.method == 'POST':
        if has_sessions:
            messages.error(
                request,
                f'إجراء محظور: لا يمكن حذف الدورة "{course.name}" لوجود {sessions_count} انعقاد تدريبي مسجل لها في النظام! لحماية السجل الأكاديمي للدورات والشهادات، لا يمكن حذف الدورة.'
            )
            return redirect(f"/courses/?category_id={category_id}")
        try:
            name = course.name
            c_num = course.course_number
            cid = course.id
            course.delete()
            log_activity(
                request=request,
                action_type=ActivityAction.DELETE,
                action_category=ActivityCategory.COURSES,
                description=f"حذف الدورة التدريبية: {name} (رمز: {c_num})",
                target_model="Course",
                target_id=cid
            )
            messages.success(request, f'تم حذف الدورة "{name}" وجميع موادها بنجاح.')
        except ProtectedError:
            messages.error(request, f'تعذر حذف الدورة "{course.name}" لوجود سجلات أكاديمية مرتبطة بها.')
        return redirect(f"/courses/?category_id={category_id}")

    return render(request, 'training/course_confirm_delete.html', {
        'course': course,
        'has_sessions': has_sessions,
        'sessions_count': sessions_count,
    })


@registrar_required
def subject_edit_view(request, subject_id):
    """تعديل مادة دراسية"""
    subject = get_object_or_404(Subject, pk=subject_id)
    course = subject.course
    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.COURSES,
                description=f"تعديل مادة دراسية: {subject.name} (كود: {subject.code}) لدورة {course.name}",
                target_model="Subject",
                target_id=subject.id
            )
            messages.success(request, f'تم تحديث بيانات المادة "{subject.name}" بنجاح.')
            return redirect(f"/courses/?category_id={course.category_id}&course_id={course.id}")
        else:
            messages.error(request, 'حدث خطأ في تحديث المادة.')
    else:
        form = SubjectForm(instance=subject)

    return render(request, 'training/subject_edit.html', {
        'form': form,
        'subject': subject,
        'course': course,
    })


@registrar_required
def subject_delete_view(request, subject_id):
    """حذف مادة دراسية مع حماية درجات الدارسين المرصودة"""
    subject = get_object_or_404(Subject, pk=subject_id)
    course = subject.course
    has_grades = subject.trainee_grades.exists()
    grades_count = subject.trainee_grades.count()

    if request.method == 'POST':
        if has_grades:
            messages.error(
                request,
                f'إجراء محظور: لا يمكن حذف المادة "{subject.name}" لوجود {grades_count} درجة مرصودة لها مسبقاً في دورات منعقدة! لحماية السجل الأكاديمي للدارسين، لا يمكن حذف المواد التي تم رصد درجاتها.'
            )
            return redirect(f"/courses/?category_id={course.category_id}&course_id={course.id}")
        try:
            name = subject.name
            sid = subject.id
            cname = course.name
            subject.delete()
            log_activity(
                request=request,
                action_type=ActivityAction.DELETE,
                action_category=ActivityCategory.COURSES,
                description=f"حذف مادة دراسية: {name} من دورة {cname}",
                target_model="Subject",
                target_id=sid
            )
            messages.success(request, f'تم حذف المادة "{name}" بنجاح.')
        except ProtectedError:
            messages.error(request, f'تعذر حذف المادة "{subject.name}" لوجود درجات مسجلة لها.')
        return redirect(f"/courses/?category_id={course.category_id}&course_id={course.id}")

    return render(request, 'training/subject_confirm_delete.html', {
        'subject': subject,
        'course': course,
        'has_grades': has_grades,
        'grades_count': grades_count,
    })


# ==========================================
# القسم 4: الدورات المنعقدة (انعقاد الدورات وربط الطلبة)
# ==========================================
@login_required
def course_sessions_view(request):
    """عرض قائمة الدورات المنعقدة حالياً مع إحصائيات وروابط الإدارة وفلتر السنوات"""
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        messages.warning(request, 'حسابك مخصص لمعلم / هيئة التدريس، وصلاحياتك محصورة في صفحة رصد نتائج المواد المكلف بها فقط.')
        return redirect('training:results_center')

    from datetime import datetime
    sessions = CourseSession.objects.select_related('course', 'course__category').prefetch_related('enrollments').all()
    if request.institute:
        sessions = sessions.filter(Q(institute=request.institute) | Q(institute__isnull=True))
    categories = CourseCategory.objects.all()
    if request.institute:
        categories = categories.filter(Q(institute=request.institute) | Q(institute__isnull=True))

    db_years = set(d.year for d in CourseSession.objects.dates('start_date', 'year'))
    db_years.update(d.year for d in CourseSession.objects.dates('end_date', 'year'))
    current_year = datetime.now().year
    for y in range(current_year - 5, current_year + 2):
        db_years.add(y)
    available_years = sorted(list(db_years), reverse=True)

    return render(request, 'training/course_sessions.html', {
        'sessions': sessions,
        'categories': categories,
        'available_years': available_years,
    })


def calculate_next_course_session_code(course, start_date=None, target_category=None):
    """
    احتساب رقم الدفعة التالي تلقائياً وفق القواعد:
    1. ترقيم مستقل لكل فئة من فئات الدارسين (الضباط لهم تسلسل مستقل، وضباط الصف لهم تسلسل مستقل، والدورات المشتركة لها تسلسل مستقل).
    2. دورات المرشد: ترقيم تراكمي مستمر لا يتكرر أبداً ولا يتصفر بالسنة (أعلى رقم دفعة سابق لنفس الدورة ونفس الفئة + 1).
    3. الدورات الخاصة: ترقيم يتكرر سنوياً، بحيث تبدأ الدفعة في كل بداية سنة من الرقم 1 لنفس الفئة (أعلى رقم دفعة في تلك السنة لنفس الفئة + 1).
    """
    import re
    from datetime import date
    if not course:
        return '1'

    # التحقق من تصنيف الدورة (دورات خاصة مقابل دورات مرشد)
    is_special = False
    if course.category and 'خاص' in course.category.name:
        is_special = True

    if is_special:
        target_year = None
        if start_date:
            if hasattr(start_date, 'year'):
                target_year = start_date.year
            elif isinstance(start_date, str) and start_date.strip():
                try:
                    parts = start_date.strip().split('-')
                    if len(parts) >= 1 and len(parts[0]) == 4:
                        target_year = int(parts[0])
                    else:
                        from django.utils.dateparse import parse_date
                        parsed = parse_date(start_date.strip())
                        if parsed:
                            target_year = parsed.year
                except Exception:
                    pass
        if not target_year:
            target_year = date.today().year

        sessions = CourseSession.objects.filter(course=course, start_date__year=target_year)
    else:
        # دورات المرشد لا تتكرر: ترقيم مستمر لا يعاد تصفيره بحسب السنة
        sessions = CourseSession.objects.filter(course=course)

    if target_category:
        sessions = sessions.filter(target_category=target_category)

    max_num = 0
    for s in sessions:
        if s.session_code:
            numbers = re.findall(r'\d+', str(s.session_code))
            for n in numbers:
                try:
                    val = int(n)
                    if val > max_num:
                        max_num = val
                except ValueError:
                    pass

    return str(max_num + 1)


@login_required
def api_get_next_course_number_view(request):
    """إرجاع رقم الدفعة التالي تلقائياً بناءً على الدورة وتاريخ الانعقاد وفئة الدارسين المستهدفة"""
    course_id = request.GET.get('course_id')
    start_date_str = request.GET.get('start_date')
    target_category = request.GET.get('target_category', 'officer').strip()
    if not course_id:
        return JsonResponse({'success': False, 'error': 'course_id مطلوب'})

    course = get_object_or_404(Course.objects.select_related('category'), pk=course_id)
    next_number = calculate_next_course_session_code(course, start_date_str, target_category=target_category)
    is_special = bool(course.category and 'خاص' in course.category.name)

    cat_display_map = {
        'officer': 'ضباط',
        'nco': 'ضباط صف',
        'joint': 'مشتركة',
        'civilian': 'مدنيين',
    }

    return JsonResponse({
        'success': True,
        'next_number': next_number,
        'is_special': is_special,
        'target_category': target_category,
        'target_category_display': cat_display_map.get(target_category, 'ضباط'),
        'category_name': course.category.name if course.category else '',
        'course_name': course.name,
    })


@login_required
def api_add_course_subject_view(request):
    """
    إضافة مادة دراسية جديدة لدورة تدريبية عبر نافذة سريعة (AJAX)
    متاحة لمسجل البيانات ومدير النظام.
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'طريقة الطلب غير مسموح بها.'}, status=405)

    if not (is_registrar_user(request.user) or is_admin_user(request.user)):
        return JsonResponse({
            'success': False,
            'message': 'عفواً، إضافة مواد دراسية جديدة محصورة بمسجل البيانات أو مدير النظام.'
        }, status=403)

    course_id = request.POST.get('course_id') or request.GET.get('course_id')
    name = (request.POST.get('name') or '').strip()
    credit_hours_raw = request.POST.get('credit_hours', '10')
    max_grade_raw = request.POST.get('max_grade', '100')
    code = (request.POST.get('code') or '').strip()
    session_id = request.POST.get('session_id')

    target_session = None
    if session_id:
        try:
            target_session = CourseSession.objects.select_related('course').get(pk=session_id)
            course = target_session.course
        except CourseSession.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'الدورة المنعقدة المحددة غير موجودة.'}, status=404)
    else:
        if not course_id:
            return JsonResponse({'success': False, 'message': 'يرجى تحديد الدورة التدريبية أولاً.'}, status=400)
        try:
            course = Course.objects.get(pk=course_id)
        except Course.DoesNotExist:
            return JsonResponse({'success': False, 'message': 'الدورة التدريبية المحددة غير موجودة.'}, status=404)

    if not name:
        return JsonResponse({'success': False, 'message': 'يرجى إدخال اسم المادة الدراسية.'}, status=400)

    # التحقق من عدم التكرار:
    if target_session:
        # فحص عدم تكرار المادة في هذه الدورة المنعقدة بالتحديد
        already_in_session = (
            target_session.subject_instructors.filter(subject__name__iexact=name).exists() or
            Subject.objects.filter(course=course, session=target_session, name__iexact=name).exists() or
            Subject.objects.filter(course=course, session__isnull=True, name__iexact=name).exists()
        )
        if already_in_session:
            return JsonResponse({'success': False, 'message': f'المادة "{name}" مضافة مسبقاً في هذه الدورة المنعقدة (رقم: {target_session.session_code}).'}, status=400)
    else:
        # فحص عدم تكرار المادة في الدورة التدريبية
        if Subject.objects.filter(course=course, name__iexact=name).exists():
            return JsonResponse({'success': False, 'message': f'المادة "{name}" مضافة مسبقاً في هذه الدورة.'}, status=400)

    try:
        credit_hours = int(credit_hours_raw)
        if credit_hours < 0:
            credit_hours = 0
    except (ValueError, TypeError):
        credit_hours = 10

    try:
        max_grade = float(max_grade_raw)
        if max_grade <= 0:
            max_grade = 100.0
    except (ValueError, TypeError):
        max_grade = 100.0

    if not code:
        code = Subject.generate_unique_code(course, session=target_session)

    # إنشاء المادة: إذا حُددت دورة منعقدة تُحفظ المادة حصرياً لها دون أن تظهر في أي دورة أخرى
    subject = Subject.objects.create(
        course=course,
        session=target_session,
        name=name,
        code=code,
        credit_hours=credit_hours,
        max_grade=max_grade
    )

    if target_session:
        SessionSubjectInstructor.objects.create(
            session=target_session,
            subject=subject,
            instructor=None
        )

    log_desc = f"إضافة مادة دراسية خاصة بالدورة المنعقدة {target_session.session_code}: {subject.name} (كود: {subject.code})" if target_session else f"إضافة مادة دراسية عامة: {subject.name} (كود: {subject.code}) لدورة {course.name}"
    log_activity(
        request=request,
        action_type=ActivityAction.CREATE,
        action_category=ActivityCategory.COURSES,
        description=log_desc,
        target_model="Subject",
        target_id=subject.id
    )

    msg = f'تمت إضافة مادة "{subject.name}" بنجاح خاصة بالدورة رقم ({target_session.session_code}) فقط ولن تظهر في أي دورة أخرى.' if target_session else f'تمت إضافة مادة "{subject.name}" بنجاح وتوليد كودها التلقائي ({subject.code}).'

    return JsonResponse({
        'success': True,
        'message': msg,
        'subject': {
            'id': subject.id,
            'code': subject.code,
            'name': subject.name,
            'credit_hours': subject.credit_hours,
            'max_grade': float(subject.max_grade),
        }
    })


@registrar_required
def course_session_create_view(request):
    """
    إنشاء انعقاد دورة جديدة وربط الطلبة بالدورة:
    - اختيار تصنيف الدورة واسم الدورة وتاريخها.
    - اختيار الطلبة الدارسين مع إمكانية تعديل الرتبة والوحدة وقت الدورة.
    - حفظ الانعقاد والطلبة.
    """
    categories = CourseCategory.objects.prefetch_related('courses__subjects').all()
    if request.institute:
        categories = categories.filter(Q(institute=request.institute) | Q(institute__isnull=True))
    trainees = Trainee.objects.all().order_by('category', 'name')
    instructors = Instructor.objects.filter(is_active=True).order_by('name')
    if request.institute:
        instructors = instructors.filter(Q(institute=request.institute) | Q(institute__isnull=True))

    if request.method == 'POST':
        course_id = request.POST.get('course')
        target_category = request.POST.get('target_category', 'officer').strip() or 'officer'
        session_code = request.POST.get('session_code', '').strip()
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')

        # توليد رقم الدفعة تلقائياً إذا تُرك الحقل فارغاً
        if not session_code and course_id:
            try:
                c_obj = Course.objects.select_related('category').get(pk=course_id)
                session_code = calculate_next_course_session_code(c_obj, start_date, target_category=target_category)
            except Course.DoesNotExist:
                pass

        movement_order_date = request.POST.get('movement_order_date', '').strip()
        movement_order_file = request.FILES.get('movement_order_file')
        status = request.POST.get('status', 'active')
        attendance_raw = request.POST.get('attendance_max_grade', '').strip()
        attendance_max_grade = attendance_raw if attendance_raw else None
        notes = request.POST.get('notes', '').strip()
        supervisor_num = request.POST.get('supervisor', '').strip()

        selected_trainee_nums = request.POST.getlist('selected_trainees')

        missing_movement = []
        for num in selected_trainee_nums:
            m_date = request.POST.get(f'movement_order_date_{num}', '').strip()
            m_file = request.FILES.get(f'movement_order_file_{num}')
            if not m_date or not m_file:
                t_obj = Trainee.objects.filter(military_number=num).first()
                missing_movement.append(f'"{t_obj.name}" ({num})' if t_obj else num)

        if not course_id or not session_code or not start_date or not end_date:
            messages.error(request, 'يرجى استكمال جميع بيانات الدورة الأساسية (الدورة، فئة الدارسين، رقم الدفعة، وتاريخ البداية والنهاية).')
        elif not selected_trainee_nums:
            messages.error(request, 'يرجى اختيار دارس واحد على الأقل للالتحاق بهذه الدورة.')
        elif missing_movement:
            names_str = '، '.join(missing_movement[:4])
            if len(missing_movement) > 4:
                names_str += f' وغيرهم (إجمالي {len(missing_movement)} دارس)'
            messages.error(request, f'قيد إلزامي: لا يمكن حفظ الدورة؛ نظراً لعدم استكمال تاريخ أمر التحرك أو إرفاق صورة scan لأمر التحرك للدارس(ين): {names_str}. يرجى استكمال بيانات أمر التحرك لكل دارس تم تحديده.')
        else:
            course = get_object_or_404(Course, pk=course_id)

            # التحقق من ملاءمة تصنيف الدارسين المختارين لتصنيف فئة الدورة المحددة
            cat_mismatch = []
            if target_category == 'officer':
                for num in selected_trainee_nums:
                    t = Trainee.objects.filter(military_number=num).first()
                    if t and t.category != 'officer':
                        cat_mismatch.append(f'"{t.name}" ({t.get_category_display()})')
            elif target_category == 'nco':
                for num in selected_trainee_nums:
                    t = Trainee.objects.filter(military_number=num).first()
                    if t and t.category == 'officer':
                        cat_mismatch.append(f'"{t.name}" (ضابط)')

            if cat_mismatch:
                mismatch_str = '، '.join(cat_mismatch[:3])
                cat_label = 'ضباط' if target_category == 'officer' else 'ضباط صف'
                messages.error(
                    request,
                    f'قيد فئة الدورة: تم تحديد الدورة لفئة ({cat_label}) فقط، بينما تم اختيار دارسين لا يتبعون هذه الفئة: {mismatch_str}. يرجى حصر الاختيار على الدارسين التابعين للفئة المحددة.'
                )
            else:
                # التحقق الصارم من قيد النجاح المسبق: منع إعادة تسجيل أي دارس أكمل نفس الدورة ونجح فيها
                blocked_trainees = []
                for num in selected_trainee_nums:
                    t = Trainee.objects.filter(military_number=num).first()
                    if t:
                        prev_passed = has_trainee_passed_course(t, course)
                        if prev_passed:
                            blocked_trainees.append((t, prev_passed))

                if blocked_trainees:
                    msg_list = "، ".join([f'"{bt[0].name}" (دفعة {bt[1].session.session_code} - تقدير {bt[1].grade_label})' for bt in blocked_trainees])
                    messages.error(
                        request,
                        f'تحذير صارم: لا يمكن إتمام تسجيل الدورة؛ نظراً لأن الدارس(ين): {msg_list} قد أكملوا دورة "{course.name}" واجتازوها بنجاح مسبقاً، ويمنع النظام تكرار دخول نفس الدورة مرة أخرى!'
                    )
                else:
                    supervisor = Instructor.objects.filter(military_number=supervisor_num).first() if supervisor_num else None

                    session = CourseSession.objects.create(
                        institute=request.institute or (course.institute if course else None),
                        course=course,
                        target_category=target_category,
                        session_code=session_code,
                        start_date=start_date,
                        end_date=end_date,
                        movement_order_date=movement_order_date if movement_order_date else None,
                        movement_order_file=movement_order_file if movement_order_file else None,
                        status=status,
                        attendance_max_grade=attendance_max_grade if attendance_max_grade is not None else course.attendance_max_grade,
                        supervisor=supervisor,
                        notes=notes
                    )

                # تعيين المعلمين لمواد الدورة العامة
                for sub in course.subjects.filter(session__isnull=True):
                    teacher_num = request.POST.get(f'subject_teacher_{sub.id}', '').strip()
                    inst = Instructor.objects.filter(military_number=teacher_num).first() if teacher_num else None
                    SessionSubjectInstructor.objects.create(
                        session=session,
                        subject=sub,
                        instructor=inst
                    )

                # تسجيل الطلبة مع حفظ الرتبة والقوة والوحدة المحدثة وقت الدورة
                enrolled_count = 0
                for num in selected_trainee_nums:
                    try:
                        t = Trainee.objects.get(military_number=num)
                        # قراءة الرتبة والقوة والوحدة وأمر التحرك المعدلة من النموذج
                        current_rank = request.POST.get(f'rank_{num}', '').strip()
                        current_force = request.POST.get(f'force_{num}', t.force).strip() or t.force
                        current_unit = request.POST.get(f'unit_{num}', t.unit).strip() or t.unit
                        m_date = request.POST.get(f'movement_order_date_{num}', '').strip()
                        m_file = request.FILES.get(f'movement_order_file_{num}')

                        CourseEnrollment.objects.create(
                            session=session,
                            trainee=t,
                            current_rank=current_rank,
                            current_force=current_force,
                            current_unit=current_unit,
                            movement_order_date=m_date if m_date else None,
                            movement_order_file=m_file if m_file else None
                        )
                        
                        has_changes = False
                        if current_force and current_force != t.force:
                            t.force = current_force
                            has_changes = True
                        if current_unit and current_unit != t.unit:
                            t.unit = current_unit
                            has_changes = True
                        if has_changes:
                            t.save(update_fields=['force', 'unit'])
                        enrolled_count += 1
                    except Trainee.DoesNotExist:
                        pass

                log_activity(
                    request=request,
                    action_type=ActivityAction.CREATE,
                    action_category=ActivityCategory.SESSIONS,
                    description=f"إنشاء انعقاد دورة جديدة: {session.session_code} لدورة '{course.name}' وتسجيل {enrolled_count} دارس بها",
                    target_model="CourseSession",
                    target_id=session.id
                )

                messages.success(request, f'تم حفظ انعقاد دورة "{course.name}" بنجاح، وتعيين مشرف الدورة ومعلمي المواد، وتسجيل {enrolled_count} دارس بها.')
                return redirect('training:course_session_manage', session_id=session.id)

    officer_count = trainees.filter(category=TraineeCategory.OFFICER).count()
    nco_count = trainees.filter(category=TraineeCategory.NCO).count()
    civilian_count = trainees.filter(category=TraineeCategory.CIVILIAN).count()

    # خريطة الدارسين والدورات التي اجتازوها بنجاح مسبقاً لمنع تكرار التسجيل
    passed_enrollments = CourseEnrollment.objects.filter(
        is_graded=True,
        percentage__gte=50.0
    ).exclude(grade_label__icontains='راسب').select_related('session', 'session__course')

    trainees_passed_map = {}
    for pe in passed_enrollments:
        tid = pe.trainee_id
        cid = str(pe.session.course_id)
        if tid not in trainees_passed_map:
            trainees_passed_map[tid] = {}
        trainees_passed_map[tid][cid] = {
            'batch': pe.session.session_code,
            'grade': pe.grade_label,
            'pct': float(pe.percentage or 0.0)
        }

    courses_subjects_map = {}
    for cat in categories:
        for c in cat.courses.all():
            courses_subjects_map[str(c.id)] = [
                {
                    'id': s.id,
                    'code': s.code,
                    'name': s.name,
                    'credit_hours': s.credit_hours,
                    'max_grade': float(s.max_grade),
                }
                for s in c.subjects.filter(session__isnull=True)
            ]

    # خريطة أرقام الدفعات التلقائية التالية لكل دورة وفئة وفق قواعد الترقيم المعتمدة
    courses_next_numbers_map = {}
    for cat in categories:
        for c in cat.courses.all():
            courses_next_numbers_map[str(c.id)] = {
                'officer': calculate_next_course_session_code(c, date.today(), 'officer'),
                'nco': calculate_next_course_session_code(c, date.today(), 'nco'),
                'joint': calculate_next_course_session_code(c, date.today(), 'joint'),
                'civilian': calculate_next_course_session_code(c, date.today(), 'civilian'),
                'next_number': calculate_next_course_session_code(c, date.today(), 'officer'),
                'is_special': bool(c.category and 'خاص' in c.category.name),
                'category_name': c.category.name if c.category else '',
            }

    return render(request, 'training/course_session_create.html', {
        'categories': categories,
        'trainees': trainees,
        'instructors': instructors,
        'courses_subjects_json': json.dumps(courses_subjects_map, ensure_ascii=False),
        'trainees_passed_json': json.dumps(trainees_passed_map, ensure_ascii=False),
        'courses_next_numbers_json': json.dumps(courses_next_numbers_map, ensure_ascii=False),
        'officer_count': officer_count,
        'nco_count': nco_count,
        'civilian_count': civilian_count,
    })


@login_required
def course_session_manage_view(request, session_id):
    """
    إدارة وتعديل الدارسين في دورة منعقدة:
    - تعديل الرتبة والقوة والوحدة للدارسين في الدورة.
    - تحديث المشرف ومعلمي المواد.
    - إضافة دارسين جدد للدورة.
    - إزالة دارس من الدورة.
    """
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        messages.warning(request, 'حسابك مخصص لمعلم / هيئة التدريس، وصلاحياتك محصورة في صفحة رصد نتائج المواد المكلف بها فقط.')
        return redirect('training:results_center')

    session = get_object_or_404(CourseSession.objects.select_related('course', 'course__category', 'supervisor'), pk=session_id)
    enrollments = session.enrollments.select_related('trainee').all()
    instructors = Instructor.objects.filter(is_active=True).order_by('name')

    # تحديث مشرف الدورة ومعلمي المواد
    if request.method == 'POST' and 'update_session_teachers' in request.POST:
        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، تعديل المشرف والمعلمين محصور بمسجل البيانات أو مدير النظام.')
            return redirect('training:course_session_manage', session_id=session.id)
        new_sup_num = request.POST.get('supervisor', '').strip()
        session.supervisor = Instructor.objects.filter(military_number=new_sup_num).first() if new_sup_num else None
        session.save(update_fields=['supervisor'])

        # تحديث المواد المسندة أو إنشاؤها إن لم تكن مسندة بعد
        session_subjects = session.get_subjects()
        for sub in session_subjects:
            t_num = request.POST.get(f'subject_teacher_{sub.id}', '').strip()
            inst = Instructor.objects.filter(military_number=t_num).first() if t_num else None
            SessionSubjectInstructor.objects.update_or_create(
                session=session,
                subject=sub,
                defaults={'instructor': inst}
            )
        messages.success(request, 'تم حفظ وتحديث بيانات مشرف الدورة ومعلمي المواد الدراسية بنجاح.')
        return redirect('training:course_session_manage', session_id=session.id)

    # إزالة مادة من هذه الدورة المنعقدة بالتحديد
    if request.method == 'POST' and 'remove_session_subject_id' in request.POST:
        if not is_registrar_user(request.user) and not is_admin_user(request.user):
            messages.error(request, 'عفواً، إزالة المواد من الدورة محصورة بمسجل البيانات أو مدير النظام.')
            return redirect('training:course_session_manage', session_id=session.id)
        
        target_sub_id = request.POST.get('remove_session_subject_id')
        ssi = get_object_or_404(SessionSubjectInstructor, session=session, subject_id=target_sub_id)
        sub = ssi.subject

        # التحقق من عدم وجود درجات مرصودة لهذه المادة في هذه الدورة
        has_grades = TraineeSubjectGrade.objects.filter(
            enrollment__session=session,
            subject=sub,
            score__isnull=False
        ).exists()
        if has_grades:
            messages.error(request, f'تعذر إزالة مادة "{sub.name}" من هذه الدورة لوجود درجات مرصودة بالفعل لدارسي الدورة بها.')
            return redirect('training:course_session_manage', session_id=session.id)

        sub_name = sub.name
        ssi.delete()
        if sub.session_id == session.id:
            sub.delete()

        log_activity(
            request=request,
            action_type=ActivityAction.DELETE,
            action_category=ActivityCategory.COURSES,
            description=f"إزالة مادة '{sub_name}' من الدورة المنعقدة {session.session_code}",
            target_model="SessionSubjectInstructor",
            target_id=str(session.id)
        )
        messages.success(request, f'تم إزالة مادة "{sub_name}" من هذه الدورة المنعقدة بنجاح دون التأثير على أي دورات أخرى.')
        return redirect('training:course_session_manage', session_id=session.id)

    # تحديث الرتب والقوة والوحدات للدارسين المسجلين
    if request.method == 'POST' and 'update_enrollments' in request.POST:
        updated_count = 0
        for enrollment in enrollments:
            num = enrollment.trainee.military_number
            new_rank = request.POST.get(f'rank_{num}', '').strip()
            new_force = request.POST.get(f'force_{num}', '').strip()
            new_unit = request.POST.get(f'unit_{num}', '').strip()
            new_mov_date = request.POST.get(f'movement_order_date_{num}', '').strip()
            new_mov_file = request.FILES.get(f'movement_order_file_{num}')
            
            t = enrollment.trainee
            t_changed = False

            if new_rank:
                enrollment.current_rank = new_rank
            if new_force:
                enrollment.current_force = new_force
                if t.force != new_force:
                    t.force = new_force
                    t_changed = True
            if new_unit:
                enrollment.current_unit = new_unit
                if t.unit != new_unit:
                    t.unit = new_unit
                    t_changed = True
            if new_mov_date:
                enrollment.movement_order_date = new_mov_date
            if new_mov_file:
                enrollment.movement_order_file = new_mov_file

            if new_rank or new_force or new_unit or new_mov_date or new_mov_file:
                enrollment.save()
                if t_changed:
                    t.save(update_fields=['force', 'unit'])
                updated_count += 1

        messages.success(request, f'تم حفظ وتحديث بيانات الرتب والقوة والوحدات وأوامر التحرك لـ {updated_count} دارس بالدورة بنجاح.')
        return redirect('training:course_session_manage', session_id=session.id)

    # إضافة دارسين إضافيين للدورة
    if request.method == 'POST' and 'add_extra_trainees' in request.POST:
        extra_nums = request.POST.getlist('extra_trainees')
        added = 0
        for num in extra_nums:
            t = Trainee.objects.filter(military_number=num).first()
            if t:
                # التحقق الصارم من أن الطالب لم يجتز هذه الدورة مسبقاً بنجاح
                prev_passed = has_trainee_passed_course(t, session.course)
                if prev_passed:
                    messages.error(
                        request,
                        f'تحذير: لا يمكن إلحاق الدارس "{t.name}" ({t.military_number})؛ نظراً لأنه قد أكمل دورة "{session.course.name}" واجتازها بنجاح مسبقاً (دفعة: {prev_passed.session.session_code} - تقدير: {prev_passed.grade_label})!'
                    )
                    continue

                if not session.enrollments.filter(trainee=t).exists():
                    r = request.POST.get(f'extra_rank_{num}', '').strip()
                    f = request.POST.get(f'extra_force_{num}', t.force).strip() or t.force
                    u = request.POST.get(f'extra_unit_{num}', t.unit).strip() or t.unit
                    m_date = request.POST.get(f'extra_movement_order_date_{num}', '').strip()
                    m_file = request.FILES.get(f'extra_movement_order_file_{num}')
                    CourseEnrollment.objects.create(
                        session=session,
                        trainee=t,
                        current_rank=r,
                        current_force=f,
                        current_unit=u,
                        movement_order_date=m_date if m_date else None,
                        movement_order_file=m_file if m_file else None
                    )
                    has_changes = False
                    if f and f != t.force:
                        t.force = f
                        has_changes = True
                    if u and u != t.unit:
                        t.unit = u
                        has_changes = True
                    if has_changes:
                        t.save(update_fields=['force', 'unit'])
                    added += 1
        if added > 0:
            messages.success(request, f'تم إلحاق {added} دارس إضافي بالدورة بنجاح.')
        return redirect('training:course_session_manage', session_id=session.id)

    # تسجيل دارس جديد وحفظه في قاعدة البيانات وإلحاقه بالدورة
    if request.method == 'POST' and 'register_and_enroll_new_trainee' in request.POST:
        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، تسجيل وإضافة دارس جديد محصورة بمسجل البيانات أو مدير النظام.')
            return redirect('training:course_session_manage', session_id=session.id)

        trainee_form = TraineeForm(request.POST)
        if trainee_form.is_valid():
            military_num = trainee_form.cleaned_data['military_number']
            if Trainee.objects.filter(military_number=military_num).exists():
                messages.error(request, f'النمرة "{military_num}" مسجلة مسبقاً لدارس آخر! الرجاء استخدام نمرة فريدة.')
            elif Instructor.objects.filter(military_number=military_num).exists():
                messages.error(request, f'النمرة العسكرية "{military_num}" مسجلة مسبقاً في النظام كمعلم في هيئة التدريس! لا يجوز تكرار النمرة العسكرية بين الدارسين والمعلمين.')
            else:
                new_trainee = trainee_form.save(commit=False)
                new_rank = request.POST.get('new_rank', '').strip()
                new_force = request.POST.get('new_force', '').strip()
                new_unit = request.POST.get('new_unit', '').strip()
                mov_date = request.POST.get('new_movement_order_date', '').strip()
                mov_file = request.FILES.get('new_movement_order_file')
                enroll_now = request.POST.get('enroll_in_session') == '1'

                if new_force:
                    new_trainee.force = new_force
                if new_unit:
                    new_trainee.unit = new_unit
                new_trainee.save()
                trainee_form.save_relatives(new_trainee)

                log_activity(
                    request=request,
                    action_type=ActivityAction.CREATE,
                    action_category=ActivityCategory.TRAINEES,
                    description=f"إضافة دارس جديد وحفظه بقاعدة البيانات: {new_trainee.name} (نمرة: {military_num})",
                    target_model="Trainee",
                    target_id=military_num
                )

                if enroll_now:
                    CourseEnrollment.objects.create(
                        session=session,
                        trainee=new_trainee,
                        current_rank=new_rank,
                        current_force=new_force or new_trainee.force,
                        current_unit=new_unit or new_trainee.unit,
                        movement_order_date=mov_date if mov_date else None,
                        movement_order_file=mov_file if mov_file else None
                    )
                    log_activity(
                        request=request,
                        action_type=ActivityAction.CREATE,
                        action_category=ActivityCategory.SESSIONS,
                        description=f"إلحاق الدارس {new_trainee.name} بالدورة {session.session_code}",
                        target_model="CourseEnrollment",
                        target_id=str(session.id)
                    )
                    messages.success(request, f'تم تسجيل بيانات الدارس "{new_trainee.name}" في قاعدة البيانات وإلحاقه بالدورة بنجاح.')
                else:
                    messages.success(request, f'تم حفظ بيانات الدارس "{new_trainee.name}" في قاعدة البيانات بنجاح.')

                return redirect('training:course_session_manage', session_id=session.id)
        else:
            for field, errors in trainee_form.errors.items():
                for error in errors:
                    messages.error(request, error)
            return redirect('training:course_session_manage', session_id=session.id)

    # معالجة قطع الدورة عن الدارس
    if request.method == 'POST' and ('drop_trainee' in request.POST or request.POST.get('action') == 'drop_trainee'):
        if not is_registrar_user(request.user) and not is_admin_user(request.user):
            messages.error(request, 'عفواً، قطع الدورة عن الدارس محصور بالمسجل أو مدير النظام.')
            return redirect('training:course_session_manage', session_id=session.id)
        enrollment_id = request.POST.get('enrollment_id')
        enrollment = get_object_or_404(CourseEnrollment, pk=enrollment_id, session=session)
        reason = request.POST.get('drop_reason', '').strip()
        enrollment.is_dropped = True
        enrollment.drop_reason = reason
        enrollment.dropped_at = timezone.now()
        enrollment.save(update_fields=['is_dropped', 'drop_reason', 'dropped_at'])
        log_activity(
            request=request,
            action_type=ActivityAction.UPDATE,
            action_category=ActivityCategory.SESSIONS,
            description=f"قطع الدورة عن الدارس {enrollment.trainee.name} ({enrollment.trainee.military_number}) في دورة {session.course.name} ({session.session_code})",
            target_model="CourseEnrollment",
            target_id=str(enrollment.id)
        )
        messages.success(request, f'تم قطع الدورة عن الدارس "{enrollment.trainee.name}" بنجاح، وتم منعه من الدخول إلى الدورة وحجب نتيجته وتفاصيله.')
        return redirect('training:course_session_manage', session_id=session.id)

    # معالجة إلغاء قطع الدورة (إعادة تفعيل الدارس في الدورة)
    if request.method == 'POST' and ('restore_trainee' in request.POST or request.POST.get('action') == 'restore_trainee'):
        if not is_registrar_user(request.user) and not is_admin_user(request.user):
            messages.error(request, 'عفواً، إعادة تفعيل الدارس محصورة بالمسجل أو مدير النظام.')
            return redirect('training:course_session_manage', session_id=session.id)
        enrollment_id = request.POST.get('enrollment_id')
        enrollment = get_object_or_404(CourseEnrollment, pk=enrollment_id, session=session)
        enrollment.is_dropped = False
        enrollment.drop_reason = ''
        enrollment.dropped_at = None
        enrollment.save(update_fields=['is_dropped', 'drop_reason', 'dropped_at'])
        log_activity(
            request=request,
            action_type=ActivityAction.UPDATE,
            action_category=ActivityCategory.SESSIONS,
            description=f"إلغاء قطع الدورة وإعادة تفعيل الدارس {enrollment.trainee.name} في دورة {session.course.name}",
            target_model="CourseEnrollment",
            target_id=str(enrollment.id)
        )
        messages.success(request, f'تم إلغاء قطع الدورة وإعادة تفعيل الدارس "{enrollment.trainee.name}" في الدورة بنجاح.')
        return redirect('training:course_session_manage', session_id=session.id)

    # إزالة دارس من الدورة
    if request.method == 'POST' and 'remove_trainee_id' in request.POST:
        if not is_admin_user(request.user):
            messages.error(request, 'إجراء محظور: إزالة الدارسين من الدورات محصورة بمدير النظام (Admin) فقط.')
            return redirect('training:course_session_manage', session_id=session.id)
        enrollment_id = request.POST.get('remove_trainee_id')
        enrollment = get_object_or_404(CourseEnrollment, pk=enrollment_id, session=session)
        if enrollment.is_graded:
            messages.error(request, f'تعذر إزالة الدارس "{enrollment.trainee.name}" نظراً لوجود نتائج معتمدة مرصودة له بهذه الدورة.')
            return redirect('training:course_session_manage', session_id=session.id)
        t_name = enrollment.trainee.name
        enrollment.delete()
        messages.success(request, f'تم إزالة الدارس "{t_name}" من الدورة.')
        return redirect('training:course_session_manage', session_id=session.id)

    # قائمة الدارسين غير المسجلين في هذه الدورة لإمكانية إضافتهم مع مراعاة فئة الدورة المستهدفة
    enrolled_trainee_ids = enrollments.values_list('trainee_id', flat=True)
    available_trainees = Trainee.objects.exclude(military_number__in=enrolled_trainee_ids)
    if session.target_category == 'officer':
        available_trainees = available_trainees.filter(category='officer')
    elif session.target_category == 'nco':
        available_trainees = available_trainees.filter(category__in=['nco', 'civilian'])
    elif session.target_category == 'civilian':
        available_trainees = available_trainees.filter(category='civilian')

    # تحديد الدارسين الذين اجتازوا هذه الدورة بنجاح مسبقاً
    passed_for_session = CourseEnrollment.objects.filter(
        session__course=session.course,
        is_graded=True,
        percentage__gte=50.0
    ).exclude(grade_label__icontains='راسب').select_related('session')

    passed_trainees_for_session = {
        pe.trainee_id: {
            'batch': pe.session.session_code,
            'grade': pe.grade_label
        }
        for pe in passed_for_session
    }

    instructors = Instructor.objects.filter(is_active=True).order_by('name')
    session_subject_instructors = list(session.subject_instructors.select_related('subject', 'instructor').all())
    # إذا كانت دورة منعقدة جديدة تماماً ولم تُعيّن لها مواد بعد ولم تكن دورة مرصودة النتائج:
    # نقوم بتهيئة موادها المبدئية من المواد العامة للمقرر فقط
    if not session_subject_instructors and not session.enrollments.filter(is_graded=True).exists():
        initial_subjects = session.course.subjects.filter(session__isnull=True)
        for sub in initial_subjects:
            assign = SessionSubjectInstructor.objects.create(session=session, subject=sub, instructor=None)
            session_subject_instructors.append(assign)

    context = {
        'session': session,
        'enrollments': enrollments,
        'available_trainees': available_trainees,
        'instructors': instructors,
        'session_subject_instructors': session_subject_instructors,
        'passed_trainees_for_session': passed_trainees_for_session,
        'trainee_form': TraineeForm(),
        'is_registrar': is_registrar_user(request.user) or is_admin_user(request.user),
    }
    return render(request, 'training/course_session_manage.html', context)


@registrar_required
def course_session_edit_view(request, session_id):
    """تعديل بيانات انعقاد الدورة (التواريخ، الحالة، الملاحظات)"""
    session = get_object_or_404(CourseSession, pk=session_id)
    if request.method == 'POST':
        form = CourseSessionForm(request.POST, request.FILES, instance=session)
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.SESSIONS,
                description=f"تعديل بيانات انعقاد الدورة: {session.session_code} لدورة '{session.course.name}'",
                target_model="CourseSession",
                target_id=session.id
            )
            messages.success(request, f'تم تحديث بيانات الدورة المنعقدة بنجاح.')
            return redirect('training:course_sessions')
        else:
            messages.error(request, 'حدث خطأ في تحديث البيانات.')
    else:
        form = CourseSessionForm(instance=session)

    return render(request, 'training/course_session_edit.html', {
        'form': form,
        'session': session,
    })


@registrar_required
def course_session_delete_view(request, session_id):
    """حذف انعقاد دورة مع حماية تسجيلات ونتائج الدارسين"""
    session = get_object_or_404(CourseSession, pk=session_id)
    has_enrollments = session.enrollments.exists()
    enrollments_count = session.enrollments.count()
    has_graded = session.enrollments.filter(is_graded=True).exists()

    if request.method == 'POST':
        if has_graded:
            messages.error(
                request,
                f'إجراء محظور: لا يمكن حذف انعقاد الدورة "{session.session_code}" لوجود درجات معتمدة وشهادات رسمية مسجلة للدارسين! يمكنك تغيير حالة الدورة إلى مكتملة بدلاً من حذفها.'
            )
            return redirect('training:course_sessions')
        elif has_enrollments:
            messages.error(
                request,
                f'إجراء محظور: لا يمكن حذف انعقاد الدورة "{session.session_code}" لوجود {enrollments_count} دارس مسجل بها! يرجى إزالة الدارسين من إدارة الدورة أولاً إن كان الانعقاد تجريبياً وغير مرصود.'
            )
            return redirect('training:course_sessions')
        try:
            code = session.session_code
            sid = session.id
            cname = session.course.name
            session.delete()
            log_activity(
                request=request,
                action_type=ActivityAction.DELETE,
                action_category=ActivityCategory.SESSIONS,
                description=f"حذف انعقاد الدورة: {code} لدورة '{cname}'",
                target_model="CourseSession",
                target_id=sid
            )
            messages.success(request, f'تم حذف انعقاد الدورة "{code}" بنجاح.')
        except ProtectedError:
            messages.error(request, f'تعذر حذف انعقاد الدورة "{session.session_code}" لوجود سجلات أكاديمية مرتبطة به.')
        return redirect('training:course_sessions')

    return render(request, 'training/course_session_confirm_delete.html', {
        'session': session,
        'has_enrollments': has_enrollments,
        'enrollments_count': enrollments_count,
        'has_graded': has_graded,
    })


# ==========================================
# القسم 5: النتائج ورصد الدرجات والشهادات والسجل التاريخي
# ==========================================
@login_required
def results_center_view(request):
    """
    مركز النتائج والشهادات:
    1. اختيار الدورة وتاريخها للدخول إلى رصد الدرجات مع دعم البحث والفلترة.
    2. السجل التاريخي الشامل لجميع نتائج الدارسين والشهادات مع فلاتر وبحث متقدم.
    """
    categories = CourseCategory.objects.all()
    if request.institute:
        categories = categories.filter(Q(institute=request.institute) | Q(institute__isnull=True))

    # فلاتر تبويب الدورات المتاحة لرصد الدرجات
    session_q = request.GET.get('session_q', '').strip()
    session_cat = request.GET.get('session_cat', '').strip()
    session_status = request.GET.get('session_status', '').strip()
    session_year = request.GET.get('session_year', '').strip()

    sessions = CourseSession.objects.select_related('course', 'course__category').prefetch_related('enrollments').all()
    if request.institute:
        sessions = sessions.filter(Q(institute=request.institute) | Q(institute__isnull=True))

    # إذا كان المستخدم معلماً، قصر الدورات المعروضة على تلك التي يدرس فيها مادة على الأقل
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        inst = get_user_instructor(request.user)
        if inst:
            teaching_session_ids = SessionSubjectInstructor.objects.filter(
                instructor=inst
            ).values_list('session_id', flat=True).distinct()
            sessions = sessions.filter(id__in=teaching_session_ids)
        else:
            sessions = sessions.none()

    if session_q:
        sessions = sessions.filter(
            Q(course__name__icontains=session_q) |
            Q(session_code__icontains=session_q)
        )
    if session_cat:
        sessions = sessions.filter(course__category_id=session_cat)
    if session_status:
        sessions = sessions.filter(status=session_status)
    if session_year and session_year.isdigit():
        sessions = sessions.filter(start_date__year=int(session_year))

    # فلاتر تبويب السجل التاريخي للنتائج والشهادات (عرض الدورات التدريبية في السجل التاريخي)
    search_query = request.GET.get('q', '').strip() or request.GET.get('archive_q', '').strip()
    grade_filter = request.GET.get('grade', '').strip()
    trainee_cat_filter = request.GET.get('trainee_category', '').strip()
    selected_session_filter = request.GET.get('session_filter', '').strip()
    year_filter = request.GET.get('year', '').strip() or request.GET.get('archive_year', '').strip()
    archive_cat = request.GET.get('archive_cat', '').strip()
    archive_status = request.GET.get('archive_status', '').strip()
    archive_session_id = request.GET.get('archive_session_id', '').strip() or request.GET.get('session_id', '').strip()

    historical_enrollments = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False).select_related(
        'trainee', 'session', 'session__course', 'session__course__category'
    ).order_by('-session__start_date', '-percentage')

    # دورات السجل التاريخي الشامل (المعتمدة فقط)
    archive_sessions = CourseSession.objects.filter(status='completed').select_related(
        'course', 'course__category', 'supervisor'
    ).prefetch_related(
        'enrollments', 'enrollments__trainee', 'enrollments__grades'
    ).all().order_by('-start_date', '-id')

    if request.institute:
        historical_enrollments = historical_enrollments.filter(Q(session__institute=request.institute) | Q(session__institute__isnull=True))
        archive_sessions = archive_sessions.filter(Q(institute=request.institute) | Q(institute__isnull=True))

    if is_instructor_user(request.user) and not is_admin_user(request.user):
        inst = get_user_instructor(request.user)
        if inst:
            teaching_session_ids = SessionSubjectInstructor.objects.filter(
                instructor=inst
            ).values_list('session_id', flat=True).distinct()
            historical_enrollments = historical_enrollments.filter(session_id__in=teaching_session_ids)
            archive_sessions = archive_sessions.filter(id__in=teaching_session_ids)
        else:
            historical_enrollments = historical_enrollments.none()
            archive_sessions = archive_sessions.none()

    if search_query:
        historical_enrollments = historical_enrollments.filter(
            Q(trainee__name__icontains=search_query) |
            Q(trainee__military_number__icontains=search_query) |
            Q(current_unit__icontains=search_query) |
            Q(current_rank__icontains=search_query) |
            Q(session__course__name__icontains=search_query) |
            Q(session__session_code__icontains=search_query)
        )
        archive_sessions = archive_sessions.filter(
            Q(course__name__icontains=search_query) |
            Q(session_code__icontains=search_query) |
            Q(course__category__name__icontains=search_query) |
            Q(enrollments__trainee__name__icontains=search_query) |
            Q(enrollments__trainee__military_number__icontains=search_query) |
            Q(enrollments__current_unit__icontains=search_query) |
            Q(enrollments__current_rank__icontains=search_query)
        ).distinct()

    if archive_cat:
        archive_sessions = archive_sessions.filter(course__category_id=archive_cat)

    if grade_filter:
        historical_enrollments = historical_enrollments.filter(grade_label__icontains=grade_filter)

    if trainee_cat_filter:
        historical_enrollments = historical_enrollments.filter(trainee__category=trainee_cat_filter)
        archive_sessions = archive_sessions.filter(enrollments__trainee__category=trainee_cat_filter).distinct()

    if selected_session_filter:
        historical_enrollments = historical_enrollments.filter(session_id=selected_session_filter)
        archive_sessions = archive_sessions.filter(id=selected_session_filter)

    if year_filter and year_filter.isdigit():
        historical_enrollments = historical_enrollments.filter(session__start_date__year=int(year_filter))
        archive_sessions = archive_sessions.filter(start_date__year=int(year_filter))

    if archive_status:
        archive_sessions = archive_sessions.filter(status=archive_status)

    # قائمة السنوات الميلادية المتاحة للفلترة
    from datetime import datetime
    db_years = set(d.year for d in CourseSession.objects.dates('start_date', 'year'))
    db_years.update(d.year for d in CourseSession.objects.dates('end_date', 'year'))
    current_year = datetime.now().year
    for y in range(current_year - 5, current_year + 2):
        db_years.add(y)
    available_years = sorted(list(db_years), reverse=True)

    # إحصائيات عامة للنتائج
    total_graded = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False).count()
    excellent_count = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False, percentage__gte=85).count()
    vgood_count = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False, percentage__gte=75, percentage__lt=85).count()
    good_count = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False, percentage__gte=65, percentage__lt=75).count()
    pass_count = CourseEnrollment.objects.filter(is_graded=True, is_dropped=False, percentage__gte=50, percentage__lt=65).count()

    # تحديد التبويب النشط بناءً على المعاملات
    active_tab = 'archive' if (
        search_query or grade_filter or trainee_cat_filter or selected_session_filter or
        year_filter or archive_cat or archive_status or archive_session_id or
        request.GET.get('tab') == 'archive'
    ) else 'sessions'

    # التحقق مما إذا تم طلب عرض دورة محددة ضمن السجل التاريخي
    selected_archive_session = None
    selected_archive_subjects = []
    selected_archive_enrollments = []
    selected_archive_total_possible = 0
    selected_archive_is_locked = False

    if archive_session_id and active_tab == 'archive':
        selected_archive_session = CourseSession.objects.filter(pk=archive_session_id, status='completed').select_related(
            'course', 'course__category', 'supervisor'
        ).prefetch_related(
            'course__subjects', 'subject_instructors__instructor',
            'enrollments__trainee', 'enrollments__grades'
        ).first()

        if selected_archive_session:
            selected_archive_subjects = selected_archive_session.get_subjects()
            selected_archive_enrollments = selected_archive_session.enrollments.filter(is_dropped=False).select_related('trainee').prefetch_related('grades').all()
            selected_archive_total_possible = selected_archive_session.total_possible_score
            selected_archive_is_locked = (selected_archive_session.status == 'completed' and not is_admin_user(request.user))

    context = {
        'sessions': sessions,
        'archive_sessions': archive_sessions,
        'all_sessions': CourseSession.objects.select_related('course').all(),
        'categories': categories,
        'historical_enrollments': historical_enrollments,
        'available_years': available_years,
        'session_q': session_q,
        'session_cat': session_cat,
        'session_status': session_status,
        'session_year': session_year,
        'search_query': search_query,
        'archive_q': search_query,
        'archive_cat': archive_cat,
        'archive_status': archive_status,
        'grade_filter': grade_filter,
        'trainee_cat_filter': trainee_cat_filter,
        'session_filter': selected_session_filter,
        'year_filter': year_filter,
        'archive_year': year_filter,
        'active_tab': active_tab,
        'selected_archive_session': selected_archive_session,
        'selected_archive_subjects': selected_archive_subjects,
        'selected_archive_enrollments': selected_archive_enrollments,
        'selected_archive_total_possible': selected_archive_total_possible,
        'selected_archive_is_locked': selected_archive_is_locked,
        'stats': {
            'total': total_graded,
            'excellent': excellent_count,
            'vgood': vgood_count,
            'good': good_count,
            'pass': pass_count,
        }
    }
    return render(request, 'training/results_center.html', context)


@login_required
def results_entry_view(request, session_id):
    """
    صفحة رصد درجات دورة معينة:
    - التحقق من صلاحيات المعلم: رصد درجات المواد المكلف بها فقط.
    - التحقق من صلاحيات المشرف: رصد المواظبة واعتماد النتيجة بعد اكتمال رصد كافة المواد.
    """
    session = get_object_or_404(
        CourseSession.objects.select_related('course', 'course__category', 'supervisor')
        .prefetch_related('course__subjects', 'subject_instructors__instructor'),
        pk=session_id
    )
    subjects = session.get_subjects()
    enrollments = session.enrollments.filter(is_dropped=False).select_related('trainee').prefetch_related('grades').all()
    dropped_enrollments = session.enrollments.filter(is_dropped=True).select_related('trainee').all()

    # خريطة المعلمين المسندين لمواد الدورة
    subject_instructors_map = {
        si.subject_id: si.instructor 
        for si in session.subject_instructors.all()
    }
    for sub in subjects:
        sub.assigned_instructor = subject_instructors_map.get(sub.id)
        sub.instructor_name = sub.assigned_instructor.name if sub.assigned_instructor else 'لم يحدد'

    # تحديد أدوار وصلاحيات المستخدم الحالي بدقة
    is_admin = is_admin_user(request.user)
    user_inst = get_user_instructor(request.user)
    is_session_supervisor = bool(user_inst and session.supervisor_id == user_inst.military_number)
    is_sup = is_supervisor_user(request.user) or is_session_supervisor
    is_inst = is_instructor_user(request.user) and not is_admin

    # تحديد المواد المصرح للمستخدم برصد وتعديل درجاتها
    allowed_subject_ids = set()
    if is_admin:
        # مدير النظام يملك صلاحية التحكم الكامل
        allowed_subject_ids = {sub.id for sub in subjects}
        can_edit_attendance = True
        can_approve_results = True
    elif is_inst:
        if not user_inst:
            messages.error(request, 'عفواً، حسابك غير مرتبط بملف معلم معتمد في هيئة التدريس.')
            return redirect('training:results_center')

        # المواد التي كلف بتدريسها هذا المعلم فقط
        allowed_subject_ids = set(
            session.subject_instructors.filter(instructor=user_inst).values_list('subject_id', flat=True)
        )
        # إذا كان المعلم هو نفسه مشرف الدورة: يملك أيضاً صلاحية المواظبة والاعتماد
        can_edit_attendance = is_session_supervisor
        can_approve_results = is_session_supervisor

        if not allowed_subject_ids and not is_session_supervisor:
            messages.error(request, 'عفواً، لست مكلفاً بتدريس أي مادة في هذه الدورة المنعقدة.')
            return redirect('training:results_center')
    elif is_sup:
        # مشرف الدورة: يرى مواد الدورة للعرض فقط (لا يعدل درجات مواد المعلمين)، ويرصد المواظبة ويعتمد النتيجة
        allowed_subject_ids = set()  # المشرف لا يعدل درجات المواد
        can_edit_attendance = True
        can_approve_results = True
    else:
        # مسجل بيانات
        allowed_subject_ids = set()
        can_edit_attendance = is_registrar_user(request.user)
        can_approve_results = False

    # معالجة حفظ ملحوظات الشهادة (متاحة في أي وقت حتى بعد اعتماد النتيجة وقفلها)
    if request.method == 'POST' and 'save_notes' in request.POST:
        updated_notes_count = 0
        for en in enrollments:
            num = en.trainee.military_number
            if f'cert_note_{num}' in request.POST:
                new_note = request.POST.get(f'cert_note_{num}', '').strip()
                if en.certificate_note != new_note:
                    en.certificate_note = new_note
                    en.save(update_fields=['certificate_note'])
                    updated_notes_count += 1
        log_activity(
            request=request,
            action_type=ActivityAction.UPDATE,
            action_category=ActivityCategory.GRADES,
            description=f"تحديث ملحوظات الشهادة لدارسي دورة '{session.course.name}' (دفعة: {session.session_code})",
            target_model="CourseSession",
            target_id=session.id
        )
        messages.success(request, 'تم حفظ وتحديث ملحوظات الشهادات لجميع الدارسين بنجاح.')
        from_param = request.POST.get('from', '').strip() or request.GET.get('from', '').strip()
        redirect_url = reverse('training:results_entry', kwargs={'session_id': session.id})
        if from_param:
            redirect_url += f'?from={from_param}'
        return redirect(redirect_url)

    # معالجة حفظ الدرجات والاعتماد
    if request.method == 'POST' and ('save_grades' in request.POST or 'mark_completed' in request.POST):
        # إذا كانت الدورة معتمدة ومكتملة، لا يُسمح بتعديل درجاتها إلا لمدير النظام
        if session.status == 'completed' and not is_admin:
            messages.error(request, 'إجراء محظور: نتائج هذه الدورة معتمدة ومقفلة، وتعديل الدرجات محصور بمدير النظام (Admin) فقط.')
            return redirect('training:results_entry', session_id=session.id)

        # التحقق من طلب الاعتماد (mark_completed)
        if 'mark_completed' in request.POST:
            if not can_approve_results:
                messages.error(request, 'إجراء محظور: اعتماد نتائج الدورة نهائياً محصور بمشرف الدورة أو مدير النظام فقط.')
                return redirect('training:results_entry', session_id=session.id)

            if not subjects:
                messages.error(request, 'لا يمكن اعتماد النتيجة: الدورة لا تحتوي على أي مواد دراسية.')
                return redirect('training:results_entry', session_id=session.id)

            if not enrollments.exists():
                messages.error(request, 'لا يمكن اعتماد النتيجة: لا يوجد دارسون مسجلون في هذه الدورة.')
                return redirect('training:results_entry', session_id=session.id)

            # التحقق الصارم من اكتمال رصد كافة درجات المواد لجميع الدارسين
            total_required_grades = len(enrollments) * len(subjects)
            total_recorded_grades = TraineeSubjectGrade.objects.filter(
                enrollment__session=session,
                enrollment__is_dropped=False,
                subject__in=subjects,
                score__isnull=False
            ).count()
            missing_count = total_required_grades - total_recorded_grades

            # التحقق أيضاً من رصد درجة المواظبة لجميع الدارسين
            missing_att = enrollments.filter(attendance_score__isnull=True).count()

            if missing_count > 0:
                messages.error(
                    request,
                    f'لا يمكن اعتماد النتيجة نهائياً لوجود مواد لم يتم رصد درجاتها بعد من قبل المعلمين لكافة الدارسين (المتبقي: {missing_count} درجة غير مرصودة). يرجى اكتمال رصد كافة درجات المواد أولاً.'
                )
                return redirect('training:results_entry', session_id=session.id)

            if missing_att > 0:
                messages.error(
                    request,
                    f'لا يمكن اعتماد النتيجة نهائياً لوجود دارسين لم تُرصد لهم درجة المواظبة والسلوك بعد (المتبقي: {missing_att} دارس). يرجى رصد المواظبة أولاً.'
                )
                return redirect('training:results_entry', session_id=session.id)

            # احتساب النتائج للجميع واعتماد الدورة مع حفظ أي ملحوظات مدخلة
            for en in enrollments:
                num = en.trainee.military_number
                if f'cert_note_{num}' in request.POST:
                    en.certificate_note = request.POST.get(f'cert_note_{num}', '').strip()
                en.calculate_results()
            session.status = 'completed'
            session.save()
            log_activity(
                request=request,
                action_type=ActivityAction.GRADE_APPROVAL,
                action_category=ActivityCategory.GRADES,
                description=f"اعتماد وإقفال نتائج دورة '{session.course.name}' (دفعة: {session.session_code}) رسمياً",
                target_model="CourseSession",
                target_id=session.id
            )
            messages.success(request, f'تم اعتماد وإقفال نتيجة دورة "{session.course.name}" بنجاح بعد اكتمال رصد كافة المواد من هيئة التدريس.')
            from_param = request.POST.get('from', '').strip() or request.GET.get('from', '').strip()
            redirect_url = reverse('training:results_entry', kwargs={'session_id': session.id})
            if from_param:
                redirect_url += f'?from={from_param}'
            return redirect(redirect_url)

        # حفظ وتحديث الدرجات
        validation_errors = []

        # 1. التحقق من درجات المواد المسموح للمستخدم بتعديلها فقط
        for en in enrollments:
            num = en.trainee.military_number
            for sub in subjects:
                if sub.id in allowed_subject_ids:
                    grade_raw = request.POST.get(f'grade_{num}_{sub.id}', '').strip()
                    if grade_raw != '':
                        try:
                            score = float(grade_raw)
                            if score < 0:
                                validation_errors.append(f'درجة مادة "{sub.name}" للدارس "{en.trainee.name}" لا يمكن أن تكون أقل من صفر.')
                            elif score > float(sub.max_grade):
                                validation_errors.append(f'درجة مادة "{sub.name}" للدارس "{en.trainee.name}" ({score}) تتجاوز الحد الأقصى للمادة ({sub.max_grade}).')
                        except ValueError:
                            validation_errors.append(f'درجة مادة "{sub.name}" المدخلة للدارس "{en.trainee.name}" غير صالحة ({grade_raw}).')

            # 2. التحقق من درجة المواظبة إذا كان مصرحاً له برصدها
            if can_edit_attendance:
                att_raw = request.POST.get(f'att_{num}', '').strip()
                if att_raw != '':
                    try:
                        att_val = float(att_raw)
                        if att_val < 0:
                            validation_errors.append(f'درجة المواظبة للدارس "{en.trainee.name}" لا يمكن أن تكون أقل من صفر.')
                        elif att_val > float(session.attendance_max_grade):
                            validation_errors.append(f'درجة المواظبة للدارس "{en.trainee.name}" ({att_val}) تتجاوز الحد الأقصى للمواظبة ({session.attendance_max_grade}).')
                    except ValueError:
                        validation_errors.append(f'درجة المواظبة للدارس "{en.trainee.name}" غير صالحة ({att_raw}).')

        if validation_errors:
            for err in validation_errors[:10]:
                messages.error(request, err)
        else:
            # تطبيق الحفظ على الحقول المصرح بها فقط دون المساس بدرجات المواد الأخرى
            for en in enrollments:
                num = en.trainee.military_number

                # حفظ الملحوظة
                if f'cert_note_{num}' in request.POST:
                    en.certificate_note = request.POST.get(f'cert_note_{num}', '').strip()

                # حفظ درجات المواد المسموح بها لهذا المعلم أو الأدمن
                for sub in subjects:
                    if sub.id in allowed_subject_ids:
                        grade_raw = request.POST.get(f'grade_{num}_{sub.id}', '').strip()
                        if grade_raw != '':
                            score = float(grade_raw)
                            TraineeSubjectGrade.objects.update_or_create(
                                enrollment=en,
                                subject=sub,
                                defaults={'score': score}
                            )
                        else:
                            TraineeSubjectGrade.objects.filter(enrollment=en, subject=sub).delete()

                # حفظ درجة المواظبة إذا كان مصرحاً له
                if can_edit_attendance:
                    att_raw = request.POST.get(f'att_{num}', '').strip()
                    en.attendance_score = float(att_raw) if att_raw != '' else None

                # إذا اكتملت جميع درجات المواد والمواظبة، يتم احتساب النتيجة تلقائياً
                total_recorded = en.grades.filter(score__isnull=False, subject__in=subjects).count()
                if total_recorded == len(subjects) and en.attendance_score is not None:
                    en.calculate_results()
                else:
                    en.is_graded = False
                    en.save(update_fields=['attendance_score', 'certificate_note', 'is_graded'])

            # رسالة نجاح واضحة حسب طبيعة الحفظ
            if allowed_subject_ids and not can_edit_attendance:
                msg = f'تم حفظ ورصد درجات المواد المكلف بها بنجاح.'
            elif can_edit_attendance and not allowed_subject_ids:
                msg = f'تم حفظ وتحديث درجات المواظبة والملحوظات بنجاح دون تعديل درجات المواد.'
            else:
                msg = f'تم حفظ ورصد الدرجات بنجاح.'

            messages.success(request, msg)
            from_param = request.POST.get('from', '').strip() or request.GET.get('from', '').strip()
            redirect_url = reverse('training:results_entry', kwargs={'session_id': session.id})
            if from_param:
                redirect_url += f'?from={from_param}'
            return redirect(redirect_url)

    # تجهيز بيانات درجات المواد لكل دارس بشكل مباشر ومتقن للعرض
    for en in enrollments:
        en_grades = {g.subject_id: g.score for g in en.grades.all()}
        en.subjects_data = []
        for sub in subjects:
            if request.method == 'POST' and f'grade_{en.trainee.military_number}_{sub.id}' in request.POST:
                posted_val = request.POST.get(f'grade_{en.trainee.military_number}_{sub.id}', '').strip()
                score = posted_val if posted_val != '' else None
            else:
                score = en_grades.get(sub.id, None)
            en.subjects_data.append({
                'subject': sub,
                'score': score
            })
        if request.method == 'POST' and f'att_{en.trainee.military_number}' in request.POST:
            posted_att = request.POST.get(f'att_{en.trainee.military_number}', '').strip()
            if posted_att != '':
                try:
                    en.attendance_score = float(posted_att)
                except ValueError:
                    pass

    is_locked = (session.status == 'completed' and not is_admin_user(request.user))

    # فحص اكتمال رصد كافة درجات المواد والمواظبة
    subjects_total_max = sum(s.max_grade for s in subjects)
    total_required = len(enrollments) * len(subjects)
    total_graded = TraineeSubjectGrade.objects.filter(
        enrollment__session=session,
        enrollment__is_dropped=False,
        subject__in=subjects,
        score__isnull=False
    ).count()
    missing_grades_count = total_required - total_graded
    missing_att_count = enrollments.filter(attendance_score__isnull=True).count()
    is_fully_graded = (missing_grades_count == 0 and missing_att_count == 0 and len(subjects) > 0 and enrollments.exists())

    context = {
        'session': session,
        'subjects': subjects,
        'subjects_total_max': subjects_total_max,
        'enrollments': enrollments,
        'total_possible_score': session.total_possible_score,
        'is_locked': is_locked,
        'is_instructor_only': is_inst,
        'user_inst': user_inst,
        'allowed_subject_ids': allowed_subject_ids or set(),
        'is_supervisor_or_admin': is_sup or is_admin,
        'can_edit_attendance': can_edit_attendance,
        'can_approve_results': can_approve_results,
        'is_fully_graded': is_fully_graded,
        'missing_grades_count': missing_grades_count,
        'missing_att_count': missing_att_count,
        'from_tab': request.GET.get('from', '').strip(),
        'dropped_enrollments': dropped_enrollments,
        'dropped_count': dropped_enrollments.count(),
    }
    return render(request, 'training/results_entry.html', context)




@login_required
def session_results_sheet_view(request, session_id):
    """كشف النتيجة العام والمعتمد للدورة المنعقدة بالكامل للطباعة والتصدير"""
    session = get_object_or_404(
        CourseSession.objects.select_related('course', 'course__category').prefetch_related('course__subjects'),
        pk=session_id
    )
    subjects = session.get_subjects()
    enrollments = session.enrollments.filter(is_dropped=False).select_related('trainee').prefetch_related('grades').order_by('-total_score')

    grades_map = {}
    for en in enrollments:
        grades_map[en.id] = {g.subject_id: g.score for g in en.grades.all()}

    return render(request, 'training/session_results_sheet.html', {
        'session': session,
        'subjects': subjects,
        'enrollments': enrollments,
        'grades_map': grades_map,
    })




@admin_access_required
def instructor_create_view(request):
    """إضافة معلم جديد للنظام من لوحة الأدمن"""
    if request.method == 'POST':
        form = InstructorForm(request.POST)
        if form.is_valid():
            mil_num = form.cleaned_data['military_number']
            if Instructor.objects.filter(military_number=mil_num).exists():
                messages.error(request, f'النمرة العسكرية "{mil_num}" مسجلة مسبقاً لمعلم آخر!')
            elif Trainee.objects.filter(military_number=mil_num).exists():
                messages.error(request, f'النمرة العسكرية "{mil_num}" مسجلة مسبقاً في النظام كدارس! لا يجوز تكرار النمرة العسكرية بين المعلمين والدارسين.')
            else:
                inst = form.save(commit=False)
                if request.institute:
                    inst.institute = request.institute
                inst.save()
                log_activity(
                    request=request,
                    action_type=ActivityAction.CREATE,
                    action_category=ActivityCategory.INSTRUCTORS,
                    description=f"إضافة معلم جديد: {inst.name} (نمرة: {inst.military_number} - رتبة: {inst.rank})",
                    target_model="Instructor",
                    target_id=inst.military_number
                )
                messages.success(request, f'تم إضافة المعلم "{inst.name}" بنجاح.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect('training:admin_dashboard')


@admin_access_required
def instructor_edit_view(request, military_number):
    """تعديل بيانات معلم"""
    instructor = get_object_or_404(Instructor, military_number=military_number)
    if request.method == 'POST':
        form = InstructorForm(request.POST, instance=instructor)
        form.fields['military_number'].disabled = True
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.INSTRUCTORS,
                description=f"تعديل بيانات المعلم: {instructor.name} (نمرة: {instructor.military_number})",
                target_model="Instructor",
                target_id=instructor.military_number
            )
            messages.success(request, f'تم حفظ تعديلات بيانات المعلم "{instructor.name}" بنجاح.')
            return redirect('training:admin_dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = InstructorForm(instance=instructor)
        form.fields['military_number'].disabled = True

    return render(request, 'admin_portal/instructor_edit.html', {
        'form': form,
        'instructor': instructor
    })


@admin_access_required
def instructor_delete_view(request, military_number):
    """حذف معلم من النظام مع حماية الدورات المسندة له"""
    instructor = get_object_or_404(Instructor, military_number=military_number)
    has_sessions = instructor.supervised_sessions.exists()
    has_assignments = instructor.teaching_assignments.exists()

    if request.method == 'POST':
        name = instructor.name
        mil_num = instructor.military_number
        instructor.delete()
        log_activity(
            request=request,
            action_type=ActivityAction.DELETE,
            action_category=ActivityCategory.INSTRUCTORS,
            description=f"حذف المعلم: {name} (نمرة: {mil_num})",
            target_model="Instructor",
            target_id=mil_num
        )
        messages.success(request, f'تم حذف المعلم "{name}" بنجاح.')
        return redirect('training:admin_dashboard')

    return render(request, 'admin_portal/instructor_confirm_delete.html', {
        'instructor': instructor,
        'has_sessions': has_sessions,
        'has_assignments': has_assignments
    })


# =====================================================================
# تخصيص وتعديل إعدادات وتوقيعات ولوغهات الشهادة
# =====================================================================


@admin_access_required
def category_create_view(request):
    """إضافة تصنيف دورات تدريبية جديد"""
    if request.method == 'POST':
        form = CourseCategoryForm(request.POST)
        if form.is_valid():
            category = form.save(commit=False)
            if request.institute:
                category.institute = request.institute
            category.save()
            log_activity(
                request=request,
                action_type=ActivityAction.CREATE,
                action_category=ActivityCategory.COURSES,
                description=f"إضافة تصنيف دورات تدريبية جديد: {category.name}",
                target_model="CourseCategory",
                target_id=category.id
            )
            messages.success(request, f'تم إضافة تصنيف الدورات الجديد "{category.name}" بنجاح.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect('training:admin_dashboard')


@admin_access_required
def category_edit_view(request, category_id):
    """تعديل تصنيف دورة تدريبية"""
    category = get_object_or_404(CourseCategory, pk=category_id)
    if request.method == 'POST':
        form = CourseCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.COURSES,
                description=f"تعديل تصنيف الدورات التدريبية: {category.name}",
                target_model="CourseCategory",
                target_id=category.id
            )
            messages.success(request, f'تم تعديل تصنيف الدورات "{category.name}" بنجاح.')
            return redirect('training:admin_dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = CourseCategoryForm(instance=category)

    return render(request, 'training/category_edit.html', {
        'form': form,
        'category': category
    })


@admin_access_required
def category_delete_view(request, category_id):
    """حذف تصنيف دورات تدريبية (مع التحقق من عدم وجود دورات مرتبطة به)"""
    category = get_object_or_404(CourseCategory, pk=category_id)
    linked_courses_count = category.courses.count()

    if request.method == 'POST':
        if linked_courses_count > 0:
            messages.error(
                request,
                f'لا يمكن حذف التصنيف "{category.name}" لوجود ({linked_courses_count}) دورة تدريبية مرتبطة به. يرجى نقل أو حذف الدورات المرتبطة به أولاً.'
            )
        else:
            category_name = category.name
            cid = category.id
            category.delete()
            log_activity(
                request=request,
                action_type=ActivityAction.DELETE,
                action_category=ActivityCategory.COURSES,
                description=f"حذف تصنيف الدورات: {category_name}",
                target_model="CourseCategory",
                target_id=cid
            )
            messages.success(request, f'تم حذف تصنيف الدورات "{category_name}" بنجاح.')
        return redirect('training:admin_dashboard')

    return render(request, 'training/category_confirm_delete.html', {
        'category': category,
        'linked_courses_count': linked_courses_count
    })


# =====================================================================
# إدارة سجل النشاط وتفريغ السجلات (Activity Log Management)
# =====================================================================


@login_required
def api_get_discipline_infractions_view(request, enrollment_id):
    """
    استرجاع سجل مخالفات الضبط والربط للدارس في دورة محددة
    """
    enrollment = get_object_or_404(
        CourseEnrollment.objects.select_related('trainee', 'session', 'session__course'),
        pk=enrollment_id
    )
    session = enrollment.session
    user_inst = get_user_instructor(request.user)
    is_session_sup = bool(user_inst and session.supervisor_id == user_inst.military_number)
    is_sup = is_supervisor_user(request.user) or is_session_sup
    is_reg = is_registrar_user(request.user)
    is_adm = is_admin_user(request.user)
    can_edit = (is_adm or is_sup or is_reg) and (session.status != 'completed' or is_adm)

    # إذا لم تكن هناك مخالفات مسجلة وكان الدارس غير مقطوع والدرجة 0 أو فارغة، تُهيأ للعظمى
    if not enrollment.discipline_infractions.exists() and not enrollment.is_dropped:
        if enrollment.attendance_score is None or enrollment.attendance_score == Decimal('0.00'):
            enrollment.attendance_score = session.attendance_max_grade or Decimal('10.00')
            enrollment.save(update_fields=['attendance_score'])
            enrollment.calculate_results()

    infractions_data = [
        {
            'id': inf.id,
            'infraction_type': inf.infraction_type,
            'infraction_display': inf.get_infraction_type_display(),
            'date': inf.date.strftime('%Y-%m-%d'),
            'notes': inf.notes,
        }
        for inf in enrollment.discipline_infractions.all().order_by('-date', '-created_at')
    ]

    choices = [
        {'value': code, 'label': label}
        for code, label in DisciplineInfraction.INFRACTION_CHOICES
    ]

    return JsonResponse({
        'success': True,
        'enrollment_id': enrollment.id,
        'trainee_name': enrollment.trainee.name,
        'military_number': enrollment.trainee.military_number,
        'current_rank': enrollment.current_rank,
        'current_unit': enrollment.current_unit,
        'max_grade': float(session.attendance_max_grade or 10.0),
        'score': float(enrollment.attendance_score or 0.0),
        'is_dropped': enrollment.is_dropped,
        'drop_reason': enrollment.drop_reason,
        'can_edit': can_edit,
        'infractions': infractions_data,
        'choices': choices,
        'today': timezone.now().strftime('%Y-%m-%d')
    })


@csrf_exempt
@login_required
def api_add_discipline_infraction_view(request):
    """
    تسجيل مخالفة ضبط وربط جديدة للدارس واحتساب النقاط تلقائياً
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'طريقة الطلب غير مسموح بها.'}, status=405)

    enrollment_id = request.POST.get('enrollment_id')
    infraction_type = request.POST.get('infraction_type')
    date_str = (request.POST.get('date') or '').strip()
    notes = (request.POST.get('notes') or '').strip()

    if not enrollment_id or not infraction_type:
        try:
            body_data = json.loads(request.body.decode('utf-8'))
            enrollment_id = enrollment_id or body_data.get('enrollment_id')
            infraction_type = infraction_type or body_data.get('infraction_type')
            date_str = date_str or (body_data.get('date') or '').strip()
            notes = notes or (body_data.get('notes') or '').strip()
        except Exception:
            pass

    if not enrollment_id or not infraction_type:
        return JsonResponse({'success': False, 'message': 'يرجى تحديد الدارس ونوع المخالفة.'}, status=400)

    enrollment = get_object_or_404(
        CourseEnrollment.objects.select_related('trainee', 'session', 'session__course'),
        pk=enrollment_id
    )
    session = enrollment.session
    user_inst = get_user_instructor(request.user)
    is_session_sup = bool(user_inst and session.supervisor_id == user_inst.military_number)
    is_sup = is_supervisor_user(request.user) or is_session_sup
    is_reg = is_registrar_user(request.user)
    is_adm = is_admin_user(request.user)

    if not (is_adm or is_sup or is_reg):
        return JsonResponse({'success': False, 'message': 'غير مصرح لك بتسجيل مخالفات الضبط والربط.'}, status=403)

    if session.status == 'completed' and not is_adm:
        return JsonResponse({'success': False, 'message': 'نتائج هذه الدورة معتمدة ومقفلة.'}, status=403)

    if infraction_type not in DisciplineInfraction.POINTS_MAP:
        return JsonResponse({'success': False, 'message': 'نوع المخالفة المحدد غير صالح.'}, status=400)

    if date_str:
        inf_date = None
        for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%Y/%m/%d'):
            try:
                inf_date = datetime.strptime(date_str, fmt).date()
                break
            except ValueError:
                pass
        if not inf_date:
            inf_date = timezone.now().date()
    else:
        inf_date = timezone.now().date()

    infraction = DisciplineInfraction.objects.create(
        enrollment=enrollment,
        infraction_type=infraction_type,
        date=inf_date,
        notes=notes
    )

    result = enrollment.update_discipline_score()

    log_activity(
        request=request,
        action_type=ActivityAction.UPDATE,
        action_category=ActivityCategory.GRADES,
        description=f"تسجيل مخالفة ضبط وربط للدارس {enrollment.trainee.name} ({infraction.get_infraction_type_display()} بتاريخ {inf_date})",
        target_model="DisciplineInfraction",
        target_id=infraction.id
    )

    infractions_data = [
        {
            'id': inf.id,
            'infraction_type': inf.infraction_type,
            'infraction_display': inf.get_infraction_type_display(),
            'date': inf.date.strftime('%Y-%m-%d'),
            'notes': inf.notes,
        }
        for inf in enrollment.discipline_infractions.all().order_by('-date', '-created_at')
    ]

    return JsonResponse({
        'success': True,
        'message': f'تم تسجيل مخالفة ({infraction.get_infraction_type_display()}) بنجاح.',
        'added_infraction': {
            'id': infraction.id,
            'type': infraction.infraction_type,
            'display': infraction.get_infraction_type_display(),
            'date': inf_date.strftime('%Y-%m-%d'),
            'notes': infraction.notes,
        },
        'enrollment_id': enrollment.id,
        'score': result['score'],
        'is_dropped': result['dropped'],
        'drop_reason': result['reason'],
        'infractions': infractions_data
    })


@csrf_exempt
@login_required
def api_delete_discipline_infraction_view(request, infraction_id):
    """
    حذف مخالفة ضبط وربط للدارس وتحديث احتساب الدرجات وإلغاء القطع إن انخفضت النقاط عن 5
    """
    if request.method != 'POST':
        return JsonResponse({'success': False, 'message': 'طريقة الطلب غير مسموح بها.'}, status=405)

    infraction = get_object_or_404(
        DisciplineInfraction.objects.select_related('enrollment', 'enrollment__trainee', 'enrollment__session'),
        pk=infraction_id
    )
    enrollment = infraction.enrollment
    session = enrollment.session
    user_inst = get_user_instructor(request.user)
    is_session_sup = bool(user_inst and session.supervisor_id == user_inst.military_number)
    is_sup = is_supervisor_user(request.user) or is_session_sup
    is_reg = is_registrar_user(request.user)
    is_adm = is_admin_user(request.user)

    if not (is_adm or is_sup or is_reg):
        return JsonResponse({'success': False, 'message': 'غير مصرح لك بحذف مخالفات الضبط والربط.'}, status=403)

    if session.status == 'completed' and not is_adm:
        return JsonResponse({'success': False, 'message': 'نتائج هذه الدورة معتمدة ومقفلة.'}, status=403)

    inf_type_display = infraction.get_infraction_type_display()
    infraction.delete()

    result = enrollment.update_discipline_score()

    log_activity(
        request=request,
        action_type=ActivityAction.DELETE,
        action_category=ActivityCategory.GRADES,
        description=f"حذف مخالفة ضبط وربط للدارس {enrollment.trainee.name} ({inf_type_display})",
        target_model="CourseEnrollment",
        target_id=enrollment.id
    )

    infractions_data = [
        {
            'id': inf.id,
            'infraction_type': inf.infraction_type,
            'infraction_display': inf.get_infraction_type_display(),
            'date': inf.date.strftime('%Y-%m-%d'),
            'notes': inf.notes,
        }
        for inf in enrollment.discipline_infractions.all().order_by('-date', '-created_at')
    ]

    return JsonResponse({
        'success': True,
        'message': 'تم حذف المخالفة وتحديث درجات الضبط والربط بنجاح.',
        'enrollment_id': enrollment.id,
        'score': result['score'],
        'is_dropped': result['dropped'],
        'drop_reason': result['reason'],
        'infractions': infractions_data
    })


# =====================================================================
# بوابة وإدارة السوبر أدمن المركزية (Super Admin Multi-Institute Portal)
# =====================================================================


