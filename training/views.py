import json
from datetime import timedelta
from functools import wraps
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Avg, Sum, Max, Min, ProtectedError
from .models import (
    Instructor, SessionSubjectInstructor,
    Trainee, TraineeCategory, CourseCategory, Course, Subject,
    CourseSession, CourseEnrollment, TraineeSubjectGrade,
    CertificateSettings, SystemSettings, UserProfile, UserRole,
    has_trainee_passed_course,
    ActivityLog, ActivityAction, ActivityCategory, log_activity
)
from .forms import (
    InstructorForm, TraineeForm, CourseForm, SubjectForm, CourseSessionForm,
    UserLoginForm, CourseCategoryForm, CertificateSettingsForm,
    SystemSettingsForm, UserCreateForm, UserEditForm, AdminLoginForm
)


def is_admin_user(user):
    """التحقق مما إذا كان المستخدم يملك صلاحية مدير النظام أو تحكم كامل"""
    if not user or not user.is_authenticated:
        return False
    return bool(
        user.is_superuser or 
        user.is_staff or 
        (hasattr(user, 'profile') and (user.profile.role == UserRole.ADMIN or user.profile.can_manage_users))
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
                new_trainee = form.save()
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

    trainees = Trainee.objects.all().prefetch_related('relatives', 'enrollments')

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

    counts = {
        'all': Trainee.objects.count(),
        'officer': Trainee.objects.filter(category=TraineeCategory.OFFICER).count(),
        'nco': Trainee.objects.filter(category=TraineeCategory.NCO).count(),
        'civilian': Trainee.objects.filter(category=TraineeCategory.CIVILIAN).count(),
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

    cat_id = request.GET.get('category_id')
    selected_category = None
    if cat_id:
        selected_category = CourseCategory.objects.filter(pk=cat_id).first()
    if not selected_category and categories.exists():
        selected_category = categories.first()

    courses = []
    if selected_category:
        courses = selected_category.courses.annotate(subjects_count=Count('subjects')).all()

    course_id = request.GET.get('course_id')
    selected_course = None
    if course_id:
        selected_course = Course.objects.filter(pk=course_id).first()
    if not selected_course and courses.exists():
        selected_course = courses.first()

    subjects = []
    if selected_course:
        subjects = selected_course.subjects.all()

    if request.method == 'POST' and 'add_course' in request.POST:
        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، إضافة دورة جديدة محصورة بمسجل البيانات أو مدير النظام.')
            return redirect(request.path)

        course_form = CourseForm(request.POST)
        if course_form.is_valid():
            new_course = course_form.save()
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
    categories = CourseCategory.objects.all()

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


@registrar_required
def course_session_create_view(request):
    """
    إنشاء انعقاد دورة جديدة وربط الطلبة بالدورة:
    - اختيار تصنيف الدورة واسم الدورة وتاريخها.
    - اختيار الطلبة الدارسين مع إمكانية تعديل الرتبة والوحدة وقت الدورة.
    - حفظ الانعقاد والطلبة.
    """
    categories = CourseCategory.objects.prefetch_related('courses__subjects').all()
    trainees = Trainee.objects.all().order_by('category', 'name')
    instructors = Instructor.objects.filter(is_active=True).order_by('name')

    if request.method == 'POST':
        course_id = request.POST.get('course')
        session_code = request.POST.get('session_code', '').strip()
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
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
            messages.error(request, 'يرجى استكمال جميع بيانات الدورة الأساسية (الدورة، رمز الدفعة، تاريخ البداية والنهاية).')
        elif not selected_trainee_nums:
            messages.error(request, 'يرجى اختيار دارس واحد على الأقل للالتحاق بهذه الدورة.')
        elif missing_movement:
            names_str = '، '.join(missing_movement[:4])
            if len(missing_movement) > 4:
                names_str += f' وغيرهم (إجمالي {len(missing_movement)} دارس)'
            messages.error(request, f'قيد إلزامي: لا يمكن حفظ الدورة؛ نظراً لعدم استكمال تاريخ أمر التحرك أو إرفاق صورة scan لأمر التحرك للدارس(ين): {names_str}. يرجى استكمال بيانات أمر التحرك لكل دارس تم تحديده.')
        else:
            course = get_object_or_404(Course, pk=course_id)

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
                    course=course,
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

                # تعيين المعلمين لمواد الدورة
                for sub in course.subjects.all():
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
                for s in c.subjects.all()
            ]

    return render(request, 'training/course_session_create.html', {
        'categories': categories,
        'trainees': trainees,
        'instructors': instructors,
        'courses_subjects_json': json.dumps(courses_subjects_map, ensure_ascii=False),
        'trainees_passed_json': json.dumps(trainees_passed_map, ensure_ascii=False),
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

        for sub in session.course.subjects.all():
            t_num = request.POST.get(f'subject_teacher_{sub.id}', '').strip()
            inst = Instructor.objects.filter(military_number=t_num).first() if t_num else None
            SessionSubjectInstructor.objects.update_or_create(
                session=session,
                subject=sub,
                defaults={'instructor': inst}
            )
        messages.success(request, 'تم حفظ وتحديث بيانات مشرف الدورة ومعلمي المواد الدراسية بنجاح.')
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

    # قائمة الدارسين غير المسجلين في هذه الدورة لإمكانية إضافتهم
    enrolled_trainee_ids = enrollments.values_list('trainee_id', flat=True)
    available_trainees = Trainee.objects.exclude(military_number__in=enrolled_trainee_ids)

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
    assigned_subject_ids = {a.subject_id for a in session_subject_instructors}
    for sub in session.course.subjects.all():
        if sub.id not in assigned_subject_ids:
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

    # فلاتر تبويب الدورات المتاحة لرصد الدرجات
    session_q = request.GET.get('session_q', '').strip()
    session_cat = request.GET.get('session_cat', '').strip()
    session_status = request.GET.get('session_status', '').strip()
    session_year = request.GET.get('session_year', '').strip()

    sessions = CourseSession.objects.select_related('course', 'course__category').prefetch_related('enrollments').all()

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

    historical_enrollments = CourseEnrollment.objects.filter(is_graded=True).select_related(
        'trainee', 'session', 'session__course', 'session__course__category'
    ).order_by('-session__start_date', '-percentage')

    # دورات السجل التاريخي الشامل
    archive_sessions = CourseSession.objects.select_related(
        'course', 'course__category', 'supervisor'
    ).prefetch_related(
        'enrollments', 'enrollments__trainee', 'enrollments__grades'
    ).all().order_by('-start_date', '-id')

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
    total_graded = CourseEnrollment.objects.filter(is_graded=True).count()
    excellent_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=85).count()
    vgood_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=75, percentage__lt=85).count()
    good_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=65, percentage__lt=75).count()
    pass_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=50, percentage__lt=65).count()

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
        selected_archive_session = CourseSession.objects.filter(pk=archive_session_id).select_related(
            'course', 'course__category', 'supervisor'
        ).prefetch_related(
            'course__subjects', 'subject_instructors__instructor',
            'enrollments__trainee', 'enrollments__grades'
        ).first()

        if selected_archive_session:
            selected_archive_subjects = list(selected_archive_session.course.subjects.all())
            selected_archive_enrollments = selected_archive_session.enrollments.select_related('trainee').prefetch_related('grades').all()
            selected_archive_total_possible = (selected_archive_session.course.total_max_marks or 0) + (selected_archive_session.attendance_max_grade or 0)
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
    subjects = list(session.course.subjects.all())
    enrollments = session.enrollments.select_related('trainee').prefetch_related('grades').all()

    # خريطة المعلمين المسندين لمواد الدورة
    subject_instructors_map = {
        si.subject_id: si.instructor 
        for si in session.subject_instructors.all()
    }
    for sub in subjects:
        sub.assigned_instructor = subject_instructors_map.get(sub.id)
        sub.instructor_name = sub.assigned_instructor.name if sub.assigned_instructor else 'لم يحدد'

    # تحديد دور وصلاحية المستخدم الحالي
    is_inst = is_instructor_user(request.user) and not is_admin_user(request.user)
    inst = get_user_instructor(request.user) if is_inst else None
    allowed_subject_ids = None

    if is_inst:
        if not inst:
            messages.error(request, 'عفواً، حسابك غير مرتبط بملف معلم معتمد في هيئة التدريس.')
            return redirect('training:results_center')
        
        allowed_subject_ids = set(
            session.subject_instructors.filter(instructor=inst).values_list('subject_id', flat=True)
        )
        if not allowed_subject_ids:
            messages.error(request, 'عفواً، لست مكلفاً بتدريس أي مادة في هذه الدورة المنعقدة.')
            return redirect('training:results_center')

    # فحص صلاحية الإشراف: إما دوره مشرف، أو محدد كمشرف لهذه الدورة، أو مدير نظام
    user_inst = get_user_instructor(request.user)
    is_session_supervisor = bool(user_inst and session.supervisor_id == user_inst.military_number)
    is_sup = is_supervisor_user(request.user) or is_session_supervisor or is_admin_user(request.user)

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

    # معالجة حفظ الدرجات
    if request.method == 'POST' and 'save_grades' in request.POST:
        # إذا كانت الدورة معتمدة ومكتملة، لا يُسمح بتعديل درجاتها إلا لمدير النظام
        if session.status == 'completed' and not is_admin_user(request.user):
            messages.error(request, 'إجراء محظور: نتائج هذه الدورة معتمدة ومقفلة، وتعديل الدرجات محصور بمدير النظام (Admin) فقط.')
            return redirect('training:results_entry', session_id=session.id)

        # التحقق من طلب الاعتماد (mark_completed)
        if 'mark_completed' in request.POST:
            if not is_sup:
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
                score__isnull=False
            ).count()
            missing_count = total_required_grades - total_recorded_grades

            if missing_count > 0:
                messages.error(
                    request,
                    f'لا يمكن اعتماد النتيجة نهائياً لوجود مواد لم يتم رصد درجاتها بعد من قبل المعلمين لكافة الدارسين (المتبقي: {missing_count} درجة غير مرصودة). يرجى اكتمال رصد كافة درجات المواد أولاً.'
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

        if is_inst:
            # المعلم يرصد مواده المكلف بها فقط ولا يحذف بقية المواد أو المواظبة
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

            if validation_errors:
                for err in validation_errors[:10]:
                    messages.error(request, err)
            else:
                for en in enrollments:
                    num = en.trainee.military_number
                    if f'cert_note_{num}' in request.POST:
                        en.certificate_note = request.POST.get(f'cert_note_{num}', '').strip()
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
                    # تحديث احتساب النتيجة إن اكتملت جميع المواد والمواظبة
                    if en.grades.filter(score__isnull=False).count() == len(subjects) and en.attendance_score is not None:
                        en.calculate_results()
                    else:
                        en.save(update_fields=['certificate_note'])

                log_activity(
                    request=request,
                    action_type=ActivityAction.GRADE_ENTRY,
                    action_category=ActivityCategory.GRADES,
                    description=f"رصد وحفظ درجات مادة/مواد مكلف بها في دورة '{session.course.name}' (دفعة: {session.session_code}) لعدد {len(enrollments)} دارس",
                    target_model="CourseSession",
                    target_id=session.id
                )

                messages.success(request, f'تم حفظ ورصد درجات المواد المكلف بها في دورة "{session.course.name}" بنجاح.')
                return redirect('training:results_entry', session_id=session.id)

        else:
            # مشرف الدورة أو الأدمن أو مسجل البيانات: رصد درجات المواظبة والمواد
            parsed_data = {}
            for en in enrollments:
                num = en.trainee.military_number
                att_raw = request.POST.get(f'att_{num}', '').strip()
                att_val = 0.0
                if att_raw != '':
                    try:
                        att_val = float(att_raw)
                        if att_val < 0:
                            validation_errors.append(f'درجة المواظبة للدارس "{en.trainee.name}" لا يمكن أن تكون أقل من صفر.')
                        elif att_val > float(session.attendance_max_grade):
                            validation_errors.append(f'درجة المواظبة للدارس "{en.trainee.name}" ({att_val}) تتجاوز الحد الأقصى ({session.attendance_max_grade}).')
                    except ValueError:
                        validation_errors.append(f'درجة المواظبة للدارس "{en.trainee.name}" غير صالحة ({att_raw}).')

                subject_grades_to_save = []
                for sub in subjects:
                    grade_raw = request.POST.get(f'grade_{num}_{sub.id}', '').strip()
                    if grade_raw != '':
                        try:
                            score = float(grade_raw)
                            if score < 0:
                                validation_errors.append(f'درجة مادة "{sub.name}" للدارس "{en.trainee.name}" لا يمكن أن تكون أقل من صفر.')
                            elif score > float(sub.max_grade):
                                validation_errors.append(f'درجة مادة "{sub.name}" للدارس "{en.trainee.name}" ({score}) تتجاوز الحد الأقصى للمادة ({sub.max_grade}).')
                            else:
                                subject_grades_to_save.append((sub, score))
                        except ValueError:
                            validation_errors.append(f'درجة مادة "{sub.name}" المدخلة للدارس "{en.trainee.name}" غير صالحة ({grade_raw}).')

                parsed_data[en.id] = {
                    'attendance': att_val,
                    'subjects': subject_grades_to_save,
                }

            if validation_errors:
                for err in validation_errors[:10]:
                    messages.error(request, err)
            else:
                for en in enrollments:
                    data = parsed_data[en.id]
                    num = en.trainee.military_number
                    if f'cert_note_{num}' in request.POST:
                        en.certificate_note = request.POST.get(f'cert_note_{num}', '').strip()
                    en.attendance_score = data['attendance']
                    for sub, score in data['subjects']:
                        TraineeSubjectGrade.objects.update_or_create(
                            enrollment=en,
                            subject=sub,
                            defaults={'score': score}
                        )
                    if en.grades.filter(score__isnull=False).count() == len(subjects):
                        en.calculate_results()
                    else:
                        en.save()

                log_activity(
                    request=request,
                    action_type=ActivityAction.GRADE_ENTRY,
                    action_category=ActivityCategory.GRADES,
                    description=f"رصد وحفظ درجات ومواظبة دورة '{session.course.name}' (دفعة: {session.session_code}) لعدد {len(enrollments)} دارس",
                    target_model="CourseSession",
                    target_id=session.id
                )

                messages.success(request, f'تم حفظ وتحديث الدرجات في دورة "{session.course.name}" بنجاح.')
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

    # فحص اكتمال رصد كافة درجات المواد
    total_required = len(enrollments) * len(subjects)
    total_graded = TraineeSubjectGrade.objects.filter(
        enrollment__session=session,
        score__isnull=False
    ).count()
    missing_grades_count = total_required - total_graded
    is_fully_graded = (missing_grades_count == 0 and len(subjects) > 0 and enrollments.exists())

    context = {
        'session': session,
        'subjects': subjects,
        'enrollments': enrollments,
        'total_possible_score': session.total_possible_score,
        'is_locked': is_locked,
        'is_instructor_only': is_inst,
        'allowed_subject_ids': allowed_subject_ids or set(),
        'is_supervisor_or_admin': is_sup,
        'is_fully_graded': is_fully_graded,
        'missing_grades_count': missing_grades_count,
        'from_tab': request.GET.get('from', '').strip(),
    }
    return render(request, 'training/results_entry.html', context)


@login_required
def certificate_view(request, enrollment_id):
    """استخراج وعرض شهادة التقدير الرسمية للدارس - حظر تام مالم تكتمل كافة البيانات والدرجات"""
    enrollment = get_object_or_404(
        CourseEnrollment.objects.select_related('trainee', 'session', 'session__course', 'session__course__category'),
        pk=enrollment_id
    )

    # التحقق الصارم والشامل: هل اكتملت كافة البيانات والدرجات؟
    if not enrollment.has_complete_data_and_grades:
        missing_reasons = []
        if not enrollment.trainee.military_number or not enrollment.trainee.name:
            missing_reasons.append("بيانات الدارس الأساسية (النمرة والاسم)")
        if not enrollment.current_rank or not enrollment.current_rank.strip():
            missing_reasons.append("الرتبة العسكرية للدارس")
        if not enrollment.current_unit or not enrollment.current_unit.strip():
            missing_reasons.append("الوحدة العسكرية للدارس")
        if not enrollment.session.start_date or not enrollment.session.end_date:
            missing_reasons.append("تواريخ انعقاد الدورة")
        
        total_subjects = enrollment.session.course.subjects.count()
        graded_count = enrollment.grades.count()
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

    cert_settings = CertificateSettings.get_settings()
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

    # التحقق الصارم والشامل: هل اكتملت كافة البيانات والدرجات؟
    if not enrollment.has_complete_data_and_grades:
        missing_reasons = []
        if not enrollment.trainee.military_number or not enrollment.trainee.name:
            missing_reasons.append("بيانات الدارس الأساسية (النمرة والاسم)")
        if not enrollment.current_rank or not enrollment.current_rank.strip():
            missing_reasons.append("الرتبة العسكرية للدارس")
        if not enrollment.current_unit or not enrollment.current_unit.strip():
            missing_reasons.append("الوحدة العسكرية للدارس")
        if not enrollment.session.start_date or not enrollment.session.end_date:
            missing_reasons.append("تواريخ انعقاد الدورة")
        
        total_subjects = enrollment.session.course.subjects.count()
        graded_count = enrollment.grades.count()
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

    cert_settings = CertificateSettings.get_settings()
    cert_type = request.GET.get('type', 'basic').lower()
    
    if cert_type == 'advanced':
        page_title = cert_settings.advanced_cert_title
        cert_badge = 'شهادة دورة حاسوب متقدمة'
    else:
        page_title = cert_settings.basic_cert_title
        cert_badge = 'شهادة دورة حاسوب أساسية'

    # تجهيز درجات المواد
    subjects = list(enrollment.session.course.subjects.all())
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
        'cert_type': cert_type,
        'page_title': page_title,
        'cert_badge': cert_badge,
        'subjects_data': subjects_data,
        'note_text': note_text,
    })


