from .models import SystemSettings, UserRole

def system_settings_processor(request):
    """توفير إعدادات وهوية وألوان النظام وحالة صلاحية المدير لجميع القوالب تلقائياً"""
    try:
        settings = SystemSettings.get_settings()
    except Exception:
        settings = None

    is_admin = False
    if request.user.is_authenticated:
        is_admin = bool(
            request.user.is_superuser or
            request.user.is_staff or
            (hasattr(request.user, 'profile') and request.user.profile.role == UserRole.ADMIN)
        )

    return {
        'system_settings': settings,
        'is_admin': is_admin,
    }
