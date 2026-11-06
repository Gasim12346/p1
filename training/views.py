from functools import wraps
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse
from django.urls import reverse
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Count, Avg, Sum, Max, Min, ProtectedError
from .models import (
    Trainee, TraineeCategory, CourseCategory, Course, Subject,
    CourseSession, CourseEnrollment, TraineeSubjectGrade,
    CertificateSettings, SystemSettings, UserProfile, UserRole
)
from .forms import (
    TraineeForm, CourseForm, SubjectForm, CourseSessionForm,
    UserLoginForm, CourseCategoryForm, CertificateSettingsForm,
    SystemSettingsForm, UserCreateForm, UserEditForm, AdminLoginForm
)


@login_required
def home_view(request):
    """الواجهة الرئيسية (لوحة التحكم الشاملة)"""
    return render(request, 'training/home.html')


# ==========================================
# الواجهة 2: واجهة الدارسين (الضباط، ضباط الصف، المدنيين)
# ==========================================
@login_required
def trainees_list_view(request):
    """عرض قائمة الدارسين وإمكانية إضافة دارس جديد والبحث والتصفية"""
    category_filter = request.GET.get('category', '').strip()
    search_query = request.GET.get('q', '').strip()

    if request.method == 'POST' and 'add_trainee' in request.POST:
        form = TraineeForm(request.POST)
        if form.is_valid():
            military_num = form.cleaned_data['military_number']
            if Trainee.objects.filter(military_number=military_num).exists():
                messages.error(request, f'النمرة "{military_num}" مسجلة مسبقاً! الرجاء استخدام نمرة فريدة.')
            else:
                form.save()
                messages.success(request, f'تم حفظ بيانات الدارس "{form.cleaned_data["name"]}" بنجاح.')
                return redirect('training:trainees_list')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        form = TraineeForm()

    trainees = Trainee.objects.all()

    if category_filter in [TraineeCategory.OFFICER, TraineeCategory.NCO, TraineeCategory.CIVILIAN]:
        trainees = trainees.filter(category=category_filter)

    if search_query:
        trainees = trainees.filter(
            Q(name__icontains=search_query) |
            Q(military_number__icontains=search_query) |
            Q(unit__icontains=search_query) |
            Q(force__icontains=search_query) |
            Q(rank__icontains=search_query)
        )

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


@login_required
def trainee_edit_view(request, military_number):
    """تعديل بيانات الدارس"""
    trainee = get_object_or_404(Trainee, military_number=military_number)
    if request.method == 'POST':
        form = TraineeForm(request.POST, instance=trainee)
        form.fields['military_number'].disabled = True
        if form.is_valid():
            form.save()
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


@login_required
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
            trainee.delete()
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
# الواجهة 3: واجهة الدورات ومفرداتها وموادها
# ==========================================
@login_required
def courses_catalog_view(request):
    """واجهة الدورات ومفرداتها والمواد"""
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
        course_form = CourseForm(request.POST)
        if course_form.is_valid():
            new_course = course_form.save()
            messages.success(request, f'تم إضافة الدورة "{new_course.name}" بنجاح.')
            return redirect(f"{request.path}?category_id={new_course.category_id}&course_id={new_course.id}")
        else:
            messages.error(request, 'يرجى مراجعة بيانات الدورة والتأكد من إدخال الحقول المطلوبة.')
    else:
        initial_cat = selected_category if selected_category else None
        course_form = CourseForm(initial={'category': initial_cat})

    if request.method == 'POST' and 'add_subject' in request.POST:
        target_course_id = request.POST.get('target_course_id')
        target_course = get_object_or_404(Course, pk=target_course_id)
        subject_form = SubjectForm(request.POST)
        if subject_form.is_valid():
            new_subject = subject_form.save(commit=False)
            new_subject.course = target_course
            new_subject.save()
            messages.success(request, f'تم إضافة المادة "{new_subject.name}" للدورة بنجاح.')
            return redirect(f"{request.path}?category_id={target_course.category_id}&course_id={target_course.id}")
        else:
            messages.error(request, 'يرجى التأكد من بيانات المادة المدخلة.')
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


