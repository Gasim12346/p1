from .models import SystemSettings, UserRole

def system_settings_processor(request):
    """توفير إعدادات وهوية وألوان النظام وحالة صلاحيات المستخدمين لجميع القوالب تلقائياً"""
    try:
        settings = SystemSettings.get_settings()
    except Exception:
        settings = None

    is_admin = False
    is_registrar = False
    is_supervisor = False
    is_instructor = False
    user_role = None
    current_instructor = None

    if request.user.is_authenticated:
        if request.user.is_superuser or request.user.is_staff:
            is_admin = True
            is_registrar = True
            is_supervisor = True

        if hasattr(request.user, 'profile'):
            profile = request.user.profile
            user_role = profile.role
            if profile.role == UserRole.ADMIN:
                is_admin = True
                is_registrar = True
                is_supervisor = True
            elif profile.role == UserRole.REGISTRAR:
                is_registrar = True
            elif profile.role == UserRole.SUPERVISOR:
                is_supervisor = True
            elif profile.role == UserRole.INSTRUCTOR:
                is_instructor = True

            current_instructor = profile.get_instructor()

    return {
        'system_settings': settings,
        'is_admin': is_admin,
        'is_registrar': is_registrar,
        'is_supervisor': is_supervisor,
        'is_instructor': is_instructor,
        'user_role': user_role,
        'current_instructor': current_instructor,
    }
