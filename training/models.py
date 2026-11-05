from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# قيد إلزامي: النمرة تقبل أرقاماً فقط
numeric_only_validator = RegexValidator(
    regex=r'^\d+$',
    message='النمرة يجب أن تحتوي على أرقام فقط بدون أحرف أو رموز (0-9).'
)


class TraineeCategory(models.TextChoices):
    OFFICER = 'officer', 'ضباط'
    NCO = 'nco', 'ضباط صف'
    CIVILIAN = 'civilian', 'مدنيين'


class Trainee(models.Model):
    """بيانات الدارس الأساسية"""
    military_number = models.CharField(
        max_length=50,
        primary_key=True,
        validators=[numeric_only_validator],
        verbose_name='النمرة (أرقام فقط)'
    )
    category = models.CharField(
        max_length=20,
        choices=TraineeCategory.choices,
        default=TraineeCategory.OFFICER,
        verbose_name='التصنيف'
    )
    rank = models.CharField(
        max_length=100,
        verbose_name='الرتبة'
    )
    name = models.CharField(
        max_length=200,
        verbose_name='الاسم الكامل'
    )
    unit = models.CharField(
        max_length=150,
        verbose_name='الوحدة'
    )
    force = models.CharField(
        max_length=150,
        verbose_name='القوة'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإضافة'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='تاريخ التحديث'
    )

    class Meta:
        verbose_name = 'دارس'
        verbose_name_plural = 'الدارسون'
        ordering = ['category', 'military_number']

    def __str__(self):
        return f"{self.rank} / {self.name} ({self.military_number})"


class CourseCategory(models.Model):
    """تصنيف الدورة (دورات مرشد، دورات خاصة، دورات مشتركة)"""
    name = models.CharField(
        max_length=150,
        unique=True,
        verbose_name='اسم تصنيف الدورة'
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name='الوصف'
    )

    class Meta:
        verbose_name = 'تصنيف دورة'
        verbose_name_plural = 'تصنيفات الدورات'
        ordering = ['id']

    def __str__(self):
        return self.name


class Course(models.Model):
    """بيانات الدورة التدريبية ومقررها"""
    category = models.ForeignKey(
        CourseCategory,
        on_delete=models.CASCADE,
        related_name='courses',
        verbose_name='تصنيف الدورة'
    )
    course_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name='رقم الدورة / الرمز'
    )
    name = models.CharField(
        max_length=200,
        verbose_name='اسم الدورة'
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name='وصف الدورة والأهداف'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإنشاء'
    )

    class Meta:
        verbose_name = 'دورة'
        verbose_name_plural = 'الدورات'
        ordering = ['category', 'name']

    def __str__(self):
        return f"{self.name} ({self.category.name})"

    @property
    def total_hours(self):
        return sum(subject.credit_hours for subject in self.subjects.all())

    @property
    def total_max_marks(self):
        return sum(subject.max_grade for subject in self.subjects.all())


class Subject(models.Model):
    """المواد الدراسية التابعة للدورة"""
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='subjects',
        verbose_name='الدورة'
    )
    code = models.CharField(
        max_length=50,
        verbose_name='رقم/كود المادة'
    )
    name = models.CharField(
        max_length=150,
        verbose_name='اسم المادة'
    )
    credit_hours = models.PositiveIntegerField(
        default=10,
        verbose_name='عدد الساعات'
    )
    max_grade = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=100.00,
        verbose_name='الدرجة العظمى'
    )

    class Meta:
        verbose_name = 'مادة دراسية'
        verbose_name_plural = 'المواد الدراسية'
        ordering = ['id']

    def __str__(self):
        return f"{self.name} ({self.code})"