@login_required
def course_edit_view(request, course_id):
    """تعديل دورة موجودة"""
    course = get_object_or_404(Course, pk=course_id)
    if request.method == 'POST':
        form = CourseForm(request.POST, instance=course)
        if form.is_valid():
            form.save()
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


@login_required
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
            course.delete()
            messages.success(request, f'تم حذف الدورة "{name}" وجميع موادها بنجاح.')
        except ProtectedError:
            messages.error(request, f'تعذر حذف الدورة "{course.name}" لوجود سجلات أكاديمية مرتبطة بها.')
        return redirect(f"/courses/?category_id={category_id}")

    return render(request, 'training/course_confirm_delete.html', {
        'course': course,
        'has_sessions': has_sessions,
        'sessions_count': sessions_count,
    })


@login_required
def subject_edit_view(request, subject_id):
    """تعديل مادة دراسية"""
    subject = get_object_or_404(Subject, pk=subject_id)
    course = subject.course
    if request.method == 'POST':
        form = SubjectForm(request.POST, instance=subject)
        if form.is_valid():
            form.save()
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


@login_required
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
            subject.delete()
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
# الواجهة 4: واجهة الدورة التي يتم دراستها (انعقاد الدورات وربط الطلبة)
# ==========================================
@login_required
def course_sessions_view(request):
    """عرض قائمة الدورات المنعقدة حالياً مع إحصائيات وروابط الإدارة"""
    sessions = CourseSession.objects.select_related('course', 'course__category').prefetch_related('enrollments').all()
    categories = CourseCategory.objects.all()
    return render(request, 'training/course_sessions.html', {
        'sessions': sessions,
        'categories': categories,
    })


@login_required
def course_session_create_view(request):
    """
    إنشاء انعقاد دورة جديدة وربط الطلبة بالدورة:
    - اختيار تصنيف الدورة واسم الدورة وتاريخها.
    - اختيار الطلبة الدارسين مع إمكانية تعديل الرتبة والوحدة وقت الدورة.
    - حفظ الانعقاد والطلبة.
    """
    categories = CourseCategory.objects.prefetch_related('courses').all()
    trainees = Trainee.objects.all().order_by('category', 'name')

    if request.method == 'POST':
        course_id = request.POST.get('course')
        session_code = request.POST.get('session_code', '').strip()
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        status = request.POST.get('status', 'active')
        attendance_max_grade = request.POST.get('attendance_max_grade', '20.0')
        notes = request.POST.get('notes', '').strip()

        selected_trainee_nums = request.POST.getlist('selected_trainees')

        if not course_id or not session_code or not start_date or not end_date:
            messages.error(request, 'يرجى استكمال جميع بيانات الدورة الأساسية (الدورة، رمز الدفعة، تاريخ البداية والنهاية).')
        elif not selected_trainee_nums:
            messages.error(request, 'يرجى اختيار دارس واحد على الأقل للالتحاق بهذه الدورة.')
        else:
            course = get_object_or_404(Course, pk=course_id)
            session = CourseSession.objects.create(
                course=course,
                session_code=session_code,
                start_date=start_date,
                end_date=end_date,
                status=status,
                attendance_max_grade=attendance_max_grade or 20.0,
                notes=notes
            )

            # تسجيل الطلبة مع حفظ الرتبة والوحدة المحدثة وقت الدورة
            enrolled_count = 0
            for num in selected_trainee_nums:
                try:
                    t = Trainee.objects.get(military_number=num)
                    # قراءة الرتبة والوحدة المعدلة من النموذج
                    current_rank = request.POST.get(f'rank_{num}', t.rank).strip() or t.rank
                    current_unit = request.POST.get(f'unit_{num}', t.unit).strip() or t.unit

                    CourseEnrollment.objects.create(
                        session=session,
                        trainee=t,
                        current_rank=current_rank,
                        current_unit=current_unit
                    )
                    enrolled_count += 1
                except Trainee.DoesNotExist:
                    pass

            messages.success(request, f'تم حفظ انعقاد دورة "{course.name}" بنجاح، وتسجيل {enrolled_count} دارس بها.')
            return redirect('training:course_session_manage', session_id=session.id)

    officer_count = trainees.filter(category=TraineeCategory.OFFICER).count()
    nco_count = trainees.filter(category=TraineeCategory.NCO).count()
    civilian_count = trainees.filter(category=TraineeCategory.CIVILIAN).count()

    return render(request, 'training/course_session_create.html', {
        'categories': categories,
        'trainees': trainees,
        'officer_count': officer_count,
        'nco_count': nco_count,
        'civilian_count': civilian_count,
    })


