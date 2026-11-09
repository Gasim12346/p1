from decimal import Decimal
from django import forms
from django.contrib.auth.models import User
from .models import (
    Instructor, Trainee, TraineeCategory, CourseCategory, Course, Subject, CourseSession,
    CertificateSettings, SystemSettings, UserProfile, UserRole
)

# ثوابت الرتب العسكرية والمدنية المحددة بدقة
OFFICER_RANKS = [
    'ملازم',
    'ملازم أول',
    'نقيب',
    'رائد',
    'مقدم',
    'عقيد',
    'عميد',
    'لواء',
]

NCO_RANKS = [
    'جندي',
    'وكيل عريف',
    'عريف',
    'رقيب',
    'رقيب أول',
    'مساعد',
]

CIVILIAN_TITLES = [
    'موظف مدني',
    'أخصائي',
    'باحث',
    'مهندس',
    'فني',
    'إداري',
]

# خيارات القوائم المنسدلة للرتب والوحدات في نماذج المستخدمين
MILITARY_RANK_CHOICES = [
    ('', '-- اختر الرتبة --'),
    ('رتب الضباط', [
        ('ملازم', 'ملازم'),
        ('ملازم أول', 'ملازم أول'),
        ('نقيب', 'نقيب'),
        ('رائد', 'رائد'),
        ('مقدم', 'مقدم'),
        ('عقيد', 'عقيد'),
        ('عميد', 'عميد'),
        ('لواء', 'لواء'),
        ('فريق', 'فريق'),
        ('فريق أول', 'فريق أول'),
    ]),
    ('رتب ضباط الصف والجنود', [
        ('جندي', 'جندي'),
        ('وكيل عريف', 'وكيل عريف'),
        ('عريف', 'عريف'),
        ('رقيب', 'رقيب'),
        ('رقيب أول', 'رقيب أول'),
        ('مساعد', 'مساعد'),
        ('مساعد أول', 'مساعد أول'),
    ]),
    ('الوظائف والرتب المدنية', [
        ('موظف مدني', 'موظف مدني'),
        ('أخصائي', 'أخصائي'),
        ('باحث', 'باحث'),
        ('مهندس', 'مهندس'),
        ('فني', 'فني'),
        ('إداري', 'إداري'),
    ]),
    ('خيارات مخصصة', [
        ('__custom__', 'رتبة أخرى (كتابة يدوية)...'),
    ]),
]

