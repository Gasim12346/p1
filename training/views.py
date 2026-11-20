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
from .models import (
    Institute, Instructor, SessionSubjectInstructor,
    Trainee, TraineeCategory, CourseCategory, Course, Subject,
    CourseSession, CourseEnrollment, TraineeSubjectGrade, DisciplineInfraction,
    CertificateSettings, MovementOrderSettings, SystemSettings, UserProfile, UserRole,
    has_trainee_passed_course,
    ActivityLog, ActivityAction, ActivityCategory, log_activity
)
from .services import initialize_new_institute
from .forms import (
    InstructorForm, TraineeForm, CourseForm, SubjectForm, CourseSessionForm,
    UserLoginForm, CourseCategoryForm, CertificateSettingsForm,
    MovementOrderSettingsForm, OFFICER_RANKS,
    SystemSettingsForm, UserCreateForm, UserEditForm, AdminLoginForm
)
from .reports import get_report_data, export_report_to_excel, get_default_date_range, get_sessions_subjects_summary


def is_super_admin_user(user):
    """التحقق مما إذا كان المستخدم يملك صلاحية سوبر أدمن (مدير عام المنظومة)"""
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or (hasattr(user, 'profile') and user.profile.role == UserRole.SUPER_ADMIN))


def super_admin_required(view_func):
    """قيد صلاحية: محصور بالمدير العام للمنظومة (سوبر أدمن) وتوجيه غير المسجلين لصفحة تسجيل دخول السوبر أدمن"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'يرجى تسجيل الدخول بحساب السوبر أدمن للوصول إلى إدارة المنظومة المركزية.')
            return redirect(f"{reverse('training:super_admin_login')}?next={quote(request.get_full_path())}")
        if not is_super_admin_user(request.user):
            messages.error(request, 'هذا القسم مخصص للمدير العام للمنظومة (سوبر أدمن) فقط.')
            return redirect('training:super_admin_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def is_admin_user(user):
    """التحقق مما إذا كان المستخدم يملك صلاحية مدير النظام أو تحكم كامل"""
    if not user or not user.is_authenticated:
        return False
    return bool(
        is_super_admin_user(user) or 
        user.is_staff or 
        (hasattr(user, 'profile') and (user.profile.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN] or user.profile.can_manage_users))
    )


def is_registrar_user(user):
    """التحقق مما إذا كان المستخدم مسجل بيانات أو يملك صلاحية الإضافة والتعديل"""
    if not user or not user.is_authenticated:
        return False
    if is_admin_user(user):
        return True
    return bool(hasattr(user, 'profile') and (user.profile.role == UserRole.REGISTRAR or (user.profile.can_add and user.profile.can_edit)))


def is_supervisor_user(user):
    """التحقق مما إذا كان المستخدم مشرف دورة أو يملك صلاحية اعتماد النتائج"""
    if not user or not user.is_authenticated:
        return False
    if is_admin_user(user):
        return True
    return bool(hasattr(user, 'profile') and (user.profile.role == UserRole.SUPERVISOR or user.profile.can_approve_results))


def is_instructor_user(user):
    """التحقق مما إذا كان المستخدم معلماً في هيئة التدريس"""
    if not user or not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return bool(user.profile.role == UserRole.INSTRUCTOR or (user.profile.can_grade and not is_admin_user(user) and not user.profile.can_approve_results))


def get_user_instructor(user):
    """إرجاع كائن المعلم المرتبط بالمستخدم إن وجد"""
    if not user or not user.is_authenticated or not hasattr(user, 'profile'):
        return None
    return user.profile.get_instructor()


def admin_required(view_func):
    """حصر الإجراءات الحساسة (مثل لوحة الأدمن أو التعديل الحرج) على مدير النظام فقط"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('training:login')}?next={request.path}")

        if not is_admin_user(request.user):
            messages.error(request, 'عفواً، هذا الإجراء محصور بصلاحيات مدير النظام (Admin) فقط.')
            referer = request.META.get('HTTP_REFERER')
            if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
                return redirect(referer)
            return redirect('training:home')

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def registrar_required(view_func):
    """حصر الإجراء على مسجل البيانات ومدير النظام، وتوجيه المعلمين لصفحة النتيجة"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('training:login')}?next={request.path}")

        if is_instructor_user(request.user) and not is_admin_user(request.user):
            messages.warning(request, 'حسابك مخصص لمعلم / هيئة التدريس، وصلاحياتك محصورة في صفحة رصد نتائج المواد المكلف بها فقط.')
            return redirect('training:results_center')

        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، يتطلب هذا الإجراء صلاحية مسجل بيانات أو مدير نظام (Admin).')
            referer = request.META.get('HTTP_REFERER')
            if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
                return redirect(referer)
            return redirect('training:home')

        return view_func(request, *args, **kwargs)
    return _wrapped_view


@login_required
def home_view(request):
    """الصفحة الرئيسية (لوحة التحكم الشاملة)"""
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        return redirect('training:results_center')
    return render(request, 'training/home.html')


# ==========================================
# القسم 2: سجل الدارسين (الضباط، ضباط الصف، المدنيين)
# ==========================================
@login_required
def trainees_list_view(request):
    """عرض قائمة الدارسين وإمكانية إضافة دارس جديد والبحث والتصفية"""
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        messages.warning(request, 'حسابك مخصص لمعلم / هيئة التدريس، وصلاحياتك محصورة في صفحة رصد نتائج المواد المكلف بها فقط.')
        return redirect('training:results_center')

    category_filter = request.GET.get('category', '').strip()
    search_query = request.GET.get('q', '').strip()

    if request.method == 'POST' and 'add_trainee' in request.POST:
        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، إضافة دارس جديد محصورة بمسجل البيانات أو مدير النظام.')
            return redirect('training:trainees_list')

        form = TraineeForm(request.POST)
        if form.is_valid():
            military_num = form.cleaned_data['military_number']
            if Trainee.objects.filter(military_number=military_num).exists():
                messages.error(request, f'النمرة "{military_num}" مسجلة مسبقاً لدارس آخر! الرجاء استخدام نمرة فريدة.')
            elif Instructor.objects.filter(military_number=military_num).exists():
                messages.error(request, f'النمرة العسكرية "{military_num}" مسجلة مسبقاً في النظام كمعلم في هيئة التدريس! لا يجوز تكرار النمرة العسكرية بين الدارسين والمعلمين.')
            else:
                new_trainee = form.save(commit=False)
                if request.institute:
                    new_trainee.institute = request.institute
                new_trainee.save()
                form.save_relatives(new_trainee)
                log_activity(
                    request=request,
                    action_type=ActivityAction.CREATE,
                    action_category=ActivityCategory.TRAINEES,
                    description=f"إضافة دارس جديد: {new_trainee.name} (نمرة: {military_num})",
                    target_model="Trainee",
                    target_id=military_num
                )
                messages.success(request, f'تم حفظ بيانات الدارس "{form.cleaned_data["name"]}" بنجاح.')
                return redirect('training:trainees_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = TraineeForm()

    # الدارسون متاحون ومشاركون لجميع المعاهد مع حصر الدورات بحسب المعهد
    trainees = Trainee.objects.all().prefetch_related('relatives')
    if request.institute:
        trainees = trainees.annotate(
            inst_courses_count=Count('enrollments', filter=Q(enrollments__session__institute=request.institute, enrollments__is_dropped=False), distinct=True)
        )
    else:
        trainees = trainees.annotate(
            inst_courses_count=Count('enrollments', filter=Q(enrollments__is_dropped=False), distinct=True)
        )

    if category_filter in [TraineeCategory.OFFICER, TraineeCategory.NCO, TraineeCategory.CIVILIAN]:
        trainees = trainees.filter(category=category_filter)

    if search_query:
        search_filter = (
            Q(name__icontains=search_query) |
            Q(military_number__icontains=search_query) |
            Q(unit__icontains=search_query) |
            Q(force__icontains=search_query) |
            Q(phone__icontains=search_query) |
            Q(residence_state__icontains=search_query) |
            Q(residence_city__icontains=search_query) |
            Q(residence_neighborhood__icontains=search_query)
        )
        if search_query.isdigit():
            search_filter |= Q(batch=int(search_query))
        trainees = trainees.filter(search_filter).distinct()

    base_trainees = Trainee.objects.all()
    counts = {
        'all': base_trainees.count(),
        'officer': base_trainees.filter(category=TraineeCategory.OFFICER).count(),
        'nco': base_trainees.filter(category=TraineeCategory.NCO).count(),
        'civilian': base_trainees.filter(category=TraineeCategory.CIVILIAN).count(),
    }

    context = {
        'trainees': trainees,
        'form': form,
        'category_filter': category_filter,
        'search_query': search_query,
        'counts': counts,
    }
    return render(request, 'training/trainees_list.html', context)


@registrar_required
def trainee_edit_view(request, military_number):
    """تعديل بيانات الدارس"""
    trainee = get_object_or_404(Trainee, military_number=military_number)
    if request.method == 'POST':
        form = TraineeForm(request.POST, instance=trainee)
        form.fields['military_number'].disabled = True
        if form.is_valid():
            updated_trainee = form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.TRAINEES,
                description=f"تعديل بيانات الدارس: {updated_trainee.name} (نمرة: {updated_trainee.military_number})",
                target_model="Trainee",
                target_id=updated_trainee.military_number
            )
            messages.success(request, f'تم تحديث بيانات الدارس "{trainee.name}" بنجاح.')
            return redirect('training:trainees_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = TraineeForm(instance=trainee)
        form.fields['military_number'].disabled = True

    return render(request, 'training/trainee_edit.html', {
        'form': form,
        'trainee': trainee,
    })


@registrar_required
def trainee_delete_view(request, military_number):
    """حذف دارس مع الحماية الصارمة من حذف الدارسين المسجلين بدورات أو شهادات"""
    trainee = get_object_or_404(Trainee, military_number=military_number)
    has_enrollments = trainee.enrollments.exists()
    enrollments_count = trainee.enrollments.count()

    if request.method == 'POST':
        if has_enrollments:
            messages.error(
                request,
                f'إجراء محظور: لا يمكن حذف الدارس "{trainee.name}" نظراً لوجود دورات تدريبية وسجلات نتائج وشهادات معتمدة مسجلة له ({enrollments_count} دورة)! لحماية السجلات التاريخية، يمكنك تعديل بياناته فقط.'
            )
            return redirect('training:trainees_list')
        try:
            name = trainee.name
            mil_num = trainee.military_number
            trainee.delete()
            log_activity(
                request=request,
                action_type=ActivityAction.DELETE,
                action_category=ActivityCategory.TRAINEES,
                description=f"حذف الدارس: {name} (نمرة: {mil_num})",
                target_model="Trainee",
                target_id=mil_num
            )
            messages.success(request, f'تم حذف الدارس "{name}" بنجاح.')
        except ProtectedError:
            messages.error(request, f'تعذر حذف الدارس "{trainee.name}" لوجود سجلات أكاديمية مرتبطة به في النظام.')
        return redirect('training:trainees_list')

    return render(request, 'training/trainee_confirm_delete.html', {
        'trainee': trainee,
        'has_enrollments': has_enrollments,
        'enrollments_count': enrollments_count,
    })


# ==========================================
# القسم 3: الدورات ومفرداتها وموادها
# ==========================================
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
def certificate_view(request, enrollment_id):
    """استخراج وعرض شهادة التقدير الرسمية للدارس - حظر تام مالم تكتمل كافة البيانات والدرجات"""
    enrollment = get_object_or_404(
        CourseEnrollment.objects.select_related('trainee', 'session', 'session__course', 'session__course__category'),
        pk=enrollment_id
    )

    if enrollment.is_dropped:
        messages.error(request, 'إجراء محظور: تم قطع الدورة عن هذا الدارس ولن تظهر نتيجته أو شهادته.')
        return redirect('training:results_center')

    # التحقق الصارم والشامل: هل اكتملت كافة البيانات والدرجات؟
    if not enrollment.has_complete_data_and_grades:
        missing_reasons = []
        if not enrollment.trainee.military_number or not enrollment.trainee.name:
            missing_reasons.append("بيانات الدارس الأساسية (النمرة والاسم)")
        if enrollment.trainee.category != TraineeCategory.CIVILIAN and (not enrollment.current_rank or not enrollment.current_rank.strip()):
            missing_reasons.append("الرتبة العسكرية للدارس")
        if not enrollment.current_unit or not enrollment.current_unit.strip():
            missing_reasons.append("الوحدة العسكرية للدارس")
        if not enrollment.session.start_date or not enrollment.session.end_date:
            missing_reasons.append("تواريخ انعقاد الدورة")
        
        session_subjects = enrollment.session.get_subjects()
        total_subjects = len(session_subjects)
        graded_count = enrollment.grades.filter(subject__in=session_subjects).count()
        if total_subjects == 0:
            missing_reasons.append("تعريف مفردات المواد الدراسية للدورة")
        elif graded_count < total_subjects:
            missing_reasons.append(f"درجات المواد (تم رصد {graded_count} من أصل {total_subjects} مادة)")
        
        if not enrollment.is_graded:
            missing_reasons.append("حفظ واعتماد النتيجة النهائية")

        reasons_text = "، ".join(missing_reasons) if missing_reasons else "عدم اكتمال رصد البيانات والدرجات"

        messages.error(
            request,
            f'تنبيه نظام الشهادات: لا يمكن إظهار أو استخراج الشهادة للدارس "{enrollment.current_rank or ""} / {enrollment.trainee.name}" لعدم اكتمال جميع البيانات والدرجات المطلوبة ({reasons_text}). يرجى استكمالها أولاً لإصدار الشهادة.'
        )
        return redirect('training:results_entry', session_id=enrollment.session.id)

    cert_settings = CertificateSettings.get_settings(institute=enrollment.session.institute or request.institute)
    return render(request, 'training/certificate.html', {
        'enrollment': enrollment,
        'trainee': enrollment.trainee,
        'session': enrollment.session,
        'course': enrollment.session.course,
        'cert_settings': cert_settings,
    })


@login_required
def certificate_detailed_view(request, enrollment_id):
    """استخراج وعرض الشهادة التفصيلية (أساسية أو متقدمة) للدارس مع كشف الدرجات والترتيب والملحوظة"""
    enrollment = get_object_or_404(
        CourseEnrollment.objects.select_related('trainee', 'session', 'session__course', 'session__course__category'),
        pk=enrollment_id
    )

    if enrollment.is_dropped:
        messages.error(request, 'إجراء محظور: تم قطع الدورة عن هذا الدارس ولن تظهر نتيجته أو شهادته.')
        return redirect('training:results_center')

    # التحقق الصارم والشامل: هل اكتملت كافة البيانات والدرجات؟
    if not enrollment.has_complete_data_and_grades:
        missing_reasons = []
        if not enrollment.trainee.military_number or not enrollment.trainee.name:
            missing_reasons.append("بيانات الدارس الأساسية (النمرة والاسم)")
        if enrollment.trainee.category != TraineeCategory.CIVILIAN and (not enrollment.current_rank or not enrollment.current_rank.strip()):
            missing_reasons.append("الرتبة العسكرية للدارس")
        if not enrollment.current_unit or not enrollment.current_unit.strip():
            missing_reasons.append("الوحدة العسكرية للدارس")
        if not enrollment.session.start_date or not enrollment.session.end_date:
            missing_reasons.append("تواريخ انعقاد الدورة")
        
        session_subjects = enrollment.session.get_subjects()
        total_subjects = len(session_subjects)
        graded_count = enrollment.grades.filter(subject__in=session_subjects).count()
        if total_subjects == 0:
            missing_reasons.append("تعريف مفردات المواد الدراسية للدورة")
        elif graded_count < total_subjects:
            missing_reasons.append(f"درجات المواد (تم رصد {graded_count} من أصل {total_subjects} مادة)")
        
        if not enrollment.is_graded:
            missing_reasons.append("حفظ واعتماد النتيجة النهائية")

        reasons_text = "، ".join(missing_reasons) if missing_reasons else "عدم اكتمال رصد البيانات والدرجات"

        messages.error(
            request,
            f'تنبيه نظام الشهادات: لا يمكن إظهار أو استخراج الشهادة للدارس "{enrollment.current_rank or ""} / {enrollment.trainee.name}" لعدم اكتمال جميع البيانات والدرجات المطلوبة ({reasons_text}). يرجى استكمالها أولاً لإصدار الشهادة.'
        )
        return redirect('training:results_entry', session_id=enrollment.session.id)

    cert_settings = CertificateSettings.get_settings(institute=enrollment.session.institute or request.institute)
    page_title = cert_settings.basic_cert_title
    cert_badge = 'شهادة التفاصيل'

    # تجهيز درجات المواد
    subjects = enrollment.session.get_subjects()
    grades_map = {g.subject_id: g.score for g in enrollment.grades.all()}
    subjects_data = []
    for sub in subjects:
        score = grades_map.get(sub.id, 0.0)
        subjects_data.append({
            'name': sub.name,
            'max_grade': sub.max_grade,
            'score': score
        })

    note_text = enrollment.certificate_note.strip() if enrollment.certificate_note else cert_settings.default_certificate_note

    return render(request, 'training/certificate_detailed.html', {
        'enrollment': enrollment,
        'trainee': enrollment.trainee,
        'session': enrollment.session,
        'course': enrollment.session.course,
        'cert_settings': cert_settings,
        'page_title': page_title,
        'cert_badge': cert_badge,
        'subjects_data': subjects_data,
        'note_text': note_text,
    })


@login_required
def movement_order_view(request, enrollment_id):
    """
    استخراج وعرض أمر التحرك الرسمي المعتمد للدارس (ضابط أو ضابط صف) للطباعة
    متاح بعد رصد درجات الدورة واعتمادها.
    """
    enrollment = get_object_or_404(
        CourseEnrollment.objects.select_related('trainee', 'session', 'session__course', 'session__course__category'),
        pk=enrollment_id
    )

    # التحقق من شروط استخراج أمر التحرك (يصدر في حالتين: 1. بعد اعتماد الدورة واكتمالها، أو 2. أثناء الدورة عند قطع الدورة عن الدارس)
    if not enrollment.is_dropped:
        if not (is_admin_user(request.user) or is_supervisor_user(request.user) or is_registrar_user(request.user)):
            if not enrollment.has_complete_data_and_grades:
                messages.warning(request, 'تنبيه: لا يمكن استخراج أمر التحرك إلا بعد اكتمال رصد كافة درجات الدورة واعتمادها، أو في حال قطع الدورة عن الدارس.')
                return redirect('training:results_entry', session_id=enrollment.session.id)

    order_settings = MovementOrderSettings.get_settings(institute=enrollment.session.institute or request.institute)

    # تحديد نوع أمر التحرك (ضابط أو ضابط صف) مع إمكانية التبديل عبر الرابط
    type_param = request.GET.get('type', '').strip().lower()
    if type_param == 'officer':
        is_officer = True
    elif type_param == 'nco':
        is_officer = False
    else:
        is_officer = (
            enrollment.trainee.category == TraineeCategory.OFFICER or
            (enrollment.current_rank in OFFICER_RANKS) or
            any(r in (enrollment.current_rank or '') for r in ['ملازم', 'نقيب', 'رائد', 'مقدم', 'عقيد', 'عميد', 'لواء', 'فريق'])
        )

    # الوحدة المسجل بها الدارس في الدورة
    destination_unit = (enrollment.current_unit or (enrollment.trainee.unit if enrollment.trainee else '') or '').strip()
    if not destination_unit:
        destination_unit = (order_settings.to_location_default or 'شعبة التدريب').strip()

    # تجهيز التعليمات الإدارية ديناميكياً لتوجيه الدارس لوحدته المسجل بها ومقابلة رئيس وحدته
    raw_admin = (order_settings.admin_instructions or '').strip()
    if '{unit}' in raw_admin:
        admin_instructions = raw_admin.replace('{unit}', destination_unit)
    else:
        import re
        pattern = r'شعبـ*ة\s+التدريب'
        if re.search(pattern, raw_admin):
            admin_instructions = re.sub(pattern, destination_unit, raw_admin)
        else:
            admin_instructions = f"بموجب هذا الأمر وجب عليك / عليكم مغادرة معهد نظم المعلومات والإحصاء والتوجه الي {destination_unit} وعند وصولك / وصولكم عليك / عليكم مقابلة السيد رئيس {destination_unit} لأخذ التعليمات الاخيرة منه ."

    # تجهيز نسخة إلى (1) ديناميكياً لتوجيهها للسيد رئيس وحدة الدارس
    raw_copy_1 = (order_settings.copy_to_1 or '').strip()
    if '{unit}' in raw_copy_1:
        copy_to_1 = raw_copy_1.replace('{unit}', destination_unit)
    else:
        import re
        pattern = r'شعبـ*ة\s+التدريب'
        if re.search(pattern, raw_copy_1):
            copy_to_1 = re.sub(pattern, destination_unit, raw_copy_1)
        elif 'رئيس' in raw_copy_1:
            copy_to_1 = f"السيد / رئيس {destination_unit}"
        else:
            copy_to_1 = f"السيد / رئيس {destination_unit}"

    if enrollment.is_dropped:
        c_name = enrollment.session.course.name.strip()
        if not c_name.startswith('دورة'):
            c_name = f"دورة {c_name}"
        purpose = f"قطع {c_name}"
        movement_date = enrollment.movement_order_date or (enrollment.dropped_at.date() if enrollment.dropped_at else timezone.now().date())
    else:
        purpose = f"{order_settings.purpose_prefix}{enrollment.session.course.name}"
        movement_date = enrollment.movement_order_date or enrollment.session.end_date

    page_title = f"أمر تحرك - {enrollment.trainee.name}"
    current_year = timezone.now().year

    return render(request, 'training/movement_order.html', {
        'enrollment': enrollment,
        'trainee': enrollment.trainee,
        'session': enrollment.session,
        'course': enrollment.session.course,
        'order_settings': order_settings,
        'is_officer': is_officer,
        'destination_unit': destination_unit,
        'admin_instructions': admin_instructions,
        'copy_to_1': copy_to_1,
        'copy_to_2': order_settings.copy_to_2,
        'purpose': purpose,
        'movement_date': movement_date,
        'current_year': current_year,
        'page_title': page_title,
    })


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


@login_required
def trainee_transcript_view(request, military_number):
    """السجل الأكاديمي التاريخي لدارس محدد معزولاً بحسب المعهد الحالي مع دعم الاسترجاع كـ JSON"""
    trainee = get_object_or_404(Trainee, military_number=military_number)
    enrollments = trainee.enrollments.filter(is_dropped=False)
    if request.institute:
        enrollments = enrollments.filter(session__institute=request.institute)
    enrollments = enrollments.select_related(
        'session', 'session__course', 'session__course__category'
    ).prefetch_related('grades__subject').order_by('-session__start_date')

    # دعم طلب البيانات عبر JSON لفتح سجل دورات الدارس مباشرة في نافذة منبثقة
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('format') == 'json':
        courses_data = []
        for en in enrollments:
            courses_data.append({
                'id': en.id,
                'course_name': en.session.course.name,
                'category_name': en.session.course.category.name,
                'session_code': en.session.session_code,
                'start_date': en.session.start_date.strftime('%Y-%m-%d') if en.session.start_date else '',
                'end_date': en.session.end_date.strftime('%Y-%m-%d') if en.session.end_date else '',
                'current_rank': en.current_rank,
                'current_unit': en.current_unit,
                'total_score': float(en.total_score or 0.0),
                'total_possible': float(en.session.total_possible_score or 0.0),
                'percentage': float(en.percentage or 0.0),
                'grade_label': en.grade_label or '',
                'is_graded': en.is_graded,
                'has_complete_data': en.has_complete_data_and_grades,
                'cert_url': reverse('training:certificate', args=[en.id]),
                'cert_basic_url': reverse('training:certificate_detailed', args=[en.id]),
                'movement_order_url': reverse('training:movement_order', args=[en.id]),
                'cert_advanced_url': reverse('training:certificate_detailed', args=[en.id]),
            })
        return JsonResponse({
            'success': True,
            'name': trainee.name,
            'military_number': trainee.military_number,
            'rank': courses_data[0]['current_rank'] if courses_data else '',
            'unit': trainee.unit,
            'force': trainee.force,
            'category_display': trainee.get_category_display(),
            'total_courses': len(courses_data),
            'full_transcript_url': reverse('training:trainee_transcript', args=[trainee.military_number]),
            'courses': courses_data,
        })

    return render(request, 'training/trainee_transcript.html', {
        'trainee': trainee,
        'enrollments': enrollments,
    })


# =====================================================================
# القسم 6: تسجيل الدخول والخروج (Authentication)
# =====================================================================
def login_view(request):
    """صفحة تسجيل الدخول الموحدة للنظام - توجيه السوبر أدمن للوحة المنظومة الشاملة والأدمن للوحة المعهد"""
    if request.user.is_authenticated:
        if is_super_admin_user(request.user) and not request.session.get('active_institute_id'):
            return redirect('training:super_admin_dashboard')
        if is_admin_user(request.user):
            return redirect('training:admin_dashboard')
        return redirect('training:home')

    redirect_to = request.GET.get('next', request.POST.get('next', '')).strip()

    # فحص أمان الرابط لمنع ثغرة التوجيه المفتوح (Open Redirect - CWE-601)
    is_safe_redirect = bool(
        redirect_to and url_has_allowed_host_and_scheme(
            url=redirect_to,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure()
        )
    )
    if not is_safe_redirect:
        redirect_to = ''

    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].strip()
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)

            if user is not None:
                login(request, user)
                
                # توجيه السوبر أدمن
                if is_super_admin_user(user):
                    messages.success(request, f'مرحباً بك {user.get_full_name() or user.username}، تم تسجيل دخولك بنجاح كمدير عام للمنظومة (سوبر أدمن).')
                    if redirect_to and not redirect_to.startswith('/login'):
                        return redirect(redirect_to)
                    return redirect('training:super_admin_dashboard')

                is_admin = is_admin_user(user)
                if is_admin:
                    messages.success(request, f'مرحباً بك {user.get_full_name() or user.username}، تم تسجيل دخولك بنجاح ونقلك إلى لوحة إدارة المعهد.')
                    if redirect_to and redirect_to.startswith('/admin-portal/'):
                        return redirect(redirect_to)
                    return redirect('training:admin_dashboard')
                else:
                    messages.success(request, f'مرحباً بك {user.get_full_name() or user.username}، تم تسجيل دخولك بنجاح.')
                    if redirect_to and not redirect_to.startswith('/admin-portal/'):
                        return redirect(redirect_to)
                    return redirect('training:home')
            else:
                messages.error(request, 'اسم المستخدم أو كلمة المرور غير صحيحة. يرجى التحقق وإعادة المحاولة.')
        else:
            messages.error(request, 'يرجى إدخال اسم المستخدم وكلمة المرور بشكل صحيح.')
    else:
        form = UserLoginForm()

    return render(request, 'auth/login.html', {
        'form': form,
        'next': redirect_to,
    })


def logout_view(request):
    """تسجيل الخروج من النظام"""
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, 'تم تسجيل خروجك من النظام بنجاح.')
    return redirect('training:login')


# =====================================================================
# القسم 7: بوابة القيادة والأدمن المنفصلة (Dedicated Admin Portal)
# =====================================================================
def admin_access_required(view_func):
    """حصر الوصول لبوابة الأدمن المنفصلة فقط على المستخدمين الذين يملكون رتبة مدير نظام أو superuser/staff"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'يرجى تسجيل الدخول بحساب مدير النظام للوصول إلى لوحة الأدمن.')
            return redirect(f"{reverse('training:login')}?next={request.path}")
        
        if not is_admin_user(request.user):
            messages.error(request, 'عفواً، هذه اللوحة مخصصة لمدير النظام (الأدمن) فقط. حسابك يملك صلاحيات النظام الرئيسي.')
            return redirect('training:home')

        return view_func(request, *args, **kwargs)
    return _wrapped_view


