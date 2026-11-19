from .models import SystemSettings, UserRole, Institute

def system_settings_processor(request):
    """توفير إعدادات وهوية وألوان النظام وحالة صلاحيات المستخدمين وسياق المعهد لجميع القوالب تلقائياً"""
    active_inst = getattr(request, 'institute', None)
    is_super_admin = getattr(request, 'is_super_admin', False)
    super_admin_switched = getattr(request, 'super_admin_switched', False)

    try:
        settings = SystemSettings.get_settings(institute=active_inst)
    except Exception:
        settings = None

    is_admin = False
    is_registrar = False
    is_supervisor = False
    is_instructor = False
    user_role = None
    current_instructor = None

    # أذونات مربعات الاختيار (Windows Permissions Checkboxes)
    can_manage_users = False
    can_view = False
    can_add = False
    can_edit = False
    can_delete = False
    can_grade = False
    can_approve_results = False

    if request.user.is_authenticated:
        if request.user.is_superuser or request.user.is_staff:
            is_admin = True
            is_registrar = True
            is_supervisor = True
            can_manage_users = True
            can_view = True
            can_add = True
            can_edit = True
            can_delete = True
            can_grade = True
            can_approve_results = True

        if hasattr(request.user, 'profile'):
            profile = request.user.profile
            user_role = profile.role

            # أخذ الأذونات المباشرة من البروفايل
            can_manage_users = can_manage_users or profile.can_manage_users or profile.is_admin
            can_view = can_view or profile.can_view
            can_add = can_add or profile.can_add or profile.is_admin
            can_edit = can_edit or profile.can_edit or profile.is_admin
            can_delete = can_delete or profile.can_delete or profile.is_admin
            can_grade = can_grade or profile.can_grade or profile.is_admin
            can_approve_results = can_approve_results or profile.can_approve_results or profile.is_admin

            if profile.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN] or can_manage_users:
                is_admin = True
                is_registrar = True
                is_supervisor = True
            elif profile.role == UserRole.REGISTRAR or (can_add and can_edit):
                is_registrar = True
            elif profile.role == UserRole.SUPERVISOR or can_approve_results:
                is_supervisor = True
            elif profile.role == UserRole.INSTRUCTOR:
                is_instructor = True

            current_instructor = profile.get_instructor()

    all_institutes = None
    if is_super_admin:
        try:
            all_institutes = Institute.objects.filter(is_active=True).order_by('name')
        except Exception:
            all_institutes = None

    return {
        'system_settings': settings,
        'active_institute': active_inst,
        'is_super_admin': is_super_admin,
        'super_admin_switched': super_admin_switched,
        'all_institutes': all_institutes,
        'is_admin': is_admin,
        'is_registrar': is_registrar,
        'is_supervisor': is_supervisor,
        'is_instructor': is_instructor,
        'user_role': user_role,
        'current_instructor': current_instructor,
        'can_manage_users': can_manage_users,
        'can_view': can_view,
        'can_add': can_add,
        'can_edit': can_edit,
        'can_delete': can_delete,
        'can_grade': can_grade,
        'can_approve_results': can_approve_results,
    }
