import copy
from functools import wraps
from urllib.parse import quote
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.contrib import messages
from apps.core.models import UserRole


# =====================================================================
# دليل ومصفوفة الأقسام والعمليات والأذونات (Permissions Catalog)
# =====================================================================
MODULES_PERMISSIONS_CATALOG = {
    'trainees': {
        'id': 'trainees',
        'name': 'شؤون وسجلات الدارسين',
        'icon': 'bi bi-people-fill',
        'color': 'primary',
        'badge_bg': '#e0e7ff',
        'badge_color': '#3730a3',
        'actions': {
            'view': {'name': 'عرض واستعراض السجلات', 'description': 'استعراض قائمة الدارسين وبطاقة البيانات الشخصية والسكن وأقارب الطوارئ'},
            'add': {'name': 'إضافة دارس جديد', 'description': 'تسجيل دارس جديد في المنظومة مع التحقق من النمرة العسكرية'},
            'edit': {'name': 'تعديل بيانات الدارس', 'description': 'تعديل البيانات الأساسية، السكن، وأقارب الطوارئ'},
            'delete': {'name': 'حذف دارس', 'description': 'حذف دارس غير مقيد بدورات أو نتائج'},
            'export': {'name': 'تصدير وسجل تاريخي', 'description': 'تصدير البيانات واستخراج كشف الدرجات الأكاديمي التاريخي للدارس'},
        }
    },
    'courses': {
        'id': 'courses',
        'name': 'المقررات والمناهج الدراسية',
        'icon': 'bi bi-journal-bookmark-fill',
        'color': 'info',
        'badge_bg': '#e0f2fe',
        'badge_color': '#0369a1',
        'actions': {
            'view': {'name': 'استعراض دليل الدورات والمواد', 'description': 'الاطلاع على قائمة المقررات وتصنيفاتها والمفردات الدراسية'},
            'add': {'name': 'إضافة دورة أو مادة', 'description': 'إنشاء دورات تدريبية وتصنيفات وإضافة مواد دراسية جديدة'},
            'edit': {'name': 'تعديل دورة أو مادة', 'description': 'تعديل مسميات المقررات وتوزيع الساعات والدرجة العظمى'},
            'delete': {'name': 'حذف دورة أو مادة', 'description': 'حذف المقررات والمواد الدراسية غير المقيدة بسجلات نتائج'},
        }
    },
    'sessions': {
        'id': 'sessions',
        'name': 'انعقاد الدورات والدفعات',
        'icon': 'bi bi-calendar-check-fill',
        'color': 'success',
        'badge_bg': '#dcfce7',
        'badge_color': '#15803d',
        'actions': {
            'view': {'name': 'استعراض الدورات المنعقدة', 'description': 'الاطلاع على جدول الدورات المنعقدة وتفاصيل كل دفعة'},
            'add': {'name': 'فتح انعقاد دورة جديدة', 'description': 'إنشاء دفعة جديدة وتحديد تواريخ البداية والنهاية والتصنيف'},
            'edit': {'name': 'تعديل الانعقاد وتكليف المعلمين', 'description': 'تحديث بيانات الدفعة، أمر التحرك وتعيين أساتذة المواد'},
            'delete': {'name': 'حذف دورة منعقدة', 'description': 'حذف دورة منعقدة غير مقفلة أو معتمدة'},
            'enroll': {'name': 'إلحاق وإدارة الدارسين', 'description': 'إلحاق الدارسين بالدفعة أو استبعادهم وتسجيل نتائجهم'},
        }
    },
    'grades': {
        'id': 'grades',
        'name': 'الدرجات ورصد النتائج',
        'icon': 'bi bi-calculator-fill',
        'color': 'warning',
        'badge_bg': '#fef3c7',
        'badge_color': '#92400e',
        'actions': {
            'view': {'name': 'استعراض مركز النتائج', 'description': 'الاطلاع على شاشات النتائج وكشوفات الرصد وشيت النتيجة'},
            'entry': {'name': 'رصد وإدخال الدرجات', 'description': 'رصد درجات المواد والمواظبة للطلاب إلكترونياً'},
            'approve': {'name': 'اعتماد وقفل النتائج', 'description': 'الاعتماد النهائي للنتيجة وحساب النسب والتقديرات الرسمية'},
        }
    },
    'certificates': {
        'id': 'certificates',
        'name': 'الشهادات المعتمدة',
        'icon': 'bi bi-award-fill',
        'color': 'danger',
        'badge_bg': '#fee2e2',
        'badge_color': '#b91c1c',
        'actions': {
            'view': {'name': 'معاينة الشهادة', 'description': 'استعراض الشهادة الرسمية وشهادة التفاصيل للدارس'},
            'issue': {'name': 'إصدار وطباعة الشهادات', 'description': 'طباعة الشهادات وتصديرها رسمياً بالختم والترويسة'},
        }
    },
    'movement_orders': {
        'id': 'movement_orders',
        'name': 'أوامر التحرك الرسمية',
        'icon': 'bi bi-signpost-2-fill',
        'color': 'secondary',
        'badge_bg': '#f3f4f6',
        'badge_color': '#374151',
        'actions': {
            'view': {'name': 'معاينة أمر التحرك', 'description': 'استعراض أمر التحرك المخصص للدارس الناجح'},
            'issue': {'name': 'إصدار وطباعة أمر التحرك', 'description': 'طباعة أمر التحرك الرسمي بالديباجة والعلامة المائية'},
        }
    },
    'reports': {
        'id': 'reports',
        'name': 'التقارير الشاملة والإحصاء',
        'icon': 'bi bi-bar-chart-line-fill',
        'color': 'primary',
        'badge_bg': '#ede9fe',
        'badge_color': '#6d28d9',
        'actions': {
            'view': {'name': 'الدخول لقسم التقارير', 'description': 'الاطلاع على شاشة التقارير والمؤشرات والرسوم البيانية'},
            'excel': {'name': 'تصدير تقارير Excel', 'description': 'استخراج وتنزيل ملفات الإكسل المنسقة بجداول تفصيلية'},
            'print': {'name': 'طباعة التقرير الرسمي', 'description': 'معاينة وطباعة التقرير الإحصائي القياسي المعتمد'},
        }
    },
    'users': {
        'id': 'users',
        'name': 'المستخدمون والأمان',
        'icon': 'bi bi-shield-lock-fill',
        'color': 'dark',
        'badge_bg': '#e2e8f0',
        'badge_color': '#1e293b',
        'actions': {
            'view': {'name': 'استعراض المستخدمين', 'description': 'الاطلاع على قائمة مستخدمي النظام وحساباتهم'},
            'add': {'name': 'إنشاء مستخدم جديد', 'description': 'إضافة حساب جديد وتحديد كلمة المرور'},
            'edit': {'name': 'تعديل المستخدمين', 'description': 'تعديل البيانات، الرتبة، الوحدة، وإعادة تعيين كلمة المرور'},
            'delete': {'name': 'حذف مستخدم', 'description': 'حذف حساب مستخدم من المنظومة نهائياً'},
            'toggle_status': {'name': 'تفعيل/تعطيل الحساب', 'description': 'إيقاف مؤقت أو إعادة تفعيل حساب المستخدم'},
            'permissions': {'name': 'إدارة مصفوفة الصلاحيات', 'description': 'تعديل الأذونات الدقيقة للمستخدم في المصفوفة'},
        }
    },
    'settings': {
        'id': 'settings',
        'name': 'إعدادات وهوية المنظومة',
        'icon': 'bi bi-palette-fill',
        'color': 'info',
        'badge_bg': '#cffafe',
        'badge_color': '#0e7490',
        'actions': {
            'view': {'name': 'استعراض الإعدادات', 'description': 'الاطلاع على هوية المعهد وألوان النظام وقوالب التوقيعات'},
            'edit': {'name': 'تعديل الهوية والقوالب', 'description': 'تعديل الألوان والشعار وتوقيعات الشهادات وأمر التحرك'},
        }
    },
    'discipline': {
        'id': 'discipline',
        'name': 'مخالفات الضبط والربط',
        'icon': 'bi bi-exclamation-triangle-fill',
        'color': 'warning',
        'badge_bg': '#ffedd5',
        'badge_color': '#c2410c',
        'actions': {
            'view': {'name': 'استعراض المخالفات', 'description': 'الاطلاع على سجل مخالفات الضبط للدارسين'},
            'add': {'name': 'تسجيل مخالفة جديدة', 'description': 'رصد مخالفة جديدة وحساب خصم درجات المواظبة'},
            'delete': {'name': 'إلغاء أو حذف مخالفة', 'description': 'إلغاء مخالفة تم تسجيلها بالخطأ واستعادة الدرجة'},
        }
    },
    'audit_log': {
        'id': 'audit_log',
        'name': 'سجل العمليات والتدقيق',
        'icon': 'bi bi-clock-history',
        'color': 'secondary',
        'badge_bg': '#f1f5f9',
        'badge_color': '#475569',
        'actions': {
            'view': {'name': 'استعراض سجل النشاط', 'description': 'مراقبة كافة عمليات وإجراءات المستخدمين بالتواريخ وعناوين IP'},
            'clear': {'name': 'مسح سجل العمليات', 'description': 'تفريغ وتنظيف سجل النشاط للمعهد للأدمن فقط'},
        }
    },
}