def admin_login_view(request):
    """تحويل مباشر لصفحة الدخول الموحدة للنظام"""
    return redirect(f"{reverse('training:login')}?next={reverse('training:admin_dashboard')}")


def admin_logout_view(request):
    """تسجيل الخروج والتحويل لصفحة الدخول الموحدة"""
    return logout_view(request)


@admin_access_required
def admin_dashboard_view(request):
    """لوحة تحكم الأدمن المنفصلة: التحليلات، إدارة المستخدمين، التصنيفات، تخصيص الشهادة وهوية النظام"""
    # 1. إحصائيات عامة ومؤشرات أداء (KPIs)
    trainees_total = Trainee.objects.count()
    trainees_officers = Trainee.objects.filter(category=TraineeCategory.OFFICER).count()
    trainees_ncos = Trainee.objects.filter(category=TraineeCategory.NCO).count()
    trainees_civilians = Trainee.objects.filter(category=TraineeCategory.CIVILIAN).count()

    courses_total = Course.objects.filter(institute=request.institute).count() if request.institute else Course.objects.count()
    categories_total = CourseCategory.objects.filter(institute=request.institute).count() if request.institute else CourseCategory.objects.count()
    sessions_qs = CourseSession.objects.filter(institute=request.institute) if request.institute else CourseSession.objects.all()
    sessions_total = sessions_qs.count()
    sessions_active = sessions_qs.filter(status='active').count()
    sessions_completed = sessions_qs.filter(status='completed').count()
    sessions_planned = sessions_qs.filter(status='planned').count()

    enrollments_qs = CourseEnrollment.objects.filter(session__institute=request.institute) if request.institute else CourseEnrollment.objects.all()
    enrollments_total = enrollments_qs.count()
    enrollments_graded = enrollments_qs.filter(is_graded=True).count()
    completion_rate = round((enrollments_graded / enrollments_total * 100), 1) if enrollments_total > 0 else 0

    avg_score_res = enrollments_qs.filter(is_graded=True).aggregate(avg_score=Avg('percentage'))
    avg_score = round(avg_score_res['avg_score'], 1) if avg_score_res['avg_score'] is not None else 0.0

    # 2. توزيع التقديرات (Grade Distribution)
    grade_a = enrollments_qs.filter(is_graded=True, percentage__gte=85).count()
    grade_b = enrollments_qs.filter(is_graded=True, percentage__gte=75, percentage__lt=85).count()
    grade_c = enrollments_qs.filter(is_graded=True, percentage__gte=65, percentage__lt=75).count()
    grade_d = enrollments_qs.filter(is_graded=True, percentage__gte=50, percentage__lt=65).count()
    grade_f = enrollments_qs.filter(is_graded=True, percentage__lt=50).count()

    def calc_pct(part, whole):
        return round((part / whole * 100), 1) if whole > 0 else 0

    grade_distribution = [
        {'label': 'ممتاز (85% فأعلى)', 'count': grade_a, 'pct': calc_pct(grade_a, enrollments_graded), 'color': '#10b981', 'badge': 'badge-grade-a'},
        {'label': 'جيد جداً (75% - 84%)', 'count': grade_b, 'pct': calc_pct(grade_b, enrollments_graded), 'color': '#3b82f6', 'badge': 'badge-grade-b'},
        {'label': 'جيد (65% - 74%)', 'count': grade_c, 'pct': calc_pct(grade_c, enrollments_graded), 'color': '#eab308', 'badge': 'badge-grade-c'},
        {'label': 'مقبول (50% - 64%)', 'count': grade_d, 'pct': calc_pct(grade_d, enrollments_graded), 'color': '#f97316', 'badge': 'badge-grade-d'},
        {'label': 'دون المستوى (أقل من 50%)', 'count': grade_f, 'pct': calc_pct(grade_f, enrollments_graded), 'color': '#ef4444', 'badge': 'bg-danger text-white'},
    ]

    # 3. توزيع الدارسين بحسب القوة (Forces Distribution)
    if request.institute:
        raw_forces = enrollments_qs.exclude(current_force__isnull=True).exclude(current_force='').values('current_force').annotate(count=Count('id')).order_by('-count')
        forces_list = []
        for item in raw_forces:
            forces_list.append({
                'name': item['current_force'],
                'count': item['count'],
                'pct': calc_pct(item['count'], enrollments_total)
            })
        top_units = enrollments_qs.exclude(current_unit__isnull=True).exclude(current_unit='').values('current_unit').annotate(count=Count('id')).order_by('-count')[:6]
    else:
        forces_stats = Trainee.objects.values('force').annotate(count=Count('military_number')).order_by('-count')
        forces_list = []
        for item in forces_stats:
            forces_list.append({
                'name': item['force'] or 'غير محدد',
                'count': item['count'],
                'pct': calc_pct(item['count'], trainees_total)
            })
        top_units = Trainee.objects.values('unit').annotate(count=Count('military_number')).order_by('-count')[:6]

    # 5. تصنيفات الدورات
    categories = CourseCategory.objects.annotate(courses_count=Count('courses')).order_by('name')
    if request.institute:
        categories = categories.filter(institute=request.institute)

    # 6. إدارة المستخدمين والصلاحيات
    users = User.objects.select_related('profile', 'profile__instructor').order_by('-date_joined')
    if request.institute:
        users = users.filter(profile__institute=request.institute)
    user_create_form = UserCreateForm()
    instructors = Instructor.objects.all().order_by('-created_at')
    if request.institute:
        instructors = instructors.filter(institute=request.institute)
    instructor_form = InstructorForm()

    role_counts = {
        'all': users.count(),
        'admin': users.filter(Q(is_superuser=True) | Q(profile__role=UserRole.ADMIN)).distinct().count(),
        'registrar': users.filter(profile__role=UserRole.REGISTRAR).count(),
        'supervisor': users.filter(profile__role=UserRole.SUPERVISOR).count(),
        'instructor': users.filter(profile__role=UserRole.INSTRUCTOR).count(),
        'regular': users.filter(profile__role=UserRole.REGULAR).count(),
    }

    # 7. إعدادات الشهادة الرسمية وتعديل اللوغهات
    cert_settings = CertificateSettings.get_settings(institute=request.institute)
    cert_form = CertificateSettingsForm(instance=cert_settings)

    # 7-ب. إعدادات وتخصيص أمر التحرك الرسمي
    movement_settings = MovementOrderSettings.get_settings(institute=request.institute)
    movement_form = MovementOrderSettingsForm(instance=movement_settings)

    # 8. إعدادات وهوية وألوان وشعار النظام بالكامل
    system_settings = SystemSettings.get_settings(institute=request.institute)
    system_form = SystemSettingsForm(instance=system_settings)

    # 9. حزم ألوان وثيمات جاهزة بنقرة واحدة (Color Palettes Presets)
    color_presets = [
        {
            'id': 'navy_gold',
            'name': 'الهوية العسكرية الرسمية (كحلي وذهبي)',
            'primary_navy': '#0f172a',
            'primary_accent': '#1e3a8a',
            'brand_blue': '#2563eb',
            'brand_cyan': '#0284c7',
            'gold_accent': '#d97706',
            'bg_light': '#f8fafc',
            'sidebar_bg_start': '#0b1329',
            'sidebar_bg_end': '#0f172a',
        },
        {
            'id': 'desert_camo',
            'name': 'الصقر الصحراوي التكتيكي (بني ورملي)',
            'primary_navy': '#292524',
            'primary_accent': '#44403c',
            'brand_blue': '#b45309',
            'brand_cyan': '#d97706',
            'gold_accent': '#ca8a04',
            'bg_light': '#fafaf9',
            'sidebar_bg_start': '#1c1917',
            'sidebar_bg_end': '#292524',
        },
        {
            'id': 'tactical_green',
            'name': 'الدرع الميداني التكتيكي (زيتي ورمادي)',
            'primary_navy': '#14281d',
            'primary_accent': '#1b3b2b',
            'brand_blue': '#059669',
            'brand_cyan': '#10b981',
            'gold_accent': '#d97706',
            'bg_light': '#f0fdf4',
            'sidebar_bg_start': '#0a1a12',
            'sidebar_bg_end': '#14281d',
        },
        {
            'id': 'dark_modern',
            'name': 'الوضع الليلي الاحترافي (Dark Slate Modern)',
            'primary_navy': '#090d16',
            'primary_accent': '#111827',
            'brand_blue': '#3b82f6',
            'brand_cyan': '#06b6d4',
            'gold_accent': '#f59e0b',
            'bg_light': '#f3f4f6',
            'sidebar_bg_start': '#030712',
            'sidebar_bg_end': '#0f172a',
        },
        {
            'id': 'royal_blue',
            'name': 'السماوي الأكاديمي المتقدم (أزرق ملكي)',
            'primary_navy': '#0c1b33',
            'primary_accent': '#102a4d',
            'brand_blue': '#1d4ed8',
            'brand_cyan': '#0284c7',
            'gold_accent': '#eab308',
            'bg_light': '#eff6ff',
            'sidebar_bg_start': '#081324',
            'sidebar_bg_end': '#0c1b33',
        },
    ]

    # 10. آخر الانعقادات ومستوى التحصيل
    recent_sessions = CourseSession.objects.select_related('course', 'course__category').annotate(
        enrolled_count=Count('enrollments')
    ).order_by('-start_date')[:6]

    # 11. سجل النشاط والعمليات الشامل ومسار تدقيق المستخدمين (Audit & Activity Logs)
    activity_qs = ActivityLog.objects.all()
    if request.institute:
        activity_qs = activity_qs.filter(institute=request.institute)

    # معلمات الفلترة والبحث
    activity_user = request.GET.get('activity_user', '').strip()
    activity_action = request.GET.get('activity_action', '').strip()
    activity_category = request.GET.get('activity_category', '').strip()
    activity_date = request.GET.get('activity_date', 'all').strip()
    activity_q = request.GET.get('activity_q', '').strip()

    if activity_user:
        if activity_user.isdigit():
            activity_qs = activity_qs.filter(user_id=int(activity_user))
        else:
            activity_qs = activity_qs.filter(username=activity_user)

    if activity_action and activity_action != 'ALL':
        activity_qs = activity_qs.filter(action_type=activity_action)

    if activity_category and activity_category != 'ALL':
        activity_qs = activity_qs.filter(action_category=activity_category)

    today = timezone.localdate()
    if activity_date == 'today':
        activity_qs = activity_qs.filter(timestamp__date=today)
    elif activity_date == '7days':
        activity_qs = activity_qs.filter(timestamp__date__gte=today - timedelta(days=7))
    elif activity_date == '30days':
        activity_qs = activity_qs.filter(timestamp__date__gte=today - timedelta(days=30))

    if activity_q:
        activity_qs = activity_qs.filter(
            Q(description__icontains=activity_q) |
            Q(username__icontains=activity_q) |
            Q(user_fullname__icontains=activity_q) |
            Q(user_military_number__icontains=activity_q) |
            Q(ip_address__icontains=activity_q)
        )

    base_activity = ActivityLog.objects.filter(institute=request.institute) if request.institute else ActivityLog.objects.all()
    activity_logs_total = base_activity.count()
    activity_logs_today = base_activity.filter(timestamp__date=today).count()
    activity_logs_creates = base_activity.filter(action_type=ActivityAction.CREATE).count()
    activity_logs_updates = base_activity.filter(action_type=ActivityAction.UPDATE).count()
    activity_logs_deletes = base_activity.filter(action_type=ActivityAction.DELETE).count()
    activity_logs_sessions = base_activity.filter(action_type__in=[ActivityAction.LOGIN, ActivityAction.LOGOUT]).count()
    activity_logs_grades = base_activity.filter(action_type__in=[ActivityAction.GRADE_ENTRY, ActivityAction.GRADE_APPROVAL]).count()

    activity_logs = list(activity_qs[:300])
    activity_users_list = User.objects.filter(profile__institute=request.institute).order_by('username') if request.institute else User.objects.all().order_by('username')

    context = {
        # KPIs
        'trainees_total': trainees_total,
        'trainees_officers': trainees_officers,
        'trainees_ncos': trainees_ncos,
        'trainees_civilians': trainees_civilians,
        'courses_total': courses_total,
        'categories_total': categories_total,
        'sessions_total': sessions_total,
        'sessions_active': sessions_active,
        'sessions_completed': sessions_completed,
        'sessions_planned': sessions_planned,
        'enrollments_total': enrollments_total,
        'enrollments_graded': enrollments_graded,
        'completion_rate': completion_rate,
        'avg_score': avg_score,
        # Analytics
        'grade_distribution': grade_distribution,
        'forces_list': forces_list,
        'top_units': top_units,
        'recent_sessions': recent_sessions,
        # Categories
        'categories': categories,
        'category_form': CourseCategoryForm(),
        # Users & Permissions
        'users': users,
        'user_create_form': user_create_form,
        'role_counts': role_counts,
        'user_roles': UserRole.choices,
        'instructors': instructors,
        'instructor_form': instructor_form,
        # Certificate Settings
        'cert_settings': cert_settings,
        'cert_form': cert_form,
        # Movement Order Settings
        'movement_settings': movement_settings,
        'movement_form': movement_form,
        # System Branding & Themes
        'system_settings': system_settings,
        'system_form': system_form,
        'color_presets': color_presets,
        # Activity Logs
        'activity_logs': activity_logs,
        'activity_logs_total': activity_logs_total,
        'activity_logs_today': activity_logs_today,
        'activity_logs_creates': activity_logs_creates,
        'activity_logs_updates': activity_logs_updates,
        'activity_logs_deletes': activity_logs_deletes,
        'activity_logs_sessions': activity_logs_sessions,
        'activity_logs_grades': activity_logs_grades,
        'activity_actions': ActivityAction.choices,
        'activity_categories': ActivityCategory.choices,
        'activity_user': activity_user,
        'activity_action': activity_action,
        'activity_category': activity_category,
        'activity_date': activity_date,
        'activity_q': activity_q,
        'activity_users_list': activity_users_list,
    }
    return render(request, 'admin_portal/dashboard.html', context)


