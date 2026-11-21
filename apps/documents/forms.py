from django import forms
from apps.documents.models import CertificateSettings, MovementOrderSettings
from apps.core.validators import validate_image_file

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
            'logo_height_mm': 'ارتفاع الشعارات (بالملم - 56)',
            'right_logo': 'تغيير شعار الشهادة الأيمن (صقر الجديان)',
            'left_logo': 'تغيير شعار الشهادة الأيسر (شعار الإدارة)',
        }

    def clean_right_logo(self):
        f = self.cleaned_data.get('right_logo')
        if f:
            validate_image_file(f)
        return f

    def clean_left_logo(self):
        f = self.cleaned_data.get('left_logo')
        if f:
            validate_image_file(f)
        return f



class MovementOrderSettingsForm(forms.ModelForm):
    """نموذج تخصيص شكل ونصوص وتوقيعات أمر التحرك الرسمي"""
    class Meta:
        model = MovementOrderSettings
        fields = [
            'bismillah_text',
            'security_label',
            'order_title',
            'issuing_authority_text',
            'from_location',
            'to_location_default',
            'arms_default',
            'ammunition_default',
            'purpose_prefix',
            'clothing_instructions',
            'travel_means',
            'ratification_text',
            'admin_instructions',
            'certificate_declaration',
            'signer_rank',
            'signer_name',
            'signer_title',
            'signer_dept',
            'copy_to_1',
            'copy_to_2',
            'watermark_image',
            'watermark_opacity',
        ]
        widgets = {
            'bismillah_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'بسم الله الرحمن الرحيم'}),
            'security_label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'محظور'}),
            'order_title': forms.TextInput(attrs={'class': 'form-control fw-bold', 'placeholder': 'أمر تــــحـــــرك'}),
            'issuing_authority_text': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'الصادر بأمر سيادة العقيد...'}),
            'from_location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'معهد نظم المعلومات والاحصاء'}),
            'to_location_default': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'شعبة التدريب'}),
            'arms_default': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'لا يكن'}),
            'ammunition_default': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'لا يكن'}),
            'purpose_prefix': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'انتهاء '}),
            'clothing_instructions': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'حسب التعليمات'}),
            'travel_means': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'بالمتاحة'}),
            'ratification_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'السيد قائد معهد نظم المعلومات والاحصاء'}),
            'admin_instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'certificate_declaration': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'signer_rank': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'مقدم مهندس ركن'}),
            'signer_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'وليد عادل جاه الله حسب الرسول'}),
            'signer_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'ع/عقيد مهندس'}),
            'signer_dept': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'قائد معهد نظم المعلومات والإحصاء'}),
            'copy_to_1': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'السيد / رئيس شعبة التدريب'}),
            'copy_to_2': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'نسخة بيد المذكور...'}),
            'watermark_image': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'watermark_opacity': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.05', 'max': '1.0', 'step': '0.05'}),
        }
        labels = {
            'bismillah_text': 'البسملة العلوية',
            'security_label': 'درجة السرية (محظور)',
            'order_title': 'عنوان أمر التحرك',
            'issuing_authority_text': 'نص ديباجة الصدور (الصادر بأمر سيادة...)',
            'from_location': 'الجهة المتحرك منها (مـن)',
            'to_location_default': 'الجهة المتحرك إليها (إلـى)',
            'arms_default': 'السلاح',
            'ammunition_default': 'الذخيرة',
            'purpose_prefix': 'بادئة الغرض من التحرك',
            'clothing_instructions': 'اللبس أثناء السفر',
            'travel_means': 'وسيلة السفر',
            'ratification_text': 'جهة التصديق',
            'admin_instructions': 'نص التعليمات الإدارية',
            'certificate_declaration': 'نص إقرار الشهادة للمسافر',
            'signer_rank': 'رتبة القائد الموقع',
            'signer_name': 'اسم القائد الموقع',
            'signer_title': 'صفة/نيابة القائد الموقع',
            'signer_dept': 'منصب/جهة القائد الموقع',
            'copy_to_1': 'نسخة إلى (1)',
            'copy_to_2': 'نسخة إلى (2)',
            'watermark_image': 'صورة العلامة المائية المخصصة',
            'watermark_opacity': 'درجة شفافية العلامة المائية (0.05 - 1.0)',
        }

    def clean_watermark_image(self):
        f = self.cleaned_data.get('watermark_image')
        if f:
            validate_image_file(f)
        return f


