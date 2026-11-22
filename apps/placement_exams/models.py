from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import Institute
from apps.core.validators import validate_secure_file, ALLOWED_DOCUMENT_EXTENSIONS
from apps.trainees.models import Trainee
from apps.academic.models import Instructor


def validate_placement_signal_file(file_obj):
    """التحقق الأمني الصارم من ملفات الإشارات والمكاتبات الرسمية المرفوعة (PDF أو صور مسح ضوئي بحجم أقصى 10 ميجابايت)"""
    return validate_secure_file(file_obj, max_mb=10, allowed_extensions=ALLOWED_DOCUMENT_EXTENSIONS)


class PlacementExamStatus(models.TextChoices):
    """حالات دورة عمل طلب امتحان تحديد المستوى"""
    IN_PROGRESS = 'in_progress', 'قيد التنفيذ'
    CONFIRMED = 'confirmed', 'تم تأكيد الانعقاد'
    PENDING_APPROVAL = 'pending_approval', 'بانتظار اعتماد النتائج'
    APPROVED = 'approved', 'معتمد'


class AssessmentType(models.TextChoices):
    """نوع تقييم الامتحان ومكونات الدرجة"""
    THEORY_AND_PRACTICAL = 'theory_and_practical', 'نظري وعملي'
    THEORY_ONLY = 'theory_only', 'نظري فقط'


class CandidateClassification(models.TextChoices):
    """تصنيف فئات الممتحنين في الطلب"""
    OFFICERS = 'officers', 'ضباط'
    NCOS = 'ncos', 'ضباط صف'
    CIVILIANS = 'civilians', 'مدنيين'
    MIXED = 'mixed', 'مشترك'


class AttendanceStatus(models.TextChoices):
    """حالات حضور الممتحن"""
    UNRECORDED = 'unrecorded', 'غير مرصود'
    PRESENT = 'present', 'حاضر'
    ABSENT = 'absent', 'غائب'


class CandidateActionType(models.TextChoices):
    """إجراء التعامل مع الممتحن في جلسة الرصد"""
    EXAM = 'exam', 'أداء الامتحان'
    RETAIN = 'retain', 'الاحتفاظ بالنتيجة السابقة'


