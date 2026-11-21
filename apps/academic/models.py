from decimal import Decimal
from django.db import models
from django.utils import timezone
from django.core.exceptions import ValidationError
from apps.core.models import Institute
from apps.core.validators import validate_movement_order_file
from apps.trainees.models import Trainee, TraineeCategory, numeric_only_validator, phone_10_digits_validator


class InstructorCategory(models.TextChoices):
    OFFICER = 'officer', 'ضابط'
    NCO = 'nco', 'ضابط صف'


class Instructor(models.Model):
    """بيانات المعلم / عضو هيئة التدريس"""
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='instructors',
        verbose_name='المعهد'
    )
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
        app_label = 'training'
        verbose_name = 'معلم'
        verbose_name_plural = 'المعلمون'
        ordering = ['name']

    def __str__(self):
        prefix = f"{self.rank} / " if self.rank else ""
        return f"{prefix}{self.name} ({self.military_number})"

    def save(self, *args, **kwargs):
        if not self.institute_id:
            default_inst = Institute.objects.filter(is_active=True).first()
            if default_inst:
                self.institute = default_inst
        super().save(*args, **kwargs)


class CourseCategory(models.Model):
    """تصنيف الدورة (دورات مرشد، دورات خاصة، دورات مشتركة)"""
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='categories',
        verbose_name='المعهد'
    )
    name = models.CharField(
        max_length=150,
        verbose_name='اسم تصنيف الدورة'
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name='الوصف'
    )

    class Meta:
        app_label = 'training'
        verbose_name = 'تصنيف دورة'
        verbose_name_plural = 'تصنيفات الدورات'
        ordering = ['id']
        unique_together = ('institute', 'name')

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.institute_id:
            default_inst = Institute.objects.filter(is_active=True).first()
            if default_inst:
                self.institute = default_inst
        super().save(*args, **kwargs)


