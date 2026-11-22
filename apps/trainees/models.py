from django.db import models
from django.core.validators import RegexValidator
from apps.core.models import Institute

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
    institute = models.ForeignKey(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='trainees',
        verbose_name='المعهد'
    )
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
    staff_status = models.CharField(
        max_length=20,
        blank=True,
        default='',
        verbose_name='صفة أركان الحرب'
    )
    profession = models.CharField(
        max_length=100,
        blank=True,
        default='',
        verbose_name='المهنة / التخصص'
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
        verbose_name = 'دارس'
        verbose_name_plural = 'الدارسون'
        ordering = ['category', 'military_number']
        indexes = [
            models.Index(fields=['military_number']),
            models.Index(fields=['category']),
            models.Index(fields=['force']),
            models.Index(fields=['unit']),
            models.Index(fields=['institute', 'category']),
        ]

    def __str__(self):
        return f"{self.name} ({self.military_number})"

    @property
    def full_rank(self):
        """إرجاع الرتبة متضمنة المهنة وصفة أركان الحرب للدارس"""
        parts = []
        if self.rank:
            parts.append(self.rank)
        if self.profession:
            parts.append(self.profession)
        if self.staff_status and self.staff_status == 'ركن':
            parts.append('ركن')
        return ' '.join(parts) if parts else (self.rank or '')

    def save(self, *args, **kwargs):
        if not self.institute_id:
            default_inst = Institute.objects.filter(is_active=True).first()
            if default_inst:
                self.institute = default_inst
        super().save(*args, **kwargs)

    @property
    def rank(self):
        """الرتبة العسكرية للدارس من آخر تسجيل له إن وجد"""
        last_en = self.enrollments.order_by('-id').first()
        return last_en.current_rank if last_en and last_en.current_rank else ''

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
        app_label = 'training'
        verbose_name = 'قريب دارس'
        verbose_name_plural = 'أقرب الأقربين'
        ordering = ['order', 'id']

    def __str__(self):
        return f"{self.name} ({self.kinship}) - دارس: {self.trainee.name}"