@login_required
def session_results_sheet_view(request, session_id):
    """كشف النتيجة العام والمعتمد للدورة المنعقدة بالكامل للطباعة والتصدير"""
    session = get_object_or_404(
        CourseSession.objects.select_related('course', 'course__category').prefetch_related('course__subjects'),
        pk=session_id
    )
    subjects = list(session.course.subjects.all())
    enrollments = session.enrollments.select_related('trainee').prefetch_related('grades').order_by('-total_score')

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
    """السجل الأكاديمي التاريخي الكامل لدارس محدد مع دعم الاسترجاع كـ JSON للنوافذ المنبثقة"""
    trainee = get_object_or_404(Trainee, military_number=military_number)
    enrollments = trainee.enrollments.select_related(
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
                'cert_basic_url': f"{reverse('training:certificate_detailed', args=[en.id])}?type=basic",
                'cert_advanced_url': f"{reverse('training:certificate_detailed', args=[en.id])}?type=advanced",
            })
        return JsonResponse({
            'success': True,
            'name': trainee.name,
            'military_number': trainee.military_number,
            'rank': trainee.rank,
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
    """صفحة تسجيل الدخول الموحدة للنظام - تحويل الأدمن مباشرة لبوابة الأدمن المنفصلة"""
    if request.user.is_authenticated:
        is_admin = (
            request.user.is_superuser or 
            request.user.is_staff or 
            (hasattr(request.user, 'profile') and request.user.profile.role == UserRole.ADMIN)
        )
        if is_admin:
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
                is_admin = (
                    user.is_superuser or 
                    user.is_staff or 
                    (hasattr(user, 'profile') and user.profile.role == UserRole.ADMIN)
                )
                
                # توجيه فوري: إذا كان المستخدم أدمن، يتم توجيهه مباشرة إلى لوحة الأدمن المنفصلة!
                if is_admin:
                    messages.success(request, f'مرحباً بك {user.get_full_name() or user.username}، تم تسجيل دخولك بنجاح ونقلك إلى لوحة الأدمن المنفصلة.')
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

    courses_total = Course.objects.count()
    categories_total = CourseCategory.objects.count()
    sessions_total = CourseSession.objects.count()
    sessions_active = CourseSession.objects.filter(status='active').count()
    sessions_completed = CourseSession.objects.filter(status='completed').count()
    sessions_planned = CourseSession.objects.filter(status='planned').count()

    enrollments_total = CourseEnrollment.objects.count()
    enrollments_graded = CourseEnrollment.objects.filter(is_graded=True).count()
    completion_rate = round((enrollments_graded / enrollments_total * 100), 1) if enrollments_total > 0 else 0

    avg_score_res = CourseEnrollment.objects.filter(is_graded=True).aggregate(avg_score=Avg('percentage'))
    avg_score = round(avg_score_res['avg_score'], 1) if avg_score_res['avg_score'] is not None else 0.0

    # 2. توزيع التقديرات (Grade Distribution)
    grade_a = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=85).count()
    grade_b = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=75, percentage__lt=85).count()
    grade_c = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=65, percentage__lt=75).count()
    grade_d = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=50, percentage__lt=65).count()
    grade_f = CourseEnrollment.objects.filter(is_graded=True, percentage__lt=50).count()

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
    forces_stats = Trainee.objects.values('force').annotate(count=Count('military_number')).order_by('-count')
    forces_list = []
    for item in forces_stats:
        forces_list.append({
            'name': item['force'] or 'غير محدد',
            'count': item['count'],
            'pct': calc_pct(item['count'], trainees_total)
        })

    # 4. توزيع الدارسين بحسب الوحدات (Top Units)
    top_units = Trainee.objects.values('unit').annotate(count=Count('military_number')).order_by('-count')[:6]

    # 5. تصنيفات الدورات
    categories = CourseCategory.objects.annotate(courses_count=Count('courses')).order_by('name')

    # 6. إدارة المستخدمين والصلاحيات
    users = User.objects.select_related('profile', 'profile__instructor').order_by('-date_joined')
    user_create_form = UserCreateForm()
    instructors = Instructor.objects.all().order_by('-created_at')
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
    cert_settings = CertificateSettings.get_settings()
    cert_form = CertificateSettingsForm(instance=cert_settings)

    # 8. إعدادات وهوية وألوان وشعار النظام بالكامل
    system_settings = SystemSettings.get_settings()
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

    activity_logs_total = ActivityLog.objects.count()
    activity_logs_today = ActivityLog.objects.filter(timestamp__date=today).count()
    activity_logs_creates = ActivityLog.objects.filter(action_type=ActivityAction.CREATE).count()
    activity_logs_updates = ActivityLog.objects.filter(action_type=ActivityAction.UPDATE).count()
    activity_logs_deletes = ActivityLog.objects.filter(action_type=ActivityAction.DELETE).count()
    activity_logs_sessions = ActivityLog.objects.filter(action_type__in=[ActivityAction.LOGIN, ActivityAction.LOGOUT]).count()
    activity_logs_grades = ActivityLog.objects.filter(action_type__in=[ActivityAction.GRADE_ENTRY, ActivityAction.GRADE_APPROVAL]).count()

    activity_logs = list(activity_qs[:300])
    activity_users_list = User.objects.all().order_by('username')

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
                inst = form.save()
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
    cert_settings = CertificateSettings.get_settings()
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
# تخصيص اللوغو الرئيسي وألوان وهوية النظام بالكامل (System Branding & Themes)
# =====================================================================
@admin_access_required
def system_settings_update_view(request):
    """حفظ وتعديل اللوغو الرئيسي وألوان وهوية النظام بالكامل أو تطبيق ثيم جاهز"""
    system_settings = SystemSettings.get_settings()

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
            category = form.save()
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
    """تفريغ وتنظيف سجل النشاط والعمليات من لوحة الأدمن مع توثيق عملية التفريغ"""
    if request.method == 'POST':
        count = ActivityLog.objects.count()
        ActivityLog.objects.all().delete()
        log_activity(
            request=request,
            action_type=ActivityAction.DELETE,
            action_category=ActivityCategory.SYSTEM,
            description=f"قام مدير النظام بتفريغ وحذف سجل النشاط والعمليات السابق بالكامل (كان يحتوي على {count} عملية مسجلة)."
        )
        messages.success(request, f'تم تفريغ وحذف سجل النشاط السابق بنجاح ({count} سجل تم تنظيفها).')
    return redirect(f"{reverse('training:admin_dashboard')}?tab=activity-log#pane-activity-log")