class CourseSession(models.Model):
    """الدورة التي يتم دراستها (انعقاد دورة محددة بتاريخ)"""
    STATUS_CHOICES = [
        ('planned', 'مخطط لها'),
        ('active', 'جارية حالياً'),
        ('completed', 'مكتملة ومُعتمدة'),
    ]

    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='sessions',
        verbose_name='الدورة التدريبية'
    )
    session_code = models.CharField(
        max_length=100,
        verbose_name='رمز الانعقاد / الدفعة',
        help_text='مثال: دفعة 14 أو دورة 2026/1'
    )
    start_date = models.DateField(
        verbose_name='تاريخ بداية الدورة'
    )
    end_date = models.DateField(
        verbose_name='تاريخ نهاية الدورة'
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='active',
        verbose_name='حالة الدورة'
    )
    attendance_max_grade = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=20.00,
        verbose_name='درجة المواظبة والسلوك العظمى'
    )
    notes = models.TextField(
        blank=True,
        null=True,
        verbose_name='ملاحظات'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإنشاء'
    )

    class Meta:
        verbose_name = 'انعقاد دورة'
        verbose_name_plural = 'الدورات المنعقدة'
        ordering = ['-start_date']

    def __str__(self):
        return f"{self.course.name} - {self.session_code} ({self.start_date})"

    @property
    def total_possible_score(self):
        subjects_total = sum(s.max_grade for s in self.course.subjects.all())
        return float(subjects_total) + float(self.attendance_max_grade)


class CourseEnrollment(models.Model):
    """ربط الطالب بالدورة المنعقدة مع حفظ الرتبة والوحدة وقت الدورة"""
    session = models.ForeignKey(
        CourseSession,
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name='انعقاد الدورة'
    )
    trainee = models.ForeignKey(
        Trainee,
        on_delete=models.CASCADE,
        related_name='enrollments',
        verbose_name='الدارس'
    )
    # تتيح تعديل الرتبة والوحدة في الدورة مع الاحتفاظ بالأصل أو التحديث
    current_rank = models.CharField(
        max_length=100,
        verbose_name='الرتبة أثناء الدورة'
    )
    current_unit = models.CharField(
        max_length=150,
        verbose_name='الوحدة أثناء الدورة'
    )
    attendance_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        verbose_name='درجة المواظبة'
    )
    total_score = models.DecimalField(
        max_digits=7,
        decimal_places=2,
        default=0.00,
        verbose_name='المجموع الكلي'
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        verbose_name='النسبة المئوية (%)'
    )
    grade_label = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='التقدير'
    )
    is_graded = models.BooleanField(
        default=False,
        verbose_name='تم رصد الدرجات'
    )

    class Meta:
        verbose_name = 'تسجيل دارس بالدورة'
        verbose_name_plural = 'تسجيلات الدارسين'
        unique_together = ('session', 'trainee')
        ordering = ['-total_score', 'trainee__name']

    def __str__(self):
        return f"{self.trainee.name} في {self.session}"

    @property
    def has_complete_data_and_grades(self):
        """
        التحقق الصارم من اكتمال كافة البيانات والدرجات المطلوبة لإصدار الشهادة:
        1. بيانات الدارس (النمرة والاسم).
        2. بيانات الرتبة والوحدة أثناء انعقاد الدورة.
        3. بيانات الدورة (الاسم، الرمز/الدفعة، تاريخ البداية والنهاية).
        4. اكتمال جميع المواد الدراسية للدورة ورصد درجاتها بالكامل.
        5. اعتماد النتيجة وحساب المجموع والنسبة.
        """
        # 1. التحقق من بيانات الدارس الأساسية
        if not self.trainee:
            return False
        if not self.trainee.military_number or not str(self.trainee.military_number).strip():
            return False
        if not self.trainee.name or not self.trainee.name.strip():
            return False

        # 2. التحقق من الرتبة والوحدة أثناء الدورة
        if not self.current_rank or not self.current_rank.strip():
            return False
        if not self.current_unit or not self.current_unit.strip():
            return False

        # 3. التحقق من بيانات الدورة المنعقدة والتواريخ
        if not self.session or not self.session.course:
            return False
        if not self.session.course.name or not self.session.course.name.strip():
            return False
        if not self.session.session_code or not self.session.session_code.strip():
            return False
        if not self.session.start_date or not self.session.end_date:
            return False

        # 4. التحقق من اكتمال درجات جميع المواد
        total_subjects = self.session.course.subjects.count()
        if total_subjects == 0:
            return False  # لا يمكن إصدار شهادة لدورة بدون مواد دراسية

        actual_grades = list(TraineeSubjectGrade.objects.filter(enrollment=self))
        graded_count = len(actual_grades)
        if graded_count < total_subjects:
            return False  # المواد غير مكتملة الرصد

        for g in actual_grades:
            if g.score is None:
                return False

        # 5. التحقق من اعتماد الرصد
        if not self.is_graded or self.total_score is None or self.percentage is None:
            return False

        return True

    def calculate_results(self):
        """
        حساب المجموع الكلي، النسبة المئوية، والتقدير
        النسبة = (مجموع درجات الطالب * 100) / مجموع الدرجات الكلي
        التقديرات:
        85 - 100 : ممتاز (أ)
        75 - 84  : جيد جداً (ب)
        65 - 74  : جيد (ج)
        50 - 64  : مقبول (د)
        أقل من 50: دون المستوى / راسب
        """
        total_subjects = self.session.course.subjects.count()
        actual_grades = list(TraineeSubjectGrade.objects.filter(enrollment=self))
        graded_count = len(actual_grades)

        # إذا كانت الدورة بدون مواد أو لم تكتمل درجات جميع المواد
        if total_subjects == 0 or graded_count < total_subjects:
            self.is_graded = False
            self.total_score = 0.0
            self.percentage = 0.0
            self.grade_label = ''
            self.save()
            return None

        subjects_scores = sum(float(g.score) for g in actual_grades)
        total_obtained = subjects_scores + float(self.attendance_score or 0.0)
        
        max_total = self.session.total_possible_score
        
        if max_total > 0:
            pct = round((total_obtained * 100.0) / max_total, 2)
        else:
            pct = 0.0

        if pct >= 85:
            grade = 'ممتاز (أ)'
        elif pct >= 75:
            grade = 'جيد جداً (ب)'
        elif pct >= 65:
            grade = 'جيد (ج)'
        elif pct >= 50:
            grade = 'مقبول (د)'
        else:
            grade = 'دون المستوى / راسب'

        self.total_score = total_obtained
        self.percentage = pct
        self.grade_label = grade
        self.is_graded = True
        self.save()
        return {
            'total': total_obtained,
            'percentage': pct,
            'grade': grade
        }