MILITARY_UNIT_CHOICES = [
    ('', '-- اختر الوحدة / الفرع --'),
    ('الأسلحة والقيادات العامة', [
        ('جناح التعليم', 'جناح التعليم'),
        ('سلاح المشاة', 'سلاح المشاة'),
        ('سلاح المدرعات', 'سلاح المدرعات'),
        ('سلاح المدفعية', 'سلاح المدفعية'),
        ('سلاح الإشارة', 'سلاح الإشارة'),
        ('سلاح المهندسين', 'سلاح المهندسين'),
        ('سلاح الصيانة', 'سلاح الصيانة'),
        ('سلاح النقل', 'سلاح النقل'),
        ('الشرطة العسكرية', 'الشرطة العسكرية'),
        ('شعبة الاستخبارات العسكرية', 'شعبة الاستخبارات العسكرية'),
        ('لواء القوات الخاصة', 'لواء القوات الخاصة'),
        ('إدارة العمليات الحربية', 'إدارة العمليات الحربية'),
        ('إدارة التدريب', 'إدارة التدريب'),
        ('إدارة نظم المعلومات والحاسب الآلي', 'إدارة نظم المعلومات والحاسب الآلي'),
        ('الإدارة المالية والمحاسبة', 'الإدارة المالية والمحاسبة'),
        ('هيئة الإمداد والتموين', 'هيئة الإمداد والتموين'),
        ('قيادة القوات البرية', 'قيادة القوات البرية'),
    ]),
    ('القوات الجوية', [
        ('قاعدة وادي سيدنا الجوية', 'قاعدة وادي سيدنا الجوية'),
        ('قاعدة الشهيد مختار الجوية', 'قاعدة الشهيد مختار الجوية'),
        ('قاعدة الأبيض الجوية', 'قاعدة الأبيض الجوية'),
        ('قاعدة مروي الجوية', 'قاعدة مروي الجوية'),
        ('جناح المقاتلات', 'جناح المقاتلات'),
        ('جناح النقل الجوي', 'جناح النقل الجوي'),
        ('جناح المروحيات', 'جناح المروحيات'),
        ('مجمع صيانة الطيران', 'مجمع صيانة الطيران'),
        ('الملاحة والمراقبة الجوية', 'الملاحة والمراقبة الجوية'),
        ('إدارة نظم المعلومات الجوية', 'إدارة نظم المعلومات الجوية'),
        ('الإدارة المالية الجوية', 'الإدارة المالية الجوية'),
        ('كلية القوات الجوية', 'كلية القوات الجوية'),
        ('قيادة القوات الجوية', 'قيادة القوات الجوية'),
    ]),
    ('القوات البحرية', [
        ('قاعدة بورتسودان البحرية', 'قاعدة بورتسودان البحرية'),
        ('قاعدة فلامنجو البحرية', 'قاعدة فلامنجو البحرية'),
        ('أسطول الزوارق والسفن', 'أسطول الزوارق والسفن'),
        ('لواء المشاة البحرية', 'لواء المشاة البحرية'),
        ('جناح الضفادع البشرية', 'جناح الضفادع البشرية'),
        ('ورش الصيانة البحرية', 'ورش الصيانة البحرية'),
        ('إدارة نظم المعلومات البحرية', 'إدارة نظم المعلومات البحرية'),
        ('الإدارة المالية البحرية', 'الإدارة المالية البحرية'),
        ('جناح الاتصالات الساحلية', 'جناح الاتصالات الساحلية'),
        ('مركز تدريب القوات البحرية', 'مركز تدريب القوات البحرية'),
        ('قيادة القوات البحرية', 'قيادة القوات البحرية'),
    ]),
    ('قوات الدفاع الجوي', [
        ('لواء الصواريخ م/ط', 'لواء الصواريخ م/ط'),
        ('كتائب المدفعية م/ط', 'كتائب المدفعية م/ط'),
        ('مراكز الرادارات والإنذار المبكر', 'مراكز الرادارات والإنذار المبكر'),
        ('قيادة السيطرة والتوجيه', 'قيادة السيطرة والتوجيه'),
        ('الحرب الإلكترونية', 'الحرب الإلكترونية'),
        ('سلاح الإشارة للدفاع الجوي', 'سلاح الإشارة للدفاع الجوي'),
        ('ورش الصيانة الفنية للدفاع الجوي', 'ورش الصيانة الفنية للدفاع الجوي'),
        ('مركز تدريب الدفاع الجوي', 'مركز تدريب الدفاع الجوي'),
        ('قيادة قوات الدفاع الجوي', 'قيادة قوات الدفاع الجوي'),
    ]),
    ('المعاهد والكليات والمستشفيات العسكرية', [
        ('معهد نظم المعلومات', 'معهد نظم المعلومات'),
        ('الكلية الحربية', 'الكلية الحربية'),
        ('جامعة كرري', 'جامعة كرري'),
        ('أكاديمية نميري العسكرية العليا', 'أكاديمية نميري العسكرية العليا'),
        ('معهد اللغات العسكري', 'معهد اللغات العسكري'),
        ('السلاح الطبي / المستشفى العسكري', 'السلاح الطبي / المستشفى العسكري'),
        ('مستشفى علياء التخصصي', 'مستشفى علياء التخصصي'),
    ]),
    ('خيارات مخصصة', [
        ('__custom__', 'وحدة أخرى (كتابة يدوية)...'),
    ]),
]


