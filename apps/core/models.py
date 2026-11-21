from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# قيد إلزامي: رقم الهاتف يتكون من 10 أرقام فقط
phone_10_digits_validator = RegexValidator(
    regex=r'^\d{10}$',
    message='رقم الهاتف يجب أن يتكون من 10 أرقام فقط دون مسافات أو رموز.'
)


class Institute(models.Model):
    """الكيان الأساسي للمعهد / الوحدة والمنشأة التعليمية"""
    code = models.SlugField(
        max_length=50,
        unique=True,
        verbose_name='رمز المعهد (ID فريد للنظام)'
    )
    name = models.CharField(
        max_length=200,
        verbose_name='اسم المعهد / المنشأة التعليمية'
    )
    parent_unit = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='الوحدة / الإدارة التابع لها'
    )
    logo = models.ImageField(
        upload_to='institute_logos/',
        blank=True,
        null=True,
        verbose_name='شعار المعهد'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='حالة النظام (نشط / معلق)'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإنشاء'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='تاريخ آخر تحديث'
    )

    class Meta:
        app_label = 'training'
        verbose_name = 'معهد / منشأة تدريبية'
        verbose_name_plural = 'المعاهد والمنشآت التدريبية'
        ordering = ['id']

    def __str__(self):
        return f"{self.name} ({self.code})"

    @property
    def logo_url(self):
        if self.logo and hasattr(self.logo, 'url'):
            return self.logo.url
        return None


class SystemSettings(models.Model):
    """إعدادات وهوية وألوان وشعار النظام بالكامل"""
    institute = models.OneToOneField(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='system_settings',
        verbose_name='المعهد'
    )
    system_name = models.CharField(
        max_length=200,
        default='نظام تسجيل واستخراج النتائج والشهادات',
        verbose_name='اسم النظام'
    )
    system_subheading = models.CharField(
        max_length=250,
        default='بوابة رصد الدرجات والشهادات المعتمدة',
        verbose_name='الوصف الفرعي للنظام'
    )
    main_logo = models.ImageField(
        upload_to='system_logos/',
        blank=True,
        null=True,
        verbose_name='شعار النظام الرئيسي'
    )
    
    # هوية الألوان الكاملة للنظام (CSS Variables)
    primary_navy = models.CharField(
        max_length=25,
        default='#0f172a',
        verbose_name='اللون الكحلي الداكن الرئيسي'
    )
    primary_accent = models.CharField(
        max_length=25,
        default='#1e3a8a',
        verbose_name='اللون الأزرق المميز (Header/Accent)'
    )
    brand_blue = models.CharField(
        max_length=25,
        default='#2563eb',
        verbose_name='لون الأزرار والروابط الأساسية'
    )
    brand_cyan = models.CharField(
        max_length=25,
        default='#0284c7',
        verbose_name='اللون الثانوي التكميلي'
    )
    gold_accent = models.CharField(
        max_length=25,
        default='#d97706',
        verbose_name='اللون الذهبي المميز'
    )
    bg_light = models.CharField(
        max_length=25,
        default='#f8fafc',
        verbose_name='لون خلفية الصفحات'
    )
    sidebar_bg_start = models.CharField(
        max_length=25,
        default='#0b1329',
        verbose_name='لون بداية تدرج القائمة الجانبية'
    )
    sidebar_bg_end = models.CharField(
        max_length=25,
        default='#0f172a',
        verbose_name='لون نهاية تدرج القائمة الجانبية'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='تاريخ آخر تعديل'
    )

    class Meta:
        app_label = 'training'
        verbose_name = 'إعدادات وهوية النظام'
        verbose_name_plural = 'إعدادات وهوية النظام'

    def __str__(self):
        return 'إعدادات وهوية وألوان النظام'

    @classmethod
    def get_settings(cls, institute=None):
        """الحصول على كائن الإعدادات أو إنشاؤه بالقيم المعتمدة"""
        if institute:
            obj, _ = cls.objects.get_or_create(institute=institute)
            return obj
        obj = cls.objects.filter(institute__isnull=True).first() or cls.objects.first()
        if not obj:
            obj = cls.objects.create(system_name='نظام تسجيل واستخراج النتائج والشهادات')
        return obj

    @property
    def main_logo_url(self):
        if self.main_logo and hasattr(self.main_logo, 'url'):
            return self.main_logo.url
        return None


