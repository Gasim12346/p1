from django.contrib.auth.models import User
from django.db import transaction
from training.models import (
    Institute, SystemSettings, CertificateSettings, MovementOrderSettings,
    CourseCategory, Course, Subject, UserProfile, UserRole, ActivityLog,
    ActivityAction, ActivityCategory
)
from apps.core.permissions import (
    MODULES_PERMISSIONS_CATALOG,
    DEFAULT_ROLE_PERMISSIONS,
    get_default_permissions_for_role,
    get_user_permissions_matrix,
    has_permission,
    check_perm,
    is_super_admin_user,
    super_admin_required,
    is_admin_user,
    admin_access_required,
    is_registrar_user,
    is_supervisor_user,
    is_instructor_user,
    get_user_instructor,
    admin_required,
    registrar_required,
    check_institute_access,
    check_user_management_access,
)


@transaction.atomic
def initialize_new_institute(institute, admin_data=None, created_by_user=None):
    """
    تهيئة معهد / منشأة تدريبية جديدة بإنشاء إعدادات الهوية والشهادات
    وتضمين نماذج وتصنيفات الدورات القياسية الجاهزة، وإنشاء حساب مدير النظام (Admin).
    """
    # 1. إعدادات الهوية والشعار
    system_settings, _ = SystemSettings.objects.get_or_create(
        institute=institute,
        defaults={
            'system_name': f"نظام {institute.name}",
            'system_subheading': f"بوابة رصد النتائج والشهادات - {institute.parent_unit or institute.name}",
            'primary_navy': '#0f172a',
            'primary_accent': '#1e3a8a',
            'brand_blue': '#2563eb',
            'brand_cyan': '#0284c7',
            'gold_accent': '#d97706',
            'bg_light': '#f8fafc',
            'sidebar_bg_start': '#0b1329',
            'sidebar_bg_end': '#0f172a',
        }
    )

    # 2. إعدادات الشهادة الرسمية
    cert_settings, _ = CertificateSettings.objects.get_or_create(
        institute=institute,
        defaults={
            'bismillah_text': 'بسم الله الرحمن الرحيم',
            'header_line_1': institute.parent_unit or 'القوات المسلحة',
            'header_line_2': institute.name,
            'cert_title': 'شهــــــادة',
            'cert_title_color': '#FF0000',
            'basic_cert_title': 'شهادة دورة تدريبية',
            'default_certificate_note': 'أكمل الدورة بنجاح وبذل جهداً متميزاً أهله للحصول على هذا التقدير.',
            'right_signer_rank': 'رتبة المسؤول',
            'right_signer_name': 'اسم المسؤول الأيمن',
            'right_signer_title': 'قــــائد جنـــــاح التعليـــــم',
            'left_signer_rank': 'رتبة القائد',
            'left_signer_name': 'اسم قائد المعهد',
            'left_signer_title': f"قــــائد {institute.name}",
        }
    )

    # 3. إعدادات أمر التحرك
    movement_settings, _ = MovementOrderSettings.objects.get_or_create(
        institute=institute,
        defaults={
            'bismillah_text': 'بسم الله الرحمن الرحيم',
            'security_label': 'محظور',
            'order_title': 'أمر تــــحـــــرك',
            'issuing_authority_text': f"الصادر بأمر السيد قائد {institute.name}.",
            'from_location': institute.name,
            'to_location_default': 'شعبـة التدريب',
            'arms_default': 'لا يكـــــن',
            'ammunition_default': 'لا يكـــــن',
            'purpose_prefix': 'انتهاء ',
            'clothing_instructions': 'حسـب التعليمـات',
        }
    )

    # 4. نماذج وتصنيفات الدورات القياسية الجاهزة للمعهد
    # تصنيف 1: دورات الحاسوب وتقنية المعلومات
    cat_it, _ = CourseCategory.objects.get_or_create(
        institute=institute,
        name='دورات الحاسوب وتقنية المعلومات',
        defaults={'description': 'الدورات التدريبية المعتمدة في علوم الحاسب وتطبيقاته.'}
    )
    course_it1, _ = Course.objects.get_or_create(
        institute=institute,
        category=cat_it,
        name='دورة قيادة الحاسب الآلي الأساسية (ICDL)',
        defaults={
            'course_number': f"IT-001-{institute.id}",
            'attendance_max_grade': 10.00,
            'description': 'دورة مهارات وتطبيقات الحاسب الآلي الأساسية ونظم التشغيل والمكتب.'
        }
    )
    Subject.objects.get_or_create(
        course=course_it1,
        name='مقدمة الحاسوب ونظام التشغيل',
        defaults={'code': f"SUB-IT1-{course_it1.id}", 'credit_hours': 10, 'max_grade': 100.00}
    )
    Subject.objects.get_or_create(
        course=course_it1,
        name='معالجة النصوص (Word)',
        defaults={'code': f"SUB-IT2-{course_it1.id}", 'credit_hours': 15, 'max_grade': 100.00}
    )

    # تصنيف 2: الدورات الإدارية والقيادية
    cat_admin, _ = CourseCategory.objects.get_or_create(
        institute=institute,
        name='الدورات الإدارية والقيادية',
        defaults={'description': 'دورات الإدارة والتنظيم وأعمال السكرتارية والمكاتب.'}
    )
    course_admin1, _ = Course.objects.get_or_create(
        institute=institute,
        category=cat_admin,
        name='دورة الإدارة وأعمال المكاتب',
        defaults={
            'course_number': f"ADM-001-{institute.id}",
            'attendance_max_grade': 10.00,
            'description': 'دورة تأهيلية في مهارات العمل الإداري وتنظيم المكاتبات.'
        }
    )
    Subject.objects.get_or_create(
        course=course_admin1,
        name='أعمال السكرتارية والمراسلات',
        defaults={'code': f"SUB-ADM1-{course_admin1.id}", 'credit_hours': 12, 'max_grade': 100.00}
    )

    # تصنيف 3: الدورات التخصصية
    cat_spec, _ = CourseCategory.objects.get_or_create(
        institute=institute,
        name='الدورات التخصصية',
        defaults={'description': 'الدورات التأهيلية التخصصية الموجهة لمهام المعهد والوحدة.'}
    )

    # 5. إنشاء حساب مدير النظام (Admin) إذا تم تمرير بياناته
    admin_user = None
    if admin_data and admin_data.get('username') and admin_data.get('password'):
        username = admin_data['username'].strip()
        password = admin_data['password'].strip()
        full_name = admin_data.get('name', '').strip()
        rank = admin_data.get('rank', '').strip()
        military_number = admin_data.get('military_number', '').strip()
        phone = admin_data.get('phone', '').strip()

        admin_user = User.objects.filter(username=username).first()
        if not admin_user:
            admin_user = User.objects.create_user(
                username=username,
                password=password,
                first_name=full_name,
                is_staff=True
            )
        else:
            admin_user.set_password(password)
            admin_user.first_name = full_name
            admin_user.is_staff = True
            admin_user.save()

        profile, _ = UserProfile.objects.get_or_create(user=admin_user)
        profile.institute = institute
        profile.role = UserRole.ADMIN
        profile.rank = rank
        profile.military_number = military_number
        profile.phone = phone
        profile.can_manage_users = True
        profile.can_view = True
        profile.can_add = True
        profile.can_edit = True
        profile.can_delete = True
        profile.can_grade = True
        profile.can_approve_results = True
        profile.save()
        admin_user.profile = profile

    return {
        'system_settings': system_settings,
        'cert_settings': cert_settings,
        'movement_settings': movement_settings,
        'admin_user': admin_user
    }
