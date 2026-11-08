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


class TraineeForm(forms.ModelForm):
    class Meta:
        model = Trainee
        fields = ['military_number', 'category', 'name']
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
        }

    def clean_military_number(self):
        number = self.cleaned_data.get('military_number', '').strip()
        if not number.isdigit():
            raise forms.ValidationError('النمرة تقبل أرقاماً فقط (0-9). يرجى عدم إدخال أحرف أو رموز.')
        return number


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
        return number


class CourseForm(forms.ModelForm):
    class Meta:
        model = Course
        fields = ['category', 'course_number', 'name', 'description']
        widgets = {
            'category': forms.Select(attrs={
                'class': 'form-select form-select-lg',
                'required': 'required'
            }),
            'course_number': forms.TextInput(attrs={
                'class': 'form-control form-control-lg font-monospace',
                'placeholder': 'مثال: GUIDE-101 أو C-2026',
            }),
            'name': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: دورة مرشد متقدمة',
                'required': 'required'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'وصف مختصر لأهداف ومخرجات الدورة (اختياري)...',
            }),
        }
        labels = {
            'category': 'تصنيف الدورة *',
            'course_number': 'رقم/رمز الدورة',
            'name': 'اسم الدورة *',
            'description': 'الوصف والأهداف',
        }


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['code', 'name', 'credit_hours', 'max_grade']
        widgets = {
            'code': forms.TextInput(attrs={
                'class': 'form-control form-control-lg font-monospace',
                'placeholder': 'مثال: G101 أو M-01',
                'required': 'required'
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
            'code': 'رقم/كود المادة *',
            'name': 'اسم المادة *',
            'credit_hours': 'عدد الساعات *',
            'max_grade': 'الدرجة العظمى *',
        }

    def clean_max_grade(self):
        mg = self.cleaned_data.get('max_grade')
        if mg is not None and mg <= 0:
            raise forms.ValidationError('الدرجة العظمى للمادة يجب أن تكون أكبر من صفر.')
        return mg


class CourseSessionForm(forms.ModelForm):
    class Meta:
        model = CourseSession
        fields = ['course', 'session_code', 'start_date', 'end_date', 'status', 'attendance_max_grade', 'notes']
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
    military_number = forms.CharField(
        label='النمرة العسكرية (إن وجدت)',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: 10452'})
    )
    rank = forms.CharField(
        label='الرتبة',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: نقيب، رائد'})
    )
    unit = forms.CharField(
        label='الوحدة / الفرع',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مثال: جناح التعليم'})
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

    class Meta:
        model = User
        fields = ['username', 'password', 'first_name', 'last_name', 'is_active']

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError('اسم المستخدم هذا مسجل مسبقاً، الرجاء اختيار اسم آخر.')
        return username


class UserEditForm(forms.ModelForm):
    """نموذج تعديل بيانات وصلاحيات وكلمة مرور المستخدم"""
    role = forms.ChoiceField(
        label='نوع وصلاحية المستخدم *',
        choices=UserRole.choices,
        widget=forms.Select(attrs={'class': 'form-select', 'required': 'required'})
    )
    military_number = forms.CharField(
        label='النمرة العسكرية',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    rank = forms.CharField(
        label='الرتبة',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    unit = forms.CharField(
        label='الوحدة / الفرع',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    phone = forms.CharField(
        label='رقم الهاتف',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )
    new_password = forms.CharField(
        label='تعيين كلمة مرور جديدة (اتركه فارغاً للإبقاء على الحالية)',
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': '••••••••'})
    )

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