class UserRole(models.TextChoices):
    SUPER_ADMIN = 'super_admin', 'سوبر أدمن (المدير العام للمنظومة)'
    ADMIN = 'admin', 'مدير نظام المعهد (أدمن)'
    REGISTRAR = 'registrar', 'مسجل بيانات'
    SUPERVISOR = 'supervisor', 'مشرف دورة'
    INSTRUCTOR = 'instructor', 'معلم / هيئة التدريس'
    REGULAR = 'regular', 'مستخدم عادي'
    CUSTOM = 'custom', 'أذونات مخصصة'


class UserProfile(models.Model):
    """الملف التعريفي ونوع وصلاحية المستخدم في النظام"""
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='user_profiles',
        verbose_name='المعهد التابع له'
    )
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        verbose_name='المستخدم'
    )
    role = models.CharField(
        max_length=30,
        choices=UserRole.choices,
        default=UserRole.REGULAR,
        verbose_name='نوع وصلاحية المستخدم'
    )
    instructor = models.ForeignKey(
        'training.Instructor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='user_profiles',
        verbose_name='سجل المعلم المرتبط'
    )
    military_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='النمرة العسكرية'
    )
    rank = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='الرتبة'
    )
    unit = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name='الوحدة'
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        validators=[phone_10_digits_validator],
        verbose_name='رقم الهاتف'
    )

    # أذونات وصلاحيات تفصيلية
    can_manage_users = models.BooleanField(
        default=False,
        verbose_name='التحكم الكامل وإدارة النظام (Full Control)'
    )
    can_view = models.BooleanField(
        default=True,
        verbose_name='القراءة والعرض (Read/View)'
    )
    can_add = models.BooleanField(
        default=False,
        verbose_name='الكتابة والإضافة (Write/Add)'
    )
    can_edit = models.BooleanField(
        default=False,
        verbose_name='التعديل والكتابة (Modify/Edit)'
    )
    can_delete = models.BooleanField(
        default=False,
        verbose_name='الحذف (Delete)'
    )
    can_grade = models.BooleanField(
        default=False,
        verbose_name='رصد الدرجات (Grade Entry)'
    )
    can_approve_results = models.BooleanField(
        default=False,
        verbose_name='اعتماد النتائج (Approve Results)'
    )

    # مصفوفة الأذونات والصلاحيات الديناميكية الشاملة (Dynamic Permissions Matrix)
    permissions_matrix = models.JSONField(
        default=dict,
        blank=True,
        verbose_name='مصفوفة الأذونات والصلاحيات الديناميكية'
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإضافة'
    )

    class Meta:
        app_label = 'training'
        verbose_name = 'الملف الشخصي للمستخدم'
        verbose_name_plural = 'ملفات وصلاحيات المستخدمين'

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    def get_effective_permissions(self):
        """إرجاع مصفوفة الصلاحيات الفعلية الكاملة للمستخدم"""
        from apps.core.permissions import get_user_permissions_matrix
        if hasattr(self, 'user') and self.user:
            self.user.profile = self
        return get_user_permissions_matrix(self.user)

    def has_perm(self, module, action):
        """التحقق من امتلاك المستخدم لصلاحية محددة في مصفوفة الصلاحيات الديناميكية"""
        from apps.core.permissions import has_permission
        if hasattr(self, 'user') and self.user:
            self.user.profile = self
        return has_permission(self.user, module, action)

    def sync_legacy_booleans_from_matrix(self):
        """مزامنة الحقول البولينية القديمة من مصفوفة الصلاحيات لضمان التوافقية الكاملة"""
        matrix = self.get_effective_permissions()
        trainees = matrix.get('trainees', {})
        courses = matrix.get('courses', {})
        grades = matrix.get('grades', {})
        users = matrix.get('users', {})
        settings = matrix.get('settings', {})

        self.can_manage_users = bool(
            self.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN] or
            (self.user and (self.user.is_superuser or self.user.is_staff)) or
            users.get('permissions') or
            settings.get('edit')
        )
        self.can_view = bool(self.can_manage_users or trainees.get('view') or courses.get('view'))
        self.can_add = bool(self.can_manage_users or trainees.get('add') or courses.get('add'))
        self.can_edit = bool(self.can_manage_users or trainees.get('edit') or courses.get('edit'))
        self.can_delete = bool(self.can_manage_users or trainees.get('delete') or courses.get('delete'))
        self.can_grade = bool(self.can_manage_users or grades.get('entry'))
        self.can_approve_results = bool(self.can_manage_users or grades.get('approve'))

    def sync_permissions_from_role(self):
        """مزامنة خانات الاختيار للأذونات تلقائياً بناءً على الدور المختار"""
        from apps.core.permissions import get_default_permissions_for_role
        if self.role != UserRole.CUSTOM or not self.permissions_matrix:
            self.permissions_matrix = get_default_permissions_for_role(self.role)

        if self.role in [UserRole.SUPER_ADMIN, UserRole.ADMIN] or (self.user and (self.user.is_superuser or self.user.is_staff)):
            self.can_manage_users = True
            self.can_view = True
            self.can_add = True
            self.can_edit = True
            self.can_delete = True
            self.can_grade = True
            self.can_approve_results = True
        elif self.role == UserRole.REGISTRAR:
            self.can_manage_users = False
            self.can_view = True
            self.can_add = True
            self.can_edit = True
            self.can_delete = True
            self.can_grade = False
            self.can_approve_results = False
        elif self.role == UserRole.SUPERVISOR:
            self.can_manage_users = False
            self.can_view = True
            self.can_add = False
            self.can_edit = False
            self.can_delete = False
            self.can_grade = True
            self.can_approve_results = True
        elif self.role == UserRole.INSTRUCTOR:
            self.can_manage_users = False
            self.can_view = False
            self.can_add = False
            self.can_edit = False
            self.can_delete = False
            self.can_grade = True
            self.can_approve_results = False
        elif self.role == UserRole.REGULAR:
            self.can_manage_users = False
            self.can_view = True
            self.can_add = False
            self.can_edit = False
            self.can_delete = False
            self.can_grade = False
            self.can_approve_results = False
        elif self.role == UserRole.CUSTOM:
            self.sync_legacy_booleans_from_matrix()

    @property
    def is_super_admin(self):
        return bool(self.role == UserRole.SUPER_ADMIN or (self.user and self.user.is_superuser))

    @property
    def is_admin(self):
        return bool(self.is_super_admin or (self.user and self.user.is_staff) or self.role == UserRole.ADMIN or self.can_manage_users)

    @property
    def is_registrar(self):
        return self.is_admin or self.role == UserRole.REGISTRAR or (self.can_add and self.can_edit)

    @property
    def is_supervisor(self):
        return self.is_admin or self.role == UserRole.SUPERVISOR or self.can_approve_results

    @property
    def is_instructor(self):
        return self.role == UserRole.INSTRUCTOR or (self.can_grade and not self.is_admin and not self.can_approve_results)

    def get_instructor(self):
        """إرجاع كائن المعلم المرتبط بهذا المستخدم إن وجد"""
        if self.instructor:
            return self.instructor
        if self.military_number:
            from apps.academic.models import Instructor
            return Instructor.objects.filter(military_number=self.military_number).first()
        return None


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """إنشاء أو تحديث بروفايل المستخدم تلقائياً عند حفظ كائن المستخدم"""
    if kwargs.get('raw', False):
        return
    if created:
        role = UserRole.ADMIN if (instance.is_superuser or instance.is_staff) else UserRole.REGULAR
        profile, _ = UserProfile.objects.get_or_create(user=instance, defaults={'role': role})
        profile.sync_permissions_from_role()
        profile.save()
    elif not hasattr(instance, 'profile'):
        role = UserRole.ADMIN if (instance.is_superuser or instance.is_staff) else UserRole.REGULAR
        profile, _ = UserProfile.objects.get_or_create(user=instance, defaults={'role': role})
        profile.sync_permissions_from_role()
        profile.save()