class TraineeForm(forms.ModelForm):
    # الدفعة (رقمي)
    batch = forms.IntegerField(
        required=False,
        min_value=1,
        widget=forms.NumberInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'أدخل رقم الدفعة (مثال: 45)',
            'min': '1',
            'step': '1',
        }),
        label='الدفعة (رقمي)'
    )
    # رقم الهاتف
    phone = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg font-monospace',
            'placeholder': 'رقم هاتف الدارس (مثال: 0912345678)',
            'type': 'tel',
        }),
        label='رقم الهاتف'
    )
    # حقول السكن
    residence_state = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'اسم الولاية (مثال: الخرطوم)',
        }),
        label='الولاية'
    )
    residence_city = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'اسم المدينة (مثال: أم درمان)',
        }),
        label='المدينة'
    )
    residence_neighborhood = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'اسم الحي (مثال: الثورة)',
        }),
        label='الحي'
    )
    residence_block = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'المربع أو الحارة (مثال: الحارة 15)',
        }),
        label='المربع / الحارة'
    )
    residence_house_number = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'رقم المنزل (مثال: 42)',
        }),
        label='رقم المنزل'
    )

    # أقرب الأقربين (4 أقارب للطوارئ والتواصل)
    # القريب 1
    relative_1_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القريب الأول'}), label='اسم القريب الأول')
    relative_1_kinship = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'صلة القرابة (مثال: والد، أخ)'}), label='صلة القرابة')
    relative_1_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف'}), label='رقم الهاتف')
    relative_1_address = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مكان السكن / العنوان'}), label='السكن / العنوان')

    # القريب 2
    relative_2_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القريب الثاني'}), label='اسم القريب الثاني')
    relative_2_kinship = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'صلة القرابة (مثال: والدة، زوجة)'}), label='صلة القرابة')
    relative_2_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف'}), label='رقم الهاتف')
    relative_2_address = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مكان السكن / العنوان'}), label='السكن / العنوان')

    # القريب 3
    relative_3_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القريب الثالث'}), label='اسم القريب الثالث')
    relative_3_kinship = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'صلة القرابة (مثال: عم، خال)'}), label='صلة القرابة')
    relative_3_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف'}), label='رقم الهاتف')
    relative_3_address = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مكان السكن / العنوان'}), label='السكن / العنوان')

    # القريب 4
    relative_4_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القريب الرابع'}), label='اسم القريب الرابع')
    relative_4_kinship = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'صلة القرابة'}), label='صلة القرابة')
    relative_4_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف'}), label='رقم الهاتف')
    relative_4_address = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مكان السكن / العنوان'}), label='السكن / العنوان')

    class Meta:
        model = Trainee
        fields = [
            'military_number', 'category', 'name', 'batch', 'phone',
            'residence_state', 'residence_city', 'residence_neighborhood',
            'residence_block', 'residence_house_number'
        ]
        widgets = {
            'military_number': forms.TextInput(attrs={
                'class': 'form-control form-control-lg font-monospace',
                'placeholder': 'أدخل النمرة (أرقام فقط، مثال: 10425)',
                'pattern': '[0-9]+',
                'inputmode': 'numeric',
                'oninput': "this.value = this.value.replace(/[^0-9]/g, '')",
                'title': 'يجب إدخال أرقام فقط',
                'required': 'required'
            }),
            'category': forms.Select(attrs={
                'class': 'form-select form-select-lg',
                'id': 'categorySelect',
                'required': 'required'
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'الاسم الكامل للدارس',
                'required': 'required'
            }),
        }
        labels = {
            'military_number': 'النمرة (أرقام فقط) *',
            'category': 'التصنيف *',
            'name': 'الاسم الكامل *',
            'batch': 'الدفعة (رقمي)',
            'phone': 'رقم الهاتف',
            'residence_state': 'الولاية',
            'residence_city': 'المدينة',
            'residence_neighborhood': 'الحي',
            'residence_block': 'المربع / الحارة',
            'residence_house_number': 'رقم المنزل',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # تحميل بيانات الأقارب المسجلين مسبقاً
            for rel in self.instance.relatives.all():
                if 1 <= rel.order <= 4:
                    self.initial[f'relative_{rel.order}_name'] = rel.name
                    self.initial[f'relative_{rel.order}_kinship'] = rel.kinship
                    self.initial[f'relative_{rel.order}_phone'] = rel.phone
                    self.initial[f'relative_{rel.order}_address'] = rel.address

    def clean_military_number(self):
        number = self.cleaned_data.get('military_number', '').strip()
        if not number.isdigit():
            raise forms.ValidationError('النمرة تقبل أرقاماً فقط (0-9). يرجى عدم إدخال أحرف أو رموز.')
        qs = Trainee.objects.filter(military_number=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'النمرة العسكرية "{number}" مسجلة مسبقاً لدارس آخر ولا يمكن تكرارها.')
        if Instructor.objects.filter(military_number=number).exists():
            raise forms.ValidationError(f'النمرة العسكرية "{number}" مسجلة مسبقاً في النظام كمعلم، ولا يجوز تكرار النمرة العسكرية بين الدارسين والمعلمين.')
        return number

    def save(self, commit=True):
        trainee = super().save(commit=commit)
        if commit:
            self.save_relatives(trainee)
        return trainee

    def save_relatives(self, trainee):
        """حفظ أو تحديث بيانات الأقارب الـ 4"""
        for i in range(1, 5):
            name = self.cleaned_data.get(f'relative_{i}_name', '').strip()
            kinship = self.cleaned_data.get(f'relative_{i}_kinship', '').strip()
            phone = self.cleaned_data.get(f'relative_{i}_phone', '').strip()
            address = self.cleaned_data.get(f'relative_{i}_address', '').strip()

            rel = trainee.relatives.filter(order=i).first()
            if any([name, kinship, phone, address]):
                if rel:
                    rel.name = name
                    rel.kinship = kinship
                    rel.phone = phone
                    rel.address = address
                    rel.save()
                else:
                    trainee.relatives.create(
                        order=i,
                        name=name,
                        kinship=kinship,
                        phone=phone,
                        address=address
                    )
            elif rel:
                rel.delete()


class InstructorForm(forms.ModelForm):
    class Meta:
        model = Instructor
        fields = ['military_number', 'category', 'rank', 'name', 'force', 'unit', 'phone', 'is_active']
        widgets = {
            'military_number': forms.TextInput(attrs={
                'class': 'form-control form-control-lg font-monospace',
                'placeholder': 'أدخل النمرة العسكرية (أرقام فقط)',
                'pattern': '[0-9]+',
                'inputmode': 'numeric',
                'oninput': "this.value = this.value.replace(/[^0-9]/g, '')",
                'required': 'required'
            }),
            'category': forms.Select(attrs={
                'class': 'form-select form-select-lg',
                'required': 'required'
            }),
            'rank': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'الرتبة',
                'required': 'required'
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'الاسم الكامل للمعلم',
                'required': 'required'
            }),
            'force': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'القوة'
            }),
            'unit': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'الوحدة'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'رقم الهاتف (اختياري)'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
                'style': 'width: 22px; height: 22px;'
            }),
        }
        labels = {
            'military_number': 'النمرة العسكرية (مفتاح أساسي) *',
            'category': 'التصنيف *',
            'rank': 'الرتبة *',
            'name': 'الاسم الكامل *',
            'force': 'القوة',
            'unit': 'الوحدة',
            'phone': 'رقم الهاتف',
            'is_active': 'نشط / على رأس العمل'
        }

    def clean_military_number(self):
        number = self.cleaned_data.get('military_number', '').strip()
        if not number.isdigit():
            raise forms.ValidationError('النمرة تقبل أرقاماً فقط (0-9).')
        qs = Instructor.objects.filter(military_number=number)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(f'النمرة العسكرية "{number}" مسجلة مسبقاً لمعلم آخر ولا يمكن تكرارها.')
        if Trainee.objects.filter(military_number=number).exists():
            raise forms.ValidationError(f'النمرة العسكرية "{number}" مسجلة مسبقاً في النظام كدارس، ولا يجوز تكرار النمرة العسكرية بين المعلمين والدارسين.')
        return number


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['category', 'course_number', 'name', 'attendance_max_grade', 'description']
        widgets = {
            'category': forms.Select(attrs={
                'class': 'form-select form-select-lg',
                'required': 'required'
            }),
            'course_number': forms.TextInput(attrs={
                'class': 'form-control form-control-lg font-monospace',
                'placeholder': 'توليد تلقائي من النظام',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: دورة مرشد متقدمة',
                'required': 'required'
            }),
            'attendance_max_grade': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg',
                'step': '0.5',
                'min': '0',
                'placeholder': '10',
                'value': '10',
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'وصف مختصر لأهداف ومخرجات الدورة (اختياري)...',
            }),
        }
        labels = {
            'category': 'تصنيف الدورة *',
            'course_number': 'رقم/رمز الدورة (توليد تلقائي)',
            'name': 'اسم الدورة *',
            'attendance_max_grade': 'درجة المواظبة *',
            'description': 'الوصف والأهداف',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['course_number'].required = False
        if 'attendance_max_grade' in self.fields:
            self.fields['attendance_max_grade'].required = False
            if not self.instance.pk:
                self.fields['attendance_max_grade'].initial = 10.00

    def clean_attendance_max_grade(self):
        val = self.cleaned_data.get('attendance_max_grade')
        if val is None or val == '':
            return Decimal('10.00')
        return val

    def clean_course_number(self):
        number = self.cleaned_data.get('course_number', '').strip()
        if not number and self.instance and self.instance.pk:
            return self.instance.course_number
        if number:
            qs = Course.objects.filter(course_number__iexact=number)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f'رقم / رمز الدورة "{number}" مسجل مسبقاً لدورة أخرى ولا يمكن تكراره.')
        return number


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['code', 'name', 'credit_hours', 'max_grade']
        widgets = {
            'code': forms.TextInput(attrs={
                'class': 'form-control form-control-lg font-monospace',
                'placeholder': 'توليد تلقائي من النظام',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: ملاحة وتوجيه أرضي',
                'required': 'required'
            }),
            'credit_hours': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: 25',
                'min': 1,
                'required': 'required'
            }),
            'max_grade': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: 100',
                'step': '0.5',
                'min': 10,
                'required': 'required'
            }),
        }
        labels = {
            'code': 'رقم/كود المادة (توليد تلقائي)',
            'name': 'اسم المادة *',
            'credit_hours': 'عدد الساعات *',
            'max_grade': 'الدرجة العظمى *',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False

    def clean_code(self):
        code = self.cleaned_data.get('code', '').strip()
        if code:
            qs = Subject.objects.filter(code__iexact=code)
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError(f'رقم / كود المادة "{code}" مسجل مسبقاً لمادة أخرى ولا يمكن تكراره.')
        return code

    def clean_max_grade(self):
        mg = self.cleaned_data.get('max_grade')
        if mg is not None and mg <= 0:
            raise forms.ValidationError('الدرجة العظمى للمادة يجب أن تكون أكبر من صفر.')
        return mg


class CourseSessionForm(forms.ModelForm):
    class Meta:
        model = CourseSession
        fields = ['course', 'session_code', 'start_date', 'end_date', 'movement_order_date', 'movement_order_file', 'status', 'attendance_max_grade', 'notes']
        widgets = {
            'course': forms.Select(attrs={
                'class': 'form-select form-select-lg',
                'required': 'required'
            }),
            'session_code': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: الدفعة 18 - 2026',
                'required': 'required'
            }),
            'start_date': forms.DateInput(attrs={
                'class': 'form-control form-control-lg',
                'type': 'date',
                'required': 'required'
            }),
            'end_date': forms.DateInput(attrs={
                'class': 'form-control form-control-lg',
                'type': 'date',
                'required': 'required'
            }),
            'movement_order_date': forms.DateInput(attrs={
                'class': 'form-control form-control-lg',
                'type': 'date',
            }),
            'movement_order_file': forms.FileInput(attrs={
                'class': 'form-control form-control-lg',
                'accept': 'image/*,.pdf',
            }),
            'status': forms.Select(attrs={
                'class': 'form-select form-select-lg',
            }),
            'attendance_max_grade': forms.NumberInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': '20',
                'step': '0.5',
                'min': 0,
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'أي ملاحظات إضافية عن الدورة المنعقدة...',
            }),
        }
        labels = {
            'course': 'الدورة التدريبية *',
            'session_code': 'رمز الدفعة / رقم الانعقاد *',
            'start_date': 'تاريخ البداية *',
            'end_date': 'تاريخ النهاية *',
            'movement_order_date': 'تاريخ أمر التحرك *',
            'movement_order_file': 'صورة scan لأمر التحرك *',
            'status': 'حالة الدورة',
            'attendance_max_grade': 'درجة المواظبة والسلوك العظمى',
            'notes': 'ملاحظات الانعقاد',
        }

    def clean_attendance_max_grade(self):
        amg = self.cleaned_data.get('attendance_max_grade')
        if amg is not None and amg < 0:
            raise forms.ValidationError('الدرجة العظمى للمواظبة لا يمكن أن تكون أقل من صفر.')
        return amg