# =====================================================================
# إدارة المستخدمين وصلاحيات الحسابات (User & Role Management)
# =====================================================================
@admin_access_required
def user_create_view(request):
    """إضافة مستخدم جديد للنظام وتحديد دوره وصلاحيته"""
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            password = form.cleaned_data['password']
            user.set_password(password)
            
            # تحديد flags في Django بناءً على الدور
            role = form.cleaned_data['role']
            if role == UserRole.SUPER_ADMIN and not is_super_admin_user(request.user):
                messages.error(request, 'عفواً، لا يمكن منح صلاحية السوبر أدمن إلا من خلال إدارة المنظومة المركزية.')
                role = UserRole.ADMIN

            if role == UserRole.ADMIN:
                user.is_staff = True
            else:
                user.is_staff = False
            user.save()

            # إنشاء أو تحديث البروفايل
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = role
            profile.instructor = form.cleaned_data.get('instructor')
            profile.military_number = form.cleaned_data.get('military_number', '')
            profile.rank = form.cleaned_data.get('rank', '')
            profile.unit = form.cleaned_data.get('unit', '')
            profile.phone = form.cleaned_data.get('phone', '')

            # في حال كان الحساب لمعلم ولم يحدد معلم بالاسم، نحاول ربطه عبر النمرة العسكرية
            if role == UserRole.INSTRUCTOR and not profile.instructor and profile.military_number:
                profile.instructor = Instructor.objects.filter(military_number=profile.military_number).first()
            if profile.instructor:
                if not profile.military_number:
                    profile.military_number = profile.instructor.military_number
                if not profile.rank:
                    profile.rank = profile.instructor.rank
                if not profile.unit:
                    profile.unit = profile.instructor.unit

            # حفظ أذونات وصلاحيات مربعات الاختيار (Windows Permissions Checkboxes)
            profile.can_manage_users = form.cleaned_data.get('can_manage_users', False)
            profile.can_view = form.cleaned_data.get('can_view', True)
            profile.can_add = form.cleaned_data.get('can_add', False)
            profile.can_edit = form.cleaned_data.get('can_edit', False)
            profile.can_delete = form.cleaned_data.get('can_delete', False)
            profile.can_grade = form.cleaned_data.get('can_grade', False)
            profile.can_approve_results = form.cleaned_data.get('can_approve_results', False)

            if profile.can_manage_users or role == UserRole.ADMIN:
                user.is_staff = True
                user.save(update_fields=['is_staff'])

            if request.institute:
                profile.institute = request.institute
            profile.save()

            log_activity(
                request=request,
                action_type=ActivityAction.CREATE,
                action_category=ActivityCategory.USERS,
                description=f"إضافة حساب مستخدم جديد: {user.username} بصلاحية ({profile.get_role_display()})",
                target_model="User",
                target_id=user.id
            )

            messages.success(request, f'تم إنشاء حساب المستخدم الجديد "{user.username}" بنجاح وتعيين الصلاحية ({profile.get_role_display()}).')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect(f"{reverse('training:admin_dashboard')}?tab=users")