class PlacementExamOrder(models.Model):
    """
    نموذج طلب / أمر امتحان تحديد المستوى.
    يمثل المكاتبة أو الإشارة الرسمية الواردة من جهة عسكرية/مدنية لانعقاد امتحان تحديد مستوى،
    ويتبع دورة عمل ثلاثية المراحل محكمة ومستقلة تماماً عن درجات المقررات والدورات.
    """
    # عزل البيانات حسب المعهد (Multi-tenancy)
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        related_name='placement_orders',
        verbose_name='المعهد / المنشأة التعليمية'
    )

    # الترقيم السنوي الداخلي والأكواد
    year = models.PositiveIntegerField(
        verbose_name='السنة الميلادية للترقيم',
        db_index=True,
        help_text='السنة التقويمية لأمر الامتحان (تُستخدم لتصفير وإعادة بدء الترقيم السنوي)'
    )
    internal_order_number = models.PositiveIntegerField(
        verbose_name='الترقيم الداخلي السنوي',
        help_text='تسلسل رقمي سنوي يبدأ من 1 لكل معهد ولكل سنة ميلادية'
    )
    order_code = models.CharField(
        max_length=50,
        blank=True,
        db_index=True,
        verbose_name='كود الطلب / الأمر',
        help_text='الكود المعروض المنظم للطلب (مثال: 001/2026 أو طلب #001)'
    )

    # بيانات المكاتبة / الإشارة الرسمية الواردة
    signal_number = models.CharField(
        max_length=100,
        db_index=True,
        verbose_name='رقم الإشارة / المكاتبة الرسمية'
    )
    source_entity = models.CharField(
        max_length=200,
        verbose_name='الجهة الطالبة / الراسلة للإشارة',
        help_text='مثال: قيادة سلاح المدرعات (الشجرة)'
    )
    host_entity = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='الجهة المستضيفة / المنعقد بها الامتحان'
    )
    destination_country = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='الدولة الموفد إليها المرشحون',
        help_text='مثال: جمهورية مصر العربية'
    )
    purpose = models.CharField(
        max_length=150,
        verbose_name='الغرض الرئيسي من الامتحان',
        help_text='مثال: آلية، ملحق، دورة خارجية...'
    )
    sub_purpose = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='البند الفرعي للغرض',
        help_text='مثال: آمر آلية، مساعد ملحق عسكري...'
    )
    classification = models.CharField(
        max_length=20,
        choices=CandidateClassification.choices,
        default=CandidateClassification.OFFICERS,
        verbose_name='تصنيف فئة الممتحنين'
    )
    receipt_date = models.DateField(
        verbose_name='تاريخ استلام الطلب / الإشارة الرسمية',
        db_index=True,
        help_text='تاريخ ثابت لا يتغير، يُعتمد عليه كمرجع زمني لفحص صلاحية النتائج السابقة (< 6 أشهر)'
    )

    # جدول الانعقاد وتكوين المادة
    exam_date = models.DateField(
        verbose_name='تاريخ انعقاد الامتحان',
        db_index=True
    )
    exam_time = models.TimeField(
        null=True,
        blank=True,
        verbose_name='وقت انعقاد الامتحان'
    )
    subject_name = models.CharField(
        max_length=100,
        default='حاسوب',
        verbose_name='المادة الامتحانية',
        help_text='افتراضياً حاسوب وفق المعيار السوداني المعتمد'
    )
    assessment_type = models.CharField(
        max_length=30,
        choices=AssessmentType.choices,
        default=AssessmentType.THEORY_AND_PRACTICAL,
        verbose_name='نوع التقييم'
    )
    theory_max_score = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=Decimal('50.0'),
        validators=[MinValueValidator(Decimal('0.0')), MaxValueValidator(Decimal('100.0'))],
        verbose_name='الدرجة العظمى للنظري'
    )
    practical_max_score = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=Decimal('50.0'),
        validators=[MinValueValidator(Decimal('0.0')), MaxValueValidator(Decimal('100.0'))],
        verbose_name='الدرجة العظمى للعملي'
    )
    total_max_score = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        default=Decimal('100.0'),
        validators=[MinValueValidator(Decimal('1.0')), MaxValueValidator(Decimal('100.0'))],
        verbose_name='الدرجة العظمى الإجمالية'
    )

    # الإشراف والملف المرفق
    supervisor = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='supervised_placement_orders',
        verbose_name='المعلم المشرف'
    )
    supervisor_name_snapshot = models.CharField(
        max_length=200,
        blank=True,
        default='',
        verbose_name='لقطة اسم المعلم المشرف وقت الامتحان'
    )
    official_signal_file = models.FileField(
        upload_to='placement_signals/%Y/',
        null=True,
        blank=True,
        validators=[validate_placement_signal_file],
        verbose_name='صورة / ملف الإشارة الرسمية'
    )

    # حالة الطلب ودورة العمل
    status = models.CharField(
        max_length=30,
        choices=PlacementExamStatus.choices,
        default=PlacementExamStatus.IN_PROGRESS,
        db_index=True,
        verbose_name='حالة الطلب'
    )
    is_confirmed = models.BooleanField(
        default=False,
        verbose_name='تم تأكيد انعقاد الامتحان'
    )
    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='وقت تأكيد الانعقاد'
    )
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='confirmed_placement_orders',
        verbose_name='المستخدم المؤكد للانعقاد'
    )
    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='وقت اعتماد النتائج'
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_placement_orders',
        verbose_name='المستخدم المعتمد للنتائج'
    )

    # التدقيق والملاحظات
    notes = models.TextField(
        blank=True,
        default='',
        verbose_name='ملاحظات إضافية'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_placement_orders',
        verbose_name='منشئ الطلب'
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
        verbose_name = 'أمر امتحان تحديد مستوى'
        verbose_name_plural = 'أوامر امتحانات تحديد المستوى'
        ordering = ['-year', '-internal_order_number']
        constraints = [
            models.UniqueConstraint(
                fields=['institute', 'year', 'internal_order_number'],
                name='unique_placement_order_per_year_institute'
            )
        ]
        indexes = [
            models.Index(fields=['institute', 'year', 'internal_order_number']),
            models.Index(fields=['institute', 'status']),
            models.Index(fields=['receipt_date']),
            models.Index(fields=['exam_date']),
        ]

    def __str__(self):
        code = self.order_code or f"{str(self.internal_order_number).zfill(3)}/{self.year}"
        return f"{code} - {self.subject_name} ({self.source_entity})"

    def clean(self):
        super().clean()
        if self.assessment_type == AssessmentType.THEORY_ONLY:
            self.practical_max_score = Decimal('0.0')
            self.total_max_score = self.theory_max_score
        else:
            calc_total = self.theory_max_score + self.practical_max_score
            if self.total_max_score != calc_total:
                self.total_max_score = calc_total

    def save(self, *args, **kwargs):
        # توليد كود الطلب التلقائي إذا لم يتم إدخاله
        if not self.order_code and self.internal_order_number and self.year:
            self.order_code = f"{str(self.internal_order_number).zfill(3)}/{self.year}"

        # لقطة اسم المعلم المشرف
        if self.supervisor and not self.supervisor_name_snapshot:
            rank_part = f"{self.supervisor.rank} / " if getattr(self.supervisor, 'rank', '') else ""
            self.supervisor_name_snapshot = f"{rank_part}{self.supervisor.name}".strip()

        # مزامنة منطق تأكيد الانعقاد
        if self.status in [PlacementExamStatus.CONFIRMED, PlacementExamStatus.PENDING_APPROVAL, PlacementExamStatus.APPROVED]:
            self.is_confirmed = True
            if not self.confirmed_at:
                self.confirmed_at = timezone.now()

        self.clean()
        super().save(*args, **kwargs)

    @property
    def is_approved(self):
        return self.status == PlacementExamStatus.APPROVED

    @property
    def is_holding_confirmed(self):
        return self.is_confirmed or self.status in [
            PlacementExamStatus.CONFIRMED,
            PlacementExamStatus.PENDING_APPROVAL,
            PlacementExamStatus.APPROVED
        ]

    @property
    def total_candidates_count(self):
        return self.candidates.count()

    @property
    def present_candidates_count(self):
        return self.candidates.filter(attendance_status=AttendanceStatus.PRESENT).count()

    @property
    def absent_candidates_count(self):
        return self.candidates.filter(attendance_status=AttendanceStatus.ABSENT).count()

    @property
    def graded_candidates_count(self):
        return self.candidates.filter(is_graded=True).count()

    @property
    def passed_candidates_count(self):
        return self.candidates.filter(is_passed=True).count()

    @property
    def failed_candidates_count(self):
        return self.candidates.filter(is_graded=True, is_passed=False).count()


class PlacementExamCandidate(models.Model):
    """
    نموذج الممتحن / المرشح في امتحان تحديد المستوى.
    يحفظ بيانات الممتحن ولقطة هويته ورتبته وقوته ووحدته وقت الامتحان،
    مع تتبع حالة الحضور والدرجات التراكمية، ومصدر النتيجة المنقولة إن وجدت،
    مفصولاً بالكامل عن جداول ودرجات المقررات الدراسية.
    """
    # الارتباط بأمر الامتحان
    order = models.ForeignKey(
        PlacementExamOrder,
        on_delete=models.CASCADE,
        related_name='candidates',
        verbose_name='أمر الامتحان'
    )

    # الارتباط بالسجل الأساسي للدارس (حماية من الحذف المباشر أثناء الارتباط)
    trainee = models.ForeignKey(
        Trainee,
        on_delete=models.PROTECT,
        related_name='placement_exam_attempts',
        verbose_name='الدارس / الممتحن'
    )

    # لقطة بيانات الدارس وقت الامتحان (حماية السجل التاريخي من أي تعديلات مستقبلية في جدول الدارسين)
    military_number_snapshot = models.CharField(
        max_length=50,
        db_index=True,
        verbose_name='النمرة العسكرية وقت الامتحان'
    )
    name_snapshot = models.CharField(
        max_length=200,
        verbose_name='الاسم وقت الامتحان'
    )
    rank_snapshot = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='الرتبة وقت الامتحان'
    )
    force_snapshot = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='القوة وقت الامتحان'
    )
    unit_snapshot = models.CharField(
        max_length=150,
        blank=True,
        default='',
        verbose_name='الوحدة وقت الامتحان'
    )

    # الحضور وإجراء الجلسة
    attendance_status = models.CharField(
        max_length=20,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.UNRECORDED,
        db_index=True,
        verbose_name='حالة الحضور'
    )
    action_type = models.CharField(
        max_length=20,
        choices=CandidateActionType.choices,
        default=CandidateActionType.EXAM,
        verbose_name='إجراء الممتحن (أداء الامتحان أو احتفاظ بنتيجة)'
    )

    # محرك نقل النتائج السابقة
    is_transferred = models.BooleanField(
        default=False,
        verbose_name='هل النتيجة منقولة من امتحان سابق'
    )
    transfer_source_candidate = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transferred_targets',
        verbose_name='محاولة الامتحان الأصلية المنقول منها'
    )
    transferred_original_date = models.DateField(
        null=True,
        blank=True,
        verbose_name='تاريخ الامتحان السابق المنقول منه'
    )
    transferred_original_score = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        verbose_name='الدرجة المنقولة الأصلية'
    )

    # الدرجات والنتائج
    theory_score = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.0'))],
        verbose_name='درجة النظري'
    )
    practical_score = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.0'))],
        verbose_name='درجة العملي'
    )
    total_score = models.DecimalField(
        max_digits=5,
        decimal_places=1,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.0'))],
        verbose_name='المجموع الكلي'
    )
    percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal('0.0')), MaxValueValidator(Decimal('100.0'))],
        verbose_name='النسبة المئوية'
    )
    grade_label = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='التقدير'
    )
    is_passed = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='ناجح (نسبة 50% فأعلى)'
    )
    is_graded = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='تم اكتمال رصد الدرجة'
    )

    # ملاحظات وتواريخ
    notes = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='ملحوظات'
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
        verbose_name = 'ممتحن تحديد مستوى'
        verbose_name_plural = 'الممتحنون في امتحانات تحديد المستوى'
        ordering = ['order', 'military_number_snapshot']
        constraints = [
            models.UniqueConstraint(
                fields=['order', 'trainee'],
                name='unique_candidate_per_placement_order'
            )
        ]
        indexes = [
            models.Index(fields=['order', 'attendance_status']),
            models.Index(fields=['trainee', 'is_passed', 'is_graded']),
            models.Index(fields=['military_number_snapshot']),
        ]

    def __str__(self):
        order_identifier = self.order.order_code if self.order else 'طلب'
        return f"{self.name_snapshot} ({self.military_number_snapshot}) - {order_identifier}"

    @staticmethod
    def get_grade_label_for_percentage(pct, is_absent=False):
        """تحديد التقدير الرسمي المعتمد وفق المعايير العسكرية المعمول بها"""
        if is_absent:
            return 'دون المستوى / راسب (غائب)'
        if pct is None:
            return ''
        pct_float = float(pct)
        if pct_float >= 85.0:
            return 'ممتاز (أ)'
        elif pct_float >= 75.0:
            return 'جيد جداً (ب)'
        elif pct_float >= 65.0:
            return 'جيد (ج)'
        elif pct_float >= 50.0:
            return 'مقبول (د)'
        else:
            return 'دون المستوى / راسب'

    def calculate_results(self):
        """
        احتساب المجموع النهائي والنسبة المئوية والتقدير وحالة النجاح
        وفق القواعد المعتمدة بالبوابة المحلية.
        """
        # 1. حالة الغياب
        if self.attendance_status == AttendanceStatus.ABSENT:
            if self.action_type == CandidateActionType.RETAIN and self.is_transferred and self.transferred_original_score is not None:
                # الممتحن غائب لكنه طلب اعتماد نتيجته السابقة الصالحة
                self.total_score = self.transferred_original_score
                max_total = self.order.total_max_score if self.order and self.order.total_max_score > 0 else Decimal('100.0')
                raw_pct = (self.total_score / max_total) * Decimal('100.0')
                self.percentage = raw_pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                self.is_passed = (self.percentage >= Decimal('50.0'))
                self.grade_label = self.get_grade_label_for_percentage(self.percentage, is_absent=False)
                self.is_graded = True
            else:
                self.theory_score = Decimal('0.0')
                self.practical_score = Decimal('0.0')
                self.total_score = Decimal('0.0')
                self.percentage = Decimal('0.0')
                self.is_passed = False
                self.grade_label = self.get_grade_label_for_percentage(0, is_absent=True)
                self.is_graded = True
            return

        # 2. حالة النتيجة المنقولة من امتحان سابق
        if self.action_type == CandidateActionType.RETAIN and self.is_transferred and self.transferred_original_score is not None:
            self.total_score = self.transferred_original_score
            max_total = self.order.total_max_score if self.order and self.order.total_max_score > 0 else Decimal('100.0')
            raw_pct = (self.total_score / max_total) * Decimal('100.0')
            self.percentage = raw_pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            self.is_passed = (self.percentage >= Decimal('50.0'))
            self.grade_label = self.get_grade_label_for_percentage(self.percentage, is_absent=False)
            self.is_graded = True
            return

        # 3. حالة الامتحان العادي المرصود
        if self.theory_score is None and self.practical_score is None:
            # لم يتم رصد أي درجات بعد
            self.total_score = None
            self.percentage = None
            self.grade_label = ''
            self.is_passed = False
            self.is_graded = False
            return

        t = self.theory_score or Decimal('0.0')
        p = self.practical_score or Decimal('0.0')
        self.total_score = t + p
        max_total = self.order.total_max_score if self.order and self.order.total_max_score > 0 else Decimal('100.0')
        raw_pct = (self.total_score / max_total) * Decimal('100.0')
        self.percentage = raw_pct.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        self.is_passed = (self.percentage >= Decimal('50.0'))
        self.grade_label = self.get_grade_label_for_percentage(self.percentage, is_absent=False)
        self.is_graded = True

    def save(self, *args, **kwargs):
        # التقاط وتثبيت لقطة بيانات الدارس من السجل الأساسي وقت الإضافة إذا كانت فارغة
        if self.trainee:
            if not self.military_number_snapshot:
                self.military_number_snapshot = str(self.trainee.military_number)
            if not self.name_snapshot:
                self.name_snapshot = self.trainee.name
            if not self.rank_snapshot:
                self.rank_snapshot = getattr(self.trainee, 'rank', '') or ''
            if not self.force_snapshot:
                self.force_snapshot = getattr(self.trainee, 'force', '') or ''
            if not self.unit_snapshot:
                self.unit_snapshot = getattr(self.trainee, 'unit', '') or ''

        # احتساب النتائج تلقائياً
        self.calculate_results()
        super().save(*args, **kwargs)
