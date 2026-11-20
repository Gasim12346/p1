from django.db import models
from apps.core.models import Institute


class CertificateSettings(models.Model):
    """إعدادات وتخصيص قالب وتوقيعات الشهادة الرسمية"""
    institute = models.OneToOneField(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='certificate_settings',
        verbose_name='المعهد'
    )
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
        app_label = 'training'
        verbose_name = 'إعدادات وتخصيص الشهادة'
        verbose_name_plural = 'إعدادات وتخصيص الشهادة'

    def __str__(self):
        return 'إعدادات الشهادة الرسمية'

    @classmethod
    def get_settings(cls, institute=None):
        """الحصول على إعدادات الشهادة أو إنشاؤها بالقيم الافتراضية"""
        if institute:
            obj, _ = cls.objects.get_or_create(institute=institute)
            return obj
        obj = cls.objects.filter(institute__isnull=True).first() or cls.objects.first()
        if not obj:
            obj = cls.objects.create()
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
    institute = models.OneToOneField(
        Institute,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='movement_order_settings',
        verbose_name='المعهد'
    )
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
        default='بموجب هذا الأمر وجب عليك / عليكم مغادرة معهد نظم المعلومات والإحصاء والتوجه الي {unit} وعند وصولك / وصولكم عليك / عليكم مقابلة السيد رئيس {unit} لأخذ التعليمات الاخيرة منه .',
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
        default='السيد / رئيس {unit}',
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
        app_label = 'training'
        verbose_name = 'إعدادات وتخصيص أمر التحرك'
        verbose_name_plural = 'إعدادات وتخصيص أمر التحرك'

    def __str__(self):
        return 'إعدادات أمر التحرك الرسمي'

    @classmethod
    def get_settings(cls, institute=None):
        if institute:
            obj, _ = cls.objects.get_or_create(institute=institute)
            return obj
        obj = cls.objects.filter(institute__isnull=True).first() or cls.objects.first()
        if not obj:
            obj = cls.objects.create()
        return obj

    @property
    def watermark_url(self):
        if self.watermark_image and hasattr(self.watermark_image, 'url'):
            return self.watermark_image.url
        return None
