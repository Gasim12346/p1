from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from .models import log_activity, ActivityAction, ActivityCategory


@receiver(user_logged_in)
def log_user_login(sender, request, user, **kwargs):
    """تسجيل وتوثيق لحظة دخول المستخدم إلى النظام"""
    name = user.get_full_name() or user.username
    log_activity(
        request=request,
        user=user,
        action_type=ActivityAction.LOGIN,
        action_category=ActivityCategory.AUTH,
        description=f"تسجيل الدخول إلى النظام للمستخدم: {user.username} ({name})",
        target_model="User",
        target_id=user.id
    )


@receiver(user_logged_out)
def log_user_logout(sender, request, user, **kwargs):
    """تسجيل وتوثيق لحظة خروج المستخدم من النظام"""
    if user and getattr(user, 'is_authenticated', False):
        name = user.get_full_name() or user.username
        log_activity(
            request=request,
            user=user,
            action_type=ActivityAction.LOGOUT,
            action_category=ActivityCategory.AUTH,
            description=f"تسجيل الخروج من النظام للمستخدم: {user.username} ({name})",
            target_model="User",
            target_id=user.id
        )

