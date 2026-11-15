from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

# قيد إلزامي: النمرة تقبل أرقاماً فقط
numeric_only_validator = RegexValidator(
    regex=r'^\d+$',
    message='النمرة يجب أن تحتوي على أرقام فقط بدون أحرف أو رموز (0-9).'
)

# قيد إلزامي: رقم الهاتف يتكون من 10 أرقام فقط
phone_10_digits_validator = RegexValidator(
    regex=r'^\d{10}$',
    message='رقم الهاتف يجب أن يتكون من 10 أرقام فقط دون مسافات أو رموز.'
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
    name = models.CharField(
        max_length=200,
        verbose_name='الاسم الكامل'
    )
    batch = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='الدفعة (رقمي)'
    )
    phone = models.CharField(
        max_length=30,
        blank=True,
        default='',
        validators=[phone_10_digits_validator],
        verbose_name='رقم الهاتف'
    )
    # حقول السكن
    residence_state = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='الولاية'
    )
    residence_city = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='المدينة'
    )
    residence_neighborhood = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='الحي'
    )
    residence_block = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='المربع / الحارة'
    )
    residence_house_number = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='رقم المنزل'
    )
    unit = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='الوحدة'
    )
    force = models.CharField(
        max_length=150,
        blank=True,
        default='',
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
        return f"{self.name} ({self.military_number})"

    @property
    def full_address(self):
        """تجميع تفاصيل السكن بصيغة نصية واضحة"""
        parts = []
        if self.residence_state:
            parts.append(f"الولاية: {self.residence_state}")
        if self.residence_city:
            parts.append(f"المدينة: {self.residence_city}")
        if self.residence_neighborhood:
            parts.append(f"الحي: {self.residence_neighborhood}")
        if self.residence_block:
            parts.append(f"المربع/الحارة: {self.residence_block}")
        if self.residence_house_number:
            parts.append(f"منزل: {self.residence_house_number}")
        return " - ".join(parts) if parts else "غير محدد"

    def get_four_relatives(self):
        """إرجاع قائمة بالأقارب الـ 4، وتعبئة البواقي بكائنات فارغة لعرضها في الشاشات"""
        existing = {r.order: r for r in self.relatives.all()[:4]}
        result = []
        for i in range(1, 5):
            result.append(existing.get(i, None))
        return result


class TraineeRelative(models.Model):
    """أقرب الأقربين للدارس (جهات الاتصال في حالات الطوارئ - حتى 4 أقارب)"""
    trainee = models.ForeignKey(
        Trainee,
        on_delete=models.CASCADE,
        related_name='relatives',
        verbose_name='الدارس'
    )
    order = models.PositiveSmallIntegerField(
        default=1,
        verbose_name='الترتيب (1-4)'
    )
    name = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='اسم القريب'
    )
    kinship = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='صلة القرابة'
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        default='',
        validators=[phone_10_digits_validator],
        verbose_name='رقم الهاتف'
    )
    address = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='مكان السكن / العنوان'
    )

    class Meta:
        verbose_name = 'قريب دارس'
        verbose_name_plural = 'أقرب الأقربين'
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.name} ({self.kinship}) - دارس: {self.trainee.name}"


class InstructorCategory(models.TextChoices):
    OFFICER = 'officer', 'ضابط'
    NCO = 'nco', 'ضابط صف'


