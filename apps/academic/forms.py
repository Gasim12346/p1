from decimal import Decimal
from django import forms
from apps.academic.models import Instructor, CourseCategory, Course, Subject, CourseSession
from apps.trainees.models import Trainee
from apps.core.forms import validate_and_clean_phone
from apps.core.validators import validate_movement_order_file

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

    def clean_phone(self):
        return validate_and_clean_phone(self.cleaned_data.get('phone'), 'رقم هاتف المعلم')



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
                self.fields['attendance_max_grade'].initial = 10
            elif self.instance and self.instance.attendance_max_grade is not None:
                if self.instance.attendance_max_grade == int(self.instance.attendance_max_grade):
                    self.initial['attendance_max_grade'] = int(self.instance.attendance_max_grade)

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
        if not self.instance.pk:
            self.fields['max_grade'].initial = 100
            self.fields['credit_hours'].initial = 10
        elif self.instance and self.instance.max_grade is not None:
            if self.instance.max_grade == int(self.instance.max_grade):
                self.initial['max_grade'] = int(self.instance.max_grade)

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
        fields = ['course', 'target_category', 'session_code', 'start_date', 'end_date', 'movement_order_date', 'movement_order_file', 'status', 'attendance_max_grade', 'notes']
        widgets = {
            'course': forms.Select(attrs={
                'class': 'form-select form-select-lg',
                'required': 'required'
            }),
            'target_category': forms.Select(attrs={
                'class': 'form-select form-select-lg',
                'required': 'required'
            }),
            'session_code': forms.TextInput(attrs={
                'class': 'form-control form-control-lg',
                'placeholder': 'مثال: 1 أو 18',
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
            'session_code': 'رقم الدورة *',
            'start_date': 'تاريخ البداية *',
            'end_date': 'تاريخ النهاية *',
            'movement_order_date': 'تاريخ أمر التحرك *',
            'movement_order_file': 'صورة scan لأمر التحرك *',
            'status': 'حالة الدورة',
            'attendance_max_grade': 'درجة المواظبة والسلوك العظمى',
            'notes': 'ملاحظات الانعقاد',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'attendance_max_grade' in self.fields:
            if not self.instance.pk:
                self.fields['attendance_max_grade'].initial = 10
            elif self.instance and self.instance.attendance_max_grade is not None:
                if self.instance.attendance_max_grade == int(self.instance.attendance_max_grade):
                    self.initial['attendance_max_grade'] = int(self.instance.attendance_max_grade)

    def clean_attendance_max_grade(self):
        amg = self.cleaned_data.get('attendance_max_grade')
        if amg is not None and amg < 0:
            raise forms.ValidationError('الدرجة العظمى للمواظبة لا يمكن أن تكون أقل من صفر.')
        return amg

    def clean_movement_order_file(self):
        f = self.cleaned_data.get('movement_order_file')
        if f:
            validate_movement_order_file(f)
        return f



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


