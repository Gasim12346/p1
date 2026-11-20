from django import forms
from apps.trainees.models import Trainee, TraineeCategory, TraineeRelative
from apps.academic.models import Instructor
from apps.core.forms import validate_and_clean_phone

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
            'placeholder': 'مثال: 0912345678 (10 أرقام)',
            'type': 'tel',
            'maxlength': '10',
            'minlength': '10',
            'pattern': r'\d{10}',
            'inputmode': 'numeric',
            'title': 'رقم الهاتف يجب أن يتكون من 10 أرقام فقط',
            'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);"
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
    relative_1_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف (10 أرقام)', 'type': 'tel', 'maxlength': '10', 'minlength': '10', 'pattern': r'\d{10}', 'inputmode': 'numeric', 'title': 'رقم الهاتف يجب أن يتكون من 10 أرقام فقط', 'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);"}), label='رقم الهاتف')
    relative_1_address = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مكان السكن / العنوان'}), label='السكن / العنوان')

    # القريب 2
    relative_2_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القريب الثاني'}), label='اسم القريب الثاني')
    relative_2_kinship = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'صلة القرابة (مثال: والدة، زوجة)'}), label='صلة القرابة')
    relative_2_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف (10 أرقام)', 'type': 'tel', 'maxlength': '10', 'minlength': '10', 'pattern': r'\d{10}', 'inputmode': 'numeric', 'title': 'رقم الهاتف يجب أن يتكون من 10 أرقام فقط', 'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);"}), label='رقم الهاتف')
    relative_2_address = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مكان السكن / العنوان'}), label='السكن / العنوان')

    # القريب 3
    relative_3_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القريب الثالث'}), label='اسم القريب الثالث')
    relative_3_kinship = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'صلة القرابة (مثال: عم، خال)'}), label='صلة القرابة')
    relative_3_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف (10 أرقام)', 'type': 'tel', 'maxlength': '10', 'minlength': '10', 'pattern': r'\d{10}', 'inputmode': 'numeric', 'title': 'رقم الهاتف يجب أن يتكون من 10 أرقام فقط', 'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);"}), label='رقم الهاتف')
    relative_3_address = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مكان السكن / العنوان'}), label='السكن / العنوان')

    # القريب 4
    relative_4_name = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'اسم القريب الرابع'}), label='اسم القريب الرابع')
    relative_4_kinship = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'صلة القرابة'}), label='صلة القرابة')
    relative_4_phone = forms.CharField(required=False, widget=forms.TextInput(attrs={'class': 'form-control font-monospace', 'placeholder': 'رقم الهاتف (10 أرقام)', 'type': 'tel', 'maxlength': '10', 'minlength': '10', 'pattern': r'\d{10}', 'inputmode': 'numeric', 'title': 'رقم الهاتف يجب أن يتكون من 10 أرقام فقط', 'oninput': "this.value = this.value.replace(/[^0-9]/g, '').slice(0, 10);"}), label='رقم الهاتف')
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

    def clean_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('phone'), 'رقم هاتف الدارس')

    def clean_relative_1_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('relative_1_phone'), 'هاتف القريب الأول')

    def clean_relative_2_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('relative_2_phone'), 'هاتف القريب الثاني')

    def clean_relative_3_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('relative_3_phone'), 'هاتف القريب الثالث')

    def clean_relative_4_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('relative_4_phone'), 'هاتف القريب الرابع')

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