class Instructor(models.Model):
    """بيانات المعلم / عضو هيئة التدريس"""
    military_number = models.CharField(
        max_length=50,
        primary_key=True,
        validators=[numeric_only_validator],
        verbose_name='النمرة العسكرية (مفتاح أساسي)'
    )
    category = models.CharField(
        max_length=20,
        choices=InstructorCategory.choices,
        default=InstructorCategory.OFFICER,
        verbose_name='التصنيف'
    )
    rank = models.CharField(
        max_length=100,
        verbose_name='الرتبة'
    )
    name = models.CharField(
        max_length=200,
        verbose_name='اسم المعلم'
    )
    force = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='القوة'
    )
    unit = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='الوحدة'
    )
    phone = models.CharField(
        max_length=50,
        blank=True,
        default='',
        validators=[phone_10_digits_validator],
        verbose_name='رقم الهاتف'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='نشط / على رأس العمل'
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
        verbose_name = 'معلم'
        verbose_name_plural = 'المعلمون'
        ordering = ['name']

    def __str__(self):
        prefix = f"{self.rank} / " if self.rank else ""
        return f"{prefix}{self.name} ({self.military_number})"


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
        unique=True,
        blank=True,
        default='',
        verbose_name='رقم الدورة / الرمز'
    )
    name = models.CharField(
        max_length=200,
        verbose_name='اسم الدورة'
    )
    attendance_max_grade = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=10.00,
        verbose_name='درجة المواظبة'
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

    @classmethod
    def generate_unique_course_number(cls, category=None):
        prefix = "CRS"
        if category and category.name:
            cat_name = category.name.strip()
            if "مرشد" in cat_name:
                prefix = "GUIDE"
            elif "خاص" in cat_name:
                prefix = "SPEC"
            elif "مشترك" in cat_name:
                prefix = "JOINT"
            else:
                prefix = f"C{category.id}"

        count = cls.objects.filter(category=category).count() + 1 if category else cls.objects.count() + 1
        candidate = f"{prefix}-{count:03d}"
        while cls.objects.filter(course_number=candidate).exists():
            count += 1
            candidate = f"{prefix}-{count:03d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.course_number:
            self.course_number = self.generate_unique_course_number(self.category)
        super().save(*args, **kwargs)

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
    session = models.ForeignKey(
        'CourseSession',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='custom_session_subjects',
        verbose_name='خاص بالدورة المنعقدة'
    )
    code = models.CharField(
        max_length=50,
        unique=True,
        blank=True,
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

    def clean(self):
        super().clean()
        if self.max_grade is not None and self.max_grade <= 0:
            raise ValidationError({'max_grade': 'الدرجة العظمى للمادة يجب أن تكون أكبر من صفر.'})

    @classmethod
    def generate_unique_code(cls, course, session=None):
        course_num = (course.course_number or f"C{course.id}").strip().replace(" ", "-")
        if session:
            sess_code = str(session.session_code or session.id).strip().replace(" ", "-")
            prefix = f"{course_num}-S{sess_code}"
        else:
            prefix = course_num
        count = cls.objects.filter(course=course).count() + 1
        candidate = f"{prefix}-{count:02d}"
        while cls.objects.filter(code=candidate).exists():
            count += 1
            candidate = f"{prefix}-{count:02d}"
        return candidate

    def save(self, *args, **kwargs):
        if not self.code and self.course_id:
            self.code = self.generate_unique_code(self.course, session=self.session)
        super().save(*args, **kwargs)

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
        on_delete=models.PROTECT,
        related_name='sessions',
        verbose_name='الدورة التدريبية'
    )
    session_code = models.CharField(
        max_length=100,
        verbose_name='رقم الدورة',
        help_text='رقم الدورة (توليد تلقائي معتمد)'
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
        default=10.00,
        verbose_name='درجة المواظبة والسلوك العظمى'
    )
    supervisor = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supervised_sessions',
        verbose_name='مشرف الدورة'
    )
    movement_order_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='تاريخ أمر التحرك',
        help_text='تاريخ صدور أمر التحرك الرسمي للدورة'
    )
    movement_order_file = models.FileField(
        upload_to='movement_orders/',
        null=True,
        blank=True,
        verbose_name='صورة أمر التحرك (Scan)',
        help_text='صورة ضوئية أو مستند PDF لأمر التحرك'
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

    def clean(self):
        super().clean()
        if self.attendance_max_grade is not None and self.attendance_max_grade < 0:
            raise ValidationError({'attendance_max_grade': 'الدرجة العظمى للمواظبة لا يمكن أن تكون سالبة.'})

    def save(self, *args, **kwargs):
        if not self.pk and (self.attendance_max_grade is None or self.attendance_max_grade == 10.00):
            if self.course and hasattr(self.course, 'attendance_max_grade') and self.course.attendance_max_grade is not None:
                self.attendance_max_grade = self.course.attendance_max_grade
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.course.name} - {self.session_code} ({self.start_date})"

    def get_subjects(self):
        """
        إرجاع قائمة المواد الدراسية الخاصة بهذه الدورة المنعقدة بالتحديد دون غيرها:
        1. إذا كان للدورة تعيينات مواد في SessionSubjectInstructor، تعتمد تلك المواد المسندة.
        2. وإذا كانت هناك مواد مخصصة منشأة لهذه الدورة (session=self)، تدرج أيضاً.
        3. وإذا كانت دورة تاريخية قديمة بدون تعيينات معلمين ولها درجات سابقة، تعتمد مواد درجاتها لحماية تاريخها.
        4. وإلا تعتمد المواد العامة للمقرر (التي لا تتبع دورات منعقدة أخرى).
        """
        # 1. إذا كان للدورة تعيينات مواد مسندة
        if self.subject_instructors.exists():
            assigned_subjects = [si.subject for si in self.subject_instructors.select_related('subject').all()]
            custom_subjects = list(self.custom_session_subjects.exclude(id__in=[s.id for s in assigned_subjects]))
            return assigned_subjects + custom_subjects

        # 2. إذا كانت هناك مواد مخصصة للدورة المنعقدة
        custom_subjects = list(self.custom_session_subjects.all())
        if custom_subjects:
            return custom_subjects

        # 3. إذا كانت دورة قديمة بدون تعيينات ولها درجات سابقة مرصودة
        graded_ids = list(TraineeSubjectGrade.objects.filter(
            enrollment__session=self,
            score__isnull=False
        ).values_list('subject_id', flat=True).distinct())
        if graded_ids:
            return list(Subject.objects.filter(id__in=graded_ids))

        # 4. الدورات الجديدة التي لم تعين موادها بعد: تعتمد المواد العامة للمقرر
        return list(self.course.subjects.filter(session__isnull=True))

    @property
    def total_possible_score(self):
        subjects = self.get_subjects()
        subjects_total = sum(s.max_grade for s in subjects)
        att = self.attendance_max_grade if self.attendance_max_grade is not None else (self.course.attendance_max_grade or Decimal('0.00'))
        return float(subjects_total) + float(att)


