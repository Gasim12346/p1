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