# =====================================================================
# الإعدادات الافتراضية لمصفوفة الصلاحيات حسب الدور (Role Defaults)
# =====================================================================
DEFAULT_ROLE_PERMISSIONS = {
    UserRole.SUPER_ADMIN: {
        module_id: {act_id: True for act_id in module_info['actions']}
        for module_id, module_info in MODULES_PERMISSIONS_CATALOG.items()
    },
    UserRole.ADMIN: {
        module_id: {act_id: True for act_id in module_info['actions']}
        for module_id, module_info in MODULES_PERMISSIONS_CATALOG.items()
    },
    UserRole.REGISTRAR: {
        'trainees': {'view': True, 'add': True, 'edit': True, 'delete': True, 'export': True},
        'courses': {'view': True, 'add': True, 'edit': True, 'delete': True},
        'sessions': {'view': True, 'add': True, 'edit': True, 'delete': True, 'enroll': True},
        'grades': {'view': True, 'entry': False, 'approve': False},
        'certificates': {'view': True, 'issue': True},
        'movement_orders': {'view': True, 'issue': True},
        'reports': {'view': True, 'excel': True, 'print': True},
        'users': {'view': False, 'add': False, 'edit': False, 'delete': False, 'toggle_status': False, 'permissions': False},
        'settings': {'view': False, 'edit': False},
        'discipline': {'view': True, 'add': False, 'delete': False},
        'audit_log': {'view': False, 'clear': False},
    },
    UserRole.SUPERVISOR: {
        'trainees': {'view': True, 'add': False, 'edit': False, 'delete': False, 'export': True},
        'courses': {'view': True, 'add': False, 'edit': False, 'delete': False},
        'sessions': {'view': True, 'add': False, 'edit': False, 'delete': False, 'enroll': False},
        'grades': {'view': True, 'entry': True, 'approve': True},
        'certificates': {'view': True, 'issue': True},
        'movement_orders': {'view': True, 'issue': True},
        'reports': {'view': True, 'excel': True, 'print': True},
        'users': {'view': False, 'add': False, 'edit': False, 'delete': False, 'toggle_status': False, 'permissions': False},
        'settings': {'view': False, 'edit': False},
        'discipline': {'view': True, 'add': True, 'delete': True},
        'audit_log': {'view': False, 'clear': False},
    },
    UserRole.INSTRUCTOR: {
        'trainees': {'view': False, 'add': False, 'edit': False, 'delete': False, 'export': False},
        'courses': {'view': True, 'add': False, 'edit': False, 'delete': False},
        'sessions': {'view': False, 'add': False, 'edit': False, 'delete': False, 'enroll': False},
        'grades': {'view': True, 'entry': True, 'approve': False},
        'certificates': {'view': False, 'issue': False},
        'movement_orders': {'view': False, 'issue': False},
        'reports': {'view': False, 'excel': False, 'print': False},
        'users': {'view': False, 'add': False, 'edit': False, 'delete': False, 'toggle_status': False, 'permissions': False},
        'settings': {'view': False, 'edit': False},
        'discipline': {'view': False, 'add': False, 'delete': False},
        'audit_log': {'view': False, 'clear': False},
    },
    UserRole.REGULAR: {
        'trainees': {'view': True, 'add': False, 'edit': False, 'delete': False, 'export': False},
        'courses': {'view': True, 'add': False, 'edit': False, 'delete': False},
        'sessions': {'view': True, 'add': False, 'edit': False, 'delete': False, 'enroll': False},
        'grades': {'view': False, 'entry': False, 'approve': False},
        'certificates': {'view': False, 'issue': False},
        'movement_orders': {'view': False, 'issue': False},
        'reports': {'view': True, 'excel': False, 'print': False},
        'users': {'view': False, 'add': False, 'edit': False, 'delete': False, 'toggle_status': False, 'permissions': False},
        'settings': {'view': False, 'edit': False},
        'discipline': {'view': False, 'add': False, 'delete': False},
        'audit_log': {'view': False, 'clear': False},
    },
    UserRole.CUSTOM: {
        module_id: {act_id: False for act_id in module_info['actions']}
        for module_id, module_info in MODULES_PERMISSIONS_CATALOG.items()
    }
}