class SessionSubjectInstructor(models.Model):
    """ربط المادة في الدورة المنعقدة بالمعلم المسؤول عنها"""
    session = models.ForeignKey(
        CourseSession,
        on_delete=models.CASCADE,
        related_name='subject_instructors',
        verbose_name='الدورة المنعقدة'
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='session_assignments',
        verbose_name='المادة الدراسية'
    )
    instructor = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teaching_assignments',
        verbose_name='معلم المادة'
    )

    class Meta:
        verbose_name = 'معلم المادة بالدورة'
        verbose_name_plural = 'معلمو المواد بالدورات'
        unique_together = ('session', 'subject')

    def __str__(self):
        inst_name = self.instructor.name if self.instructor else 'لم يحدد'
        return f"{self.session.session_code} - {self.subject.name}: {inst_name}"


class CourseEnrollment(models.Model):
    """ربط الطالب بالدورة المنعقدة مع حفظ الرتبة والوحدة وقت الدورة"""
    session = models.ForeignKey(
        CourseSession,
        on_delete=models.PROTECT,
        related_name='enrollments',
        verbose_name='انعقاد الدورة'
    )
    trainee = models.ForeignKey(
        Trainee,
        on_delete=models.PROTECT,
        related_name='enrollments',
        verbose_name='الدارس'
    )
    # تتيح تعديل الرتبة والوحدة في الدورة مع الاحتفاظ بالأصل أو التحديث
    current_rank = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='الرتبة أثناء الدورة'
    )
    current_force = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='القوة أثناء الدورة'
    )
    current_unit = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='الوحدة أثناء الدورة'
    )
    movement_order_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='تاريخ أمر التحرك الخاص بالدارس'
    )
    movement_order_file = models.FileField(
        upload_to='trainee_movement_orders/',
        null=True,
        blank=True,
        verbose_name='صورة أمر التحرك الخاص بالدارس (Scan)'
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
    certificate_note = models.TextField(
        blank=True,
        default='',
        verbose_name='ملحوظة الشهادة'
    )
    is_dropped = models.BooleanField(
        default=False,
        verbose_name='تم قطع الدورة'
    )
    drop_reason = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='سبب قطع الدورة'
    )
    dropped_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='تاريخ ووقت قطع الدورة'
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
        # 0. التحقق من عدم قطع الدورة عن الدارس
        if self.is_dropped:
            return False

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

        # 4. التحقق من اكتمال درجات جميع المواد الخاصة بهذه الدورة المنعقدة
        session_subjects = self.session.get_subjects()
        total_subjects = len(session_subjects)
        if total_subjects == 0:
            return False  # لا يمكن إصدار شهادة لدورة بدون مواد دراسية

        actual_grades = list(TraineeSubjectGrade.objects.filter(enrollment=self, subject__in=session_subjects))
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

    def clean(self):
        super().clean()
        if self.attendance_score is not None:
            if self.attendance_score < 0:
                raise ValidationError({'attendance_score': 'لا يمكن أن تكون درجة المواظبة أقل من صفر.'})
            if hasattr(self, 'session') and self.session and self.session.attendance_max_grade is not None:
                if self.attendance_score > self.session.attendance_max_grade:
                    raise ValidationError({'attendance_score': f'درجة المواظبة ({self.attendance_score}) تتجاوز الحد الأقصى للمواظبة بالدورة ({self.session.attendance_max_grade}).'})

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
        session_subjects = self.session.get_subjects()
        total_subjects = len(session_subjects)
        actual_grades = list(TraineeSubjectGrade.objects.filter(enrollment=self, subject__in=session_subjects))
        graded_count = len(actual_grades)

        # إذا كانت الدورة بدون مواد أو لم تكتمل درجات جميع المواد الخاصة بهذه الدورة
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

    @property
    def rank_number(self):
        """الترتيب الرقمي للدارس بين زملائه في نفس الانعقاد حسب المجموع الكلي"""
        if not self.is_graded or self.total_score is None:
            return None
        graded_ids = list(
            self.session.enrollments.filter(is_graded=True)
            .order_by('-total_score', 'trainee__name')
            .values_list('id', flat=True)
        )
        try:
            return graded_ids.index(self.id) + 1
        except ValueError:
            return None

    @property
    def total_enrolled_count(self):
        """إجمالي عدد الدارسين المرصودين في نفس الانعقاد"""
        count = self.session.enrollments.filter(is_graded=True).count()
        return count if count > 0 else self.session.enrollments.count()

    @property
    def rank_arabic_text(self):
        """الترتيب كتابة باللغة العربية (الأول، الثاني، ...)"""
        rn = self.rank_number
        if not rn:
            return '-'
        ranks = {
            1: 'الأول', 2: 'الثاني', 3: 'الثالث', 4: 'الرابع', 5: 'الخامس',
            6: 'السادس', 7: 'السابع', 8: 'الثامن', 9: 'التاسع', 10: 'العاشر',
            11: 'الحادي عشر', 12: 'الثاني عشر', 13: 'الثالث عشر', 14: 'الرابع عشر', 15: 'الخامس عشر',
            16: 'السادس عشر', 17: 'السابع عشر', 18: 'الثامن عشر', 19: 'التاسع عشر', 20: 'العشرون',
            21: 'الحادي والعشرون', 22: 'الثاني والعشرون', 23: 'الثالث والعشرون', 24: 'الرابع والعشرون', 25: 'الخامس والعشرون',
            26: 'السادس والعشرون', 27: 'السابع والعشرون', 28: 'الثامن والعشرون', 29: 'التاسع والعشرون', 30: 'الثلاثون',
            31: 'الحادي والثلاثون', 32: 'الثاني والثلاثون', 33: 'الثالث والثلاثون', 34: 'الرابع والثلاثون', 35: 'الخامس والثلاثون',
            36: 'السادس والثلاثون', 37: 'السابع والثلاثون', 38: 'الثامن والثلاثون', 39: 'التاسع والثلاثون', 40: 'الأربعون',
            41: 'الحادي والأربعون', 42: 'الثاني والأربعون', 43: 'الثالث والأربعون', 44: 'الرابع والأربعون', 45: 'الخامس والأربعون',
            46: 'السادس والأربعون', 47: 'السابع والأربعون', 48: 'الثامن والأربعون', 49: 'التاسع والأربعون', 50: 'الخمسون'
        }
        return ranks.get(rn, f'الترتيب {rn}')

    @property
    def rank_display(self):
        """عرض الترتيب متبوعاً بإجمالي الدارسين، مثل: الأول / 17"""
        rn = self.rank_number
        if not rn:
            return '-'
        return f"{self.rank_arabic_text} / {self.total_enrolled_count}"

    @property
    def grade_symbol(self):
        """رمز التقدير (أ، ب، ج، د، هـ) المطابق لشهادات المعهد العسكري"""
        pct = float(self.percentage or 0.0)
        if pct >= 85:
            return '(أ)'
        elif pct >= 75:
            return '(ب)'
        elif pct >= 65:
            return '(ج)'
        elif pct >= 50:
            return '(د)'
        else:
            return '(هـ)'


