"""
إعادة تصدير نماذج الاستمارات (Forms) من التطبيقات المصغرة المنظمة
لضمان التوافقية الكاملة للخلف مع جميع أجزاء النظام.
"""
from apps.core.forms import (
    validate_and_clean_phone,
    validate_and_clean_email,
    MILITARY_RANK_CHOICES,
    MILITARY_UNIT_CHOICES,
    UserLoginForm,
    SystemSettingsForm,
    UserCreateForm,
    UserEditForm,
    AdminLoginForm,
)

from apps.trainees.forms import (
    OFFICER_RANKS,
    NCO_RANKS,
    CIVILIAN_TITLES,
    TraineeForm,
)

from apps.academic.forms import (
    InstructorForm,
    CourseForm,
    SubjectForm,
    CourseSessionForm,
    CourseCategoryForm,
)

from apps.documents.forms import (
    CertificateSettingsForm,
    MovementOrderSettingsForm,
)

__all__ = [
    'validate_and_clean_phone',
    'validate_and_clean_email',
    'OFFICER_RANKS',
    'NCO_RANKS',
    'CIVILIAN_TITLES',
    'MILITARY_RANK_CHOICES',
    'MILITARY_UNIT_CHOICES',
    'TraineeForm',
    'InstructorForm',
    'CourseForm',
    'SubjectForm',
    'CourseSessionForm',
    'UserLoginForm',
    'CourseCategoryForm',
    'CertificateSettingsForm',
    'MovementOrderSettingsForm',
    'SystemSettingsForm',
    'UserCreateForm',
    'UserEditForm',
    'AdminLoginForm',
]