@admin_access_required
def user_edit_view(request, user_id):
    """تعديل بيانات وصلاحيات وكلمة مرور المستخدم"""
    target_user = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
    profile = target_user.profile if hasattr(target_user, 'profile') else UserProfile.objects.create(user=target_user)

    if request.method == 'POST':
        form = UserEditForm(request.POST, instance=target_user)
        if form.is_valid():
            u = form.save()
            new_password = form.cleaned_data.get('new_password')
            if new_password and new_password.strip():
                u.set_password(new_password.strip())
            
            role = form.cleaned_data.get('role')
            if role == UserRole.SUPER_ADMIN and not is_super_admin_user(request.user):
                messages.error(request, 'عفواً، لا يمكن منح صلاحية السوبر أدمن إلا من خلال إدارة المنظومة المركزية.')
                role = UserRole.ADMIN

            if role == UserRole.ADMIN:
                u.is_staff = True
            elif u.id != request.user.id:  # منع المستخدم الحالي من إزالة صفة الإدارة عن نفسه بالخطأ
                u.is_staff = False
            u.save()

            profile.role = role
            profile.instructor = form.cleaned_data.get('instructor')
            profile.military_number = form.cleaned_data.get('military_number', '')
            profile.rank = form.cleaned_data.get('rank', '')
            profile.unit = form.cleaned_data.get('unit', '')
            profile.phone = form.cleaned_data.get('phone', '')

            if role == UserRole.INSTRUCTOR and not profile.instructor and profile.military_number:
                profile.instructor = Instructor.objects.filter(military_number=profile.military_number).first()
            if profile.instructor:
                if not profile.military_number:
                    profile.military_number = profile.instructor.military_number
                if not profile.rank:
                    profile.rank = profile.instructor.rank
                if not profile.unit:
                    profile.unit = profile.instructor.unit

            # حفظ أذونات وصلاحيات مربعات الاختيار (Windows Permissions Checkboxes)
            profile.can_manage_users = form.cleaned_data.get('can_manage_users', False)
            profile.can_view = form.cleaned_data.get('can_view', True)
            profile.can_add = form.cleaned_data.get('can_add', False)
            profile.can_edit = form.cleaned_data.get('can_edit', False)
            profile.can_delete = form.cleaned_data.get('can_delete', False)
            profile.can_grade = form.cleaned_data.get('can_grade', False)
            profile.can_approve_results = form.cleaned_data.get('can_approve_results', False)

            if profile.can_manage_users or role == UserRole.ADMIN:
                u.is_staff = True
            elif u.id != request.user.id:  # منع المستخدم الحالي من إزالة صفة الإدارة عن نفسه بالخطأ
                u.is_staff = False
            u.save()

            if request.institute:
                profile.institute = request.institute
            profile.save()

            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.USERS,
                description=f"تعديل بيانات المستخدم: {target_user.username} (الصلاحية: {profile.get_role_display()})",
                target_model="User",
                target_id=target_user.id
            )

            messages.success(request, f'تم حفظ تعديلات المستخدم "{target_user.username}" بنجاح.')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=users")
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        initial_data = {
            'role': profile.role,
            'instructor': profile.instructor,
            'military_number': profile.military_number,
            'rank': profile.rank,
            'unit': profile.unit,
            'phone': profile.phone,
            'can_manage_users': profile.can_manage_users,
            'can_view': profile.can_view,
            'can_add': profile.can_add,
            'can_edit': profile.can_edit,
            'can_delete': profile.can_delete,
            'can_grade': profile.can_grade,
            'can_approve_results': profile.can_approve_results,
        }
        form = UserEditForm(instance=target_user, initial=initial_data)

    instructors = Instructor.objects.filter(is_active=True).order_by('name')
    return render(request, 'admin_portal/user_edit.html', {
        'form': form,
        'target_user': target_user,
        'profile': profile,
        'instructors': instructors,
    })