@login_required
def course_session_manage_view(request, session_id):
    """
    إدارة وتعديل الدارسين في دورة منعقدة:
    - تعديل الرتبة والوحدة للدارسين في الدورة.
    - إضافة دارسين جدد للدورة.
    - إزالة دارس من الدورة.
    """
    session = get_object_or_404(CourseSession.objects.select_related('course', 'course__category'), pk=session_id)
    enrollments = session.enrollments.select_related('trainee').all()

    # تحديث الرتب والوحدات للدارسين المسجلين
    if request.method == 'POST' and 'update_enrollments' in request.POST:
        updated_count = 0
        for enrollment in enrollments:
            num = enrollment.trainee.military_number
            new_rank = request.POST.get(f'rank_{num}', '').strip()
            new_unit = request.POST.get(f'unit_{num}', '').strip()
            if new_rank or new_unit:
                if new_rank:
                    enrollment.current_rank = new_rank
                if new_unit:
                    enrollment.current_unit = new_unit
                enrollment.save()
                updated_count += 1

        messages.success(request, f'تم حفظ وتحديث بيانات الرتب والوحدات لـ {updated_count} دارس بالدورة بنجاح.')
        return redirect('training:course_session_manage', session_id=session.id)

    # إضافة دارسين إضافيين للدورة
    if request.method == 'POST' and 'add_extra_trainees' in request.POST:
        extra_nums = request.POST.getlist('extra_trainees')
        added = 0
        for num in extra_nums:
            t = Trainee.objects.filter(military_number=num).first()
            if t and not session.enrollments.filter(trainee=t).exists():
                r = request.POST.get(f'extra_rank_{num}', t.rank).strip() or t.rank
                u = request.POST.get(f'extra_unit_{num}', t.unit).strip() or t.unit
                CourseEnrollment.objects.create(
                    session=session,
                    trainee=t,
                    current_rank=r,
                    current_unit=u
                )
                added += 1
        if added > 0:
            messages.success(request, f'تم إلحاق {added} دارس إضافي بالدورة بنجاح.')
        return redirect('training:course_session_manage', session_id=session.id)

    # إزالة دارس من الدورة
    if request.method == 'POST' and 'remove_trainee_id' in request.POST:
        enrollment_id = request.POST.get('remove_trainee_id')
        enrollment = get_object_or_404(CourseEnrollment, pk=enrollment_id, session=session)
        t_name = enrollment.trainee.name
        enrollment.delete()
        messages.success(request, f'تم إزالة الدارس "{t_name}" من الدورة.')
        return redirect('training:course_session_manage', session_id=session.id)

    # قائمة الدارسين غير المسجلين في هذه الدورة لإمكانية إضافتهم
    enrolled_trainee_ids = enrollments.values_list('trainee_id', flat=True)
    available_trainees = Trainee.objects.exclude(military_number__in=enrolled_trainee_ids)

    context = {
        'session': session,
        'enrollments': enrollments,
        'available_trainees': available_trainees,
    }
    return render(request, 'training/course_session_manage.html', context)


@login_required
def course_session_edit_view(request, session_id):
    """تعديل بيانات انعقاد الدورة (التواريخ، الحالة، الملاحظات)"""
    session = get_object_or_404(CourseSession, pk=session_id)
    if request.method == 'POST':
        form = CourseSessionForm(request.POST, instance=session)
        if form.is_valid():
            form.save()
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


