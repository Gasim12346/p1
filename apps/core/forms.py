from django import forms
from django.core.validators import validate_email
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from apps.core.models import SystemSettings, UserProfile, UserRole
from apps.academic.models import Instructor
from apps.core.validators import validate_image_file

def validate_and_clean_phone(phone_val, field_label='رقم الهاتف'):
    """
    التحقق الصارم من قيود رقم الهاتف:
    - يقبل أرقاماً فقط (0-9).
    - يشترط أن يتكون من 10 أرقام بالضبط.
    """
    if not phone_val:
        return ''
    cleaned = str(phone_val).strip()
    if not cleaned:
        return ''
    if not cleaned.isdigit():
        raise forms.ValidationError(f'{field_label} يجب أن يحتوي على أرقام فقط دون مسافات أو أحرف أو رموز.')
    if len(cleaned) != 10:
        raise forms.ValidationError(f'{field_label} يجب أن يتكون من 10 أرقام بالضبط (المدخل حالياً: {len(cleaned)} أرقام).')
    return cleaned


def validate_and_clean_email(email_val, field_label='البريد الإلكتروني'):
    """
    التحقق الصارم من صحة عنوان البريد الإلكتروني.
    """
    if not email_val:
        return ''
    cleaned = str(email_val).strip()
    if not cleaned:
        return ''
    try:
        validate_email(cleaned)
    except forms.ValidationError:
        raise forms.ValidationError('يرجى إدخال عنوان بريد إلكتروني صحيح (مثال: name@domain.com).')
    return cleaned


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

    def clean_main_logo(self):
        f = self.cleaned_data.get('main_logo')
        if f:
            validate_image_file(f)
        return f



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
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'الاسم الأول'})
    )
    last_name = forms.CharField(
        label='اسم العائلة / اللقب',
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم العائلة'})
    )
    email = forms.EmailField(
        label='البريد الإلكتروني',
        required=False,
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com'}),
        error_messages={'invalid': 'يرجى إدخال عنوان بريد إلكتروني صحيح (مثال: name@domain.com).'}
    )
    role = forms.ChoiceField(
        label='نوع وصلاحية المستخدم *',
        choices=[c for c in UserRole.choices if c[0] != UserRole.SUPER_ADMIN],
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
        widget=forms.TextInput(attrs={
            'class': 'form-control font-monospace',
            'placeholder': 'مثال: 0912345678 (10 أرقام)',
            'type': 'tel',
            'maxlength': '10',
            'minlength': '10',
            'pattern': r'\d{10}',
            'inputmode': 'numeric',
            'title': 'رقم الهاتف يجب أن يتكون من 10 أرقام فقط',
            'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);"
        })
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
        fields = ['username', 'password', 'first_name', 'last_name', 'email', 'is_active']

    def clean_password(self):
        password = self.cleaned_data.get('password')
        if password:
            validate_password(password)
        return password

    def clean_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('phone'), 'رقم الهاتف')

    def clean_email(self):
        return validate_and_clean_email(self.cleaned_data.get('email'))

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

    def clean(self):
        cleaned_data = super().clean()
        first_name = (cleaned_data.get('first_name') or '').strip()
        instructor = cleaned_data.get('instructor')
        if not first_name:
            if instructor and instructor.name:
                parts = instructor.name.strip().split()
                cleaned_data['first_name'] = parts[0] if parts else instructor.name
                if not cleaned_data.get('last_name') and len(parts) > 1:
                    cleaned_data['last_name'] = " ".join(parts[1:])
            else:
                self.add_error('first_name', 'الاسم الأول مطلوب.')
        return cleaned_data



class UserEditForm(forms.ModelForm):
    """نموذج تعديل بيانات وصلاحيات وكلمة مرور المستخدم"""
    role = forms.ChoiceField(
        label='نوع وصلاحية المستخدم *',
        choices=[c for c in UserRole.choices if c[0] != UserRole.SUPER_ADMIN],
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
        widget=forms.TextInput(attrs={
            'class': 'form-control font-monospace',
            'placeholder': 'مثال: 0912345678 (10 أرقام)',
            'type': 'tel',
            'maxlength': '10',
            'minlength': '10',
            'pattern': r'\d{10}',
            'inputmode': 'numeric',
            'title': 'رقم الهاتف يجب أن يتكون من 10 أرقام فقط',
            'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);"
        })
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

    def clean(self):
        cleaned_data = super().clean()
        first_name = (cleaned_data.get('first_name') or '').strip()
        instructor = cleaned_data.get('instructor')
        if not first_name:
            if instructor and instructor.name:
                parts = instructor.name.strip().split()
                cleaned_data['first_name'] = parts[0] if parts else instructor.name
                if not cleaned_data.get('last_name') and len(parts) > 1:
                    cleaned_data['last_name'] = " ".join(parts[1:])
            else:
                self.add_error('first_name', 'الاسم الأول مطلوب.')
        return cleaned_data

    def clean_new_password(self):
        new_password = self.cleaned_data.get('new_password')
        if new_password and new_password.strip():
            validate_password(new_password.strip(), user=self.instance)
        return new_password

    def clean_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('phone'), 'رقم الهاتف')

    def clean_email(self):
        return validate_and_clean_email(self.cleaned_data.get('email'))

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'is_active']
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'name@example.com'}),
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