def has_trainee_passed_course(trainee, course):
    """
    التحقق مما إذا كان الطالب قد أكمل الدورة ونجح فيها مسبقاً (في أي دفعة سابقة).
    النجاح: تم رصد الدرجات (is_graded=True)، والنسبة >= 50%، والتقدير ليس راسباً.
    """
    return CourseEnrollment.objects.filter(
        trainee=trainee,
        session__course=course,
        is_graded=True,
        percentage__gte=50.0
    ).exclude(grade_label__icontains='راسب').select_related('session').first()


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
        on_delete=models.PROTECT,
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

    def clean(self):
        super().clean()
        if self.score is not None:
            if self.score < 0:
                raise ValidationError({'score': 'لا يمكن أن تكون الدرجة أقل من صفر.'})
            if hasattr(self, 'subject') and self.subject and self.subject.max_grade is not None:
                if self.score > self.subject.max_grade:
                    raise ValidationError({'score': f'الدرجة المكتسبة ({self.score}) تتجاوز الدرجة العظمى للمادة ({self.subject.max_grade}).'})

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
    basic_cert_title = models.CharField(
        max_length=200,
        default='شهادة دورة حاسوب أساسية',
        verbose_name='عنوان شهادة التفاصيل'
    )
    default_certificate_note = models.TextField(
        default='بدأ الدورة بدون معلومات، بذل مجهوداً أهله للحصول على هذا التقدير، مواظب ومشارك، مهتم وطموح.',
        verbose_name='نص الملحوظة الافتراضي للشهادة'
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


class MovementOrderSettings(models.Model):
    """إعدادات وتخصيص قالب ونصوص أمر التحرك الرسمي المعتمد"""
    bismillah_text = models.CharField(
        max_length=200,
        default='بسم الله الرحمن الرحيم',
        verbose_name='البسملة'
    )
    security_label = models.CharField(
        max_length=100,
        default='محظور',
        verbose_name='درجة السرية'
    )
    order_title = models.CharField(
        max_length=150,
        default='أمر تــــحـــــرك',
        verbose_name='عنوان الأمر'
    )
    issuing_authority_text = models.TextField(
        default='الصادر بأمر سيادة العقيد مهندس المعز علي محمد خير حامل وسام الدفاع الذهبي ، نوط الواجب ، وسام الانجاز العسكري ، الخدمة الطويلة الممتازة ، وقائد معهد نظم المعلومات والإحصاء.',
        verbose_name='نص ديباجة الصدور (الآمر)'
    )
    from_location = models.CharField(
        max_length=250,
        default='معهد نــظـــــم المعلومات والاحصاء',
        verbose_name='الجهة المتحرك منها (مـن)'
    )
    to_location_default = models.CharField(
        max_length=250,
        default='شعبـــــــــــــــــــة التدريب',
        verbose_name='الجهة المتحرك إليها الافتراضية (إلـى)'
    )
    arms_default = models.CharField(
        max_length=150,
        default='لا يكـــــــــــــــــــــــــــــــــن',
        verbose_name='السلاح'
    )
    ammunition_default = models.CharField(
        max_length=150,
        default='لا يكـــــــــــــــــــــــــــــــــن',
        verbose_name='الذخيرة'
    )
    purpose_prefix = models.CharField(
        max_length=100,
        default='انتهاء ',
        verbose_name='بادئة الغرض'
    )
    clothing_instructions = models.CharField(
        max_length=250,
        default='حســــــــــــب التعليمــــــــــــــــات',
        verbose_name='اللبس'
    )
    travel_means = models.CharField(
        max_length=250,
        default='بالمتاحـــــــــــــــــــــــــــــــــــــة',
        verbose_name='وسيلة السفر'
    )
    ratification_text = models.CharField(
        max_length=250,
        default='السيد قائد معهد نظم المعلومات والاحصاء',
        verbose_name='التصديق'
    )
    admin_instructions = models.TextField(
        default='بموجب هذا الأمر وجب عليك / عليكم مغادرة معهد نظم المعلومات والإحصاء والتوجه الي شعبة التدريب وعند وصولك / وصولكم عليك / عليكم مقابلة السيد رئيس شعبة التدريب لأخذ التعليمات الاخيرة منه .',
        verbose_name='نص التعليمات الإدارية'
    )
    certificate_declaration = models.TextField(
        default='اشهد بأن التعليمات قد تليت علي / علينا وسوف أعمل / نعمل بموجبها ونحافظ على الضبط والربط والانتظام في اللبس أثناء السفر حتى وصولي / وصولنا',
        verbose_name='نص إقرار الشهادة'
    )
    signer_rank = models.CharField(
        max_length=100,
        default='مقدم مهندس ركن',
        verbose_name='رتبة القائد الموقع'
    )
    signer_name = models.CharField(
        max_length=150,
        default='وليد عادل جاه الله حسب الرسول',
        verbose_name='اسم القائد الموقع'
    )
    signer_title = models.CharField(
        max_length=150,
        default='ع/عقيد مهندس',
        verbose_name='صفة/نيابة القائد الموقع'
    )
    signer_dept = models.CharField(
        max_length=150,
        default='قائد معهد نظم المعلومات والإحصاء',
        verbose_name='منصب القائد الموقع'
    )
    copy_to_1 = models.CharField(
        max_length=250,
        default='السيد / رئيس شعبـــــــــة التدريب',
        verbose_name='نسخة إلى (1)'
    )
    copy_to_2 = models.CharField(
        max_length=250,
        default='نسخة بيد المذكور / بالـمـ ه / ل 3 / ف',
        verbose_name='نسخة إلى (2)'
    )
    watermark_image = models.ImageField(
        upload_to='movement_watermarks/',
        null=True,
        blank=True,
        verbose_name='صورة العلامة المائية المخصصة'
    )
    watermark_opacity = models.FloatField(
        default=0.15,
        verbose_name='درجة شفافية العلامة المائية'
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name='تاريخ آخر تعديل'
    )

    class Meta:
        verbose_name = 'إعدادات وتخصيص أمر التحرك'
        verbose_name_plural = 'إعدادات وتخصيص أمر التحرك'

    def __str__(self):
        return 'إعدادات أمر التحرك الرسمي'

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj

    @property
    def watermark_url(self):
        if self.watermark_image and hasattr(self.watermark_image, 'url'):
            return self.watermark_image.url
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
    REGISTRAR = 'registrar', 'مسجل بيانات'
    SUPERVISOR = 'supervisor', 'مشرف دورة'
    INSTRUCTOR = 'instructor', 'معلم / هيئة التدريس'
    REGULAR = 'regular', 'مستخدم عادي'
    CUSTOM = 'custom', 'أذونات مخصصة'


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
    instructor = models.ForeignKey(
        'Instructor',
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

    # أذونات وصلاحيات تفصيلية كخيارات صح (Checkboxes) بأسلوب ويندوز
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

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ الإضافة'
    )

    class Meta:
        verbose_name = 'الملف الشخصي للمستخدم'
        verbose_name_plural = 'ملفات وصلاحيات المستخدمين'

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"

    def sync_permissions_from_role(self):
        """مزامنة خانات الاختيار للأذونات تلقائياً بناءً على الدور المختار"""
        if self.role == UserRole.ADMIN or (self.user and (self.user.is_superuser or self.user.is_staff)):
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

    @property
    def is_admin(self):
        return bool(self.user.is_superuser or self.user.is_staff or self.role == UserRole.ADMIN or self.can_manage_users)

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
        ordering = ['-timestamp']
        verbose_name = 'سجل النشاط والعمليات'
        verbose_name_plural = 'سجل الأنشطة والعمليات'

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
    ip_address=None
):
    """دالة مركزية لتسجيل وتوثيق أي عملية أو حدث في سجل نشاط المستخدمين"""
    try:
        current_user = None
        if user and getattr(user, 'is_authenticated', False):
            current_user = user
        elif request and hasattr(request, 'user') and getattr(request.user, 'is_authenticated', False):
            current_user = request.user

        username = current_user.username if current_user else "مستخدم غير مسجل"
        user_fullname = current_user.get_full_name() if current_user else ""
        user_role = ""
        user_mil = ""

        if current_user and hasattr(current_user, 'profile'):
            user_role = current_user.profile.get_role_display()
            user_mil = current_user.profile.military_number or ""
        elif current_user and current_user.is_superuser:
            user_role = "مدير نظام عام (Superuser)"

        if not ip_address and request:
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = request.META.get('REMOTE_ADDR')

        return ActivityLog.objects.create(
            user=current_user,
            username=username,
            user_fullname=user_fullname,
            user_role=user_role,
            user_military_number=user_mil,
            action_type=action_type,
            action_category=action_category,
            description=description,
            target_model=target_model or "",
            target_id=str(target_id) if target_id is not None else "",
            ip_address=ip_address or None,
            timestamp=timezone.now()
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Error logging activity: {e}")
        return None