@login_required
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
            session.delete()
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
# الواجهة 5: واجهة النتيجة ورصد الدرجات والشهادات والسجل التاريخي
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

    sessions = CourseSession.objects.select_related('course', 'course__category').prefetch_related('enrollments').all()

    if session_q:
        sessions = sessions.filter(
            Q(course__name__icontains=session_q) |
            Q(session_code__icontains=session_q)
        )
    if session_cat:
        sessions = sessions.filter(course__category_id=session_cat)
    if session_status:
        sessions = sessions.filter(status=session_status)

    # فلاتر تبويب السجل التاريخي للنتائج والشهادات
    search_query = request.GET.get('q', '').strip()
    grade_filter = request.GET.get('grade', '').strip()
    trainee_cat_filter = request.GET.get('trainee_category', '').strip()
    selected_session_filter = request.GET.get('session_filter', '').strip()

    historical_enrollments = CourseEnrollment.objects.filter(is_graded=True).select_related(
        'trainee', 'session', 'session__course', 'session__course__category'
    ).order_by('-session__start_date', '-percentage')

    if search_query:
        historical_enrollments = historical_enrollments.filter(
            Q(trainee__name__icontains=search_query) |
            Q(trainee__military_number__icontains=search_query) |
            Q(current_unit__icontains=search_query) |
            Q(current_rank__icontains=search_query) |
            Q(session__course__name__icontains=search_query) |
            Q(session__session_code__icontains=search_query)
        )

    if grade_filter:
        historical_enrollments = historical_enrollments.filter(grade_label__icontains=grade_filter)

    if trainee_cat_filter:
        historical_enrollments = historical_enrollments.filter(trainee__category=trainee_cat_filter)

    if selected_session_filter:
        historical_enrollments = historical_enrollments.filter(session_id=selected_session_filter)

    # إحصائيات عامة للنتائج
    total_graded = CourseEnrollment.objects.filter(is_graded=True).count()
    excellent_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=85).count()
    vgood_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=75, percentage__lt=85).count()
    good_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=65, percentage__lt=75).count()
    pass_count = CourseEnrollment.objects.filter(is_graded=True, percentage__gte=50, percentage__lt=65).count()

    # تحديد التبويب النشط بناءً على المعاملات
    active_tab = 'archive' if (search_query or grade_filter or trainee_cat_filter or selected_session_filter or request.GET.get('tab') == 'archive') else 'sessions'

    context = {
        'sessions': sessions,
        'all_sessions': CourseSession.objects.select_related('course').all(),
        'categories': categories,
        'historical_enrollments': historical_enrollments,
        'session_q': session_q,
        'session_cat': session_cat,
        'session_status': session_status,
        'search_query': search_query,
        'grade_filter': grade_filter,
        'trainee_cat_filter': trainee_cat_filter,
        'session_filter': selected_session_filter,
        'active_tab': active_tab,
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
    واجهة رصد درجات دورة معينة:
    - تظهر جميع الطلبة في هذه الدورة.
    - إدخال درجات المواد + درجة المواظبة.
    - حساب المجموع التلقائي والنسبة ومعادلة: (مجموع الطالب * 100) / المجموع الكلي.
    - احتساب التقدير تلقائياً:
        85-100: ممتاز (أ)
        75-84: جيد جداً (ب)
        65-74: جيد (ج)
        50-64: مقبول (د)
    """
    session = get_object_or_404(
        CourseSession.objects.select_related('course', 'course__category').prefetch_related('course__subjects'),
        pk=session_id
    )
    subjects = list(session.course.subjects.all())
    enrollments = session.enrollments.select_related('trainee').prefetch_related('grades').all()

    # معالجة حفظ الدرجات
    if request.method == 'POST' and 'save_grades' in request.POST:
        for en in enrollments:
            num = en.trainee.military_number
            att_raw = request.POST.get(f'att_{num}', '').strip()

            # فحص درجات المواد هل تم إدخالها
            all_subjects_filled = True
            subject_grades_to_save = []

            for sub in subjects:
                grade_raw = request.POST.get(f'grade_{num}_{sub.id}', '').strip()
                if grade_raw == '':
                    all_subjects_filled = False
                    # حذف أي درجة مسجلة مسبقاً لهذه المادة لأن الحقل أصبح فارغاً
                    TraineeSubjectGrade.objects.filter(enrollment=en, subject=sub).delete()
                else:
                    try:
                        score = float(grade_raw)
                        subject_grades_to_save.append((sub, score))
                    except ValueError:
                        all_subjects_filled = False
                        TraineeSubjectGrade.objects.filter(enrollment=en, subject=sub).delete()

            # إذا كانت درجات جميع المواد مدخلة بالفعل
            if all_subjects_filled and len(subject_grades_to_save) == len(subjects) and len(subjects) > 0:
                # حفظ درجة المواظبة
                try:
                    en.attendance_score = float(att_raw) if att_raw != '' else 0.0
                except ValueError:
                    en.attendance_score = 0.0

                # حفظ درجات المواد
                for sub, score in subject_grades_to_save:
                    TraineeSubjectGrade.objects.update_or_create(
                        enrollment=en,
                        subject=sub,
                        defaults={'score': score}
                    )

                # احتساب النسبة والتقدير واعتماد الرصد
                en.calculate_results()
            else:
                # إذا كانت الدرجات ناقصة أو غير مدخلة، لا يتم اعتماد النتيجة له ولا تصدر له شهادة
                if len(subject_grades_to_save) > 0:
                    for sub, score in subject_grades_to_save:
                        TraineeSubjectGrade.objects.update_or_create(
                            enrollment=en,
                            subject=sub,
                            defaults={'score': score}
                        )
                en.attendance_score = 0.0
                en.total_score = 0.0
                en.percentage = 0.0
                en.grade_label = ''
                en.is_graded = False
                en.save()

        # تحديث حالة الدورة
        if 'mark_completed' in request.POST:
            session.status = 'completed'
            session.save()

        messages.success(request, f'تم حفظ وتحديث درجات الدارسين في دورة "{session.course.name}" بنجاح.')
        return redirect('training:results_entry', session_id=session.id)

    # تجهيز بيانات درجات المواد لكل دارس بشكل مباشر ومتقن للعرض
    for en in enrollments:
        en_grades = {g.subject_id: g.score for g in en.grades.all()}
        en.subjects_data = []
        for sub in subjects:
            score = en_grades.get(sub.id, None)
            en.subjects_data.append({
                'subject': sub,
                'score': score
            })

    context = {
        'session': session,
        'subjects': subjects,
        'enrollments': enrollments,
        'total_possible_score': session.total_possible_score,
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
            })
        return JsonResponse({
            'success': True,
            'name': trainee.name,
            'military_number': trainee.military_number,
            'rank': trainee.rank,
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
# الواجهة 6: تسجيل الدخول والخروج (Authentication)
# =====================================================================
def login_view(request):
    """صفحة تسجيل الدخول الموحدة للنظام - تحويل الأدمن مباشرة لواجهة الأدمن المنفصلة"""
    if request.user.is_authenticated:
        is_admin = (
            request.user.is_superuser or 
            request.user.is_staff or 
            (hasattr(request.user, 'profile') and request.user.profile.role == UserRole.ADMIN)
        )
        if is_admin:
            return redirect('training:admin_dashboard')
        return redirect('training:home')

    redirect_to = request.GET.get('next', request.POST.get('next', ''))

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
# الواجهة 7: بوابة القيادة والأدمن المنفصلة (Dedicated Admin Portal)
# =====================================================================
def admin_access_required(view_func):
    """حصر الوصول لواجهة الأدمن المنفصلة فقط على المستخدمين الذين يملكون رتبة مدير نظام أو superuser/staff"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'يرجى تسجيل الدخول بحساب مدير النظام للوصول إلى لوحة الأدمن.')
            return redirect(f"{reverse('training:login')}?next={request.path}")
        
        is_admin = (
            request.user.is_superuser or 
            request.user.is_staff or 
            (hasattr(request.user, 'profile') and request.user.profile.role == UserRole.ADMIN)
        )
        if not is_admin:
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
    users = User.objects.select_related('profile').order_by('-date_joined')
    user_create_form = UserCreateForm()

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
        # Users
        'users': users,
        'user_create_form': user_create_form,
        # Certificate Settings
        'cert_settings': cert_settings,
        'cert_form': cert_form,
        # System Branding & Themes
        'system_settings': system_settings,
        'system_form': system_form,
        'color_presets': color_presets,
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
            profile.military_number = form.cleaned_data.get('military_number', '')
            profile.rank = form.cleaned_data.get('rank', '')
            profile.unit = form.cleaned_data.get('unit', '')
            profile.phone = form.cleaned_data.get('phone', '')
            profile.save()

            messages.success(request, f'تم إنشاء حساب المستخدم الجديد "{user.username}" بنجاح وتعيين الصلاحية ({profile.get_role_display()}).')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect('training:admin_dashboard')


@admin_access_required
def user_edit_view(request, user_id):
    """تعديل بيانات وصلاحيات وكلمة مرور المستخدم"""
    target_user = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
    profile, _ = UserProfile.objects.get_or_create(user=target_user)

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
            profile.military_number = form.cleaned_data.get('military_number', '')
            profile.rank = form.cleaned_data.get('rank', '')
            profile.unit = form.cleaned_data.get('unit', '')
            profile.phone = form.cleaned_data.get('phone', '')
            profile.save()

            messages.success(request, f'تم حفظ تعديلات المستخدم "{target_user.username}" بنجاح.')
            return redirect('training:admin_dashboard')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    else:
        initial_data = {
            'role': profile.role,
            'military_number': profile.military_number,
            'rank': profile.rank,
            'unit': profile.unit,
            'phone': profile.phone,
        }
        form = UserEditForm(instance=target_user, initial=initial_data)

    return render(request, 'admin_portal/user_edit.html', {
        'form': form,
        'target_user': target_user,
        'profile': profile,
    })


@admin_access_required
def user_delete_view(request, user_id):
    """حذف مستخدم من النظام مع الحماية التامة لحساب المدير الحالي"""
    target_user = get_object_or_404(User, pk=user_id)

    if target_user.id == request.user.id:
        messages.error(request, 'إجراء محظور: لا يمكنك حذف حسابك الحالي الذي تستخدمه لتسجيل الدخول!')
        return redirect('training:admin_dashboard')

    if request.method == 'POST':
        uname = target_user.username
        target_user.delete()
        messages.success(request, f'تم حذف المستخدم "{uname}" نهائياً من النظام.')
        return redirect('training:admin_dashboard')

    return render(request, 'admin_portal/user_confirm_delete.html', {
        'target_user': target_user
    })


@admin_access_required
def user_toggle_active_view(request, user_id):
    """تفعيل أو تعطيل حساب مستخدم بنقرة واحدة"""
    target_user = get_object_or_404(User, pk=user_id)
    if target_user.id == request.user.id:
        messages.error(request, 'إجراء محظور: لا يمكنك تعطيل حسابك الحالي!')
    else:
        target_user.is_active = not target_user.is_active
        target_user.save()
        status_text = 'تفعيل' if target_user.is_active else 'تعطيل'
        messages.success(request, f'تم {status_text} حساب المستخدم "{target_user.username}" بنجاح.')
    return redirect('training:admin_dashboard')


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
            return redirect('training:admin_dashboard')

        # إعادة تعيين اللوغو الأيسر إذا طلب
        if 'reset_left_logo' in request.POST:
            cert_settings.left_logo = None
            cert_settings.save()
            messages.success(request, 'تمت إعادة تعيين الشعار الأيسر للشهادة إلى الشعار الافتراضي (شعار نظم المعلومات).')
            return redirect('training:admin_dashboard')

        form = CertificateSettingsForm(request.POST, request.FILES, instance=cert_settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم حفظ وتحديث إعدادات وتوقيعات ولوغهات الشهادة الرسمية بنجاح. ستنعكس فوراً على جميع الشهادات.')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, error)
    return redirect('training:admin_dashboard')


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
                messages.success(request, f'تم تطبيق حزمة الألوان بنجاح وانعكست على كافة واجهات النظام فوراً.')
                return redirect('training:admin_dashboard')

        # 3. حفظ النموذج المخصص
        form = SystemSettingsForm(request.POST, request.FILES, instance=system_settings)
        if form.is_valid():
            form.save()
            messages.success(request, 'تم حفظ وتحديث هوية وشعار وألوان النظام بنجاح. تنعكس الآن على كامل واجهات النظام فوراً.')
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
            category.delete()
            messages.success(request, f'تم حذف تصنيف الدورات "{category_name}" بنجاح.')
        return redirect('training:admin_dashboard')

    return render(request, 'training/category_confirm_delete.html', {
        'category': category,
        'linked_courses_count': linked_courses_count
    })


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