def get_default_permissions_for_role(role):
    """إرجاع نسخة عميقة من الصلاحيات الافتراضية لدور محدد"""
    role_perms = DEFAULT_ROLE_PERMISSIONS.get(role, DEFAULT_ROLE_PERMISSIONS.get(UserRole.REGULAR, {}))
    return copy.deepcopy(role_perms)


def get_user_permissions_matrix(user):
    """
    إرجاع مصفوفة الصلاحيات الديناميكية الكاملة للمستخدم محلولة (Resolved Dict):
    - للسوبر أدمن أو الأدمن: كافة الصلاحيات مفعلة (True).
    - إذا كان لدى المستخدم مصفوفة مخصصة (permissions_matrix): يتم دمجها مع القيم الافتراضية لدوره.
    - وإلا: يتم إرجاع القيم الافتراضية لدوره.
    """
    if not user or not user.is_authenticated:
        return {
            m_id: {a_id: False for a_id in m_info['actions']}
            for m_id, m_info in MODULES_PERMISSIONS_CATALOG.items()
        }

    # سوبر أدمن المنظومة ومسؤول دجانغو المباشر
    if user.is_superuser or (hasattr(user, 'profile') and user.profile.role == UserRole.SUPER_ADMIN):
        return {
            m_id: {a_id: True for a_id in m_info['actions']}
            for m_id, m_info in MODULES_PERMISSIONS_CATALOG.items()
        }

    # مدير نظام المعهد
    if user.is_staff or (hasattr(user, 'profile') and user.profile.role == UserRole.ADMIN):
        return {
            m_id: {a_id: True for a_id in m_info['actions']}
            for m_id, m_info in MODULES_PERMISSIONS_CATALOG.items()
        }

    profile = getattr(user, 'profile', None)
    role = profile.role if profile else UserRole.REGULAR
    base_perms = get_default_permissions_for_role(role)

    # دمج التخصيصات المخزنة في permissions_matrix للمستخدم إن وجدت
    if profile and isinstance(profile.permissions_matrix, dict) and profile.permissions_matrix:
        custom_matrix = profile.permissions_matrix
        for mod, acts in custom_matrix.items():
            if mod in base_perms and isinstance(acts, dict):
                for act, val in acts.items():
                    if act in base_perms[mod]:
                        base_perms[mod][act] = bool(val)

    return base_perms