@admin_access_required
def user_delete_view(request, user_id):
    """حذف مستخدم من النظام مع الحماية التامة لحساب المدير الحالي"""
    target_user = get_object_or_404(User, pk=user_id)

    if target_user.id == request.user.id:
        messages.error(request, 'إجراء محظور: لا يمكنك حذف حسابك الحالي الذي تستخدمه لتسجيل الدخول!')
        return redirect(f"{reverse('training:admin_dashboard')}?tab=users")

    if request.method == 'POST':
        uname = target_user.username
        uid = target_user.id
        target_user.delete()
        log_activity(
            request=request,
            action_type=ActivityAction.DELETE,
            action_category=ActivityCategory.USERS,
            description=f"حذف حساب المستخدم نهائياً: {uname}",
            target_model="User",
            target_id=uid
        )
        messages.success(request, f'تم حذف المستخدم "{uname}" نهائياً من النظام.')
        return redirect(f"{reverse('training:admin_dashboard')}?tab=users")

    return render(request, 'admin_portal/user_confirm_delete.html', {
        'target_user': target_user
    })


@admin_access_required
def user_toggle_active_view(request, user_id):
    """تفعيل أو تعطيل حساب مستخدم بنقرة واحدة - محمي بطلب POST و CSRF لمنع هجمات CSRF عبر GET"""
    if request.method != 'POST':
        messages.warning(request, 'إجراء غير مسموح: تعديل حالة الحساب يتطلب إرسال نموذج آمن.')
        return redirect('training:admin_dashboard')

    target_user = get_object_or_404(User, pk=user_id)
    if target_user.id == request.user.id:
        messages.error(request, 'إجراء محظور: لا يمكنك تعطيل حسابك الحالي!')
    else:
        target_user.is_active = not target_user.is_active
        target_user.save()
        status_text = 'تفعيل' if target_user.is_active else 'تعطيل'
        log_activity(
            request=request,
            action_type=ActivityAction.STATUS_CHANGE,
            action_category=ActivityCategory.USERS,
            description=f"تغيير حالة حساب المستخدم '{target_user.username}' إلى ({status_text})",
            target_model="User",
            target_id=target_user.id
        )
        messages.success(request, f'تم {status_text} حساب المستخدم "{target_user.username}" بنجاح.')
    return redirect(f"{reverse('training:admin_dashboard')}?tab=users")


