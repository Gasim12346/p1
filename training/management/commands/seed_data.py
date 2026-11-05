from django.core.management.base import BaseCommand
from datetime import date, timedelta
from training.models import (
    CourseCategory, Course, Subject, Trainee, TraineeCategory,
    CourseSession, CourseEnrollment, TraineeSubjectGrade
)

class Command(BaseCommand):
    help = 'إدخال بيانات تجريبية لنظام التدريب والدرجات'

    def handle(self, *args, **options):
        self.stdout.write('بدء إدخال البيانات التجريبية...')

        # 1. تصنيفات الدورات المحددة بالطلب
        cat_guide, _ = CourseCategory.objects.get_or_create(
            name='دورات مرشد',
            defaults={'description': 'الدورات التأسيسية والمتقدمة لإرشاد وتوجيه العمليات التدريبية'}
        )
        cat_special, _ = CourseCategory.objects.get_or_create(
            name='دورات خاصة',
            defaults={'description': 'الدورات التخصصية والمهام النوعية المتقدمة'}
        )
        cat_joint, _ = CourseCategory.objects.get_or_create(
            name='دورات مشتركة',
            defaults={'description': 'الدورات الميدانية والتدريبية المشتركة بين مختلف التشكيلات'}
        )

        # 2. نماذج من الدورات
        c1, _ = Course.objects.get_or_create(
            category=cat_guide,
            name='دورة مرشد متقدمة',
            defaults={
                'course_number': 'GUIDE-101',
                'description': 'دورة تأهيل المرشدين للقيادة والإشراف التكتيكي'
            }
        )
        c2, _ = Course.objects.get_or_create(
            category=cat_special,
            name='دورة أمن وحماية المنشآت الحيوية',
            defaults={
                'course_number': 'SPEC-204',
                'description': 'التدريب التخصصي على أنظمة الحماية والأمن الاستراتيجي'
            }
        )
        c3, _ = Course.objects.get_or_create(
            category=cat_joint,
            name='دورة القيادة والسيطرة المشتركة',
            defaults={
                'course_number': 'JOINT-305',
                'description': 'تنسيق العمليات الميدانية المشتركة وتوحيد الاتصالات'
            }
        )

        # 3. مواد الدورة c1
        subjects_data = [
            ('G101', 'ملاحة وتوجيه أرضي', 25, 100),
            ('G102', 'تكتيك وإشارة متقدمة', 30, 100),
            ('G103', 'إدارة العمليات التكتيكية', 20, 100),
        ]
        for code, name, hours, max_g in subjects_data:
            Subject.objects.get_or_create(
                course=c1,
                code=code,
                defaults={'name': name, 'credit_hours': hours, 'max_grade': max_g}
            )

        # 4. نماذج دارسين (ضباط، ضباط صف، مدنيين) - نمر أرقام فقط
        trainees_data = [
            # ضباط
            ('1001', TraineeCategory.OFFICER, 'مقدم', 'أحمد بن خالد التميمي', 'لواء التدريب المشترك', 'القوات البرية'),
            ('1002', TraineeCategory.OFFICER, 'رائد', 'عبدالعزيز صالح الغامدي', 'كتيبة الاستطلاع', 'قوات الدفاع الجوي'),
            ('1003', TraineeCategory.OFFICER, 'نقيب', 'محمد بن سلطان الحربي', 'سلاح الإشارة', 'القوات الجوية'),
            # ضباط صف
            ('2001', TraineeCategory.NCO, 'مساعد', 'فهد بن منصور العتيبي', 'معهد الدراسات الفنية', 'الحرس الوطني'),
            ('2002', TraineeCategory.NCO, 'رقيب أول', 'سعيد مبارك القحطاني', 'مركز القيادة والسيطرة', 'حرس الحدود'),
            ('2003', TraineeCategory.NCO, 'رقيب', 'عمر نايف الشمري', 'سلاح المهندسين', 'القوات البرية'),
            # مدنيين
            ('3001', TraineeCategory.CIVILIAN, 'أخصائي', 'م. طارق حمزة الدوسري', 'إدارة تقنية المعلومات والاتصالات', 'الوزارة'),
            ('3002', TraineeCategory.CIVILIAN, 'باحث', 'د. يوسف إبراهيم السبيعي', 'مركز الأبحاث والتطوير', 'هيئة التدريب'),
        ]

        created_trainees = []
        for num, cat, rank, name, unit, force in trainees_data:
            t, _ = Trainee.objects.get_or_create(
                military_number=num,
                defaults={
                    'category': cat,
                    'rank': rank,
                    'name': name,
                    'unit': unit,
                    'force': force
                }
            )
            created_trainees.append(t)

        # 5. انعقاد دورة تجريبية (الدورة التي يتم دراستها)
        session, _ = CourseSession.objects.get_or_create(
            course=c1,
            session_code='الدفعة 18 - 2026',
            defaults={
                'start_date': date.today() - timedelta(days=20),
                'end_date': date.today() + timedelta(days=10),
                'status': 'active',
                'attendance_max_grade': 20.0,
                'notes': 'انعقاد دورة مرشد متقدمة الدفعة 18 للعام التدريبي الحالي'
            }
        )

        # 6. تسجيل طلبة ورصد درجات نموذجية
        subs = list(c1.subjects.all())
        sample_scores = [
            (created_trainees[0], [92, 95, 88], 19.5), # ممتاز
            (created_trainees[1], [82, 78, 85], 18.0), # جيد جداً
            (created_trainees[2], [70, 72, 68], 16.0), # جيد
            (created_trainees[3], [58, 62, 55], 14.0), # مقبول
        ]

        for tr, marks, att in sample_scores:
            enrollment, _ = CourseEnrollment.objects.get_or_create(
                session=session,
                trainee=tr,
                defaults={
                    'current_rank': tr.rank,
                    'current_unit': tr.unit,
                    'attendance_score': att
                }
            )
            for idx, s in enumerate(subs):
                if idx < len(marks):
                    TraineeSubjectGrade.objects.update_or_create(
                        enrollment=enrollment,
                        subject=s,
                        defaults={'score': marks[idx]}
                    )
            enrollment.calculate_results()

        self.stdout.write(self.style.SUCCESS('تم إدخال البيانات التجريبية بنجاح!'))