def has_permission(user, module, action):
    """
    الدالة المركزية الديناميكية للتحقق مما إذا كان المستخدم يملك إذناً محدداً:
    مثال: has_permission(request.user, 'trainees', 'delete')
    """
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    profile = getattr(user, 'profile', None)
    if profile:
        if profile.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN] or profile.can_manage_users:
            return True

    matrix = get_user_permissions_matrix(user)
    return bool(matrix.get(module, {}).get(action, False))


def check_perm(module, action):
    """محدد صلاحية كـ Decorator ديناميكي يفحص مصفوفة الصلاحيات"""
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect(f"{reverse('training:login')}?next={request.path}")

            if not has_permission(request.user, module, action):
                messages.error(request, f'عفواً، حسابك لا يملك صلاحية تنفيذ هذا الإجراء في المنظومة.')
                referer = request.META.get('HTTP_REFERER')
                if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
                    return redirect(referer)
                return redirect('training:home')

            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


# =====================================================================
# توابع ومحددات الصلاحيات المتوافقة مع النظام الحالي
# =====================================================================
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


def is_registrar_user(user):
    """التحقق مما إذا كان المستخدم مسجل بيانات أو يملك صلاحية الإضافة والتعديل"""
    if not user or not user.is_authenticated:
        return False
    if is_admin_user(user):
        return True
    return bool(
        hasattr(user, 'profile') and (
            user.profile.role == UserRole.REGISTRAR or 
            (user.profile.can_add and user.profile.can_edit) or
            (has_permission(user, 'trainees', 'add') and has_permission(user, 'trainees', 'edit'))
        )
    )