class UserLoginForm(forms.Form):
    """نموذج تسجيل دخول المستخدم للنظام"""
    username = forms.CharField(
        label='اسم المستخدم',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'اسم المستخدم (مثال: admin)',
            'autocomplete': 'username',
            'required': 'required'
        })
    )
    password = forms.CharField(
        label='كلمة المرور',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
            'required': 'required'
        })
    )


class CourseCategoryForm(forms.ModelForm):
    """نموذج إضافة وتعديل تصنيف الدورات التدريبية"""
    class Meta:
        model = CourseCategory
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: دورات القيادة والأركان، دورات تقنية المعلومات...',
                'required': 'required'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'وصف مختصر لطبيعة وأهداف هذا التصنيف من الدورات...',
            }),
        }
        labels = {
            'name': 'اسم تصنيف الدورات *',
            'description': 'الوصف والنبذة',
        }


class CertificateSettingsForm(forms.ModelForm):
    """نموذج تخصيص شكل وتوقيعات ونصوص الشهادة الرسمية"""
    class Meta:
        model = CertificateSettings
        fields = [
            'bismillah_text',
            'header_line_1',
            'header_line_2',
            'cert_title',
            'cert_title_color',
            'basic_cert_title',
            'advanced_cert_title',
            'default_certificate_note',
            'right_signer_rank',
            'right_signer_name',
            'right_signer_title',
            'left_signer_rank',
            'left_signer_name',
            'left_signer_title',
            'center_approval_prefix',
            'center_signer_rank',
            'center_signer_name',
            'center_signer_title',
            'station_text',
            'seal_notice',
            'logo_height_mm',
            'right_logo',
            'left_logo',
        ]
        widgets = {
            'bismillah_text': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'بسم الله الرحمن الرحيم'
            }),
            'header_line_1': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'إدارة نظم المعلومات والإحصاء'
            }),
            'header_line_2': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'معهد نظم المعلومات والإحصاء'
            }),
            'cert_title': forms.TextInput(attrs={
                'class': 'form-control fw-bold',
                'placeholder': 'شهــــــادة'
            }),
            'cert_title_color': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'basic_cert_title': forms.TextInput(attrs={
                'class': 'form-control fw-bold',
                'placeholder': 'شهادة دورة حاسوب أساسية'
            }),
            'advanced_cert_title': forms.TextInput(attrs={
                'class': 'form-control fw-bold',
                'placeholder': 'شهادة دورة حاسوب متقدمة'
            }),
            'default_certificate_note': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'بدأ الدورة بدون معلومات، بذل مجهوداً أهله للحصول على هذا التقدير، مواظب ومشارك، مهتم وطموح.'
            }),
            'right_signer_rank': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مقدم مهندس ركن'
            }),
            'right_signer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'وليد عادل جاه الله حسب الرسول'
            }),
            'right_signer_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'قــــــائد جنـــــــــاح التعليــــــــــم'
            }),
            'left_signer_rank': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'عقيد مهندس'
            }),
            'left_signer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'المعــز علـــــي محمــــــد خيـــــــــر'
            }),
            'left_signer_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'قائد معهد نظم المعلومات والإحصاء'
            }),
            'center_approval_prefix': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'يعتمد'
            }),
            'center_signer_rank': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'لواء دكتور ركن'
            }),
            'center_signer_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'إبــــراهيم محمــــد علـــــــي أحمــــد'
            }),
            'center_signer_title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'مدير إدارة نظم المعلومات والإحصاء'
            }),
            'station_text': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'الخرطــــــــــــوم'
            }),
            'seal_notice': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '(أي شهادة غير مختومة بالختم البارز لا تعتمد)'
            }),
            'logo_height_mm': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': '30',
                'max': '90',
                'placeholder': '56'
            }),
            'right_logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'left_logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
        }
        labels = {
            'bismillah_text': 'نص البسملة العلوي',
            'header_line_1': 'سطر الترويسة الأول (الإدارة)',
            'header_line_2': 'سطر الترويسة الثاني (المعهد/الجهة)',
            'cert_title': 'كلمة عنوان الشهادة',
            'cert_title_color': 'لون كلمة الشهادة',
            'right_signer_rank': 'رتبة الموقع الأول (الأيمن)',
            'right_signer_name': 'اسم الموقع الأول (الأيمن)',
            'right_signer_title': 'منصب الموقع الأول (الأيمن)',
            'left_signer_rank': 'رتبة الموقع الثاني (الأيسر)',
            'left_signer_name': 'اسم الموقع الثاني (الأيسر)',
            'left_signer_title': 'منصب الموقع الثاني (الأيسر)',
            'center_approval_prefix': 'كلمة الاعتماد (الوسط)',
            'center_signer_rank': 'رتبة معتمد الشهادة (الوسط)',
            'center_signer_name': 'اسم معتمد الشهادة (الوسط)',
            'center_signer_title': 'منصب معتمد الشهادة (الوسط)',
            'station_text': 'المحطة / المدينة',
            'seal_notice': 'تنبيه الختم البارز (التذييل الأخضر)',
            'logo_height_mm': 'ارتفاع الشعارات (بالملم - الافتراضي 56)',
            'right_logo': 'تغيير شعار الشهادة الأيمن (صقر الجديان)',
            'left_logo': 'تغيير شعار الشهادة الأيسر (شعار الإدارة)',
        }