# =====================================================================
# تقرير التحليل والإحصاء الشامل القابل للطباعة
# =====================================================================
@admin_access_required
def admin_report_print_view(request):
    """تقرير تحليلي تنفيذي رسمي جاهز للطباعة لقيادة المعهد والإدارة"""
    trainees_total = Trainee.objects.count()
    trainees_officers = Trainee.objects.filter(category=TraineeCategory.OFFICER).count()
    trainees_ncos = Trainee.objects.filter(category=TraineeCategory.NCO).count()
    trainees_civilians = Trainee.objects.filter(category=TraineeCategory.CIVILIAN).count()

    courses_total = Course.objects.count()
    categories = CourseCategory.objects.annotate(courses_count=Count('courses')).order_by('name')
    sessions = CourseSession.objects.select_related('course', 'course__category').annotate(
        enrolled_count=Count('enrollments')
    ).order_by('-start_date')

    enrollments_total = CourseEnrollment.objects.count()
    enrollments_graded = CourseEnrollment.objects.filter(is_graded=True).count()
    avg_score_res = CourseEnrollment.objects.filter(is_graded=True).aggregate(avg_score=Avg('percentage'))
    avg_score = round(avg_score_res['avg_score'], 1) if avg_score_res['avg_score'] is not None else 0.0

    grade_a = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=85).count()
    grade_b = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=75, percentage__lt=85).count()
    grade_c = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=65, percentage__lt=75).count()
    grade_d = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=50, percentage__lt=65).count()
    grade_f = CourseEnrollment.objects.filter(is_graded=True, percentage__lt=50).count()

    def calc_pct(part, whole):
        return round((part / whole * 100), 1) if whole > 0 else 0

    forces_stats = Trainee.objects.values('force').annotate(count=Count('military_number')).order_by('-count')
    cert_settings = CertificateSettings.get_settings()
    system_settings = SystemSettings.get_settings()

    return render(request, 'training/admin_report_print.html', {
        'trainees_total': trainees_total,
        'trainees_officers': trainees_officers,
        'trainees_ncos': trainees_ncos,
        'trainees_civilians': trainees_civilians,
        'courses_total': courses_total,
        'categories': categories,
        'sessions': sessions,
        'enrollments_total': enrollments_total,
        'enrollments_graded': enrollments_graded,
        'avg_score': avg_score,
        'grade_a': grade_a,
        'grade_b': grade_b,
        'grade_c': grade_c,
        'grade_d': grade_d,
        'grade_f': grade_f,
        'grade_a_pct': calc_pct(grade_a, enrollments_graded),
        'grade_b_pct': calc_pct(grade_b, enrollments_graded),
        'grade_c_pct': calc_pct(grade_c, enrollments_graded),
        'grade_d_pct': calc_pct(grade_d, enrollments_graded),
        'grade_f_pct': calc_pct(grade_f, enrollments_graded),
        'forces_stats': forces_stats,
        'cert_settings': cert_settings,
        'system_settings': system_settings,
    })