@admin_access_required
def user_update_role_view(request, user_id):
    """تحديث سريع لدور وصلاحيات المستخدم وأذونات مربعات الاختيار (Windows Permissions)"""
    if request.method != 'POST':
        return redirect(f"{reverse('training:admin_dashboard')}?tab=users")

    target_user = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
    profile = target_user.profile if hasattr(target_user, 'profile') else UserProfile.objects.create(user=target_user)

    new_role = request.POST.get('role', '').strip()
    instructor_num = request.POST.get('instructor', '').strip()

    # قراءة أذونات مربعات الاختيار (Windows Permissions Checkboxes)
    def is_checked(name):
        val = request.POST.get(name)
        return val in ('1', 'on', 'true', 'True')

    can_manage_users = is_checked('can_manage_users')
    can_view = is_checked('can_view')
    can_add = is_checked('can_add')
    can_edit = is_checked('can_edit')
    can_delete = is_checked('can_delete')
    can_grade = is_checked('can_grade')
    can_approve_results = is_checked('can_approve_results')

    if new_role not in UserRole.values:
        new_role = UserRole.CUSTOM

    # منع الأدمن الحالي من خفض صلاحياته بنفسه لمنع حبس النظام
    if target_user.id == request.user.id and not can_manage_users and new_role != UserRole.ADMIN:
        messages.error(request, 'إجراء محظور: لا يمكنك إزالة صلاحية الإدارة أو التحكم الكامل عن حسابك الحالي!')
        return redirect(f"{reverse('training:admin_dashboard')}?tab=users")

    # إذا اختار دوراً قياسياً بدون مربعات محددة مسبقاً في الطلب، نحدد أذوناته الافتراضية
    has_explicit_checkboxes = any(k in request.POST for k in (
        'can_manage_users', 'can_view', 'can_add', 'can_edit', 'can_delete', 'can_grade', 'can_approve_results'
    ))

    profile.role = new_role
    if has_explicit_checkboxes:
        profile.can_manage_users = can_manage_users
        profile.can_view = can_view
        profile.can_add = can_add
        profile.can_edit = can_edit
        profile.can_delete = can_delete
        profile.can_grade = can_grade
        profile.can_approve_results = can_approve_results
    else:
        profile.sync_permissions_from_role()

    if profile.can_manage_users or new_role == UserRole.ADMIN:
        target_user.is_staff = True
    else:
        if target_user.id != request.user.id:
            target_user.is_staff = False
    target_user.save(update_fields=['is_staff'])

    # ربط المعلم إن وجد
    if instructor_num:
        profile.instructor = Instructor.objects.filter(military_number=instructor_num).first()
    elif (new_role == UserRole.INSTRUCTOR or profile.can_grade) and profile.military_number:
        profile.instructor = Instructor.objects.filter(military_number=profile.military_number).first()
    elif new_role != UserRole.INSTRUCTOR and not profile.can_grade:
        profile.instructor = None

    profile.save()
    log_activity(
        request=request,
        action_type=ActivityAction.UPDATE,
        action_category=ActivityCategory.USERS,
        description=f"تحديث أذونات وصلاحيات المستخدم '{target_user.username}' إلى دور: {profile.get_role_display()}",
        target_model="User",
        target_id=target_user.id
    )
    messages.success(request, f'تم حفظ وتطبيق أذونات وصلاحيات المستخدم "{target_user.username}" بنجاح.')
    return redirect(f"{reverse('training:admin_dashboard')}?tab=users")


# =====================================================================
# إدارة هيئة التعليم والمعلمين (Instructor Management)
# =====================================================================
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
def certificate_settings_update_view(request):
    """حفظ التعديلات على شكل وبيانات وتوقيعات ولوغهات الشهادة الرسمية"""
    cert_settings = CertificateSettings.get_settings(institute=request.institute)
    if request.method == 'POST':
        # إعادة تعيين اللوغو الأيمن إذا طلب
        if 'reset_right_logo' in request.POST:
            cert_settings.right_logo = None
            cert_settings.save()
            messages.success(request, 'تمت إعادة تعيين الشعار الأيمن للشهادة إلى الشعار الافتراضي (صقر الجديان).')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#pane-certificate")
        # إعادة تعيين اللوغو الأيسر إذا طلب
        if 'reset_left_logo' in request.POST:
            cert_settings.left_logo = None
            cert_settings.save()
            messages.success(request, 'تمت إعادة تعيين الشعار الأيسر للشهادة إلى الشعار الافتراضي (شعار نظم المعلومات).')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#pane-certificate")

        form = CertificateSettingsForm(request.POST, request.FILES, instance=cert_settings)
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.SETTINGS,
                description="تحديث إعدادات وتوقيعات ولوغهات الشهادة الرسمية",
                target_model="CertificateSettings"
            )
            messages.success(request, 'تم حفظ وتحديث إعدادات وتوقيعات ولوغهات الشهادة الرسمية بنجاح. ستنعكس فوراً على جميع الشهادات.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#pane-certificate")


# =====================================================================
# تخصيص وتعديل إعدادات ونصوص أمر التحرك الرسمي
# =====================================================================
@admin_access_required
def movement_order_settings_update_view(request):
    """حفظ التعديلات على شكل وبيانات ونصوص وتوقيعات أمر التحرك الرسمي"""
    movement_settings = MovementOrderSettings.get_settings(institute=request.institute)
    if request.method == 'POST':
        # إعادة تعيين العلامة المائية إذا طلب
        if 'reset_watermark' in request.POST:
            movement_settings.watermark_image = None
            movement_settings.save()
            messages.success(request, 'تمت إعادة تعيين العلامة المائية لأمر التحرك إلى الشعار الافتراضي بنجاح.')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#subpane-movement-order")

        form = MovementOrderSettingsForm(request.POST, request.FILES, instance=movement_settings)
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.SETTINGS,
                description="تحديث إعدادات وتنسيقات ونصوص أمر التحرك الرسمي",
                target_model="MovementOrderSettings"
            )
            messages.success(request, 'تم حفظ وتحديث إعدادات ونصوص أمر التحرك بنجاح. ستنعكس فوراً على جميع أوامر التحرك.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#subpane-movement-order")


# =====================================================================
# تخصيص اللوغو الرئيسي وألوان وهوية النظام بالكامل (System Branding & Themes)
# =====================================================================
@admin_access_required
def system_settings_update_view(request):
    """حفظ وتعديل اللوغو الرئيسي وألوان وهوية النظام بالكامل أو تطبيق ثيم جاهز"""
    system_settings = SystemSettings.get_settings(institute=request.institute)

    if request.method == 'POST':
        # 1. إزالة الشعار والعودة للافتراضي
        if 'reset_main_logo' in request.POST:
            system_settings.main_logo = None
            system_settings.save()
            messages.success(request, 'تمت إعادة تعيين شعار النظام الرئيسي إلى الشعار الافتراضي بنجاح.')
            return redirect('training:admin_dashboard')

        # 2. تطبيق ثيم جاهز بنقرة واحدة
        preset_id = request.POST.get('apply_preset')
        if preset_id:
            presets_map = {
                'navy_gold': {
                    'primary_navy': '#0f172a',
                    'primary_accent': '#1e3a8a',
                    'brand_blue': '#2563eb',
                    'brand_cyan': '#0284c7',
                    'gold_accent': '#d97706',
                    'bg_light': '#f8fafc',
                    'sidebar_bg_start': '#0b1329',
                    'sidebar_bg_end': '#0f172a',
                },
                'desert_camo': {
                    'primary_navy': '#292524',
                    'primary_accent': '#44403c',
                    'brand_blue': '#b45309',
                    'brand_cyan': '#d97706',
                    'gold_accent': '#ca8a04',
                    'bg_light': '#fafaf9',
                    'sidebar_bg_start': '#1c1917',
                    'sidebar_bg_end': '#292524',
                },
                'tactical_green': {
                    'primary_navy': '#14281d',
                    'primary_accent': '#1b3b2b',
                    'brand_blue': '#059669',
                    'brand_cyan': '#10b981',
                    'gold_accent': '#d97706',
                    'bg_light': '#f0fdf4',
                    'sidebar_bg_start': '#0a1a12',
                    'sidebar_bg_end': '#14281d',
                },
                'dark_modern': {
                    'primary_navy': '#090d16',
                    'primary_accent': '#111827',
                    'brand_blue': '#3b82f6',
                    'brand_cyan': '#06b6d4',
                    'gold_accent': '#f59e0b',
                    'bg_light': '#f3f4f6',
                    'sidebar_bg_start': '#030712',
                    'sidebar_bg_end': '#0f172a',
                },
                'royal_blue': {
                    'primary_navy': '#0c1b33',
                    'primary_accent': '#102a4d',
                    'brand_blue': '#1d4ed8',
                    'brand_cyan': '#0284c7',
                    'gold_accent': '#eab308',
                    'bg_light': '#eff6ff',
                    'sidebar_bg_start': '#081324',
                    'sidebar_bg_end': '#0c1b33',
                },
            }
            if preset_id in presets_map:
                p = presets_map[preset_id]
                for k, v in p.items():
                    setattr(system_settings, k, v)
                system_settings.save()
                log_activity(
                    request=request,
                    action_type=ActivityAction.UPDATE,
                    action_category=ActivityCategory.SETTINGS,
                    description=f"تطبيق حزمة ألوان وثيم جاهز: {presets_map[preset_id].get('name', preset_id)}",
                    target_model="SystemSettings"
                )
                messages.success(request, f'تم تطبيق حزمة الألوان بنجاح وانعكست على كافة شاشات النظام فوراً.')
                return redirect('training:admin_dashboard')

        # 3. حفظ النموذج المخصص
        form = SystemSettingsForm(request.POST, request.FILES, instance=system_settings)
        if form.is_valid():
            form.save()
            log_activity(
                request=request,
                action_type=ActivityAction.UPDATE,
                action_category=ActivityCategory.SETTINGS,
                description="تحديث إعدادات وشعار وهوية وألوان النظام المخصصة",
                target_model="SystemSettings"
            )
            messages.success(request, 'تم حفظ وتحديث هوية وشعار وألوان النظام بنجاح. تنعكس الآن على كامل شاشات النظام فوراً.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)

    return redirect('training:admin_dashboard')


# =====================================================================
# إدارة تصنيفات الدورات التدريبية (Course Categories CRUD)
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
@admin_access_required
def admin_clear_activity_logs_view(request):
    """تفريغ وتنظيف سجل النشاط والعمليات من لوحة الأدمن مع توثيق عملية التفريغ للمعهد المحدد"""
    if request.method == 'POST':
        qs = ActivityLog.objects.filter(institute=request.institute) if request.institute else ActivityLog.objects.all()
        count = qs.count()
        qs.delete()
        inst_name = request.institute.name if request.institute else "العام"
        log_activity(
            request=request,
            action_type=ActivityAction.DELETE,
            action_category=ActivityCategory.SYSTEM,
            description=f"قام مدير النظام بتفريغ وحذف سجل النشاط والعمليات السابق لنظام ({inst_name}) بالكامل (كان يحتوي على {count} عملية مسجلة)."
        )
        messages.success(request, f'تم تفريغ وحذف سجل النشاط السابق لنظام "{inst_name}" بنجاح ({count} سجل تم تنظيفها).')
    return redirect(f"{reverse('training:admin_dashboard')}?tab=activity-log#pane-activity-log")


# =====================================================================
# تقرير التحليل والإحصاء الشامل القابل للطباعة
# =====================================================================
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
    has_filters = any(k in params for k in [
        'start_date', 'end_date', 'all_dates', 'force', 'unit',
        'course_id', 'category_id', 'session_id', 'status',
        'session_status', 'trainee_category', 'instructor_id', 'q'
    ])

    def calc_pct(part, whole):
        return round((part / whole * 100), 1) if whole > 0 else 0.0

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
        avg_score = round(avg_score_res['avg_score'], 1) if avg_score_res['avg_score'] is not None else 0.0

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
            avg_score = round(avg_score_res['avg_score'], 1) if avg_score_res['avg_score'] is not None else 0.0

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
                {'force': f['current_force'], 'count': f['count'], 'pct': round((f['count'] / total_trainees * 100), 1)}
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
            avg_score = round(avg_score_res['avg_score'], 1) if avg_score_res['avg_score'] is not None else 0.0

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
    sessions_data = [
        {
            'id': s.id,
            'session_code': s.session_code,
            'name': f"{s.course.name} ({s.session_code}) - {'معتمدة ومحفوظة' if s.status == 'completed' else 'منعقدة'}",
            'course_id': s.course_id,
            'category_id': s.course.category_id if s.course else None,
            'status': s.status
        }
        for s in sessions
    ]

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
def super_admin_login_view(request):
    """صفحة تسجيل الدخول المخصصة والمعزولة للمدير العام للمنظومة (سوبر أدمن)"""
    if request.user.is_authenticated and is_super_admin_user(request.user):
        return redirect('training:super_admin_dashboard')

    redirect_to = request.GET.get('next', request.POST.get('next', '')).strip()
    is_safe_redirect = bool(
        redirect_to and url_has_allowed_host_and_scheme(
            url=redirect_to,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure()
        )
    )
    if not is_safe_redirect:
        redirect_to = ''

    if request.method == 'POST':
        form = UserLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].strip()
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)

            if user is not None:
                if is_super_admin_user(user):
                    login(request, user)
                    log_activity(
                        request=request,
                        action_type=ActivityAction.LOGIN,
                        action_category=ActivityCategory.AUTH,
                        description=f"تسجيل الدخول إلى بوابة السوبر أدمن المركزية للمستخدم: {username}",
                        target_model="User",
                        target_id=user.id
                    )
                    messages.success(request, f'مرحباً بك {user.get_full_name() or user.username}، تم تسجيل دخولك بنجاح كمدير عام للمنظومة (سوبر أدمن).')
                    if redirect_to and not redirect_to.startswith('/super-admin/login'):
                        return redirect(redirect_to)
                    return redirect('training:super_admin_dashboard')
                else:
                    messages.error(request, 'عفواً، هذا الحساب لا يملك صلاحيات السوبر أدمن (المدير العام للمنظومة). يرجى استخدام بوابة تسجيل دخول المعاهد.')
            else:
                messages.error(request, 'اسم المستخدم أو كلمة المرور غير صحيحة. يرجى التحقق وإعادة المحاولة.')
        else:
            messages.error(request, 'يرجى إدخال اسم المستخدم وكلمة المرور بشكل صحيح.')
    else:
        form = UserLoginForm()

    return render(request, 'training/super_admin/login.html', {
        'form': form,
        'next': redirect_to,
    })


