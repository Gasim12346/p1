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
    is_supervisor_user, is_instructor_user, get_user_instructor,
    MODULES_PERMISSIONS_CATALOG, DEFAULT_ROLE_PERMISSIONS,
    get_default_permissions_for_role, get_user_permissions_matrix,
    has_permission, check_perm
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
def home_view(request):
    """الصفحة الرئيسية (لوحة التحكم الشاملة)"""
    if is_instructor_user(request.user) and not is_admin_user(request.user):
        return redirect('training:results_center')
    return render(request, 'training/home.html')


# ==========================================
# القسم 2: سجل الدارسين (الضباط، ضباط الصف، المدنيين)
# ==========================================


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
        'grade_distribution_json': json.dumps(grade_distribution),
        'forces_list': forces_list,
        'forces_list_json': json.dumps(forces_list),
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
        # مصفوفة الأذونات والصلاحيات الديناميكية
        'modules_permissions_catalog': MODULES_PERMISSIONS_CATALOG,
        'modules_permissions_catalog_json': json.dumps(MODULES_PERMISSIONS_CATALOG),
        'default_role_permissions_json': json.dumps(DEFAULT_ROLE_PERMISSIONS),
        'selected_matrix_user': (users.filter(id=request.GET.get('matrix_user') or request.GET.get('user_id')).first() if (request.GET.get('matrix_user') or request.GET.get('user_id')) else users.first()) if users.exists() else None,
        'selected_matrix': get_user_permissions_matrix((users.filter(id=request.GET.get('matrix_user') or request.GET.get('user_id')).first() if (request.GET.get('matrix_user') or request.GET.get('user_id')) else users.first())) if users.exists() else {},
        'selected_matrix_json': json.dumps(get_user_permissions_matrix((users.filter(id=request.GET.get('matrix_user') or request.GET.get('user_id')).first() if (request.GET.get('matrix_user') or request.GET.get('user_id')) else users.first()))) if users.exists() else '{}',
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
            if role in [UserRole.INSTRUCTOR, UserRole.SUPERVISOR]:
                profile.instructor = form.cleaned_data.get('instructor')
            else:
                profile.instructor = None
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

            # تحديث مصفوفة الأذونات والصلاحيات إن تم إرسالها
            matrix_raw = request.POST.get('permissions_matrix') or request.POST.get('permissions_matrix_json')
            if matrix_raw:
                try:
                    matrix_data = json.loads(matrix_raw)
                    if isinstance(matrix_data, dict):
                        clean_matrix = {}
                        for mod_id, mod_info in MODULES_PERMISSIONS_CATALOG.items():
                            clean_matrix[mod_id] = {}
                            mod_input = matrix_data.get(mod_id, {})
                            if isinstance(mod_input, dict):
                                for act_id in mod_info['actions']:
                                    clean_matrix[mod_id][act_id] = bool(mod_input.get(act_id, False))
                        profile.permissions_matrix = clean_matrix
                except Exception:
                    pass
            elif role != UserRole.CUSTOM and not profile.permissions_matrix:
                profile.permissions_matrix = get_default_permissions_for_role(role)

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
            if role in [UserRole.INSTRUCTOR, UserRole.SUPERVISOR]:
                profile.instructor = form.cleaned_data.get('instructor')
            else:
                profile.instructor = None
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

            # تحديث مصفوفة الأذونات والصلاحيات إن تم إرسالها
            matrix_raw = request.POST.get('permissions_matrix') or request.POST.get('permissions_matrix_json')
            if matrix_raw:
                try:
                    matrix_data = json.loads(matrix_raw)
                    if isinstance(matrix_data, dict):
                        clean_matrix = {}
                        for mod_id, mod_info in MODULES_PERMISSIONS_CATALOG.items():
                            clean_matrix[mod_id] = {}
                            mod_input = matrix_data.get(mod_id, {})
                            if isinstance(mod_input, dict):
                                for act_id in mod_info['actions']:
                                    clean_matrix[mod_id][act_id] = bool(mod_input.get(act_id, False))
                        profile.permissions_matrix = clean_matrix
                except Exception:
                    pass
            elif role != UserRole.CUSTOM and not profile.permissions_matrix:
                profile.permissions_matrix = get_default_permissions_for_role(role)

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
        'modules_permissions_catalog': MODULES_PERMISSIONS_CATALOG,
        'modules_permissions_catalog_json': json.dumps(MODULES_PERMISSIONS_CATALOG),
        'user_matrix': get_user_permissions_matrix(target_user),
        'user_matrix_json': json.dumps(get_user_permissions_matrix(target_user)),
        'default_role_permissions_json': json.dumps(DEFAULT_ROLE_PERMISSIONS),
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

    # ربط المعلم إن وجد فقط عند اختيار صلاحية معلم أو مشرف
    if new_role in [UserRole.INSTRUCTOR, UserRole.SUPERVISOR]:
        if instructor_num:
            profile.instructor = Instructor.objects.filter(military_number=instructor_num).first()
        elif profile.military_number:
            profile.instructor = Instructor.objects.filter(military_number=profile.military_number).first()
    else:
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