def is_supervisor_user(user):
    """التحقق مما إذا كان المستخدم مشرف دورة أو يملك صلاحية اعتماد النتائج"""
    if not user or not user.is_authenticated:
        return False
    if is_admin_user(user):
        return True
    return bool(
        hasattr(user, 'profile') and (
            user.profile.role == UserRole.SUPERVISOR or 
            user.profile.can_approve_results or
            has_permission(user, 'grades', 'approve')
        )
    )


def is_instructor_user(user):
    """التحقق مما إذا كان المستخدم معلماً في هيئة التدريس"""
    if not user or not user.is_authenticated:
        return False
    if not hasattr(user, 'profile'):
        return False
    return bool(
        user.profile.role == UserRole.INSTRUCTOR or 
        (user.profile.can_grade and not is_admin_user(user) and not user.profile.can_approve_results) or
        (has_permission(user, 'grades', 'entry') and not is_admin_user(user) and not has_permission(user, 'grades', 'approve'))
    )


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
    """حصر الإجراء على مسجل البيانات ومدير النظام، وتوجيه المعلمين لشاشة النتيجة"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect(f"{reverse('training:login')}?next={request.path}")

        if is_instructor_user(request.user) and not is_admin_user(request.user):
            messages.warning(request, 'حسابك مخصص لمعلم / هيئة التدريس، وصلاحياتك محصورة في شاشة رصد نتائج المواد المكلف بها فقط.')
            return redirect('training:results_center')

        if not is_registrar_user(request.user):
            messages.error(request, 'عفواً، يتطلب هذا الإجراء صلاحية مسجل بيانات أو مدير نظام (Admin).')
            referer = request.META.get('HTTP_REFERER')
            if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
                return redirect(referer)
            return redirect('training:home')

        return view_func(request, *args, **kwargs)
    return _wrapped_view