class SystemSettingsForm(forms.ModelForm):
    """نموذج تخصيص اللوغو الرئيسي وألوان وهوية النظام بالكامل"""
    class Meta:
        model = SystemSettings
        fields = [
            'system_name',
            'system_subheading',
            'main_logo',
            'primary_navy',
            'primary_accent',
            'brand_blue',
            'brand_cyan',
            'gold_accent',
            'bg_light',
            'sidebar_bg_start',
            'sidebar_bg_end',
        ]
        widgets = {
            'system_name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'نظام تسجيل واستخراج النتائج والشهادات'
            }),
            'system_subheading': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'بوابة رصد الدرجات والشهادات المعتمدة'
            }),
            'main_logo': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'primary_navy': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'primary_accent': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'brand_blue': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'brand_cyan': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'gold_accent': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'bg_light': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'sidebar_bg_start': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
            'sidebar_bg_end': forms.TextInput(attrs={
                'class': 'form-control form-control-color w-100',
                'type': 'color'
            }),
        }
        labels = {
            'system_name': 'اسم النظام الرسمي *',
            'system_subheading': 'الوصف الفرعي للنظام',
            'main_logo': 'شعار النظام الرئيسي (Navbar & Sidebar Logo)',
            'primary_navy': 'اللون الداكن الرئيسي (Header Background)',
            'primary_accent': 'اللون الكحلي المميز (Accent & Cards)',
            'brand_blue': 'لون الأزرار والروابط الأساسية (Primary Buttons)',
            'brand_cyan': 'اللون التكميلي الثانوي (Cyan)',
            'gold_accent': 'اللون الذهبي المميز (Gold Accent & Borders)',
            'bg_light': 'لون خلفية الصفحات (Page Background)',
            'sidebar_bg_start': 'بداية تدرج القائمة الجانبية (Sidebar Gradient Top)',
            'sidebar_bg_end': 'نهاية تدرج القائمة الجانبية (Sidebar Gradient Bottom)',
        }


