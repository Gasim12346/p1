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
from django.core.exceptions import PermissionDenied
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q, Count, Avg, Sum, Max, Min, ProtectedError

from apps.core.permissions import (
    is_super_admin_user, super_admin_required,
    is_admin_user, admin_access_required, admin_required,
    is_registrar_user, registrar_required,
    is_supervisor_user, is_instructor_user, get_user_instructor,
    has_permission, check_institute_access
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
def certificate_view(request, enrollment_id):
    """استخراج وعرض شهادة التقدير الرسمية للدارس - حظر تام مالم تكتمل كافة البيانات والدرجات"""
    enrollment = get_object_or_404(
        CourseEnrollment.objects.select_related('trainee', 'session', 'session__course', 'session__course__category'),
        pk=enrollment_id
    )
    check_institute_access(request, enrollment)
    if not (is_admin_user(request.user) or is_registrar_user(request.user) or is_supervisor_user(request.user) or has_permission(request.user, 'certificates', 'view') or (hasattr(request.user, 'profile') and request.user.profile.can_view)):
        raise PermissionDenied("إجراء محظور: حسابك لا يملك صلاحية استعراض الشهادات في المنظومة.")

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
    check_institute_access(request, enrollment)
    if not (is_admin_user(request.user) or is_registrar_user(request.user) or is_supervisor_user(request.user) or has_permission(request.user, 'certificates', 'view') or (hasattr(request.user, 'profile') and request.user.profile.can_view)):
        raise PermissionDenied("إجراء محظور: حسابك لا يملك صلاحية استعراض الشهادات في المنظومة.")

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
    check_institute_access(request, enrollment)
    if not (is_admin_user(request.user) or is_supervisor_user(request.user) or is_registrar_user(request.user) or has_permission(request.user, 'movement_orders', 'view') or (hasattr(request.user, 'profile') and request.user.profile.can_view)):
        raise PermissionDenied("إجراء محظور: حسابك لا يملك صلاحية استعراض أوامر التحرك في المنظومة.")

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




@admin_access_required
def certificate_settings_update_view(request):
    """حفظ التعديلات على شكل وبيانات وتوقيعات ولوغهات الشهادة الرسمية"""
    cert_settings = CertificateSettings.get_settings(institute=request.institute)
    if request.method == 'POST':
        # إعادة تعيين اللوغو الأيمن إذا طلب
        if 'reset_right_logo' in request.POST:
            cert_settings.right_logo = None
            cert_settings.save()
            messages.success(request, 'تمت إعادة تعيين الشعار الأيمن للشهادة إلى الشعار المعتمد (صقر الجديان).')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#pane-certificate")
        # إعادة تعيين اللوغو الأيسر إذا طلب
        if 'reset_left_logo' in request.POST:
            cert_settings.left_logo = None
            cert_settings.save()
            messages.success(request, 'تمت إعادة تعيين الشعار الأيسر للشهادة إلى الشعار المعتمد (شعار نظم المعلومات).')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#subpane-cert")
        # إعادة تعيين أبعاد ومسافات الشهادة إذا طلب
        if 'reset_cert_layout' in request.POST:
            cert_settings.layout_config = {}
            cert_settings.save()
            messages.success(request, 'تمت إعادة ضبط مسافات ومواقع نصوص الشهادة إلى القيم الافتراضية بنجاح.')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#subpane-cert")

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
            messages.success(request, 'تمت إعادة تعيين العلامة المائية لأمر التحرك إلى الشعار المعتمد بنجاح.')
            return redirect(f"{reverse('training:admin_dashboard')}?tab=certificate#subpane-movement-order")
        # إعادة تعيين أبعاد ومسافات أمر التحرك إذا طلب
        if 'reset_movement_layout' in request.POST:
            movement_settings.layout_config = {}
            movement_settings.save()
            messages.success(request, 'تمت إعادة ضبط مسافات ومواقع أمر التحرك إلى القيم الافتراضية بنجاح.')
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