class TraineeSubjectGrade(models.Model):
    """درجة مادة محددة للدارس في انعقاد الدورة"""
    enrollment = models.ForeignKey(
        CourseEnrollment,
        on_delete=models.CASCADE,
        related_name='grades',
        verbose_name='تسجيل الدارس'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='trainee_grades',
        verbose_name='المادة'
    )
    score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
        verbose_name='الدرجة المكتسبة'
    )

    class Meta:
        verbose_name = 'درجة مادة'
        verbose_name_plural = 'درجات المواد'
        unique_together = ('enrollment', 'subject')

    def __str__(self):
        return f"{self.enrollment.trainee.name} - {self.subject.name}: {self.score}"


class CertificateSettings(models.Model):
    """إعدادات وتخصيص قالب وتوقيعات الشهادة الرسمية"""
    bismillah_text = models.CharField(
        max_length=200,
        default='بسم الله الرحمن الرحيم',
        verbose_name='البسملة'
    )
    header_line_1 = models.CharField(
        max_length=250,
        default='إدارة نظم المعلومات والإحصاء',
        verbose_name='عنوان الترويسة الأول'
    )
    header_line_2 = models.CharField(
        max_length=250,
        default='معهد نظم المعلومات والإحصاء',
        verbose_name='عنوان الترويسة الثاني'
    )
    cert_title = models.CharField(
        max_length=100,
        default='شهــــــادة',
        verbose_name='عنوان الشهادة'
    )
    cert_title_color = models.CharField(
        max_length=20,
        default='#FF0000',
        verbose_name='لون عنوان الشهادة'
    )

    # الموقع الأيمن (قائد جناح التعليم)
    right_signer_rank = models.CharField(
        max_length=100,
        default='مقدم مهندس ركن',
        verbose_name='رتبة الموقع الأيمن'
    )
    right_signer_name = models.CharField(
        max_length=150,
        default='وليد عادل جاه الله حسب الرسول',
        verbose_name='اسم الموقع الأيمن'
    )
    right_signer_title = models.CharField(
        max_length=150,
        default='قــــــائد جنـــــــــاح التعليــــــــــم',
        verbose_name='منصب/صفة الموقع الأيمن'
    )

    # الموقع الأيسر (قائد معهد نظم المعلومات والإحصاء)
    left_signer_rank = models.CharField(
        max_length=100,
        default='عقيد مهندس',
        verbose_name='رتبة الموقع الأيسر'
    )
    left_signer_name = models.CharField(
        max_length=150,
        default='المعــز علـــــي محمــــــد خيـــــــــر',
        verbose_name='اسم الموقع الأيسر'
    )
    left_signer_title = models.CharField(
        max_length=150,
        default='قائد معهد نظم المعلومات والإحصاء',
        verbose_name='منصب/صفة الموقع الأيسر'
    )

    # معتمد الشهادة (الوسط - مدير إدارة نظم المعلومات)
    center_approval_prefix = models.CharField(
        max_length=50,
        default='يعتمد',
        verbose_name='كلمة الاعتماد'
    )
    center_signer_rank = models.CharField(
        max_length=100,
        default='لواء دكتور ركن',
        verbose_name='رتبة معتمد الشهادة'
    )
    center_signer_name = models.CharField(
        max_length=150,
        default='إبــــراهيم محمــــد علـــــــي أحمــــد',
        verbose_name='اسم معتمد الشهادة'
    )
    center_signer_title = models.CharField(
        max_length=150,
        default='مدير إدارة نظم المعلومات والإحصاء',
        verbose_name='منصب/صفة معتمد الشهادة'
    )

    # تذييل الشهادة
    station_text = models.CharField(
        max_length=100,
        default='الخرطــــــــــــوم',
        verbose_name='المحطة'
    )
    seal_notice = models.CharField(
        max_length=250,
        default='(أي شهادة غير مختومة بالختم البارز لا تعتمد)',
        verbose_name='عبارة الختم البارز'
    )
    logo_height_mm = models.PositiveIntegerField(
        default=56,
        verbose_name='ارتفاع الشعار (ملم)'
    )
    # الشعارات القابلة للتخصيص
    right_logo = models.ImageField(
        upload_to='cert_logos/',
        blank=True,
        null=True,
        verbose_name='شعار الشهادة الأيمن'
    )
    left_logo = models.ImageField(
        upload_to='cert_logos/',
        blank=True,
        null=True,
        verbose_name='شعار الشهادة الأيسر'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='تاريخ آخر تعديل'
    )

    class Meta:
        verbose_name = 'إعدادات وتخصيص الشهادة'
        verbose_name_plural = 'إعدادات وتخصيص الشهادة'

    def __str__(self):
        return 'إعدادات الشهادة الرسمية'

    @classmethod
    def get_settings(cls):
        """الحصول على إعدادات الشهادة أو إنشاؤها بالقيم الافتراضية"""
        obj, created = cls.objects.get_or_create(id=1)
        return obj

    @property
    def right_logo_url(self):
        if self.right_logo and hasattr(self.right_logo, 'url'):
            return self.right_logo.url
        return None

    @property
    def left_logo_url(self):
        if self.left_logo and hasattr(self.left_logo, 'url'):
            return self.left_logo.url
        return None


