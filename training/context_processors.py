from .models import SystemSettings

def system_settings_processor(request):
    """توفير إعدادات وهوية وألوان النظام لجميع القوالب تلقائياً"""
    try:
        settings = SystemSettings.get_settings()
    except Exception:
        settings = None
    return {
        'system_settings': settings
    }
