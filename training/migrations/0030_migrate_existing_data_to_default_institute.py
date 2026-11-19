from django.db import migrations


def migrate_to_default_institute(apps, schema_editor):
    Institute = apps.get_model('training', 'Institute')
    Trainee = apps.get_model('training', 'Trainee')
    Instructor = apps.get_model('training', 'Instructor')
    CourseCategory = apps.get_model('training', 'CourseCategory')
    Course = apps.get_model('training', 'Course')
    CourseSession = apps.get_model('training', 'CourseSession')
    SystemSettings = apps.get_model('training', 'SystemSettings')
    CertificateSettings = apps.get_model('training', 'CertificateSettings')
    MovementOrderSettings = apps.get_model('training', 'MovementOrderSettings')
    UserProfile = apps.get_model('training', 'UserProfile')
    ActivityLog = apps.get_model('training', 'ActivityLog')

    # إنشاء المعهد الافتراضي الأول للنظام القائم
    default_inst, created = Institute.objects.get_or_create(
        code='issi',
        defaults={
            'name': 'معهد نظم المعلومات والإحصاء',
            'parent_unit': 'إدارة نظم المعلومات والإحصاء',
            'is_active': True,
        }
    )

    if schema_editor.connection.vendor == 'postgresql':
        with schema_editor.connection.cursor() as cursor:
            cursor.execute("SELECT setval(pg_get_serial_sequence('training_institute', 'id'), COALESCE(max(id), 1)) FROM training_institute;")

    # ربط كافة السجلات الحالية بالمعهد الافتراضي
    Trainee.objects.filter(institute__isnull=True).update(institute=default_inst)
    Instructor.objects.filter(institute__isnull=True).update(institute=default_inst)
    CourseCategory.objects.filter(institute__isnull=True).update(institute=default_inst)
    Course.objects.filter(institute__isnull=True).update(institute=default_inst)
    CourseSession.objects.filter(institute__isnull=True).update(institute=default_inst)
    SystemSettings.objects.filter(institute__isnull=True).update(institute=default_inst)
    CertificateSettings.objects.filter(institute__isnull=True).update(institute=default_inst)
    MovementOrderSettings.objects.filter(institute__isnull=True).update(institute=default_inst)
    UserProfile.objects.filter(institute__isnull=True).update(institute=default_inst)
    ActivityLog.objects.filter(institute__isnull=True).update(institute=default_inst)

    # ترقية المستخدمين ذوي الصلاحيات العليا إلى سوبر أدمن
    UserProfile.objects.filter(user__is_superuser=True).update(role='super_admin')


def reverse_migration(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('training', '0029_institute_alter_course_course_number_and_more'),
    ]

    operations = [
        migrations.RunPython(migrate_to_default_institute, reverse_migration),
    ]