class UserCreateForm(forms.ModelForm):
    """نموذج إضافة مستخدم جديد وتحديد دوره وصلاحياته في النظام"""
    username = forms.CharField(
        label='اسم المستخدم للدخول *',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'مثال: registrar1, officer_ali',
            'required': 'required'
        })
    )
    password = forms.CharField(
        label='كلمة المرور *',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': '••••••••',
            'required': 'required'
        })
    )
    first_name = forms.CharField(
        label='الاسم الأول *',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'الاسم الأول'})
    )
    last_name = forms.CharField(
        label='اسم العائلة / اللقب',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم العائلة'})
    )
    role = forms.ChoiceField(
        label='نوع وصلاحية المستخدم *',
        choices=UserRole.choices,
        widget=forms.Select(attrs={'class': 'form-select form-select-lg', 'required': 'required'})
    )
    instructor = forms.ModelChoiceField(
        queryset=Instructor.objects.filter(is_active=True),
        required=False,
        label='ربط بملف المعلم من هيئة التدريس',
        empty_label='-- اختياري: غير مرتبط بمعلم محدد --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    military_number = forms.CharField(
        label='النمرة العسكرية (إن وجدت)',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 10452'})
    )
    rank = forms.CharField(
        label='الرتبة',
        required=False,
        widget=forms.Select(
            choices=MILITARY_RANK_CHOICES,
            attrs={'class': 'form-select', 'id': 'createUserRankSelect', 'onchange': 'toggleUserCustomRank("createUser")'}
        )
    )
    unit = forms.CharField(
        label='الوحدة / الفرع',
        required=False,
        widget=forms.Select(
            choices=MILITARY_UNIT_CHOICES,
            attrs={'class': 'form-select', 'id': 'createUserUnitSelect', 'onchange': 'toggleUserCustomUnit("createUser")'}
        )
    )
    phone = forms.CharField(
        label='رقم الهاتف',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': '09xxxxxxx'})
    )
    is_active = forms.BooleanField(
        label='حساب مفعل ونشط',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    # أذونات وصلاحيات كخيارات صح (Checkboxes) بأسلوب ويندوز
    can_manage_users = forms.BooleanField(
        label='التحكم الكامل وإدارة النظام (Full Control)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'create_perm_manage_users'})
    )
    can_view = forms.BooleanField(
        label='القراءة والعرض (Read / View)',
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'create_perm_view'})
    )
    can_add = forms.BooleanField(
        label='الكتابة والإضافة (Write / Add)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'create_perm_add'})
    )
    can_edit = forms.BooleanField(
        label='التعديل والكتابة (Modify / Edit)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'create_perm_edit'})
    )
    can_delete = forms.BooleanField(
        label='الحذف (Delete)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'create_perm_delete'})
    )
    can_grade = forms.BooleanField(
        label='رصد الدرجات (Grade Entry)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'create_perm_grade'})
    )
    can_approve_results = forms.BooleanField(
        label='اعتماد النتائج النهائية (Approve Results)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'create_perm_approve'})
    )

    class Meta:
        model = User
        fields = ['username', 'password', 'first_name', 'last_name', 'is_active']

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('اسم المستخدم هذا مسجل مسبقاً، الرجاء اختيار اسم آخر.')
        return username

    def clean_rank(self):
        val = self.cleaned_data.get('rank', '').strip()
        custom_val = self.data.get('custom_rank', '').strip()
        if val == '__custom__':
            return custom_val
        return val

    def clean_unit(self):
        val = self.cleaned_data.get('unit', '').strip()
        custom_val = self.data.get('custom_unit', '').strip()
        if val == '__custom__':
            return custom_val
        return val


