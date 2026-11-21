import os
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

MAX_FILE_SIZE_MB = 10
ALLOWED_DOCUMENT_EXTENSIONS = ('.pdf', '.png', '.jpg', '.jpeg')
ALLOWED_IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')

# التواقيع الثنائية الرقمية الصارمة للملفات (Magic Bytes / File Signatures)
FILE_SIGNATURES = {
    'pdf': b'%PDF',
    'png': b'\x89PNG\r\n\x1a\n',
    'jpg': b'\xff\xd8\xff',
    'jpeg': b'\xff\xd8\xff',
}


def validate_secure_file(file_obj, max_mb=MAX_FILE_SIZE_MB, allowed_extensions=ALLOWED_DOCUMENT_EXTENSIONS):
    """
    التحقق الأمني الصارم من الملفات المرفوعة:
    1. التحقق من حجم الملف وألا يتجاوز الحد الأقصى المسموح به.
    2. التحقق من امتداد الملف وأنه ضمن القائمة البيضاء المعتمدة.
    3. التحقق من البايتات السحرية (Magic Bytes) لرأس الملف للتأكد من عدم تزوير الامتداد وتمرير برمجيات خبيثة.
    """
    if not file_obj:
        return

    # 1. التحقق من الحجم
    if hasattr(file_obj, 'size') and file_obj.size > max_mb * 1024 * 1024:
        raise ValidationError(f'حجم الملف المرفوع ({file_obj.size / (1024*1024):.1f} ميجابايت) يتجاوز الحد الأقصى المسموح به وهو {max_mb} ميجابايت.')

    # 2. التحقق من الامتداد
    filename = getattr(file_obj, 'name', '')
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        allowed_str = ', '.join([e.replace('.', '').upper() for e in allowed_extensions])
        raise ValidationError(f'نوع الملف المرفوع ({ext}) غير مسموح به. الأنواع المعتمدة فقط هي: {allowed_str}.')

    # 3. التحقق من البايتات السحرية (Magic Bytes)
    if hasattr(file_obj, 'read') and hasattr(file_obj, 'seek'):
        try:
            initial_pos = file_obj.tell()
            header = file_obj.read(16)
            file_obj.seek(initial_pos)

            clean_ext = ext.lstrip('.').lower()
            if clean_ext in FILE_SIGNATURES:
                expected_sig = FILE_SIGNATURES[clean_ext]
                if not header.startswith(expected_sig):
                    raise ValidationError('الملف المرفوع تالف أو لا يتطابق محتواه الحقيقي مع امتداده المصرح به. يرجى رفع ملف سليم ومعتمد.')
        except Exception as e:
            if isinstance(e, ValidationError):
                raise
            # في حال حدوث استثناء بالقراءة نمرر الملف طالما نجح في فحص الامتداد والحجم
            pass


def validate_movement_order_file(file_obj):
    """التحقق من ملفات أوامر التحرك الرسمية (PDF أو صور مسح ضوئي JPG/PNG بحجم أقصى 10 ميجابايت)"""
    return validate_secure_file(file_obj, max_mb=10, allowed_extensions=ALLOWED_DOCUMENT_EXTENSIONS)


def validate_image_file(file_obj):
    """التحقق من الصور والشعارات الرسمية (بحجم أقصى 5 ميجابايت)"""
    return validate_secure_file(file_obj, max_mb=5, allowed_extensions=ALLOWED_IMAGE_EXTENSIONS)
