"""
إعادة تصدير نماذج البيانات (Models) من التطبيقات المصغرة المنظمة
لضمان التوافقية الكاملة للخلف وبقاء الجداول والمخططات وقاعدة البيانات سليمة 100%.
"""
from apps.core.models import (
    phone_10_digits_validator,
    Institute,
    SystemSettings,
    UserRole,
    UserProfile,
    create_or_update_user_profile,
    ActivityAction,
    ActivityCategory,
    ActivityLog,
    log_activity,
)

from apps.trainees.models import (
    numeric_only_validator,
    TraineeCategory,
    Trainee,
    TraineeRelative,
)

from apps.academic.models import (
    InstructorCategory,
    Instructor,
    CourseCategory,
    Course,
    Subject,
    SessionTargetGroup,
    CourseSession,
    SessionSubjectInstructor,
    CourseEnrollment,
    has_trainee_passed_course,
    TraineeSubjectGrade,
    DisciplineInfraction,
)

from apps.documents.models import (
    CertificateSettings,
    MovementOrderSettings,
)

__all__ = [
    'Institute',
    'phone_10_digits_validator',
    'numeric_only_validator',
    'SystemSettings',
    'UserRole',
    'UserProfile',
    'create_or_update_user_profile',
    'ActivityAction',
    'ActivityCategory',
    'ActivityLog',
    'log_activity',
    'TraineeCategory',
    'Trainee',
    'TraineeRelative',
    'InstructorCategory',
    'Instructor',
    'CourseCategory',
    'Course',
    'Subject',
    'SessionTargetGroup',
    'CourseSession',
    'SessionSubjectInstructor',
    'CourseEnrollment',
    'has_trainee_passed_course',
    'TraineeSubjectGrade',
    'DisciplineInfraction',
    'CertificateSettings',
    'MovementOrderSettings',
]