class Course(models.Model):
    """بيانات الدورة التدريبية ومقررها"""
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='courses',
        verbose_name='المعهد'
    )
    category = models.ForeignKey(
        CourseCategory,
        on_delete=models.CASCADE,
        related_name='courses',
        verbose_name='تصنيف الدورة'
    )
    course_number = models.CharField(
        max_length=50,
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
        app_label = 'training'
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
        if not self.institute and self.category and self.category.institute:
            self.institute = self.category.institute
        elif not self.institute_id:
            default_inst = Institute.objects.filter(is_active=True).first()
            if default_inst:
                self.institute = default_inst
        if not self.course_number:
            self.course_number = self.generate_unique_course_number(self.category)
        super().save(*args, **kwargs)

    @property
    def total_hours(self):
        return sum(subject.credit_hours for subject in self.subjects.all())

    @property
    def total_max_marks(self):
        val = sum(subject.max_grade for subject in self.subjects.all())
        if val is not None and val == int(val):
            return int(val)
        return val

    @property
    def natural_attendance_grade(self):
        if self.attendance_max_grade is None:
            return 10
        return int(self.attendance_max_grade) if self.attendance_max_grade == int(self.attendance_max_grade) else self.attendance_max_grade


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
        app_label = 'training'
        verbose_name = 'مادة دراسية'
        verbose_name_plural = 'المواد الدراسية'
        ordering = ['id']

    def clean(self):
        super().clean()
        if self.max_grade is not None and self.max_grade <= 0:
            raise ValidationError({'max_grade': 'الدرجة العظمى للمادة يجب أن تكون أكبر من صفر.'})

    @property
    def natural_max_grade(self):
        if self.max_grade is None:
            return 100
        return int(self.max_grade) if self.max_grade == int(self.max_grade) else self.max_grade

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


class SessionTargetGroup(models.TextChoices):
    OFFICER = 'officer', 'ضباط'
    NCO = 'nco', 'ضباط صف'
    JOINT = 'joint', 'مشتركة'
    CIVILIAN = 'civilian', 'مدنيين'


class CourseSession(models.Model):
    """الدورة التي يتم دراستها (انعقاد دورة محددة بتاريخ)"""
    STATUS_CHOICES = [
        ('planned', 'مخطط لها'),
        ('active', 'جارية حالياً'),
        ('completed', 'مكتملة ومُعتمدة'),
    ]

    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='sessions',
        verbose_name='المعهد'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.PROTECT,
        related_name='sessions',
        verbose_name='الدورة التدريبية'
    )
    target_category = models.CharField(
        max_length=20,
        choices=SessionTargetGroup.choices,
        default=SessionTargetGroup.OFFICER,
        verbose_name='فئة الدارسين المستهدفة'
    )
    session_code = models.CharField(
        max_length=100,
        verbose_name='رقم الدفعة',
        help_text='رقم الدفعة (توليد تلقائي معتمد)'
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
        validators=[validate_movement_order_file],
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
        app_label = 'training'
        verbose_name = 'انعقاد دورة'
        verbose_name_plural = 'الدورات المنعقدة'
        ordering = ['-start_date']

    def clean(self):
        super().clean()
        if self.attendance_max_grade is not None and self.attendance_max_grade < 0:
            raise ValidationError({'attendance_max_grade': 'الدرجة العظمى للمواظبة لا يمكن أن تكون سالبة.'})

    def save(self, *args, **kwargs):
        if not self.institute_id:
            if self.course and hasattr(self.course, 'institute') and self.course.institute:
                self.institute = self.course.institute
            else:
                default_inst = Institute.objects.filter(is_active=True).first()
                if default_inst:
                    self.institute = default_inst
        if not self.pk and (self.attendance_max_grade is None or self.attendance_max_grade == 10.00):
            if self.course and hasattr(self.course, 'attendance_max_grade') and self.course.attendance_max_grade is not None:
                self.attendance_max_grade = self.course.attendance_max_grade
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.course.name} - دفعة {self.session_code} ({self.get_target_category_display()})"

    def get_subjects(self):
        """
        إرجاع قائمة المواد الدراسية الخاصة بهذه الدورة المنعقدة بالتحديد دون غيرها:
        1. إذا كان للدورة تعيينات مواد في SessionSubjectInstructor، تعتمد تلك المواد المسندة.
        2. وإذا كانت هناك مواد مخصصة منشأة لهذه الدورة (session=self)، تدرج أيضاً.
        3. وإذا كانت دورة تاريخية قديمة بدون تعيينات معلمين ولها درجات سابقة، تعتمد مواد درجاتها لحماية تاريخها.
        4. وإلا تعتمد المواد العامة للمقرر (التي لا تتبع دورات منعقدة أخرى).
        """
        if self.subject_instructors.exists():
            assigned_subjects = [si.subject for si in self.subject_instructors.select_related('subject').all()]
            custom_subjects = list(self.custom_session_subjects.exclude(id__in=[s.id for s in assigned_subjects]))
            graded_ids = list(TraineeSubjectGrade.objects.filter(
                enrollment__session=self,
                score__isnull=False
            ).exclude(subject_id__in=[s.id for s in assigned_subjects]).values_list('subject_id', flat=True).distinct())
            extra_graded = list(Subject.objects.filter(id__in=graded_ids)) if graded_ids else []
            return assigned_subjects + custom_subjects + extra_graded

        custom_subjects = list(self.custom_session_subjects.all())
        if custom_subjects:
            return custom_subjects

        graded_ids = list(TraineeSubjectGrade.objects.filter(
            enrollment__session=self,
            score__isnull=False
        ).values_list('subject_id', flat=True).distinct())
        if graded_ids:
            return list(Subject.objects.filter(id__in=graded_ids))

        return list(self.course.subjects.filter(session__isnull=True))

    @property
    def natural_attendance_grade(self):
        if self.attendance_max_grade is None:
            return 10
        return int(self.attendance_max_grade) if self.attendance_max_grade == int(self.attendance_max_grade) else self.attendance_max_grade

    @property
    def total_possible_score(self):
        subjects = self.get_subjects()
        subjects_total = sum(s.max_grade for s in subjects)
        att = self.attendance_max_grade if self.attendance_max_grade is not None else (self.course.attendance_max_grade or Decimal('0.00'))
        val = float(subjects_total) + float(att)
        return int(val) if val.is_integer() else val


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
        app_label = 'training'
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
        validators=[validate_movement_order_file],
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
        app_label = 'training'
        verbose_name = 'تسجيل دارس بالدورة'
        verbose_name_plural = 'تسجيلات الدارسين'
        unique_together = ('session', 'trainee')
        ordering = ['-total_score', 'trainee__name']

    def __str__(self):
        return f"{self.trainee.name} في {self.session}"

    @property
    def has_complete_data_and_grades(self):
        """التحقق الصارم من اكتمال كافة البيانات والدرجات المطلوبة لإصدار الشهادة"""
        if self.is_dropped:
            return False
        if not self.trainee:
            return False
        if not self.trainee.military_number or not str(self.trainee.military_number).strip():
            return False
        if not self.trainee.name or not self.trainee.name.strip():
            return False
        if self.trainee and self.trainee.category != TraineeCategory.CIVILIAN:
            if not self.current_rank or not self.current_rank.strip():
                return False
        if not self.current_unit or not self.current_unit.strip():
            return False
        if not self.session or not self.session.course:
            return False
        if not self.session.course.name or not self.session.course.name.strip():
            return False
        if not self.session.session_code or not self.session.session_code.strip():
            return False
        if not self.session.start_date or not self.session.end_date:
            return False

        session_subjects = self.session.get_subjects()
        total_subjects = len(session_subjects)
        if total_subjects == 0:
            return False

        actual_grades = list(TraineeSubjectGrade.objects.filter(enrollment=self, subject__in=session_subjects))
        graded_count = len(actual_grades)
        if graded_count < total_subjects:
            return False

        for g in actual_grades:
            if g.score is None:
                return False

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

    @property
    def total_discipline_points(self):
        """إجمالي نقاط مخالفات الضبط والربط المسجلة للدارس"""
        points = sum(inf.points for inf in self.discipline_infractions.all())
        return Decimal(str(points))

    def update_discipline_score(self):
        """حساب وتحديث درجة الضبط والربط وفحص قيد قطع الدورة التلقائي"""
        total_pts = self.total_discipline_points
        max_att = Decimal(str(self.session.attendance_max_grade)) if (self.session and self.session.attendance_max_grade is not None) else Decimal('10.00')

        if total_pts > Decimal('5.0'):
            self.is_dropped = True
            self.drop_reason = f'قطع دورة تلقائي: تجاوز حد مخالفات الضبط والربط المسموح به ({total_pts} نقطة)'
            if not self.dropped_at:
                self.dropped_at = timezone.now()
            self.attendance_score = Decimal('0.00')
            self.is_graded = False
            self.total_score = Decimal('0.00')
            self.percentage = Decimal('0.00')
            self.grade_label = 'تم قطع الدورة'
            self.save(update_fields=['is_dropped', 'drop_reason', 'dropped_at', 'attendance_score', 'is_graded', 'total_score', 'percentage', 'grade_label'])
            return {
                'dropped': True,
                'total_points': float(total_pts),
                'score': 0.0,
                'reason': self.drop_reason
            }
        else:
            if self.is_dropped and 'مخالفات الضبط والربط' in (self.drop_reason or ''):
                self.is_dropped = False
                self.drop_reason = ''
                self.dropped_at = None

            new_score = max(Decimal('0.00'), max_att - total_pts)
            self.attendance_score = new_score
            self.save(update_fields=['is_dropped', 'drop_reason', 'dropped_at', 'attendance_score'])
            self.calculate_results()
            return {
                'dropped': False,
                'total_points': float(total_pts),
                'score': float(new_score),
                'reason': ''
            }

    def calculate_results(self):
        """حساب المجموع الكلي، النسبة المئوية، والتقدير"""
        if self.is_dropped:
            self.is_graded = False
            self.total_score = Decimal('0.00')
            self.percentage = Decimal('0.00')
            self.grade_label = 'تم قطع الدورة'
            self.save(update_fields=['is_graded', 'total_score', 'percentage', 'grade_label'])
            return None
        session_subjects = self.session.get_subjects()
        total_subjects = len(session_subjects)
        actual_grades = list(TraineeSubjectGrade.objects.filter(enrollment=self, subject__in=session_subjects))
        graded_count = len(actual_grades)

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
    """التحقق مما إذا كان الطالب قد أكمل الدورة ونجح فيها مسبقاً"""
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
        app_label = 'training'
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