# =====================================================================
# سجل النشاط والعمليات ومسار تدقيق المستخدمين (Audit & Activity Log)
# =====================================================================
class ActivityAction(models.TextChoices):
    LOGIN = 'LOGIN', 'تسجيل دخول'
    LOGOUT = 'LOGOUT', 'تسجيل خروج'
    CREATE = 'CREATE', 'إضافة جديدة'
    UPDATE = 'UPDATE', 'تعديل بيانات'
    DELETE = 'DELETE', 'حذف'
    GRADE_ENTRY = 'GRADE_ENTRY', 'رصد درجات'
    GRADE_APPROVAL = 'GRADE_APPROVAL', 'اعتماد نتائج'
    STATUS_CHANGE = 'STATUS_CHANGE', 'تغيير حالة'
    OTHER = 'OTHER', 'عملية أخرى'


class ActivityCategory(models.TextChoices):
    AUTH = 'AUTH', 'تسجيل الدخول والمصادقة'
    USERS = 'USERS', 'إدارة المستخدمين والصلاحيات'
    INSTRUCTORS = 'INSTRUCTORS', 'هيئة التعليم والمعلمون'
    TRAINEES = 'TRAINEES', 'سجل وشؤون الدارسين'
    COURSES = 'COURSES', 'الدورات والمناهج والمواد'
    SESSIONS = 'SESSIONS', 'انعقاد الدورات والدفعات'
    GRADES = 'GRADES', 'النتائج ورصد الدرجات والشهادات'
    SETTINGS = 'SETTINGS', 'إعدادات النظام والهوية'
    SYSTEM = 'SYSTEM', 'عمليات النظام العامة'