def super_admin_logout_view(request):
    """تسجيل خروج السوبر أدمن والتحويل لصفحة تسجيل دخول السوبر أدمن"""
    if request.user.is_authenticated:
        username = request.user.username
        user_id = request.user.id
        logout(request)
        request.session.pop('active_institute_id', None)
        log_activity(
            request=request,
            action_type=ActivityAction.LOGOUT,
            action_category=ActivityCategory.AUTH,
            description=f"تسجيل الخروج من بوابة السوبر أدمن المركزية للمستخدم: {username}",
            target_model="User",
            target_id=user_id
        )
        messages.info(request, 'تم تسجيل خروج السوبر أدمن بنجاح.')
    return redirect('training:super_admin_login')


@super_admin_required
def super_admin_dashboard_view(request):
    """لوحة تحكم السوبر أدمن المركزية: عرض كافة الأنظمة والمعاهد وإحصائياتها والتحكم بها"""
    institutes = Institute.objects.all().order_by('id')

    institutes_data = []
    for inst in institutes:
        admin_profiles = inst.user_profiles.filter(role=UserRole.ADMIN).select_related('user')
        institutes_data.append({
            'institute': inst,
            'trainees_count': inst.trainees.count(),
            'courses_count': inst.courses.count(),
            'sessions_count': inst.sessions.count(),
            'active_sessions_count': inst.sessions.filter(status='active').count(),
            'instructors_count': inst.instructors.count(),
            'users_count': inst.user_profiles.count(),
            'admins': admin_profiles,
        })

    stats = {
        'institutes_total': institutes.count(),
        'institutes_active': institutes.filter(is_active=True).count(),
        'trainees_total': Trainee.objects.count(),
        'courses_total': Course.objects.count(),
        'sessions_total': CourseSession.objects.count(),
        'active_sessions_total': CourseSession.objects.filter(status='active').count(),
        'instructors_total': Instructor.objects.count(),
        'users_total': User.objects.count(),
        'super_admins_count': User.objects.filter(Q(is_superuser=True) | Q(profile__role=UserRole.SUPER_ADMIN)).distinct().count(),
        'admins_count': UserProfile.objects.filter(role=UserRole.ADMIN).count(),
    }

    institute_filter_id = request.GET.get('institute_filter', '').strip()
    selected_filter_institute = None
    activities_qs = ActivityLog.objects.select_related('institute', 'user').order_by('-timestamp')
    if institute_filter_id:
        if institute_filter_id.isdigit():
            selected_filter_institute = Institute.objects.filter(pk=int(institute_filter_id)).first()
            if selected_filter_institute:
                activities_qs = activities_qs.filter(institute=selected_filter_institute)

    recent_activities = activities_qs[:40]

    # جلب حسابات مدراء الأنظمة والسوبر أدمن للتحكم بصلاحياتهم
    admin_users = User.objects.select_related('profile', 'profile__institute').filter(
        Q(is_superuser=True) |
        Q(is_staff=True) |
        Q(profile__role__in=[UserRole.SUPER_ADMIN, UserRole.ADMIN])
    ).distinct().order_by('-is_superuser', 'profile__role', 'username')

    context = {
        'institutes_data': institutes_data,
        'institutes': institutes,
        'stats': stats,
        'recent_activities': recent_activities,
        'selected_filter_institute': selected_filter_institute,
        'selected_institute_id': institute_filter_id,
        'admin_users': admin_users,
        'officer_ranks': OFFICER_RANKS,
        'user_roles': UserRole.choices,
    }
    return render(request, 'training/super_admin/dashboard.html', context)


@super_admin_required
def super_admin_institute_create_view(request):
    """إنشاء نظام معهد / منشأة تدريبية جديدة مع توليد المعرف وحساب المدير والإعدادات القياسية"""
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        code = request.POST.get('code', '').strip().lower()
        parent_unit = request.POST.get('parent_unit', '').strip()
        logo = request.FILES.get('logo')

        admin_username = request.POST.get('admin_username', '').strip()
        admin_password = request.POST.get('admin_password', '').strip()
        admin_name = request.POST.get('admin_name', '').strip()
        admin_rank = request.POST.get('admin_rank', '').strip()
        admin_military_number = request.POST.get('admin_military_number', '').strip()
        admin_phone = request.POST.get('admin_phone', '').strip()

        errors = []
        if not name:
            errors.append('اسم المعهد / المنشأة التعليمية مطلوب.')
        if not code:
            errors.append('رمز المعهد (ID فريد) مطلوب.')
        elif Institute.objects.filter(code=code).exists():
            errors.append(f'رمز المعهد "{code}" مستخدم مسبقاً! الرجاء اختيار رمز فريد آخر.')

        if not admin_username:
            errors.append('اسم المستخدم لمدير المعهد مطلوب.')
        elif User.objects.filter(username=admin_username).exists():
            errors.append(f'اسم المستخدم "{admin_username}" مسجل مسبقاً! الرجاء اختيار اسم مستخدم آخر.')

        if not admin_password:
            errors.append('كلمة المرور لمدير المعهد مطلوبة.')
        elif len(admin_password) < 4:
            errors.append('كلمة المرور يجب أن لا تقل عن 4 خانات.')

        if errors:
            for err in errors:
                messages.error(request, err)
            return render(request, 'training/super_admin/institute_create.html', {
                'name': name,
                'code': code,
                'parent_unit': parent_unit,
                'admin_username': admin_username,
                'admin_name': admin_name,
                'admin_rank': admin_rank,
                'admin_military_number': admin_military_number,
                'admin_phone': admin_phone,
                'officer_ranks': OFFICER_RANKS,
            })

        # إنشاء المعهد
        institute = Institute.objects.create(
            name=name,
            code=code,
            parent_unit=parent_unit,
            logo=logo,
            is_active=True
        )

        # تهيئة إعدادات المعهد والقوالب وحساب المدير
        admin_data = {
            'username': admin_username,
            'password': admin_password,
            'name': admin_name,
            'rank': admin_rank,
            'military_number': admin_military_number,
            'phone': admin_phone,
        }
        initialize_new_institute(institute, admin_data=admin_data, created_by_user=request.user)

        log_activity(
            request=request,
            action_type=ActivityAction.CREATE,
            action_category=ActivityCategory.SYSTEM,
            description=f"إنشاء نظام معهد جديد: {institute.name} (رمز: {institute.code}) وحساب مديره: {admin_username}",
            target_model="Institute",
            target_id=institute.id,
            institute=institute
        )

        messages.success(request, f'تم بنجاح إنشاء نظام "{institute.name}" (ID: {institute.code}) وتجهيز نماذج الدورات القياسية وهوية الشهادات، وحساب المدير المعتمد "{admin_username}".')
        return redirect('training:super_admin_dashboard')

    return render(request, 'training/super_admin/institute_create.html', {
        'officer_ranks': OFFICER_RANKS,
    })