class DisciplineInfraction(models.Model):
    """سجل مخالفات الضبط والربط للدارس في الدورة"""

    INFRACTION_CHOICES = [
        ('delay_lecture', 'أ. التأخير عن تمام المحاضرة الواحدة (خصم نصف درجة)'),
        ('medical_rest', 'ب. الراحة الطبية لليوم الواحد (خصم نصف درجة)'),
        ('absent_full_day', 'ج. الغياب ليوم كامل (خصم درجتان)'),
        ('absent_lecture', 'د. الغياب عن المحاضرة الواحدة (خصم درجة ونصف)'),
        ('enter_supervisor_office', 'هـ. دخول مكتب المشرف (خصم درجة ونصف)'),
        ('enter_education_commander_office', 'و. دخول مكتب قائد جناح التعليم (خصم درجتان)'),
        ('enter_chief_instructor_office', 'ز. دخول مكتب كبير المعلمين (خصم درجتان ونصف)'),
        ('enter_commander_office', 'ح. دخول مكتب قائد المعهد (خصم ثلاث درجات)'),
    ]

    POINTS_MAP = {
        'delay_lecture': Decimal('0.5'),
        'medical_rest': Decimal('0.5'),
        'absent_full_day': Decimal('2.0'),
        'absent_lecture': Decimal('1.5'),
        'enter_supervisor_office': Decimal('1.5'),
        'enter_education_commander_office': Decimal('2.0'),
        'enter_chief_instructor_office': Decimal('2.5'),
        'enter_commander_office': Decimal('3.0'),
    }

    enrollment = models.ForeignKey(
        CourseEnrollment,
        on_delete=models.CASCADE,
        related_name='discipline_infractions',
        verbose_name='تسجيل الدارس بالدورة'
    )
    infraction_type = models.CharField(
        max_length=50,
        choices=INFRACTION_CHOICES,
        verbose_name='نوع المخالفة'
    )
    date = models.DateField(
        default=timezone.now,
        verbose_name='تاريخ المخالفة'
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='ملاحظات'
    )
    points = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default=Decimal('0.0'),
        verbose_name='النقاط المحتسبة'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='تاريخ ووقت التسجيل'
    )

    class Meta:
        app_label = 'training'
        verbose_name = 'مخالفة ضبط وربط'
        verbose_name_plural = 'مخالفات الضبط والربط'
        ordering = ['-date', '-created_at']

    def save(self, *args, **kwargs):
        if self.infraction_type in self.POINTS_MAP:
            self.points = self.POINTS_MAP[self.infraction_type]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.enrollment.trainee.name} - {self.get_infraction_type_display()} ({self.date})"