@admin_access_required
def user_update_permissions_matrix_view(request, user_id):
    """تحديث مصفوفة الصلاحيات والأذونات الديناميكية لمستخدم محدد (عبر AJAX أو نموذج عادي)"""
    target_user = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
    profile = target_user.profile if hasattr(target_user, 'profile') else UserProfile.objects.create(user=target_user)

    if not is_super_admin_user(request.user):
        if hasattr(request, 'institute') and request.institute and profile.institute:
            if profile.institute != request.institute:
                if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
                    return JsonResponse({'status': 'error', 'message': 'لا يمكنك تعديل صلاحيات مستخدم في معهد آخر.'}, status=403)
                messages.error(request, 'لا يمكنك تعديل صلاحيات مستخدم في معهد آخر.')
                return redirect(f"{reverse('training:admin_dashboard')}?tab=permissions-matrix")

    if request.method == 'POST':
        reset_to_role = request.POST.get('reset_to_role') == 'true'
        role = request.POST.get('role')
        if role and role in dict(UserRole.choices):
            profile.role = role

        if reset_to_role:
            profile.permissions_matrix = get_default_permissions_for_role(profile.role)
        else:
            matrix_data = None
            if request.content_type == 'application/json':
                try:
                    body = json.loads(request.body)
                    matrix_data = body.get('permissions_matrix', body)
                    if 'role' in body and body['role'] in dict(UserRole.choices):
                        profile.role = body['role']
                except Exception:
                    pass
            elif 'permissions_matrix' in request.POST:
                try:
                    matrix_data = json.loads(request.POST['permissions_matrix'])
                except Exception:
                    pass
            elif 'permissions_matrix_json' in request.POST:
                try:
                    matrix_data = json.loads(request.POST['permissions_matrix_json'])
                except Exception:
                    pass
            else:
                matrix_data = {}
                for mod_id, mod_info in MODULES_PERMISSIONS_CATALOG.items():
                    matrix_data[mod_id] = {}
                    for act_id in mod_info['actions']:
                        key = f"perm_{mod_id}_{act_id}"
                        matrix_data[mod_id][act_id] = bool(request.POST.get(key) in ['on', 'true', '1'])

            if matrix_data and isinstance(matrix_data, dict):
                clean_matrix = {}
                for mod_id, mod_info in MODULES_PERMISSIONS_CATALOG.items():
                    clean_matrix[mod_id] = {}
                    mod_input = matrix_data.get(mod_id, {})
                    if isinstance(mod_input, dict):
                        for act_id in mod_info['actions']:
                            clean_matrix[mod_id][act_id] = bool(mod_input.get(act_id, False))
                    else:
                        for act_id in mod_info['actions']:
                            clean_matrix[mod_id][act_id] = False
                profile.permissions_matrix = clean_matrix

        profile.sync_legacy_booleans_from_matrix()
        if request.institute and not profile.institute:
            profile.institute = request.institute
        profile.save()

        # Update user is_staff if can_manage_users
        if profile.can_manage_users or profile.role == UserRole.ADMIN:
            target_user.is_staff = True
        elif target_user.id != request.user.id and not target_user.is_superuser:
            target_user.is_staff = False
        target_user.save()

        log_activity(
            request=request,
            action_type=ActivityAction.UPDATE,
            action_category=ActivityCategory.USERS,
            description=f"تحديث مصفوفة الصلاحيات والأذونات الديناميكية للمستخدم: {target_user.username}",
            target_model="UserProfile",
            target_id=profile.id
        )

        msg = f'تم حفظ وتحديث مصفوفة الأذونات للمستخدم "{target_user.username}" بنجاح.'
        if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.content_type == 'application/json':
            return JsonResponse({
                'status': 'success',
                'message': msg,
                'role': profile.role,
                'role_display': profile.get_role_display(),
                'permissions_matrix': profile.get_effective_permissions()
            })

        messages.success(request, msg)
        return redirect(f"{reverse('training:admin_dashboard')}?tab=permissions-matrix&matrix_user={target_user.id}")

    return redirect(f"{reverse('training:admin_dashboard')}?tab=permissions-matrix")


@admin_access_required
def api_get_permissions_matrix_view(request):
    """API لجلب مصفوفة الصلاحيات لمستخدم أو لدور محدد أو الدليل الكامل"""
    user_id = request.GET.get('user_id')
    role = request.GET.get('role')

    if user_id:
        target_user = get_object_or_404(User.objects.select_related('profile'), pk=user_id)
        matrix = get_user_permissions_matrix(target_user)
        user_role = target_user.profile.role if hasattr(target_user, 'profile') else UserRole.REGULAR
        role_display = target_user.profile.get_role_display() if hasattr(target_user, 'profile') else 'مستخدم عادي'
        return JsonResponse({
            'status': 'success',
            'user_id': target_user.id,
            'username': target_user.username,
            'role': user_role,
            'role_display': role_display,
            'matrix': matrix
        })
    elif role:
        matrix = get_default_permissions_for_role(role)
        return JsonResponse({
            'status': 'success',
            'role': role,
            'matrix': matrix
        })

    return JsonResponse({
        'status': 'success',
        'catalog': MODULES_PERMISSIONS_CATALOG,
        'role_defaults': DEFAULT_ROLE_PERMISSIONS
    })


# =====================================================================
# إدارة هيئة التعليم والمعلمين (Instructor Management)
# =====================================================================


@admin_access_required
def system_settings_update_view(request):
    """حفظ وتعديل اللوغو الرئيسي وألوان وهوية النظام بالكامل أو تطبيق ثيم جاهز"""
    system_settings = SystemSettings.get_settings(institute=request.institute)

    if request.method == 'POST':
        # 1. إزالة الشعار والعودة للشعار المعتمد
        if 'reset_main_logo' in request.POST:
            system_settings.main_logo = None
            system_settings.save()
            messages.success(request, 'تمت إعادة تعيين شعار النظام الرئيسي إلى الشعار المعتمد بنجاح.')
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