class UserEditForm(forms.ModelForm):
    """نموذج تعديل بيانات وصلاحيات وكلمة مرور المستخدم"""
    role = forms.ChoiceField(
        label='نوع وصلاحية المستخدم *',
        choices=UserRole.choices,
        widget=forms.Select(attrs={'class': 'form-select', 'required': 'required'})
    )
    instructor = forms.ModelChoiceField(
        queryset=Instructor.objects.filter(is_active=True),
        required=False,
        label='ربط بملف المعلم من هيئة التدريس',
        empty_label='-- اختياري: غير مرتبط بمعلم محدد --',
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    military_number = forms.CharField(
        label='النمرة العسكرية',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    rank = forms.CharField(
        label='الرتبة',
        required=False,
        widget=forms.Select(
            choices=MILITARY_RANK_CHOICES,
            attrs={'class': 'form-select', 'id': 'editUserRankSelect', 'onchange': 'toggleUserCustomRank("editUser")'}
        )
    )
    unit = forms.CharField(
        label='الوحدة / الفرع',
        required=False,
        widget=forms.Select(
            choices=MILITARY_UNIT_CHOICES,
            attrs={'class': 'form-select', 'id': 'editUserUnitSelect', 'onchange': 'toggleUserCustomUnit("editUser")'}
        )
    )
    phone = forms.CharField(
        label='رقم الهاتف',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    # أذونات وصلاحيات كخيارات صح (Checkboxes) بأسلوب ويندوز
    can_manage_users = forms.BooleanField(
        label='التحكم الكامل وإدارة النظام (Full Control)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'edit_perm_manage_users'})
    )
    can_view = forms.BooleanField(
        label='القراءة والعرض (Read / View)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'edit_perm_view'})
    )
    can_add = forms.BooleanField(
        label='الكتابة والإضافة (Write / Add)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'edit_perm_add'})
    )
    can_edit = forms.BooleanField(
        label='التعديل والكتابة (Modify / Edit)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'edit_perm_edit'})
    )
    can_delete = forms.BooleanField(
        label='الحذف (Delete)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'edit_perm_delete'})
    )
    can_grade = forms.BooleanField(
        label='رصد الدرجات (Grade Entry)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'edit_perm_grade'})
    )
    can_approve_results = forms.BooleanField(
        label='اعتماد النتائج النهائية (Approve Results)',
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input perm-check', 'id': 'edit_perm_approve'})
    )

    new_password = forms.CharField(
        label='تعيين كلمة مرور جديدة (اتركه فارغاً للإبقاء على الحالية)',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '••••••••'})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # إذا كانت الرتبة الحالية للمستخدم مخصصة وغير موجودة في الخيارات القياسية، نضيفها للخيارات
        current_rank = self.initial.get('rank') or (self.instance.profile.rank if hasattr(self.instance, 'profile') else '')
        if current_rank:
            all_ranks = [opt[0] for grp in MILITARY_RANK_CHOICES for opt in (grp[1] if isinstance(grp[1], (list, tuple)) else [(grp[0], grp[1])])]
            if current_rank not in all_ranks:
                choices = list(self.fields['rank'].widget.choices)
                choices.append(('رتب مسجلة مسبقاً', [(current_rank, current_rank)]))
                self.fields['rank'].widget.choices = choices

        # إذا كانت الوحدة الحالية للمستخدم مخصصة وغير موجودة في الخيارات القياسية، نضيفها للخيارات
        current_unit = self.initial.get('unit') or (self.instance.profile.unit if hasattr(self.instance, 'profile') else '')
        if current_unit:
            all_units = [opt[0] for grp in MILITARY_UNIT_CHOICES for opt in (grp[1] if isinstance(grp[1], (list, tuple)) else [(grp[0], grp[1])])]
            if current_unit not in all_units:
                choices = list(self.fields['unit'].widget.choices)
                choices.append(('وحدات مسجلة مسبقاً', [(current_unit, current_unit)]))
                self.fields['unit'].widget.choices = choices

    def clean_rank(self):
        val = self.cleaned_data.get('rank', '').strip()
        custom_val = self.data.get('custom_rank', '').strip()
        if val == '__custom__':
            return custom_val
        return val

    def clean_unit(self):
        val = self.cleaned_data.get('unit', '').strip()
        custom_val = self.data.get('custom_unit', '').strip()
        if val == '__custom__':
            return custom_val
        return val

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'first_name': 'الاسم الأول',
            'last_name': 'اسم العائلة',
            'email': 'البريد الإلكتروني',
            'is_active': 'حساب نشط ومفعل',
        }


class AdminLoginForm(forms.Form):
    """نموذج الدخول الخاص والمنفصل للوحة القيادة والأدمن"""
    username = forms.CharField(
        label='اسم مستخدم الأدمن',
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'اسم مستخدم الأدمن',
            'autocomplete': 'username',
            'autofocus': True,
            'required': 'required'
        })
    )
    password = forms.CharField(
        label='كلمة المرور السرية',
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': '••••••••',
            'autocomplete': 'current-password',
            'required': 'required'
        })
    )