class SystemSettings(models.Model):
    """إعدادات وهوية وألوان وشعار النظام بالكامل"""
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
        verbose_name = 'إعدادات وهوية النظام'
        verbose_name_plural = 'إعدادات وهوية النظام'

    def __str__(self):
        return 'إعدادات وهوية وألوان النظام'

    @classmethod
    def get_settings(cls):
        """الحصول على كائن الإعدادات أو إنشاؤه بالقيم الافتراضية"""
        obj, created = cls.objects.get_or_create(id=1)
        return obj

    @property
    def main_logo_url(self):
        if self.main_logo and hasattr(self.main_logo, 'url'):
            return self.main_logo.url
        return None


class UserRole(models.TextChoices):
    ADMIN = 'admin', 'مدير نظام (أدمن)'
    REGULAR = 'regular', 'مستخدم عادي'


class UserProfile(models.Model):
    """الملف التعريفي ونوع وصلاحية المستخدم في النظام"""
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
        verbose_name='رقم الهاتف'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإضافة'
    )

    class Meta:
        verbose_name = 'الملف الشخصي للمستخدم'
        verbose_name_plural = 'ملفات وصلاحيات المستخدمين'

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


@receiver(post_save, sender=User)
def create_or_update_user_profile(sender, instance, created, **kwargs):
    """إنشاء أو تحديث بروفايل المستخدم تلقائياً عند حفظ كائن المستخدم"""
    if created:
        role = UserRole.ADMIN if (instance.is_superuser or instance.is_staff) else UserRole.REGULAR
        UserProfile.objects.get_or_create(user=instance, defaults={'role': role})
    else:
        if hasattr(instance, 'profile'):
            instance.profile.save()
        else:
            role = UserRole.ADMIN if (instance.is_superuser or instance.is_staff) else UserRole.REGULAR
            UserProfile.objects.get_or_create(user=instance, defaults={'role': role})

