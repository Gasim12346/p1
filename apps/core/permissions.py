from functools import wraps
from urllib.parse import quote
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib import messages
from apps.core.models import UserRole


def is_super_admin_user(user):
    """التحقق مما إذا كان المستخدم يملك صلاحية سوبر أدمن (مدير عام المنظومة)"""
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or (hasattr(user, 'profile') and user.profile.role == UserRole.SUPER_ADMIN))


def super_admin_required(view_func):
    """قيد صلاحية: محصور بالمدير العام للمنظومة (سوبر أدمن) وتوجيه غير المسجلين لصفحة تسجيل دخول السوبر أدمن"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            messages.warning(request, 'يرجى تسجيل الدخول بحساب السوبر أدمن للوصول إلى إدارة المنظومة المركزية.')
            return redirect(f"{reverse('training:super_admin_login')}?next={quote(request.get_full_path())}")
        if not is_super_admin_user(request.user):
            messages.error(request, 'هذا القسم مخصص للمدير العام للمنظومة (سوبر أدمن) فقط.')
            return redirect('training:super_admin_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def is_admin_user(user):
    """التحقق مما إذا كان المستخدم يملك صلاحية مدير النظام أو تحكم كامل"""
    if not user or not user.is_authenticated:
        return False
    return bool(
        is_super_admin_user(user) or 
        user.is_staff or 
        (hasattr(user, 'profile') and (user.profile.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN] or user.profile.can_manage_users))
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