@super_admin_required
def super_admin_institute_edit_view(request, institute_id):
    """تعديل بيانات المعهد أو تحديث شعاره وحالته"""
    institute = get_object_or_404(Institute, id=institute_id)
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        parent_unit = request.POST.get('parent_unit', '').strip()
        code = request.POST.get('code', '').strip().lower()
        is_active = request.POST.get('is_active') == '1'

        if not name:
            messages.error(request, 'اسم المعهد مطلوب.')
            return redirect('training:super_admin_dashboard')

        if code and code != institute.code:
            if Institute.objects.filter(code=code).exclude(id=institute.id).exists():
                messages.error(request, f'رمز المعهد "{code}" مستخدم لمعهد آخر.')
                return redirect('training:super_admin_dashboard')
            institute.code = code

        institute.name = name
        institute.parent_unit = parent_unit
        institute.is_active = is_active
        if request.FILES.get('logo'):
            institute.logo = request.FILES.get('logo')
        institute.save()

        messages.success(request, f'تم تحديث بيانات نظام {institute.name} بنجاح.')
        return redirect('training:super_admin_dashboard')

    return redirect('training:super_admin_dashboard')


@super_admin_required
def super_admin_institute_toggle_status_view(request, institute_id):
    """تجميد أو تنشيط نظام المعهد"""
    institute = get_object_or_404(Institute, id=institute_id)
    institute.is_active = not institute.is_active
    institute.save()
    status_label = 'تنشيط' if institute.is_active else 'تجميد'
    messages.success(request, f'تم {status_label} نظام {institute.name} بنجاح.')
    return redirect('training:super_admin_dashboard')


@super_admin_required
def super_admin_user_create_view(request):
    """إضافة مستخدم سوبر أدمن جديد أو مدير نظام من صفحة السوبر أدمن"""
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        role = request.POST.get('role', UserRole.SUPER_ADMIN).strip()
        institute_id = request.POST.get('institute', '').strip()
        rank = request.POST.get('rank', '').strip()
        military_number = request.POST.get('military_number', '').strip()
        unit = request.POST.get('unit', '').strip()
        phone = request.POST.get('phone', '').strip()
        is_active = request.POST.get('is_active') == '1'

        errors = []
        if not username:
            errors.append('اسم المستخدم مطلوب.')
        elif User.objects.filter(username__iexact=username).exists():
            errors.append(f'اسم المستخدم "{username}" مسجل مسبقاً! الرجاء اختيار اسم آخر.')

        if not password:
            errors.append('كلمة المرور مطلوبة.')
        elif len(password) < 4:
            errors.append('كلمة المرور يجب أن لا تقل عن 4 خانات.')

        valid_roles = [c[0] for c in UserRole.choices]
        if role not in valid_roles:
            role = UserRole.SUPER_ADMIN

        if errors:
            for err in errors:
                messages.error(request, err)
            return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")

        # إنشاء المستخدم
        is_super = (role == UserRole.SUPER_ADMIN)
        is_staff_val = True if (is_super or role == UserRole.ADMIN) else False
        user = User.objects.create_user(
            username=username,
            password=password,
            first_name=first_name,
            last_name=last_name,
            email=email,
            is_active=is_active
        )
        user.is_superuser = is_super
        user.is_staff = is_staff_val
        user.save()

        # إنشاء أو تحديث البروفايل
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role
        if not is_super and institute_id and institute_id.isdigit():
            inst = Institute.objects.filter(id=int(institute_id)).first()
            profile.institute = inst
        else:
            profile.institute = None

        profile.rank = rank
        profile.military_number = military_number
        profile.unit = unit
        profile.phone = phone

        if is_super or role == UserRole.ADMIN:
            profile.can_manage_users = True
            profile.can_view = True
            profile.can_add = True
            profile.can_edit = True
            profile.can_delete = True
            profile.can_grade = True
            profile.can_approve_results = True
        else:
            profile.sync_permissions_from_role()

        profile.save()

        log_activity(
            request=request,
            action_type=ActivityAction.CREATE,
            action_category=ActivityCategory.USERS,
            description=f"إنشاء حساب {profile.get_role_display()} جديد: {username} بواسطة السوبر أدمن",
            target_model="User",
            target_id=user.id,
            institute=profile.institute
        )

        messages.success(request, f'تم بنجاح إنشاء وتفعيل حساب "{username}" بصلاحية ({profile.get_role_display()}).')
        return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")

    return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")


@super_admin_required
def super_admin_user_edit_view(request, user_id):
    """تعديل بيانات وصلاحية حسابات مدراء الأنظمة والسوبر أدمن بواسطة السوبر أدمن"""
    target_user = get_object_or_404(User.objects.select_related('profile', 'profile__institute'), pk=user_id)
    profile = getattr(target_user, 'profile', None)
    if not profile:
        profile = UserProfile.objects.create(user=target_user)

    if request.method == 'POST':
        is_self = (target_user.id == request.user.id)

        role = request.POST.get('role', '').strip()
        institute_id = request.POST.get('institute', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        rank = request.POST.get('rank', '').strip()
        military_number = request.POST.get('military_number', '').strip()
        unit = request.POST.get('unit', '').strip()
        phone = request.POST.get('phone', '').strip()
        new_password = request.POST.get('new_password', '').strip()
        is_active = request.POST.get('is_active') == '1'

        # منع السوبر أدمن من إزالة صلاحية السوبر أدمن عن نفسه لتجنب قفل الحساب
        if is_self and role != UserRole.SUPER_ADMIN:
            messages.error(request, 'لا يمكنك إزالة صلاحية السوبر أدمن عن حسابك الشخصي الحالي لتجنب فقدان الوصول إلى إدارة المنظومة.')
            return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")

        # منع السوبر أدمن من تعطيل حسابه الحالي
        if is_self and not is_active:
            messages.error(request, 'لا يمكنك تعطيل حسابك الشخصي الحالي.')
            return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")

        valid_roles = [c[0] for c in UserRole.choices]
        if role and role in valid_roles:
            profile.role = role
        else:
            messages.error(request, 'نوع الصلاحية المحدد غير صالح.')
            return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")

        # تعيين المعهد
        if role == UserRole.SUPER_ADMIN and not institute_id:
            profile.institute = None
        elif institute_id and institute_id.isdigit():
            inst = Institute.objects.filter(id=int(institute_id)).first()
            profile.institute = inst
        else:
            profile.institute = None

        # تحديث بيانات User
        target_user.first_name = first_name
        target_user.last_name = last_name
        target_user.email = email
        target_user.is_active = is_active

        if role == UserRole.SUPER_ADMIN:
            target_user.is_superuser = True
            target_user.is_staff = True
            profile.can_manage_users = True
            profile.can_view = True
            profile.can_add = True
            profile.can_edit = True
            profile.can_delete = True
            profile.can_grade = True
            profile.can_approve_results = True
        elif role == UserRole.ADMIN:
            target_user.is_superuser = False
            target_user.is_staff = True
            profile.can_manage_users = True
            profile.can_view = True
            profile.can_add = True
            profile.can_edit = True
            profile.can_delete = True
            profile.can_grade = True
            profile.can_approve_results = True
        else:
            if not is_self:
                target_user.is_superuser = False
                target_user.is_staff = False
            profile.sync_permissions_from_role()

        # أذونات مربعات الاختيار
        if 'can_manage_users' in request.POST:
            profile.can_manage_users = request.POST.get('can_manage_users') == '1'
        if 'can_view' in request.POST:
            profile.can_view = request.POST.get('can_view') == '1'
        if 'can_add' in request.POST:
            profile.can_add = request.POST.get('can_add') == '1'
        if 'can_edit' in request.POST:
            profile.can_edit = request.POST.get('can_edit') == '1'
        if 'can_delete' in request.POST:
            profile.can_delete = request.POST.get('can_delete') == '1'
        if 'can_grade' in request.POST:
            profile.can_grade = request.POST.get('can_grade') == '1'
        if 'can_approve_results' in request.POST:
            profile.can_approve_results = request.POST.get('can_approve_results') == '1'

        if new_password:
            if len(new_password) < 4:
                messages.error(request, 'كلمة المرور الجديدة يجب ألا تقل عن 4 خانات.')
                return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")
            target_user.set_password(new_password)

        target_user.save()

        profile.rank = rank
        profile.military_number = military_number
        profile.unit = unit
        profile.phone = phone
        profile.save()

        log_activity(
            request=request,
            action_type=ActivityAction.UPDATE,
            action_category=ActivityCategory.USERS,
            description=f"تعديل حساب وصلاحية المستخدم: {target_user.username} إلى ({profile.get_role_display()}) بواسطة السوبر أدمن",
            target_model="User",
            target_id=target_user.id,
            institute=profile.institute
        )

        messages.success(request, f'تم بنجاح تحديث بيانات وصلاحية حساب "{target_user.username}" ({profile.get_role_display()}).')
        return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")

    return redirect(f"{reverse('training:super_admin_dashboard')}#admin_users_section")


@super_admin_required
def super_admin_switch_institute_view(request, institute_id):
    """تبديل السياق والدخول لإدارة وتصفح نظام معهد معين كمدير كامل الصلاحيات"""
    institute = get_object_or_404(Institute, id=institute_id)
    request.session['active_institute_id'] = institute.id
    messages.success(request, f'أنت الآن تتصفح وتدير نظام: {institute.name} ({institute.code}) بصلاحيات السوبر أدمن الكاملة.')
    return redirect('training:home')


@super_admin_required
def super_admin_exit_switch_view(request):
    """الخروج من سياق المعهد والعودة إلى لوحة السوبر أدمن المركزية"""
    request.session.pop('active_institute_id', None)
    messages.info(request, 'تمت العودة بنجاح إلى لوحة تحكم السوبر أدمن المركزية.')
    return redirect('training:super_admin_dashboard')