class ActivityLog(models.Model):
    """سجل النشاط والعمليات الشامل لمراقبة كافة إجراءات المستخدمين في النظام"""
    institute = models.ForeignKey(
        Institute,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
        verbose_name='المعهد'
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
        verbose_name='المستخدم'
    )
    username = models.CharField(
        max_length=150,
        verbose_name='اسم المستخدم وقت العملية'
    )
    user_fullname = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='الاسم الكامل للمستخدم'
    )
    user_role = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='الدور والصلاحية وقت العملية'
    )
    user_military_number = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='النمرة العسكرية'
    )
    action_type = models.CharField(
        max_length=30,
        choices=ActivityAction.choices,
        default=ActivityAction.OTHER,
        verbose_name='نوع العملية'
    )
    action_category = models.CharField(
        max_length=30,
        choices=ActivityCategory.choices,
        default=ActivityCategory.SYSTEM,
        verbose_name='قسم وسياق العملية'
    )
    description = models.TextField(
        verbose_name='تفاصيل ووصف العملية'
    )
    target_model = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='العنصر المستهدف'
    )
    target_id = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name='معرف العنصر'
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name='عنوان IP'
    )
    timestamp = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name='تاريخ ووقت العملية'
    )

    class Meta:
        app_label = 'training'
        ordering = ['-timestamp']
        verbose_name = 'سجل النشاط والعمليات'
        verbose_name_plural = 'سجل الأنشطة والعمليات'
        indexes = [
            models.Index(fields=['action_type', '-timestamp']),
            models.Index(fields=['action_category', '-timestamp']),
            models.Index(fields=['institute', '-timestamp']),
        ]

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M')}] {self.username} - {self.get_action_type_display()}: {self.description[:40]}"

    @property
    def badge_class(self):
        mapping = {
            ActivityAction.LOGIN: 'bg-info bg-opacity-10 text-info border border-info border-opacity-25',
            ActivityAction.LOGOUT: 'bg-secondary bg-opacity-10 text-secondary border border-secondary border-opacity-25',
            ActivityAction.CREATE: 'bg-success bg-opacity-10 text-success border border-success border-opacity-25',
            ActivityAction.UPDATE: 'bg-primary bg-opacity-10 text-primary border border-primary border-opacity-25',
            ActivityAction.DELETE: 'bg-danger bg-opacity-10 text-danger border border-danger border-opacity-25',
            ActivityAction.GRADE_ENTRY: 'bg-warning bg-opacity-10 text-dark border border-warning border-opacity-25',
            ActivityAction.GRADE_APPROVAL: 'bg-success bg-opacity-25 text-success border border-success',
            ActivityAction.STATUS_CHANGE: 'bg-dark bg-opacity-10 text-dark border border-dark border-opacity-25',
            ActivityAction.OTHER: 'bg-light text-dark border',
        }
        return mapping.get(self.action_type, 'bg-light text-dark border')

    @property
    def icon_class(self):
        mapping = {
            ActivityAction.LOGIN: 'bi bi-box-arrow-in-right text-info',
            ActivityAction.LOGOUT: 'bi bi-box-arrow-right text-secondary',
            ActivityAction.CREATE: 'bi bi-plus-circle-fill text-success',
            ActivityAction.UPDATE: 'bi bi-pencil-square text-primary',
            ActivityAction.DELETE: 'bi bi-trash-fill text-danger',
            ActivityAction.GRADE_ENTRY: 'bi bi-calculator-fill text-warning',
            ActivityAction.GRADE_APPROVAL: 'bi bi-patch-check-fill text-success',
            ActivityAction.STATUS_CHANGE: 'bi bi-arrow-repeat text-dark',
            ActivityAction.OTHER: 'bi bi-dot text-muted',
        }
        return mapping.get(self.action_type, 'bi bi-dot text-muted')


def log_activity(
    request=None,
    user=None,
    action_type=ActivityAction.OTHER,
    action_category=ActivityCategory.SYSTEM,
    description="",
    target_model="",
    target_id="",
    ip_address=None,
    institute=None
):
    """دالة مركزية لتسجيل وتوثيق أي عملية أو حدث في سجل نشاط المستخدمين"""
    try:
        current_user = None
        if user and getattr(user, 'is_authenticated', False):
            current_user = user
        elif request and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
            current_user = request.user

        inst = institute
        if not inst:
            if request and hasattr(request, 'institute') and request.institute:
                inst = request.institute
            elif current_user and hasattr(current_user, 'profile') and current_user.profile.institute:
                inst = current_user.profile.institute

        username = current_user.username if current_user else "مستخدم غير مسجل"
        user_fullname = current_user.get_full_name() if current_user else ""
        user_role = ""
        user_mil = ""

        if current_user and hasattr(current_user, 'profile'):
            user_role = current_user.profile.get_role_display()
            user_mil = current_user.profile.military_number or ""
        elif current_user and current_user.is_superuser:
            user_role = "مدير عام المنظومة (Super Admin)"

        if not ip_address and request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')

        return ActivityLog.objects.create(
            institute=inst,
            user=current_user,
            username=username,
            user_fullname=user_fullname,
            user_role=user_role,
            user_military_number=user_mil,
            action_type=action_type,
            action_category=action_category,
            description=description,
            target_model=target_model,
            target_id=str(target_id) if target_id else "",
            ip_address=ip_address,
            timestamp=timezone.now()
        )
    except Exception as e:
        import logging
        logging.getLogger('activity_logger').error(f"Error logging activity: {e}")
        return None
