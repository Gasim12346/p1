import io
import json
from datetime import date, timedelta
import openpyxl
from django.utils import timezone
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from training.models import (
    UserProfile, UserRole, CourseCategory, Course, Subject,
    CourseSession, Trainee, TraineeCategory, CourseEnrollment,
    TraineeSubjectGrade, Instructor, InstructorCategory, SessionSubjectInstructor,
    CertificateSettings, MovementOrderSettings
)
from training.reports import get_default_date_range, get_report_data, export_report_to_excel


class AuthenticationAndSecurityTests(TestCase):
    def setUp(self):
        self.client = Client()
        
        # 1. إنشاء حساب مدير نظام (أدمن)
        self.admin_user = User.objects.create_user(
            username='admin_test',
            password='Password123!',
            first_name='Admin',
            last_name='User',
            is_staff=True
        )
        self.admin_user.profile.role = UserRole.ADMIN
        self.admin_user.profile.save()

        # 2. إنشاء حساب مستخدم عادي
        self.regular_user = User.objects.create_user(
            username='user_test',
            password='Password123!',
            first_name='Regular',
            last_name='User',
            is_staff=False
        )
        self.regular_user.profile.role = UserRole.REGULAR
        self.regular_user.profile.save()

    def test_unauthenticated_user_redirected_to_login(self):
        """التحقق من حظر الوصول غير المصرح به لجميع الشاشات الرئيسية والتحويل لصفحة تسجيل الدخول"""
        protected_urls = [
            '/',
            '/trainees/',
            '/courses/',
            '/sessions/',
            '/results/',
            '/admin-portal/dashboard/',
        ]
        for url in protected_urls:
            response = self.client.get(url)
            self.assertEqual(
                response.status_code, 302,
                f"Page {url} did not redirect unauthenticated user."
            )
            self.assertIn('/login/', response.url)

    def test_login_page_is_completely_standalone(self):
        """التحقق من أن صفحة تسجيل الدخول مستقلة تماماً وخالية من السايدبار والنافبار وعناصر النظام الداخلي"""
        response = self.client.get(reverse('training:login'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        
        # لا يوجد سايدبار
        self.assertNotIn('app-sidebar', content)
        self.assertNotIn('sidebar-page-layout', content)
        self.assertNotIn('app-inner-topbar', content)
        
        # لا يوجد شريط تنقل علوي للنظام الداخلي
        self.assertNotIn('navbar-custom', content)
        self.assertNotIn('بوابات النظام الأساسية', content)
        
        # تحتوي على عناصر الدخول الأساسية
        self.assertIn('دخول إلى النظام', content)
        self.assertIn('name="username"', content)
        self.assertIn('name="password"', content)

    def test_admin_login_redirects_directly_to_admin_portal(self):
        """تسجيل دخول الأدمن يحوله مباشرة وبشكل منعزل إلى بوابة الأدمن المنفصلة"""
        response = self.client.post(reverse('training:login'), {
            'username': 'admin_test',
            'password': 'Password123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('training:admin_dashboard'))

        # الدخول إلى بوابة الأدمن بنجاح
        admin_page_response = self.client.get(reverse('training:admin_dashboard'))
        self.assertEqual(admin_page_response.status_code, 200)
        self.assertIn('لوحة القيادة والأدمن المنفصلة', admin_page_response.content.decode('utf-8'))

    def test_regular_user_login_redirects_to_home(self):
        """تسجيل دخول المستخدم العادي يحوله إلى الصفحة الرئيسية"""
        response = self.client.post(reverse('training:login'), {
            'username': 'user_test',
            'password': 'Password123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('training:home'))

        # الدخول إلى الصفحة الرئيسية بنجاح
        home_page_response = self.client.get(reverse('training:home'))
        self.assertEqual(home_page_response.status_code, 200)

    def test_regular_user_strictly_forbidden_from_admin_portal(self):
        """حظر المستخدم العادي بشكل صارم وتام من الدخول إلى بوابة الأدمن المنفصلة"""
        self.client.login(username='user_test', password='Password123!')
        response = self.client.get(reverse('training:admin_dashboard'))
        # يتم تحويله إلى الرئيسية
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('training:home'))

    def test_home_page_does_not_contain_admin_banner(self):
        """التحقق من إزالة أي بنر أو عناصر تحكم خاصة بالأدمن من الصفحة الرئيسية"""
        self.client.login(username='admin_test', password='Password123!')
        response = self.client.get(reverse('training:home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # التأكد من إزالة البنر المدموج
        self.assertNotIn('لوحة القيادة المنفصلة، إدارة المستخدمين', content)
        self.assertNotIn('دخول لوحة تحكم الأدمن المنفصلة', content)

    def test_home_page_contains_logout_button(self):
        """التحقق من وجود زر تسجيل الخروج في الصفحة الرئيسية للمستخدم"""
        self.client.login(username='user_test', password='Password123!')
        response = self.client.get(reverse('training:home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn(reverse('training:logout'), content)
        self.assertIn('تسجيل الخروج', content)

    def test_certificate_blocked_if_grades_incomplete(self):
        """التحقق من منع طباعة أو عرض الشهادة إذا كانت الدرجات غير مكتملة"""
        self.client.login(username='user_test', password='Password123!')
        
        # إنشاء دورة وانعقاد ودارس
        from training.models import CourseCategory, Course, CourseSession, Trainee, CourseEnrollment, Subject
        import datetime

        cat = CourseCategory.objects.create(name='تصنيف اختباري')
        course = Course.objects.create(name='دورة اختبارية', category=cat)
        Subject.objects.create(course=course, name='مادة 1', max_grade=100)
        
        trainee = Trainee.objects.create(
            military_number='9999',
            name='دارس اختبار',
            unit='سلاح الإشارة'
        )
        session = CourseSession.objects.create(
            course=course,
            session_code='BATCH-99',
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 2, 1)
        )
        enrollment = CourseEnrollment.objects.create(
            session=session,
            trainee=trainee,
            current_rank='ملازم',
            current_unit='سلاح الإشارة',
            is_graded=False
        )

        response = self.client.get(reverse('training:certificate', kwargs={'enrollment_id': enrollment.id}))
        # يجب أن يحظر الشهادة ويعيد التوجيه لصفحة الرصد
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('training:results_entry', kwargs={'session_id': session.id}))

    def test_results_center_gregorian_year_filter(self):
        """التحقق من عمل فلتر السنة الميلادية في مركز النتائج والسجل التاريخي"""
        self.client.login(username='user_test', password='Password123!')
        from training.models import CourseCategory, Course, CourseSession, Trainee, CourseEnrollment
        import datetime

        cat = CourseCategory.objects.create(name='تصنيف فحص السنوات')
        course = Course.objects.create(name='دورة تحليل البيانات', category=cat)
        
        session_2024 = CourseSession.objects.create(
            course=course,
            session_code='BATCH-2024',
            start_date=datetime.date(2024, 3, 1),
            end_date=datetime.date(2024, 4, 1)
        )
        session_2025 = CourseSession.objects.create(
            course=course,
            session_code='BATCH-2025',
            start_date=datetime.date(2025, 5, 1),
            end_date=datetime.date(2025, 6, 1)
        )

        trainee = Trainee.objects.create(
            military_number='8888',
            name='دارس السنوات',
            unit='سلاح المدرعات'
        )
        CourseEnrollment.objects.create(
            session=session_2024,
            trainee=trainee,
            current_rank='نقيب',
            current_unit='سلاح المدرعات',
            is_graded=True,
            percentage=90.0,
            grade_label='ممتاز'
        )

        # 1. فحص فلترة الدورات حسب سنة 2024
        res_2024 = self.client.get(reverse('training:results_center'), {'tab': 'sessions', 'session_year': '2024'})
        self.assertEqual(res_2024.status_code, 200)
        self.assertIn(session_2024, res_2024.context['sessions'])
        self.assertNotIn(session_2025, res_2024.context['sessions'])

        # 2. فحص فلترة السجل التاريخي حسب سنة 2024
        res_arch_2024 = self.client.get(reverse('training:results_center'), {'tab': 'archive', 'year': '2024'})
        self.assertEqual(res_arch_2024.status_code, 200)
        self.assertEqual(len(res_arch_2024.context['historical_enrollments']), 1)

        # 3. فحص فلترة السجل التاريخي حسب سنة 2025 (لا يوجد فيها نتائج مرصودة)
        res_arch_2025 = self.client.get(reverse('training:results_center'), {'tab': 'archive', 'year': '2025'})
        self.assertEqual(res_arch_2025.status_code, 200)
        self.assertEqual(len(res_arch_2025.context['historical_enrollments']), 0)

    def test_results_center_archive_courses_and_students_view(self):
        """التحقق من عرض الدورات في تبويب السجل التاريخي والوصول لطلبة ونتائج الدورة"""
        self.client.login(username='user_test', password='Password123!')
        from training.models import CourseCategory, Course, CourseSession, Trainee, CourseEnrollment

        cat = CourseCategory.objects.create(name="تصنيف أرشيف تجريبي")
        course = Course.objects.create(name="دورة اختبار السجل التاريخي", category=cat)
        session = CourseSession.objects.create(
            course=course,
            session_code="دفعة-سجل-01",
            start_date="2026-01-01",
            end_date="2026-01-20",
            status="completed"
        )
        trainee = Trainee.objects.create(
            name="دارس أرشيف تجريبي",
            military_number="99887766",
            category="officer",
            unit="جناح الأرشيف",
            force="القوات البرية"
        )
        CourseEnrollment.objects.create(
            session=session,
            trainee=trainee,
            current_rank="نقيب",
            current_unit="جناح الأرشيف",
            is_graded=True,
            total_score=95,
            percentage=95.0,
            grade_label="ممتاز (أ)"
        )

        # 1. فتح تبويب السجل التاريخي والتأكد من ظهور الدورات في archive_sessions
        res_arch = self.client.get(reverse('training:results_center'), {'tab': 'archive'})
        self.assertEqual(res_arch.status_code, 200)
        self.assertIn('archive_sessions', res_arch.context)
        self.assertIn(session, res_arch.context['archive_sessions'])
        self.assertContains(res_arch, "دورة اختبار السجل التاريخي")
        self.assertContains(res_arch, "دفعة-سجل-01")

        # 2. فحص الدخول لصفحة رصد ونتائج الدورة مع معامل from=archive
        res_entry = self.client.get(reverse('training:results_entry', kwargs={'session_id': session.id}), {'from': 'archive'})
        self.assertEqual(res_entry.status_code, 200)
        self.assertContains(res_entry, "العودة إلى السجل التاريخي")
        self.assertContains(res_entry, "دارس أرشيف تجريبي")
        self.assertContains(res_entry, "99887766")

        # 3. فحص عرض الدورة مباشرة داخل السجل التاريخي عبر session_id
        res_inline = self.client.get(reverse('training:results_center'), {'tab': 'archive', 'session_id': session.id})
        self.assertEqual(res_inline.status_code, 200)
        self.assertEqual(res_inline.context['selected_archive_session'], session)
        self.assertContains(res_inline, "العودة إلى قائمة الدورات في السجل التاريخي")
        self.assertContains(res_inline, "دارس أرشيف تجريبي")

    def test_login_open_redirect_protection(self):
        """التحقق من حظر التوجيه المفتوح Open Redirect ومنع التوجيه لروابط خارجية خبيثة"""
        # 1. محاولة تسجيل دخول بتوجيه خارجي احتيالي //evil.com
        res_evil = self.client.post(f"{reverse('training:login')}?next=//evil.com", {
            'username': 'user_test',
            'password': 'Password123!',
        })
        self.assertEqual(res_evil.status_code, 302)
        # يجب عدم التوجيه لـ evil.com والتوجيه للرئيسية بأمان
        self.assertRedirects(res_evil, reverse('training:home'))

        # 2. تسجيل خروج والمحاولة برابط داخلي سليم /results/
        self.client.logout()
        res_safe = self.client.post(f"{reverse('training:login')}?next=/results/", {
            'username': 'user_test',
            'password': 'Password123!',
        })
        self.assertEqual(res_safe.status_code, 302)
        self.assertRedirects(res_safe, '/results/')

    def test_user_toggle_active_requires_post(self):
        """التحقق من رفض طلبات GET لمنع ثغرة CSRF وحصر تعديل حالة الحساب على POST"""
        self.client.login(username='admin_test', password='Password123!')
        target = User.objects.get(username='user_test')
        self.assertTrue(target.is_active)

        # 1. طلب GET يجب أن يتم رفضه ولا يعدل حالة الحساب
        get_res = self.client.get(reverse('training:user_toggle_active', kwargs={'user_id': target.id}))
        self.assertEqual(get_res.status_code, 302)
        target.refresh_from_db()
        self.assertTrue(target.is_active, 'يجب ألا يتم تعديل حالة المستخدم عبر طلب GET')

        # 2. طلب POST آمن يقوم بتعطيل الحساب
        post_res = self.client.post(reverse('training:user_toggle_active', kwargs={'user_id': target.id}))
        self.assertEqual(post_res.status_code, 302)
        target.refresh_from_db()
        self.assertFalse(target.is_active, 'يجب أن يتم تعديل حالة المستخدم عبر طلب POST بنجاح')

    def test_results_entry_rejects_negative_or_exceeding_grades(self):
        """التحقق من رفض الدرجات السالبة والدرجات التي تتجاوز الحد الأقصى للمادة أو المواظبة"""
        self.client.login(username='admin_test', password='Password123!')
        from training.models import CourseCategory, Course, CourseSession, Trainee, CourseEnrollment, Subject, TraineeSubjectGrade
        import datetime

        cat = CourseCategory.objects.create(name='تصنيف فحص الدرجات')
        course = Course.objects.create(name='دورة أمن المعلومات', category=cat)
        sub1 = Subject.objects.create(course=course, name='التشفير', max_grade=50.00)
        
        session = CourseSession.objects.create(
            course=course,
            session_code='BATCH-SEC-01',
            start_date=datetime.date(2026, 7, 1),
            end_date=datetime.date(2026, 8, 1),
            attendance_max_grade=20.00
        )
        trainee = Trainee.objects.create(
            military_number='777711',
            name='دارس فحص الحدود',
            unit='سلاح الإشارة'
        )
        en = CourseEnrollment.objects.create(
            session=session,
            trainee=trainee,
            current_rank='نقيب',
            current_unit='سلاح الإشارة'
        )

        url = reverse('training:results_entry', kwargs={'session_id': session.id})

        # 1. محاولة إدخال درجة مادة تتجاوز الحد الأقصى (75 من 50)
        res_exceed = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub1.id}': '75.0',
            f'att_{trainee.military_number}': '15.0',
        })
        self.assertEqual(res_exceed.status_code, 200)
        en.refresh_from_db()
        self.assertFalse(en.is_graded, 'يجب ألا يتم اعتماد الرصد عند تجاوز الدرجة العظمى')
        self.assertEqual(TraineeSubjectGrade.objects.filter(enrollment=en).count(), 0)

        # 2. محاولة إدخال درجة مادة سالبة (-10)
        res_neg = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub1.id}': '-10.0',
            f'att_{trainee.military_number}': '15.0',
        })
        self.assertEqual(res_neg.status_code, 200)
        en.refresh_from_db()
        self.assertFalse(en.is_graded, 'يجب ألا يتم اعتماد الرصد عند إدخال درجة سالبة')

        # 3. محاولة إدخال مواظبة تتجاوز الحد الأقصى (30 من 20)
        res_att = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub1.id}': '40.0',
            f'att_{trainee.military_number}': '30.0',
        })
        self.assertEqual(res_att.status_code, 200)
        en.refresh_from_db()
        self.assertFalse(en.is_graded)

        # 4. إدخال درجات نظامية صحيحة (40 من 50 و مواظبة 18 من 20)
        res_valid = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub1.id}': '40.0',
            f'att_{trainee.military_number}': '18.0',
        })
        self.assertEqual(res_valid.status_code, 302)
        en.refresh_from_db()
        self.assertTrue(en.is_graded, 'يجب اعتماد الرصد بنجاح للدرجات الصحيحة')
        self.assertEqual(float(en.attendance_score), 18.0)
        self.assertEqual(float(en.total_score), 58.0)

    def test_regular_user_blocked_from_deletions(self):
        """التحقق من حظر المستخدم العادي تماماً من حذف الدارسين والدورات والمواد والانعقادات"""
        self.client.login(username='user_test', password='Password123!')
        from training.models import CourseCategory, Course, Subject, CourseSession, Trainee
        import datetime

        cat = CourseCategory.objects.create(name='تصنيف اختبار الصلاحيات')
        course = Course.objects.create(name='دورة صلاحيات', category=cat)
        sub = Subject.objects.create(course=course, name='مادة صلاحيات', max_grade=50)
        session = CourseSession.objects.create(
            course=course,
            session_code='BATCH-PERM',
            start_date=datetime.date(2026, 9, 1),
            end_date=datetime.date(2026, 10, 1)
        )
        trainee = Trainee.objects.create(
            military_number='12345678',
            name='دارس الصلاحيات',
            unit='الجوية'
        )

        # 1. محاولة حذف دارس بواسطة مستخدم عادي
        res_t = self.client.post(reverse('training:trainee_delete', kwargs={'military_number': trainee.military_number}))
        self.assertEqual(res_t.status_code, 302)
        self.assertTrue(Trainee.objects.filter(military_number=trainee.military_number).exists(), 'لا يجب حذف الدارس بواسطة مستخدم عادي')

        # 2. محاولة حذف دورة بواسطة مستخدم عادي
        res_c = self.client.post(reverse('training:course_delete', kwargs={'course_id': course.id}))
        self.assertEqual(res_c.status_code, 302)
        self.assertTrue(Course.objects.filter(pk=course.id).exists(), 'لا يجب حذف الدورة بواسطة مستخدم عادي')

        # 3. محاولة حذف مادة بواسطة مستخدم عادي
        res_s = self.client.post(reverse('training:subject_delete', kwargs={'subject_id': sub.id}))
        self.assertEqual(res_s.status_code, 302)
        self.assertTrue(Subject.objects.filter(pk=sub.id).exists(), 'لا يجب حذف المادة بواسطة مستخدم عادي')

        # 4. محاولة حذف انعقاد بواسطة مستخدم عادي
        res_sess = self.client.post(reverse('training:course_session_delete', kwargs={'session_id': session.id}))
        self.assertEqual(res_sess.status_code, 302)
        self.assertTrue(CourseSession.objects.filter(pk=session.id).exists(), 'لا يجب حذف الانعقاد بواسطة مستخدم عادي')

    def test_regular_user_blocked_from_editing_completed_session_grades(self):
        """التحقق من حظر المستخدم العادي من تعديل نتائج دورة مكتملة ومعتمدة"""
        from training.models import CourseCategory, Course, Subject, CourseSession, Trainee, CourseEnrollment
        import datetime

        cat = CourseCategory.objects.create(name='تصنيف معتمد')
        course = Course.objects.create(name='دورة معتمدة نهائياً', category=cat)
        sub = Subject.objects.create(course=course, name='مادة معتمدة', max_grade=100)
        session = CourseSession.objects.create(
            course=course,
            session_code='BATCH-DONE',
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 2, 1),
            status='completed'
        )
        trainee = Trainee.objects.create(
            military_number='9990001',
            name='دارس معتمد',
            unit='البحرية'
        )
        en = CourseEnrollment.objects.create(
            session=session,
            trainee=trainee,
            current_rank='نقيب',
            current_unit='البحرية',
            is_graded=True,
            total_score=95.0,
            percentage=95.0,
            grade_label='ممتاز'
        )

        # محاولة تعديل الدرجة بواسطة مستخدم عادي
        self.client.login(username='user_test', password='Password123!')
        url = reverse('training:results_entry', kwargs={'session_id': session.id})
        res = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub.id}': '60.0',
            f'att_{trainee.military_number}': '10.0',
        })
        self.assertEqual(res.status_code, 302)
        en.refresh_from_db()
        self.assertEqual(float(en.total_score), 95.0, 'لا يجب تغيير الدرجة في دورة معتمدة من قبل مستخدم عادي')


class InstructorManagementAndCourseSessionTests(TestCase):
    def setUp(self):
        self.client = Client()

        # Admin user
        self.admin_user = User.objects.create_user(
            username='admin_inst',
            password='Password123!',
            is_staff=True
        )
        self.admin_user.profile.role = UserRole.ADMIN
        self.admin_user.profile.save()

        # Regular user
        self.regular_user = User.objects.create_user(
            username='user_inst',
            password='Password123!'
        )
        self.regular_user.profile.role = UserRole.REGULAR
        self.regular_user.profile.save()

        # Category and Course
        from training.models import Instructor, CourseCategory, Course, Subject, CourseSession, SessionSubjectInstructor, Trainee

        self.cat = CourseCategory.objects.create(name='دورات مرشد')
        self.course = Course.objects.create(
            name='دورة أمن المعلومات',
            course_number='SEC-101',
            category=self.cat
        )
        self.subject1 = Subject.objects.create(
            course=self.course,
            name='الأمن السيبراني',
            code='CS-01',
            credit_hours=3,
            max_grade=100
        )
        self.subject2 = Subject.objects.create(
            course=self.course,
            name='التشفير والشبكات',
            code='CS-02',
            credit_hours=2,
            max_grade=100
        )

        # Instructors
        self.instructor1 = Instructor.objects.create(
            military_number='112233',
            name='د. أحمد عبد الله',
            rank='عقيد',
            phone='0123456789',
            is_active=True
        )
        self.instructor2 = Instructor.objects.create(
            military_number='445566',
            name='أ. سامي عثمان',
            rank='مقدم',
            phone='0987654321',
            is_active=True
        )

        # Trainee
        self.trainee = Trainee.objects.create(
            military_number='55667788',
            name='علي محمد خالد',
            category='officer',
            force='القوات البرية',
            unit='سلاح الإشارة'
        )

    def test_instructor_creation_and_primary_key(self):
        """التحقق من أن النمرة العسكرية هي المفتاح الأساسي للمعلم وتتطابق مع أرقام فقط"""
        from training.models import Instructor
        inst = Instructor.objects.get(military_number='112233')
        self.assertEqual(inst.pk, '112233')
        self.assertEqual(inst.name, 'د. أحمد عبد الله')
        self.assertEqual(inst.rank, 'عقيد')
        self.assertTrue(inst.is_active)

    def test_admin_portal_instructor_crud(self):
        """التحقق من إضافة وتعديل وحذف المعلمين مع التصنيف والقوة والوحدة عبر لوحة الأدمن"""
        self.client.login(username='admin_inst', password='Password123!')

        # 1. إضافة معلم جديد
        create_url = reverse('training:instructor_create')
        res = self.client.post(create_url, {
            'military_number': '778899',
            'category': 'officer',
            'rank': 'رائد',
            'name': 'خالد إبراهيم حسن',
            'force': 'القوات البرية',
            'unit': 'سلاح الإشارة',
            'phone': '0111223344',
            'is_active': 'on'
        })
        self.assertEqual(res.status_code, 302)
        from training.models import Instructor
        inst = Instructor.objects.filter(military_number='778899').first()
        self.assertIsNotNone(inst)
        self.assertEqual(inst.category, 'officer')
        self.assertEqual(inst.force, 'القوات البرية')
        self.assertEqual(inst.unit, 'سلاح الإشارة')

        # 2. تعديل المعلم
        edit_url = reverse('training:instructor_edit', kwargs={'military_number': '778899'})
        res = self.client.post(edit_url, {
            'military_number': '778899',
            'category': 'officer',
            'rank': 'مقدم',
            'name': 'خالد إبراهيم حسن المعدل',
            'force': 'القوات الجوية',
            'unit': 'جناح المقاتلات',
            'phone': '0111223355',
            'is_active': 'on'
        })
        self.assertEqual(res.status_code, 302)
        inst.refresh_from_db()
        self.assertEqual(inst.rank, 'مقدم')
        self.assertEqual(inst.name, 'خالد إبراهيم حسن المعدل')
        self.assertEqual(inst.force, 'القوات الجوية')
        self.assertEqual(inst.unit, 'جناح المقاتلات')

        # 3. حذف المعلم
        del_url = reverse('training:instructor_delete', kwargs={'military_number': '778899'})
        res = self.client.post(del_url)
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Instructor.objects.filter(military_number='778899').exists())

    def test_regular_user_cannot_manage_instructors(self):
        """المستخدم العادي محظور من إضافة أو تعديل أو حذف المعلمين ويتم تحويله للرئيسية"""
        self.client.login(username='user_inst', password='Password123!')
        res = self.client.post(reverse('training:instructor_create'), {
            'military_number': '999888',
            'rank': 'نقيب',
            'name': 'محاولة غير مصرح بها',
        })
        self.assertEqual(res.status_code, 302)
        self.assertRedirects(res, reverse('training:home'))

    def test_course_session_creation_with_supervisor_and_subject_instructors(self):
        """التحقق من إنشاء دورة وتعيين مشرف الدورة ومعلمي المواد الدراسية"""
        self.client.login(username='admin_inst', password='Password123!')
        url = reverse('training:course_session_create')

        # التحقق من تحميل صفحة الإنشاء وتوفر المعلمين ومواد الدورة بصيغة JSON
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)
        self.assertIn('instructors', get_res.context)
        self.assertIn('courses_subjects_json', get_res.context)
        self.assertTrue(len(get_res.context['instructors']) > 0)
        self.assertIn(self.instructor1.military_number, get_res.content.decode('utf-8'))
        self.assertIn(self.instructor1.name, get_res.content.decode('utf-8'))

        from django.core.files.uploadedfile import SimpleUploadedFile
        fake_scan = SimpleUploadedFile("movement_order.png", b"file_content", content_type="image/png")

        post_data = {
            'category': str(self.cat.id),
            'course': str(self.course.id),
            'session_code': 'الدفعة التجريبية 2026',
            'start_date': '2026-05-01',
            'end_date': '2026-07-01',
            'status': 'active',
            'attendance_max_grade': '20.0',
            'supervisor': self.instructor1.military_number,
            f'subject_teacher_{self.subject1.id}': self.instructor1.military_number,
            f'subject_teacher_{self.subject2.id}': self.instructor2.military_number,
            'selected_trainees': [self.trainee.military_number],
            f'rank_{self.trainee.military_number}': 'ملازم أول',
            f'force_{self.trainee.military_number}': 'القوات البرية',
            f'unit_{self.trainee.military_number}': 'سلاح الإشارة',
            f'movement_order_date_{self.trainee.military_number}': '2026-04-25',
            f'movement_order_file_{self.trainee.military_number}': fake_scan,
        }

        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        from training.models import CourseSession, SessionSubjectInstructor
        session = CourseSession.objects.filter(session_code='الدفعة التجريبية 2026').first()
        self.assertIsNotNone(session)
        self.assertEqual(session.supervisor, self.instructor1)

        # التحقق من مواد الدورة وتعيين المعلمين
        assign1 = SessionSubjectInstructor.objects.filter(session=session, subject=self.subject1).first()
        self.assertIsNotNone(assign1)
        self.assertEqual(assign1.instructor, self.instructor1)

        assign2 = SessionSubjectInstructor.objects.filter(session=session, subject=self.subject2).first()
        self.assertIsNotNone(assign2)
        self.assertEqual(assign2.instructor, self.instructor2)

        # التحقق من تسجيل الطالب وحفظ بيانات أمر التحرك الخاص به
        enrollment = session.enrollments.filter(trainee=self.trainee).first()
        self.assertIsNotNone(enrollment)
        self.assertEqual(enrollment.current_rank, 'ملازم أول')
        self.assertEqual(str(enrollment.movement_order_date), '2026-04-25')
        self.assertTrue(bool(enrollment.movement_order_file))

    def test_course_session_creation_requires_movement_order_date_and_file(self):
        """التحقق من إلزامية تاريخ وصورة أمر التحرك لكل دارس ومنع حفظ الدورة بدونهما"""
        self.client.login(username='admin_inst', password='Password123!')
        url = reverse('training:course_session_create')
        from django.core.files.uploadedfile import SimpleUploadedFile
        from training.models import CourseSession

        t_num = self.trainee.military_number
        base_data = {
            'category': str(self.cat.id),
            'course': str(self.course.id),
            'session_code': 'دفعة فحص القيود',
            'start_date': '2026-06-01',
            'end_date': '2026-08-01',
            'status': 'active',
            'selected_trainees': [t_num],
        }

        # 1. إرسال بدون تاريخ أمر التحرك للدارس
        data_no_date = dict(base_data)
        data_no_date[f'movement_order_file_{t_num}'] = SimpleUploadedFile("scan.pdf", b"pdf_data", content_type="application/pdf")
        res1 = self.client.post(url, data_no_date)
        self.assertEqual(res1.status_code, 200)
        self.assertFalse(CourseSession.objects.filter(session_code='دفعة فحص القيود').exists())

        # 2. إرسال بدون صورة أمر التحرك للدارس
        data_no_file = dict(base_data)
        data_no_file[f'movement_order_date_{t_num}'] = '2026-05-20'
        res2 = self.client.post(url, data_no_file)
        self.assertEqual(res2.status_code, 200)
        self.assertFalse(CourseSession.objects.filter(session_code='دفعة فحص القيود').exists())

        # 3. إرسال مع كلا الحقلين ينجح في حفظ الدورة وحفظ أمر التحرك على سجل الدارس
        data_valid = dict(base_data)
        data_valid[f'movement_order_date_{t_num}'] = '2026-05-20'
        data_valid[f'movement_order_file_{t_num}'] = SimpleUploadedFile("scan.pdf", b"pdf_data", content_type="application/pdf")
        res3 = self.client.post(url, data_valid)
        self.assertEqual(res3.status_code, 302)
        created_session = CourseSession.objects.filter(session_code='دفعة فحص القيود').first()
        self.assertIsNotNone(created_session)
        created_enrollment = created_session.enrollments.filter(trainee=self.trainee).first()
        self.assertIsNotNone(created_enrollment)
        self.assertEqual(str(created_enrollment.movement_order_date), '2026-05-20')
        self.assertTrue(bool(created_enrollment.movement_order_file))

    def test_course_session_manage_update_teachers(self):
        """التحقق من تحديث مشرف الدورة ومعلمي المواد من صفحة إدارة الدورة"""
        self.client.login(username='admin_inst', password='Password123!')
        from training.models import CourseSession, SessionSubjectInstructor
        session = CourseSession.objects.create(
            course=self.course,
            session_code='دفعة التعديل',
            start_date='2026-01-01',
            end_date='2026-03-01',
            status='active'
        )

        manage_url = reverse('training:course_session_manage', kwargs={'session_id': session.id})
        res = self.client.post(manage_url, {
            'update_session_teachers': '1',
            'supervisor': self.instructor2.military_number,
            f'subject_teacher_{self.subject1.id}': self.instructor2.military_number,
            f'subject_teacher_{self.subject2.id}': self.instructor1.military_number,
        })
        self.assertEqual(res.status_code, 302)

        session.refresh_from_db()
        self.assertEqual(session.supervisor, self.instructor2)

        assign1 = SessionSubjectInstructor.objects.get(session=session, subject=self.subject1)
        self.assertEqual(assign1.instructor, self.instructor2)

        assign2 = SessionSubjectInstructor.objects.get(session=session, subject=self.subject2)
        self.assertEqual(assign2.instructor, self.instructor1)

    def test_course_session_manage_update_movement_order(self):
        """التحقق من تحديث تاريخ وصورة أمر التحرك للدارس من قائمة الدارسين وتعديل الرتب والوحدات"""
        self.client.login(username='admin_inst', password='Password123!')
        from training.models import CourseSession, CourseEnrollment
        from django.core.files.uploadedfile import SimpleUploadedFile
        session = CourseSession.objects.create(
            course=self.course,
            session_code='دفعة أمر التحرك',
            start_date='2026-01-01',
            end_date='2026-03-01',
            status='active'
        )
        enrollment = CourseEnrollment.objects.create(
            session=session,
            trainee=self.trainee,
            current_rank='ملازم',
            current_force=self.trainee.force,
            current_unit=self.trainee.unit
        )
        manage_url = reverse('training:course_session_manage', kwargs={'session_id': session.id})
        t_num = self.trainee.military_number
        fake_file = SimpleUploadedFile("updated_order.pdf", b"pdf_data", content_type="application/pdf")
        res = self.client.post(manage_url, {
            'update_enrollments': '1',
            f'rank_{t_num}': 'ملازم أول',
            f'force_{t_num}': 'القوات البرية',
            f'unit_{t_num}': 'اللواء الأول',
            f'movement_order_date_{t_num}': '2026-01-05',
            f'movement_order_file_{t_num}': fake_file,
        })
        self.assertEqual(res.status_code, 302)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.current_rank, 'ملازم أول')
        self.assertEqual(str(enrollment.movement_order_date), '2026-01-05')
        self.assertTrue(bool(enrollment.movement_order_file))

    def test_register_and_enroll_new_trainee_from_session_manage(self):
        """التحقق من تسجيل دارس جديد في قاعدة البيانات وإلحاقه فوراً بالدورة التدريبية"""
        self.client.login(username='admin_inst', password='Password123!')
        from training.models import CourseSession, CourseEnrollment, Trainee
        session = CourseSession.objects.create(
            course=self.course,
            session_code='دفعة تجربة التسجيل',
            start_date='2026-02-01',
            end_date='2026-04-01',
            status='active'
        )
        manage_url = reverse('training:course_session_manage', kwargs={'session_id': session.id})
        new_num = '99887766'
        res = self.client.post(manage_url, {
            'register_and_enroll_new_trainee': '1',
            'military_number': new_num,
            'category': 'officer',
            'name': 'الدارس الجديد التجريبي',
            'batch': '50',
            'phone': '0912345678',
            'residence_state': 'الخرطوم',
            'residence_city': 'أم درمان',
            'residence_neighborhood': 'الملازمين',
            'residence_block': 'مربع 1',
            'residence_house_number': '12',
            'relative_1_name': 'محمد التجريبي',
            'relative_1_kinship': 'والد',
            'relative_1_phone': '0999999999',
            'relative_1_address': 'أم درمان',
            'new_rank': 'نقيب',
            'new_force': 'القوات البرية',
            'new_unit': 'سلاح الإشارة',
            'new_movement_order_date': '2026-02-02',
            'enroll_in_session': '1'
        })
        self.assertEqual(res.status_code, 302)
        # التحقق من حفظ الدارس بقاعدة البيانات
        trainee = Trainee.objects.filter(military_number=new_num).first()
        self.assertIsNotNone(trainee)
        self.assertEqual(trainee.name, 'الدارس الجديد التجريبي')
        self.assertEqual(trainee.batch, 50)
        self.assertEqual(trainee.residence_state, 'الخرطوم')
        self.assertEqual(trainee.residence_city, 'أم درمان')
        self.assertEqual(trainee.relatives.count(), 1)
        # التحقق من إلحاقه بالدورة
        enrollment = CourseEnrollment.objects.filter(session=session, trainee=trainee).first()
        self.assertIsNotNone(enrollment)
        self.assertEqual(enrollment.current_rank, 'نقيب')
        self.assertEqual(enrollment.current_force, 'القوات البرية')
        self.assertEqual(enrollment.current_unit, 'سلاح الإشارة')
        self.assertEqual(str(enrollment.movement_order_date), '2026-02-02')


class BusinessConstraintsTests(TestCase):
    """
    اختبارات القيود الصارمة:
    1. منع تسجيل الطالب في نفس الدورة إذا كان قد أكملها ونجح فيها مسبقاً.
    2. منع تكرار النمرة العسكرية بين الدارسين والمعلمين في الاتجاهين.
    3. منع تكرار رقم الدورة ورقم/كود المادة.
    4. توليد كود المادة ورقمها تلقائياً من النظام وإمكانية الحفظ دون إدخال كود يدوي.
    """
    def setUp(self):
        self.client = Client()
        self.admin_user = User.objects.create_user(
            username='admin_constraints',
            password='Password123!',
            is_staff=True
        )
        self.admin_user.profile.role = UserRole.ADMIN
        self.admin_user.profile.save()

        from training.models import CourseCategory, Course, Subject, Trainee, Instructor
        self.category = CourseCategory.objects.create(name='تصنيف القيود')
        self.course = Course.objects.create(
            category=self.category,
            course_number='C-CNST-100',
            name='دورة القيود المتقدمة'
        )
        self.subject = Subject.objects.create(
            course=self.course,
            name='مادة القيود الأولى',
            credit_hours=10,
            max_grade=100.0
        )
        self.trainee = Trainee.objects.create(
            military_number='11223344',
            name='دارس تجربة القيود',
            category='officer',
            force='القوات البرية',
            unit='سلاح الإشارة'
        )

    def test_passed_trainee_cannot_re_enroll_same_course(self):
        """التحقق من منع تسجيل الدارس في نفس الدورة إذا اجتازها بنجاح مسبقاً"""
        from training.models import CourseSession, CourseEnrollment, has_trainee_passed_course
        # الدفعة الأولى: إكمال ونجاح الدارس
        session1 = CourseSession.objects.create(
            course=self.course,
            session_code='دفعة 1 سابقة',
            start_date='2026-01-01',
            end_date='2026-02-01',
            status='completed'
        )
        enrollment1 = CourseEnrollment.objects.create(
            session=session1,
            trainee=self.trainee,
            current_rank='نقيب',
            current_force='القوات البرية',
            current_unit='سلاح الإشارة',
            percentage=85.0,
            grade_label='جيد جداً',
            is_graded=True
        )

        # التحقق البرمجي المباشر من دالة التحقق
        passed = has_trainee_passed_course(self.trainee, self.course)
        self.assertIsNotNone(passed)
        self.assertEqual(passed.id, enrollment1.id)

        # محاولة إنشاء دورة جديدة وتسجيل نفس الدارس فيها عبر POST
        self.client.login(username='admin_constraints', password='Password123!')
        create_url = reverse('training:course_session_create')
        res = self.client.post(create_url, {
            'category': str(self.category.id),
            'course': str(self.course.id),
            'session_code': 'دفعة 2 جديدة',
            'start_date': '2026-03-01',
            'end_date': '2026-04-01',
            'status': 'active',
            'attendance_max_grade': '20.0',
            'selected_trainees': [self.trainee.military_number],
            f'rank_{self.trainee.military_number}': 'رائد',
            f'force_{self.trainee.military_number}': 'القوات البرية',
            f'unit_{self.trainee.military_number}': 'سلاح الإشارة',
        })
        # يجب ألا يتم إنشاء الدورة بالدارس المحظور بل إعادة تحميل الصفحة مع رسالة خطأ
        session2 = CourseSession.objects.filter(session_code='دفعة 2 جديدة').first()
        self.assertIsNone(session2)

        # محاولة إضافة الدارس عبر صفحة إدارة دورة منعقدة أخرى لنفس المادة
        session3 = CourseSession.objects.create(
            course=self.course,
            session_code='دفعة 3 منعقدة',
            start_date='2026-05-01',
            end_date='2026-06-01',
            status='active'
        )
        manage_url = reverse('training:course_session_manage', kwargs={'session_id': session3.id})
        res_manage = self.client.post(manage_url, {
            'add_extra_trainees': '1',
            'extra_trainees': [self.trainee.military_number],
        })
        self.assertFalse(session3.enrollments.filter(trainee=self.trainee).exists())

    def test_military_number_cannot_be_duplicated_across_trainees_and_instructors(self):
        """التحقق من منع تكرار النمرة العسكرية بين الدارسين وهيئة التدريس في كلا الاتجاهين"""
        from training.models import Instructor, Trainee
        from training.forms import TraineeForm, InstructorForm

        # 1. إنشاء معلم بنمرة محددة
        instructor = Instructor.objects.create(
            military_number='77889900',
            name='المعلم الأول',
            rank='مقدم',
            force='القوات البرية',
            unit='إدارة التدريب'
        )

        # محاولة تسجيل دارس بنفس نمرة المعلم عبر النموذج
        trainee_form = TraineeForm(data={
            'military_number': '77889900',
            'name': 'دارس مكرر النمرة',
            'category': 'officer',
            'force': 'القوات البرية',
            'unit': 'سلاح المدرعات'
        })
        self.assertFalse(trainee_form.is_valid())
        self.assertIn('military_number', trainee_form.errors)

        # 2. إنشاء دارس بنمرة محددة ومحاولة تسجيل معلم بنفس النمرة
        Trainee.objects.create(
            military_number='66554433',
            name='دارس أصيل',
            category='officer',
            force='القوات الجوية',
            unit='جناح المقاتلات'
        )
        inst_form = InstructorForm(data={
            'military_number': '66554433',
            'name': 'معلم مكرر النمرة',
            'category': 'officer',
            'rank': 'عقيد',
            'force': 'القوات الجوية',
            'unit': 'جناح المقاتلات'
        })
        self.assertFalse(inst_form.is_valid())
        self.assertIn('military_number', inst_form.errors)

    def test_course_number_and_subject_code_uniqueness(self):
        """التحقق من عدم تكرار رقم الدورة ورقم المادة الدراسية"""
        from training.forms import CourseForm, SubjectForm
        from training.models import Course, Subject

        # رقم دورة مكرر
        course_form = CourseForm(data={
            'category': self.category.id,
            'course_number': self.course.course_number,  # مكرر
            'name': 'دورة مكررة الرمز',
            'description': ''
        })
        self.assertFalse(course_form.is_valid())
        self.assertIn('course_number', course_form.errors)

        # كود مادة مكرر
        sub_form = SubjectForm(data={
            'name': 'مادة مكررة الكود',
            'code': self.subject.code,  # مكرر
            'credit_hours': 5,
            'max_grade': 100.0
        })
        self.assertFalse(sub_form.is_valid())
        self.assertIn('code', sub_form.errors)

    def test_subject_code_auto_generation_and_hidden_field(self):
        """التحقق من توليد كود المادة ورقمها تلقائياً من النظام دون الحاجة لإدخاله يدوياً"""
        from training.models import Subject
        # إنشاء مادتين جديدتين لنفس الدورة دون تعيين الكود
        sub1 = Subject.objects.create(
            course=self.course,
            name='مادة تلقائية 1',
            credit_hours=4,
            max_grade=50.0
        )
        self.assertTrue(bool(sub1.code))
        self.assertTrue(sub1.code.startswith(self.course.course_number))

        sub2 = Subject.objects.create(
            course=self.course,
            name='مادة تلقائية 2',
            credit_hours=6,
            max_grade=100.0
        )
        self.assertTrue(bool(sub2.code))
        self.assertNotEqual(sub1.code, sub2.code)

    def test_course_number_auto_generation_and_hidden_field(self):
        """التحقق من توليد رقم/رمز الدورة تلقائياً من النظام وإخفاء الحقل وإمكانية الحفظ دون إدخاله يدوياً"""
        from training.models import Course
        from training.forms import CourseForm

        # 1. إنشاء دورات مباشرة دون تحديد رقم الدورة
        c1 = Course.objects.create(
            category=self.category,
            name='دورة توليد تلقائي 1'
        )
        self.assertTrue(bool(c1.course_number))

        c2 = Course.objects.create(
            category=self.category,
            name='دورة توليد تلقائي 2'
        )
        self.assertTrue(bool(c2.course_number))
        self.assertNotEqual(c1.course_number, c2.course_number)

        # 2. التحقق من صلاحية النموذج عند عدم إدخال رقم الدورة
        form = CourseForm(data={
            'category': self.category.id,
            'name': 'دورة نموذج دون رقم',
            'description': 'وصف اختياري'
        })
        self.assertTrue(form.is_valid())
        saved_course = form.save()
        self.assertTrue(bool(saved_course.course_number))

        # 3. محاكاة طلب الحفظ من الشاشة عبر POST دون إرسال course_number
        self.client.login(username='admin_constraints', password='Password123!')
        res = self.client.post(reverse('training:courses_catalog'), {
            'add_course': '1',
            'category': str(self.category.id),
            'name': 'دورة عبر الطلب المباشر',
            'description': ''
        })
        self.assertEqual(res.status_code, 302)
        created_c = Course.objects.filter(name='دورة عبر الطلب المباشر').first()
        self.assertIsNotNone(created_c)
        self.assertTrue(bool(created_c.course_number))


class UserRolePermissionsTest(TestCase):
    """اختبارات نظام الصلاحيات المتقن والأدوار (معلم، مشرف، مسجل بيانات، مدير نظام)"""

    def setUp(self):
        self.client = Client()

        # تصنيف دورة
        self.category = CourseCategory.objects.create(name='دورات تخصصية')

        # دورة ومواد
        self.course = Course.objects.create(
            category=self.category,
            name='دورة إدارة العمليات',
            course_number='OPS-101'
        )
        self.subject1 = Subject.objects.create(
            course=self.course,
            name='تخطيط استراتيجي',
            credit_hours=20,
            max_grade=50.0
        )
        self.subject2 = Subject.objects.create(
            course=self.course,
            name='إدارة الموارد',
            credit_hours=20,
            max_grade=50.0
        )

        # معلم 1 ومعلم 2
        self.instructor1 = Instructor.objects.create(
            military_number='11111',
            name='معلم أحمد علي',
            rank='رائد',
            category=InstructorCategory.OFFICER
        )
        self.instructor2 = Instructor.objects.create(
            military_number='22222',
            name='معلم ياسر حسن',
            rank='نقيب',
            category=InstructorCategory.OFFICER
        )

        # مشرف
        self.supervisor_instructor = Instructor.objects.create(
            military_number='33333',
            name='مشرف كمال إبراهيم',
            rank='عقيد',
            category=InstructorCategory.OFFICER
        )

        # مستخدم معلم 1
        self.user_inst1 = User.objects.create_user(
            username='inst_ahmed',
            password='Password123!',
            first_name='أحمد',
            last_name='علي'
        )
        self.user_inst1.profile.role = UserRole.INSTRUCTOR
        self.user_inst1.profile.instructor = self.instructor1
        self.user_inst1.profile.military_number = self.instructor1.military_number
        self.user_inst1.profile.save()

        # مستخدم مشرف
        self.user_supervisor = User.objects.create_user(
            username='sup_kamal',
            password='Password123!',
            first_name='كمال',
            last_name='إبراهيم'
        )
        self.user_supervisor.profile.role = UserRole.SUPERVISOR
        self.user_supervisor.profile.instructor = self.supervisor_instructor
        self.user_supervisor.profile.military_number = self.supervisor_instructor.military_number
        self.user_supervisor.profile.save()

        # مستخدم مسجل بيانات
        self.user_registrar = User.objects.create_user(
            username='registrar_user',
            password='Password123!',
            first_name='مسجل',
            last_name='البيانات'
        )
        self.user_registrar.profile.role = UserRole.REGISTRAR
        self.user_registrar.profile.save()

        # مستخدم أدمن
        self.user_admin = User.objects.create_superuser(
            username='admin_role_tester',
            password='Password123!',
            email='admin@academy.test'
        )
        self.user_admin.profile.role = UserRole.ADMIN
        self.user_admin.profile.save()

        # انعقاد دورة
        self.session = CourseSession.objects.create(
            course=self.course,
            session_code='الدفعة 10 - 2026',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 1),
            attendance_max_grade=20.0,
            supervisor=self.supervisor_instructor,
            status='active'
        )

        # ربط المواد بالمعلمين
        SessionSubjectInstructor.objects.create(
            session=self.session,
            subject=self.subject1,
            instructor=self.instructor1
        )
        SessionSubjectInstructor.objects.create(
            session=self.session,
            subject=self.subject2,
            instructor=self.instructor2
        )

        # دارس وتسجيله
        self.trainee = Trainee.objects.create(
            military_number='77777',
            name='دارس طارق محمود',
            category=TraineeCategory.OFFICER,
            force='القوات البرية',
            unit='اللواء الأول'
        )
        self.enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank='نقيب',
            current_unit='اللواء الأول'
        )

    def test_instructor_restricted_from_management_pages(self):
        """التحقق من حصر المعلم في صفحة النتيجة وتوجيهه عند محاولة دخول أقسام الإدارة"""
        self.client.login(username='inst_ahmed', password='Password123!')

        # 1. الدخول للرئيسية يوجه المعلم لصفحة النتيجة
        res_home = self.client.get(reverse('training:home'))
        self.assertEqual(res_home.status_code, 302)
        self.assertEqual(res_home.url, reverse('training:results_center'))

        # 2. محاولة الدخول للدارسين توجه لصفحة النتيجة
        res_trainees = self.client.get(reverse('training:trainees_list'))
        self.assertEqual(res_trainees.status_code, 302)
        self.assertEqual(res_trainees.url, reverse('training:results_center'))

        # 3. محاولة الدخول للدورات توجه لصفحة النتيجة
        res_courses = self.client.get(reverse('training:courses_catalog'))
        self.assertEqual(res_courses.status_code, 302)
        self.assertEqual(res_courses.url, reverse('training:results_center'))

        # 4. محاولة الدخول للانعقادات توجه لصفحة النتيجة
        res_sessions = self.client.get(reverse('training:course_sessions'))
        self.assertEqual(res_sessions.status_code, 302)
        self.assertEqual(res_sessions.url, reverse('training:results_center'))

        # 5. صفحة رصد النتائج متاحة للمعلم
        res_results = self.client.get(reverse('training:results_entry', kwargs={'session_id': self.session.id}))
        self.assertEqual(res_results.status_code, 200)

    def test_instructor_grades_only_assigned_subject(self):
        """التحقق من أن المعلم يرصد درجات مادته فقط ولا يؤثر على درجات مادة زميله أو المواظبة"""
        # أولاً: رصد درجة المادة الثانية مسبقاً
        TraineeSubjectGrade.objects.create(
            enrollment=self.enrollment,
            subject=self.subject2,
            score=45.0
        )
        self.enrollment.attendance_score = 18.0
        self.enrollment.save()

        # تسجيل دخول المعلم 1 (مكلف بالمادة 1 فقط)
        self.client.login(username='inst_ahmed', password='Password123!')

        # 1. المعلم يرسل درجات المادة 1، مع محاولة تغيير مادة زميله والمواظبة
        res = self.client.post(
            reverse('training:results_entry', kwargs={'session_id': self.session.id}),
            {
                'save_grades': '1',
                f'grade_{self.trainee.military_number}_{self.subject1.id}': '48.0',
                f'grade_{self.trainee.military_number}_{self.subject2.id}': '10.0',  # محاولة تعديل مادة زميله
                f'att_{self.trainee.military_number}': '5.0',  # محاولة تعديل المواظبة
            }
        )
        self.assertEqual(res.status_code, 302)

        # التحقق من أن درجة المادة 1 حُفظت بنجاح
        g1 = TraineeSubjectGrade.objects.filter(enrollment=self.enrollment, subject=self.subject1).first()
        self.assertIsNotNone(g1)
        self.assertEqual(float(g1.score), 48.0)

        # التحقق من أن درجة المادة 2 لم تتأثر وظلت 45.0 ولم تُحذف
        g2 = TraineeSubjectGrade.objects.filter(enrollment=self.enrollment, subject=self.subject2).first()
        self.assertIsNotNone(g2)
        self.assertEqual(float(g2.score), 45.0)

        # التحقق من أن المواظبة لم يغيرها المعلم
        self.enrollment.refresh_from_db()
        self.assertEqual(float(self.enrollment.attendance_score), 18.0)

        # 2. محاولة اعتماد غير مصرح بها من قبل المعلم
        res_mark = self.client.post(
            reverse('training:results_entry', kwargs={'session_id': self.session.id}),
            {
                'save_grades': '1',
                'mark_completed': '1',
            }
        )
        self.assertEqual(res_mark.status_code, 302)

        # الدورة لا تزال جارية ولم يتم اعتمادها
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'active')

    def test_supervisor_cannot_finalize_until_all_grades_complete(self):
        """التحقق من أن المشرف لا يستطيع اعتماد النتيجة نهائياً إلا بعد اكتمال رصد كافة درجات المواد"""
        self.client.login(username='sup_kamal', password='Password123!')

        # محاولة الاعتماد بينما درجات المواد غير مكتملة
        res = self.client.post(
            reverse('training:results_entry', kwargs={'session_id': self.session.id}),
            {
                'save_grades': '1',
                'mark_completed': '1',
            }
        )
        self.assertEqual(res.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'active')

        # الآن نقوم برصد درجات كافة المواد للدارس
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.subject1, score=45.0)
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.subject2, score=42.0)
        self.enrollment.attendance_score = 19.0
        self.enrollment.save()

        # المشرف يعتمد النتيجة بعد اكتمال رصد جميع المواد
        res_ok = self.client.post(
            reverse('training:results_entry', kwargs={'session_id': self.session.id}),
            {
                'save_grades': '1',
                'mark_completed': '1',
            }
        )
        self.assertEqual(res_ok.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.status, 'completed')

    def test_registrar_can_manage_trainees_and_courses_but_not_admin_portal(self):
        """التحقق من صلاحيات مسجل البيانات في إضافة وتعديل وحذف الدارسين والدورات ومنعه من لوحة الأدمن"""
        self.client.login(username='registrar_user', password='Password123!')

        # 1. إضافة دارس جديد
        res_trainee = self.client.post(reverse('training:trainees_list'), {
            'add_trainee': '1',
            'military_number': '88888',
            'name': 'دارس مسجل جديد',
            'category': TraineeCategory.NCO,
            'force': 'القوات الجوية',
            'unit': 'قاعدة الخرطوم'
        })
        self.assertEqual(res_trainee.status_code, 302)
        self.assertTrue(Trainee.objects.filter(military_number='88888').exists())

        # 2. حذف دارس غير مسجل بدورات
        res_del_trainee = self.client.post(reverse('training:trainee_delete', kwargs={'military_number': '88888'}))
        self.assertEqual(res_del_trainee.status_code, 302)
        self.assertFalse(Trainee.objects.filter(military_number='88888').exists())

        # 3. إضافة دورة جديدة
        res_course = self.client.post(reverse('training:courses_catalog'), {
            'add_course': '1',
            'category': str(self.category.id),
            'name': 'دورة اتصالات حربية',
            'description': 'دورة مخصصة'
        })
        self.assertEqual(res_course.status_code, 302)
        new_c = Course.objects.filter(name='دورة اتصالات حربية').first()
        self.assertIsNotNone(new_c)

        # 4. حذف دورة ليس لها انعقادات
        res_del_course = self.client.post(reverse('training:course_delete', kwargs={'course_id': new_c.id}))
        self.assertEqual(res_del_course.status_code, 302)
        self.assertFalse(Course.objects.filter(id=new_c.id).exists())

        # 5. محاولة الدخول للوحة الأدمن المنفصلة تمنع مسجل البيانات وتوجهه للرئيسية
        res_admin = self.client.get(reverse('training:admin_dashboard'))
        self.assertEqual(res_admin.status_code, 302)
        self.assertEqual(res_admin.url, reverse('training:home'))

    def test_windows_style_checkbox_permissions_update(self):
        """التحقق من مرونة تعديل الصلاحيات بخانات صح على غرار أذونات ويندوز"""
        self.client.login(username='admin_role_tester', password='Password123!')

        # 1. تحديث أذونات المستخدم sup_kamal بخانات مخصصة (Custom Permissions)
        update_url = reverse('training:user_update_role', kwargs={'user_id': self.user_supervisor.id})
        res = self.client.post(update_url, {
            'role': 'custom',
            'can_view': 'on',
            'can_add': 'on',
            'can_edit': 'on',
            # can_delete غير محدد (False)
            'can_grade': 'on',
            # can_approve_results غير محدد (False)
            # can_manage_users غير محدد (False)
        })
        self.assertEqual(res.status_code, 302)
        self.user_supervisor.refresh_from_db()
        profile = UserProfile.objects.get(user=self.user_supervisor)
        self.assertEqual(profile.role, 'custom')
        self.assertTrue(profile.can_view)
        self.assertTrue(profile.can_add)
        self.assertTrue(profile.can_edit)
        self.assertFalse(profile.can_delete)
        self.assertTrue(profile.can_grade)
        self.assertFalse(profile.can_approve_results)
        self.assertFalse(profile.can_manage_users)
        self.assertFalse(self.user_supervisor.is_staff)

        # 2. منح التحكم الكامل لمستخدم
        res2 = self.client.post(update_url, {
            'role': 'admin',
            'can_manage_users': 'on',
            'can_view': 'on',
            'can_add': 'on',
            'can_edit': 'on',
            'can_delete': 'on',
            'can_grade': 'on',
            'can_approve_results': 'on',
        })
        self.assertEqual(res2.status_code, 302)
        self.user_supervisor.refresh_from_db()
        profile2 = UserProfile.objects.get(user=self.user_supervisor)
        self.assertTrue(profile2.can_manage_users)
        self.assertTrue(self.user_supervisor.is_staff)

        # 3. حماية الأدمن الحالي من إزالة التحكم الكامل عن نفسه
        admin_update_url = reverse('training:user_update_role', kwargs={'user_id': self.user_admin.id})
        res_self = self.client.post(admin_update_url, {
            'role': 'regular',
            # بدون can_manage_users
        })
        self.assertEqual(res_self.status_code, 302)
        self.user_admin.refresh_from_db()
        profile_admin = UserProfile.objects.get(user=self.user_admin)
        self.assertTrue(profile_admin.can_manage_users or profile_admin.role == UserRole.ADMIN)
        self.assertTrue(self.user_admin.is_staff)

    def test_course_and_session_attendance_grade_inheritance(self):
        """التحقق من نزول درجة المواظبة في نموذج وشاشة الدورات وافتراضيتها 10 ووراثتها للدورات المنعقدة"""
        from decimal import Decimal
        from training.forms import CourseForm

        # 1. التحقق من القيمة الافتراضية في نموذج الدورة Course
        category = CourseCategory.objects.first() or CourseCategory.objects.create(name="تصنيف اختبار")
        course_default = Course.objects.create(
            category=category,
            name="دورة قيادة افتراضية",
            course_number="TEST-ATT-1"
        )
        self.assertEqual(course_default.attendance_max_grade, Decimal('10.00'))

        # 2. التحقق من الدورة المنعقدة CourseSession ووراثتها للدرجة تلقائياً
        session = CourseSession.objects.create(
            course=course_default,
            session_code="دفعة 1 - مواظبة",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 1),
            status='active'
        )
        self.assertEqual(session.attendance_max_grade, Decimal('10.00'))

        # 3. التحقق من دورة بدرجة مواظبة مخصصة
        course_custom = Course.objects.create(
            category=category,
            name="دورة متقدمة بمواظبة 15",
            course_number="TEST-ATT-2",
            attendance_max_grade=Decimal('15.00')
        )
        session_custom = CourseSession.objects.create(
            course=course_custom,
            session_code="دفعة 2 - مواظبة مخصصة",
            start_date=date(2026, 4, 1),
            end_date=date(2026, 6, 1),
            status='active'
        )
        self.assertEqual(session_custom.attendance_max_grade, Decimal('15.00'))

        # 4. اختبار CourseForm ووجود حقل attendance_max_grade وقيمته الافتراضية 10
        form = CourseForm(data={
            'category': category.id,
            'name': 'دورة مجربة عبر النموذج',
            'attendance_max_grade': '',
        })
        self.assertTrue(form.is_valid())
        course_form_obj = form.save()
        self.assertEqual(course_form_obj.attendance_max_grade, Decimal('10.00'))

    def test_activity_log_tracking_and_user_session_journey(self):
        """التحقق من توثيق سجل النشاط لعمليات المستخدم من الدخول حتى الخروج والفلاتر في صفحة الأدمن"""
        from training.models import ActivityLog, ActivityAction, ActivityCategory

        # 1. تسجيل دخول المستخدم مسجل البيانات
        self.client.login(username='registrar_user', password='Password123!')
        login_log = ActivityLog.objects.filter(username='registrar_user', action_type=ActivityAction.LOGIN).first()
        self.assertIsNotNone(login_log)
        self.assertEqual(login_log.action_category, ActivityCategory.AUTH)

        # 2. قيام المستخدم بعملية إضافة دارس جديد
        res_add = self.client.post(reverse('training:trainees_list'), {
            'add_trainee': '1',
            'military_number': '99881',
            'category': 'officer',
            'name': 'دارس سجل النشاط',
            'force': 'القوات الجوية',
            'unit': 'قاعدة الخرطوم'
        })
        self.assertEqual(res_add.status_code, 302)
        add_log = ActivityLog.objects.filter(username='registrar_user', action_type=ActivityAction.CREATE, target_model='Trainee').first()
        self.assertIsNotNone(add_log)
        self.assertIn('99881', add_log.description)

        # 3. قيام المستخدم بتعديل بيانات الدارس
        res_edit = self.client.post(reverse('training:trainee_edit', kwargs={'military_number': '99881'}), {
            'military_number': '99881',
            'category': 'officer',
            'name': 'دارس معدل في سجل النشاط',
            'force': 'القوات الجوية',
            'unit': 'جناح العمليات'
        })
        self.assertEqual(res_edit.status_code, 302)
        edit_log = ActivityLog.objects.filter(username='registrar_user', action_type=ActivityAction.UPDATE, target_model='Trainee').first()
        self.assertIsNotNone(edit_log)
        self.assertIn('دارس معدل', edit_log.description)

        # 4. تسجيل الخروج من النظام
        self.client.get(reverse('training:logout'))
        logout_log = ActivityLog.objects.filter(username='registrar_user', action_type=ActivityAction.LOGOUT).first()
        self.assertIsNotNone(logout_log)

        # 5. دخول الأدمن للوحة الأدمن وتفحص سجل النشاط
        self.client.login(username='admin_role_tester', password='Password123!')
        res_admin = self.client.get(reverse('training:admin_dashboard') + '?tab=activity-log')
        self.assertEqual(res_admin.status_code, 200)
        self.assertContains(res_admin, 'سجل النشاط ومسار عمليات المستخدمين')
        self.assertContains(res_admin, 'registrar_user')

        # 6. فلترة مسار جلسة المستخدم المختار
        res_user_filter = self.client.get(reverse('training:admin_dashboard') + '?tab=activity-log&activity_user=registrar_user')
        self.assertEqual(res_user_filter.status_code, 200)
        self.assertContains(res_user_filter, 'تتبع مسار نشاط وجلسات المستخدم')
        self.assertContains(res_user_filter, 'دارس معدل في سجل النشاط')

        # 7. التحقق من تفريغ سجل النشاط
        clear_res = self.client.post(reverse('training:admin_clear_activity_logs'))
        self.assertEqual(clear_res.status_code, 302)
        # بعد التفريغ، يجب أن يتواجد سجل واحد يوثق قيام الأدمن بالتفريغ نفسه
        self.assertEqual(ActivityLog.objects.count(), 1)
        clear_log = ActivityLog.objects.first()
        self.assertEqual(clear_log.action_type, ActivityAction.DELETE)
        self.assertIn('تفريغ وحذف سجل النشاط', clear_log.description)


class UserRankAndUnitListTests(TestCase):
    """اختبارات قوائم الرتبة والوحدة المنسدلة في إدارة المستخدمين"""

    def setUp(self):
        self.admin = User.objects.create_superuser(
            username='admin_list_tester',
            password='Password123!',
            email='admin_list@example.com'
        )
        profile, _ = UserProfile.objects.get_or_create(user=self.admin)
        profile.role = UserRole.ADMIN
        profile.can_manage_users = True
        profile.can_view = True
        profile.can_add = True
        profile.can_edit = True
        profile.can_delete = True
        profile.save()

    def test_user_creation_with_rank_and_unit_from_list(self):
        """التحقق من إنشاء مستخدم باختيار الرتبة والوحدة من القائمة المنسدلة"""
        self.client.login(username='admin_list_tester', password='Password123!')
        url = reverse('training:user_create')

        post_data = {
            'username': 'officer_user',
            'password': 'Password123!',
            'first_name': 'عمر',
            'last_name': 'الفاروق',
            'role': UserRole.REGISTRAR,
            'military_number': '556677',
            'rank': 'رائد',
            'unit': 'سلاح الإشارة',
            'phone': '0912345678',
            'is_active': 'on',
            'can_view': 'on',
            'can_add': 'on',
            'can_edit': 'on',
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        user = User.objects.get(username='officer_user')
        self.assertEqual(user.profile.rank, 'رائد')
        self.assertEqual(user.profile.unit, 'سلاح الإشارة')
        self.assertEqual(user.profile.military_number, '556677')

    def test_user_creation_with_custom_rank_and_unit(self):
        """التحقق من حفظ الرتبة والوحدة المخصصة عند اختيار أخرى"""
        self.client.login(username='admin_list_tester', password='Password123!')
        url = reverse('training:user_create')

        post_data = {
            'username': 'custom_rank_user',
            'password': 'Password123!',
            'first_name': 'طارق',
            'last_name': 'زياد',
            'role': UserRole.INSTRUCTOR,
            'military_number': '998877',
            'rank': '__custom__',
            'custom_rank': 'عقيد ركن طيار',
            'unit': '__custom__',
            'custom_unit': 'كتيبة الصيانة الإلكترونية الخاصة',
            'is_active': 'on',
            'can_grade': 'on',
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        user = User.objects.get(username='custom_rank_user')
        self.assertEqual(user.profile.rank, 'عقيد ركن طيار')
        self.assertEqual(user.profile.unit, 'كتيبة الصيانة الإلكترونية الخاصة')

    def test_user_edit_form_choices_and_save(self):
        """التحقق من تعديل رتبة ووحدة المستخدم عبر شاشة التعديل"""
        target = User.objects.create_user(username='edit_target', password='Password123!')
        target_prof, _ = UserProfile.objects.get_or_create(user=target)
        target_prof.role = UserRole.REGULAR
        target_prof.rank = 'نقيب'
        target_prof.unit = 'سلاح المشاة'
        target_prof.save()

        self.client.login(username='admin_list_tester', password='Password123!')
        url = reverse('training:user_edit', kwargs={'user_id': target.id})

        # فحص وجود خيارات الرتب والوحدات في صفحة التعديل
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'editUserRankSelect')
        self.assertContains(get_res, 'editUserUnitSelect')

        # تعديل الرتبة والوحدة
        post_data = {
            'first_name': 'معدل',
            'last_name': 'الاسم',
            'email': 'target@example.com',
            'role': UserRole.REGULAR,
            'military_number': '112233',
            'rank': 'مقدم',
            'unit': 'سلاح المدرعات',
            'phone': '0999999999',
            'is_active': 'on',
            'can_view': 'on',
        }
        post_res = self.client.post(url, post_data)
        self.assertEqual(post_res.status_code, 302)

        target.refresh_from_db()
        self.assertEqual(target.profile.rank, 'مقدم')
        self.assertEqual(target.profile.unit, 'سلاح المدرعات')


class TraineeExtendedDataTests(TestCase):
    """
    اختبارات تسجيل وتعديل الدارس مع الحقول الموسعة:
    - الدفعة (رقمي)
    - السكن (الولاية، المدينة، الحي، المربع/الحارة، رقم المنزل)
    - رقم الهاتف
    - أقرب الأقربين (4 أقارب)
    """
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_user(
            username='registrar_user_test',
            password='Password123!',
            is_staff=True,
            is_superuser=True
        )
        self.admin_profile, _ = UserProfile.objects.get_or_create(user=self.admin)
        self.admin_profile.role = UserRole.ADMIN
        self.admin_profile.can_write = True
        self.admin_profile.save()

    def test_create_trainee_with_batch_residence_phone_and_four_relatives(self):
        self.client.login(username='registrar_user_test', password='Password123!')
        url = reverse('training:trainees_list')

        post_data = {
            'add_trainee': '1',
            'military_number': '998877',
            'category': 'officer',
            'name': 'خالد محمد إبراهيم',
            'batch': '25',
            'phone': '0912345678',
            'residence_state': 'الخرطوم',
            'residence_city': 'بحري',
            'residence_neighborhood': 'الصافية',
            'residence_block': 'مربع 3',
            'residence_house_number': '12',
            # القريب 1
            'relative_1_name': 'محمد إبراهيم علي',
            'relative_1_kinship': 'والد',
            'relative_1_phone': '0911111111',
            'relative_1_address': 'الصافية مربع 3',
            # القريب 2
            'relative_2_name': 'فاطمة أحمد',
            'relative_2_kinship': 'والدة',
            'relative_2_phone': '0922222222',
            'relative_2_address': 'الصافية مربع 3',
            # القريب 3
            'relative_3_name': 'أحمد محمد إبراهيم',
            'relative_3_kinship': 'أخ',
            'relative_3_phone': '0933333333',
            'relative_3_address': 'بحري الشعبية',
            # القريب 4
            'relative_4_name': 'عمر إبراهيم علي',
            'relative_4_kinship': 'عم',
            'relative_4_phone': '0944444444',
            'relative_4_address': 'الخرطوم العمارات',
        }

        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        from training.models import Trainee
        t = Trainee.objects.filter(military_number='998877').first()
        self.assertIsNotNone(t)
        self.assertEqual(t.name, 'خالد محمد إبراهيم')
        self.assertEqual(t.batch, 25)
        self.assertEqual(t.phone, '0912345678')
        self.assertEqual(t.residence_state, 'الخرطوم')
        self.assertEqual(t.residence_city, 'بحري')
        self.assertEqual(t.residence_neighborhood, 'الصافية')
        self.assertEqual(t.residence_block, 'مربع 3')
        self.assertEqual(t.residence_house_number, '12')
        self.assertIn('بحري', t.full_address)

        # التحقق من الأقارب الـ 4
        self.assertEqual(t.relatives.count(), 4)
        r1 = t.relatives.get(order=1)
        self.assertEqual(r1.name, 'محمد إبراهيم علي')
        self.assertEqual(r1.kinship, 'والد')
        self.assertEqual(r1.phone, '0911111111')

        r4 = t.relatives.get(order=4)
        self.assertEqual(r4.name, 'عمر إبراهيم علي')
        self.assertEqual(r4.kinship, 'عم')

    def test_edit_trainee_batch_residence_and_relatives(self):
        from training.models import Trainee
        t = Trainee.objects.create(
            military_number='776655',
            category='nco',
            name='ياسر علي حسن',
            batch=18,
            phone='0987654321',
            residence_city='أم درمان'
        )
        self.client.login(username='registrar_user_test', password='Password123!')
        url = reverse('training:trainee_edit', kwargs={'military_number': t.military_number})

        edit_data = {
            'category': 'nco',
            'name': 'ياسر علي حسن (معدل)',
            'batch': '20',
            'phone': '0911223344',
            'residence_state': 'الخرطوم',
            'residence_city': 'أم درمان',
            'residence_neighborhood': 'المهندسين',
            'residence_block': 'حارة 5',
            'residence_house_number': '88',
            'relative_1_name': 'علي حسن',
            'relative_1_kinship': 'والد',
            'relative_1_phone': '0900000001',
            'relative_1_address': 'أم درمان',
        }
        res = self.client.post(url, edit_data)
        self.assertEqual(res.status_code, 302)

        t.refresh_from_db()
        self.assertEqual(t.name, 'ياسر علي حسن (معدل)')
        self.assertEqual(t.batch, 20)
        self.assertEqual(t.phone, '0911223344')
        self.assertEqual(t.residence_neighborhood, 'المهندسين')
        self.assertEqual(t.relatives.count(), 1)
        r1 = t.relatives.first()
        self.assertEqual(r1.name, 'علي حسن')


class CertificateOptionsAndNoteTests(TestCase):
    """اختبارات الشهادات المتعددة (الأساسية، المتقدمة، التقدير) والملحوظات المخصصة"""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='admin_cert',
            password='Password123!',
            email='admin_cert@test.com'
        )
        self.category = CourseCategory.objects.create(name='دورات حاسوب')
        self.course = Course.objects.create(
            name='دورة حاسوب أساسية',
            category=self.category,
            attendance_max_grade=10.0
        )
        self.subject1 = Subject.objects.create(
            course=self.course,
            name='مقدمة وتشغيل',
            max_grade=100.0
        )
        self.subject2 = Subject.objects.create(
            course=self.course,
            name='معالجة النصوص',
            max_grade=100.0
        )
        self.session = CourseSession.objects.create(
            course=self.course,
            session_code='BATCH-50',
            start_date=date(2026, 9, 13),
            end_date=date(2026, 10, 13),
            status='in_progress',
            attendance_max_grade=10.0
        )
        self.trainee = Trainee.objects.create(
            military_number='29803',
            name='محمد عبدالجليل خلف الله',
            category='officer',
            unit='إدارة الشئون المالية',
            force='القوات البرية',
            batch=6
        )
        self.enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank='رائد محاسب',
            current_unit='إدارة الشئون المالية',
            current_force='القوات البرية',
            attendance_score=10.0,
            certificate_note='ملحوظة تجريبية خاصة بالدارس'
        )
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.subject1, score=100.0)
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.subject2, score=100.0)
        self.enrollment.calculate_results()

    def test_rank_and_grade_symbol_properties(self):
        """اختبار حساب الترتيب ورمز التقدير بشكل سليم"""
        self.assertEqual(self.enrollment.rank_number, 1)
        self.assertEqual(self.enrollment.rank_arabic_text, 'الأول')
        self.assertEqual(self.enrollment.grade_symbol, '(أ)')
        self.assertIn('الأول', self.enrollment.rank_display)

    def test_detailed_and_official_certificate_view(self):
        """اختبار فتح شهادة التفاصيل وشهادة التقدير الرسمية والتأكد من البيانات"""
        self.client.login(username='admin_cert', password='Password123!')
        
        # شهادة التفاصيل
        url_detailed = reverse('training:certificate_detailed', args=[self.enrollment.id])
        res_detailed = self.client.get(url_detailed)
        self.assertEqual(res_detailed.status_code, 200)
        self.assertContains(res_detailed, 'شهادة دورة حاسوب أساسية')
        self.assertContains(res_detailed, '29803')
        self.assertContains(res_detailed, 'محمد عبدالجليل خلف الله')
        self.assertContains(res_detailed, 'ملحوظة تجريبية خاصة بالدارس')
        self.assertContains(res_detailed, 'مقدمة وتشغيل')
        self.assertContains(res_detailed, 'السلوك والمواظبة')

        # شهادة التقدير الرسمية
        url_official = reverse('training:certificate', args=[self.enrollment.id])
        res_official = self.client.get(url_official)
        self.assertEqual(res_official.status_code, 200)
        self.assertContains(res_official, 'محمد عبدالجليل خلف الله')

    def test_save_notes_even_when_session_is_locked(self):
        """اختبار إمكانية تعديل وحفظ ملحوظة الشهادة حتى بعد اعتماد وإقفال الدورة"""
        self.client.login(username='admin_cert', password='Password123!')
        self.session.status = 'completed'
        self.session.save()

        url = reverse('training:results_entry', args=[self.session.id])
        post_data = {
            'save_notes': '1',
            f'cert_note_{self.trainee.military_number}': 'ملحوظة جديدة بعد اعتماد النتيجة'
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.certificate_note, 'ملحوظة جديدة بعد اعتماد النتيجة')

    def test_customize_certificate_titles_in_admin(self):
        """اختبار تخصيص عنوان شهادة التفاصيل والملحوظة الافتراضية من لوحة الإدارة"""
        self.client.login(username='admin_cert', password='Password123!')
        url = reverse('training:certificate_settings_update')
        cert = CertificateSettings.get_settings()

        post_data = {
            'bismillah_text': cert.bismillah_text,
            'header_line_1': cert.header_line_1,
            'header_line_2': cert.header_line_2,
            'cert_title': cert.cert_title,
            'cert_title_color': cert.cert_title_color,
            'basic_cert_title': 'شهادة دورة حاسوب أساسية مخصصة',
            'default_certificate_note': 'أظهر كفاءة ممتازة واجتهاداً كبيراً.',
            'right_signer_rank': cert.right_signer_rank,
            'right_signer_name': cert.right_signer_name,
            'right_signer_title': cert.right_signer_title,
            'left_signer_rank': cert.left_signer_rank,
            'left_signer_name': cert.left_signer_name,
            'left_signer_title': cert.left_signer_title,
            'center_approval_prefix': cert.center_approval_prefix,
            'center_signer_rank': cert.center_signer_rank,
            'center_signer_name': cert.center_signer_name,
            'center_signer_title': cert.center_signer_title,
            'station_text': cert.station_text,
            'seal_notice': cert.seal_notice,
            'logo_height_mm': cert.logo_height_mm,
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)

        cert.refresh_from_db()
        self.assertEqual(cert.basic_cert_title, 'شهادة دورة حاسوب أساسية مخصصة')
        self.assertEqual(cert.default_certificate_note, 'أظهر كفاءة ممتازة واجتهاداً كبيراً.')

    def test_results_center_archive_only_completed_sessions(self):
        """التحقق من أن السجل التاريخي لا يعرض إلا الدورات المعتمدة والمكتملة فقط"""
        self.client.login(username='admin_cert', password='Password123!')
        from training.models import CourseCategory, Course, CourseSession
        import datetime

        cat = CourseCategory.objects.create(name='تصنيف التحقق من الاعتماد')
        course = Course.objects.create(name='دورة اختبار الاعتماد', category=cat)

        completed_session = CourseSession.objects.create(
            course=course,
            session_code='BATCH-COMPLETED-01',
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 15),
            status='completed'
        )
        active_session = CourseSession.objects.create(
            course=course,
            session_code='BATCH-ACTIVE-01',
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 15),
            status='active'
        )

        res = self.client.get(reverse('training:results_center'), {'tab': 'archive'})
        self.assertEqual(res.status_code, 200)
        self.assertIn(completed_session, res.context['archive_sessions'])
        self.assertNotIn(active_session, res.context['archive_sessions'])

    def test_drop_and_restore_trainee_flow(self):
        """التحقق من إجراء قطع الدورة للدارس وحجبه عن الرصد والشهادات ثم إمكانية إلغاء القطع"""
        self.client.login(username='admin_cert', password='Password123!')
        from training.models import CourseCategory, Course, CourseSession, Trainee, CourseEnrollment
        import datetime

        cat = CourseCategory.objects.create(name='تصنيف فحص القطع')
        course = Course.objects.create(name='دورة فحص قطع الدورة', category=cat)
        session = CourseSession.objects.create(
            course=course,
            session_code='BATCH-DROP-01',
            start_date=datetime.date(2026, 1, 1),
            end_date=datetime.date(2026, 1, 20),
            status='active'
        )
        trainee = Trainee.objects.create(
            name='طالب اختبار القطع',
            military_number='777666',
            category='officer',
            unit='سلاح الصيانة',
            force='القوات البرية'
        )
        enrollment = CourseEnrollment.objects.create(
            session=session,
            trainee=trainee,
            current_rank='ملازم',
            current_unit='سلاح الصيانة'
        )

        # 1. فحص تنفيذ إجراء قطع الدورة
        drop_url = reverse('training:course_session_manage', kwargs={'session_id': session.id})
        res_drop = self.client.post(drop_url, {
            'action': 'drop_trainee',
            'enrollment_id': enrollment.id,
            'drop_reason': 'أسباب انضباطية وسفر طارئ'
        })
        self.assertEqual(res_drop.status_code, 302)

        enrollment.refresh_from_db()
        self.assertTrue(enrollment.is_dropped)
        self.assertEqual(enrollment.drop_reason, 'أسباب انضباطية وسفر طارئ')
        self.assertIsNotNone(enrollment.dropped_at)

        # 2. التأكد من استبعاد الدارس المقطوع عن جدول رصد الدرجات النشط في صفحة الرصد
        res_entry = self.client.get(reverse('training:results_entry', kwargs={'session_id': session.id}))
        self.assertEqual(res_entry.status_code, 200)
        self.assertNotIn(enrollment, res_entry.context['enrollments'])
        self.assertIn(enrollment, res_entry.context['dropped_enrollments'])
        self.assertEqual(res_entry.context['dropped_count'], 1)

        # 3. التأكد من منع استخراج الشهادات للدارس المقطوعة دورته
        res_cert = self.client.get(reverse('training:certificate', kwargs={'enrollment_id': enrollment.id}))
        self.assertEqual(res_cert.status_code, 302)

        res_cert_detail = self.client.get(reverse('training:certificate_detailed', kwargs={'enrollment_id': enrollment.id}))
        self.assertEqual(res_cert_detail.status_code, 302)

        # 4. فحص إلغاء قطع الدورة واستعادة الدارس
        res_restore = self.client.post(drop_url, {
            'action': 'restore_trainee',
            'enrollment_id': enrollment.id
        })
        self.assertEqual(res_restore.status_code, 302)

        enrollment.refresh_from_db()
        self.assertFalse(enrollment.is_dropped)
        self.assertEqual(enrollment.drop_reason, '')
        self.assertIsNone(enrollment.dropped_at)

    def test_auto_course_session_numbering_rules(self):
        """التحقق من قواعد ترقيم الدورات: دورة المرشد لا تتكرر، والدورة الخاصة تتكرر وتبدأ كل سنة من 1"""
        self.client.login(username='admin_cert', password='Password123!')
        from training.models import CourseCategory, Course, CourseSession
        from training.views import calculate_next_course_session_code
        import datetime

        # 1. اختبار دورة المرشد: لا تتكرر أبداً وتزيد تراكمياً عبر السنوات
        cat_guide = CourseCategory.objects.create(name='دورات مرشد معتمدة')
        course_guide = Course.objects.create(name='دورة المرشد البرمجية', category=cat_guide)

        # أول انعقاد في 2025
        num1 = calculate_next_course_session_code(course_guide, datetime.date(2025, 1, 1))
        self.assertEqual(num1, '1')
        CourseSession.objects.create(
            course=course_guide,
            session_code='1',
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 2, 1)
        )

        # انعقاد تالٍ في 2025
        num2 = calculate_next_course_session_code(course_guide, datetime.date(2025, 5, 1))
        self.assertEqual(num2, '2')
        CourseSession.objects.create(
            course=course_guide,
            session_code='2',
            start_date=datetime.date(2025, 5, 1),
            end_date=datetime.date(2025, 6, 1)
        )

        # انعقاد في سنة جديدة 2026: دورة المرشد لا تتكرر ولا تتصفر
        num3 = calculate_next_course_session_code(course_guide, datetime.date(2026, 1, 1))
        self.assertEqual(num3, '3')

        # 2. اختبار الدورة الخاصة: تتكرر سنوياً وتبدأ كل بداية سنة من الرقم 1
        cat_special = CourseCategory.objects.create(name='دورات خاصة أمنية')
        course_special = Course.objects.create(name='دورة خاصة لحماية الشبكات', category=cat_special)

        # سنة 2025: أول دورة تبدأ من 1
        num_sp_2025_1 = calculate_next_course_session_code(course_special, datetime.date(2025, 3, 1))
        self.assertEqual(num_sp_2025_1, '1')
        CourseSession.objects.create(
            course=course_special,
            session_code='1',
            start_date=datetime.date(2025, 3, 1),
            end_date=datetime.date(2025, 4, 1)
        )

        # سنة 2025: ثاني دورة تكون 2
        num_sp_2025_2 = calculate_next_course_session_code(course_special, datetime.date(2025, 8, 1))
        self.assertEqual(num_sp_2025_2, '2')
        CourseSession.objects.create(
            course=course_special,
            session_code='2',
            start_date=datetime.date(2025, 8, 1),
            end_date=datetime.date(2025, 9, 1)
        )

        # بداية سنة جديدة 2026: الدورة الخاصة تتكرر وتبدأ من 1 مجدداً
        num_sp_2026_1 = calculate_next_course_session_code(course_special, datetime.date(2026, 1, 10))
        self.assertEqual(num_sp_2026_1, '1')

        # فحص استعلام API لرقم الدورة التالي
        api_url = reverse('training:api_next_course_number')
        res_api = self.client.get(api_url, {
            'course_id': course_special.id,
            'start_date': '2026-02-15'
        })
        self.assertEqual(res_api.status_code, 200)
        data = res_api.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['next_number'], '1')
        self.assertTrue(data['is_special'])

    def test_quick_add_subject_api_and_integration(self):
        """التحقق من إضافة مادة دراسية سريعة عبر API للدورة وربطها بالدورة المنعقدة وظهورها في صفحة الإنشاء"""
        cat = CourseCategory.objects.create(name='دورات حاسوب عامة')
        course = Course.objects.create(
            name='دورة برمجة متقدمة',
            category=cat,
            course_number='PROG-200'
        )
        session = CourseSession.objects.create(
            course=course,
            session_code='1',
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 30)
        )

        api_url = reverse('training:api_add_course_subject')

        # 1. مستخدم غير مسجل / غير مصرح
        self.client.logout()
        res_anon = self.client.post(api_url, {'course_id': course.id, 'name': 'بايثون'})
        self.assertEqual(res_anon.status_code, 302)

        # مستخدم عادي ليس مسجل أو أدمن
        reg_user = User.objects.create_user(username='regular_subject_user', password='Password123!')
        reg_user.profile.role = UserRole.REGULAR
        reg_user.profile.save()
        self.client.force_login(reg_user)
        res_forbidden = self.client.post(api_url, {'course_id': course.id, 'name': 'بايثون'})
        self.assertEqual(res_forbidden.status_code, 403)

        # 2. مستخدم مسجل / أدمن يضيف مادة بنجاح
        self.client.force_login(self.admin)
        res_success = self.client.post(api_url, {
            'course_id': course.id,
            'session_id': session.id,
            'name': 'بايثون متقدم',
            'credit_hours': '15',
            'max_grade': '100'
        })
        self.assertEqual(res_success.status_code, 200)
        data = res_success.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['subject']['name'], 'بايثون متقدم')
        self.assertEqual(data['subject']['credit_hours'], 15)
        self.assertEqual(data['subject']['max_grade'], 100.0)

        # التحقق من حفظ المادة في قاعدة البيانات
        sub = Subject.objects.get(name='بايثون متقدم', course=course)
        self.assertEqual(sub.credit_hours, 15)

        # التحقق من الربط التلقائي بالدورة المنعقدة
        self.assertTrue(SessionSubjectInstructor.objects.filter(session=session, subject=sub).exists())

        # 3. محاولة إضافة مادة مكررة بنفس الاسم
        res_dup = self.client.post(api_url, {
            'course_id': course.id,
            'name': 'بايثون متقدم',
        })
        self.assertEqual(res_dup.status_code, 400)
        self.assertIn('مضافة مسبقاً', res_dup.json()['message'])

        # 4. فحص صفحة إنشاء دورة جديدة وتأكد وجود زر إضافة مادة
        create_page_res = self.client.get(reverse('training:course_session_create'))
        self.assertEqual(create_page_res.status_code, 200)
        content = create_page_res.content.decode('utf-8')
        self.assertIn('إضافة مادة لهذه الدورة', content)
        self.assertIn('quickAddSubjectModal', content)

    def test_session_subject_isolation_across_multiple_sessions(self):
        """التحقق التام من عزل المواد المضافة لدورة معينة (مثل الدورة 75) وعدم ظهورها في أي دورة محفوظة أخرى"""
        cat = CourseCategory.objects.create(name='دورات القيادة العامة')
        course = Course.objects.create(name='إدارة متقدمة تجريبية', category=cat, course_number='MGT-100')
        sub_base = Subject.objects.create(course=course, name='مبادئ إدارة أساسية', max_grade=100)

        # دورتان منعقدتان لنفس المقرر: دورة 74 ودورة 75
        session_74 = CourseSession.objects.create(
            course=course, session_code='74',
            start_date=date(2026, 1, 1), end_date=date(2026, 1, 30)
        )
        SessionSubjectInstructor.objects.create(session=session_74, subject=sub_base)

        session_75 = CourseSession.objects.create(
            course=course, session_code='75',
            start_date=date(2026, 2, 1), end_date=date(2026, 2, 28)
        )
        SessionSubjectInstructor.objects.create(session=session_75, subject=sub_base)

        # إضافة مادة خاصة بالدورة 75 فقط عبر API
        self.client.force_login(self.admin)
        api_url = reverse('training:api_add_course_subject')
        res = self.client.post(api_url, {
            'course_id': course.id,
            'session_id': session_75.id,
            'name': 'تخطيط استراتيجي خاص 75',
            'credit_hours': '20',
            'max_grade': '100'
        })
        self.assertEqual(res.status_code, 200)

        # التحقق من أن المادة تتبع الدورة 75 حصرياً
        sub_75 = Subject.objects.get(name='تخطيط استراتيجي خاص 75')
        self.assertEqual(sub_75.session_id, session_75.id)

        # الدورة 75 تحتوي على المادتين
        sub_names_75 = [s.name for s in session_75.get_subjects()]
        self.assertIn('مبادئ إدارة أساسية', sub_names_75)
        self.assertIn('تخطيط استراتيجي خاص 75', sub_names_75)

        # الدورة 74 (الدورة الأخرى المحفوظة) لا تحتوي على المادة المضافة في الدورة 75 إطلاقاً!
        sub_names_74 = [s.name for s in session_74.get_subjects()]
        self.assertIn('مبادئ إدارة أساسية', sub_names_74)
        self.assertNotIn('تخطيط استراتيجي خاص 75', sub_names_74)

        # فحص صفحة رصد درجات الدورة 74 والتأكد من عدم ظهور المادة الخاصة بالدورة 75
        res_grades_74 = self.client.get(reverse('training:results_entry', kwargs={'session_id': session_74.id}))
        self.assertEqual(res_grades_74.status_code, 200)
        self.assertNotIn('تخطيط استراتيجي خاص 75', res_grades_74.content.decode('utf-8'))

        # فحص دليل ومفردات الدورات العام والتأكد من عدم ظهور مادة الدورة 75 في الخطة العامة
        res_cat = self.client.get(reverse('training:courses_catalog') + f'?category_id={cat.id}&course_id={course.id}')
        self.assertEqual(res_cat.status_code, 200)
        self.assertNotIn('تخطيط استراتيجي خاص 75', res_cat.content.decode('utf-8'))

        # إزالة المادة الخاصة من الدورة 75
        manage_url = reverse('training:course_session_manage', kwargs={'session_id': session_75.id})
        res_del = self.client.post(manage_url, {'remove_session_subject_id': sub_75.id})
        self.assertEqual(res_del.status_code, 302)
        sub_names_75_after = [s.name for s in session_75.get_subjects()]
        self.assertNotIn('تخطيط استراتيجي خاص 75', sub_names_75_after)

    def test_teacher_grades_assigned_subject_while_others_empty_and_supervisor_workflow(self):
        """
        التحقق من:
        1. تمكن المعلم من رصد درجات مواده فقط وحفظها بنجاح حتى مع بقاء درجات المعلمين الآخرين والمواظبة فارغة.
        2. عدم ظهور أي أخطاء أو إلزام للمعلم بملء مواد غيره.
        3. تمكن مشرف الدورة من الاطلاع على الدورة ورصد المواظبة، مع حظر تعديله على درجات المواد التخصصية للمعلمين.
        4. تمكن المشرف من اعتماد النتيجة بعد اكتمال رصد كافة درجات المواد من المعلمين ورصد المواظبة.
        """
        cat = CourseCategory.objects.create(name='دورات الذكاء الاصطناعي')
        course = Course.objects.create(name='دورة برمجة متقدمة', category=cat)
        sub_ml = Subject.objects.create(course=course, name='تعلم الآلة', max_grade=100)
        sub_it = Subject.objects.create(course=course, name='شبكات حاسوب', max_grade=100)

        inst_ml = Instructor.objects.create(
            military_number='112233',
            name='معلم تعلم الآلة',
            rank='نقيب',
            unit='سلاح الإشارة'
        )
        user_ml = User.objects.create_user(username='teacher_ml', password='Password123!')
        user_ml.profile.role = UserRole.INSTRUCTOR
        user_ml.profile.instructor = inst_ml
        user_ml.profile.military_number = inst_ml.military_number
        user_ml.profile.save()

        inst_it = Instructor.objects.create(
            military_number='445566',
            name='معلم الشبكات',
            rank='رائد',
            unit='سلاح الصيانة'
        )
        user_it = User.objects.create_user(username='teacher_it', password='Password123!')
        user_it.profile.role = UserRole.INSTRUCTOR
        user_it.profile.instructor = inst_it
        user_it.profile.military_number = inst_it.military_number
        user_it.profile.save()

        inst_sup = Instructor.objects.create(
            military_number='778899',
            name='مشرف الدورة الأكاديمي',
            rank='مقدم',
            unit='قيادة المعهد'
        )
        user_sup = User.objects.create_user(username='supervisor_user', password='Password123!')
        user_sup.profile.role = UserRole.SUPERVISOR
        user_sup.profile.instructor = inst_sup
        user_sup.profile.military_number = inst_sup.military_number
        user_sup.profile.save()

        session = CourseSession.objects.create(
            course=course,
            session_code='دورة 78 - اختبار الصلاحيات',
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 30),
            attendance_max_grade=20.0,
            supervisor=inst_sup,
            status='active'
        )

        SessionSubjectInstructor.objects.create(session=session, subject=sub_ml, instructor=inst_ml)
        SessionSubjectInstructor.objects.create(session=session, subject=sub_it, instructor=inst_it)

        trainee = Trainee.objects.create(
            military_number='999001',
            name='دارس تجربة الصلاحيات',
            category=TraineeCategory.OFFICER,
            unit='لواء المدرعات'
        )
        enrollment = CourseEnrollment.objects.create(
            session=session,
            trainee=trainee,
            current_rank='ملازم أول',
            current_unit='لواء المدرعات'
        )

        url = reverse('training:results_entry', kwargs={'session_id': session.id})

        # 1. تسجيل دخول معلم مادة تعلم الآلة
        self.client.login(username='teacher_ml', password='Password123!')
        res_get_ml = self.client.get(url)
        self.assertEqual(res_get_ml.status_code, 200)
        html_ml = res_get_ml.content.decode('utf-8')
        # المادة المكلف بها تظهر كحقل إدخال
        self.assertIn(f'name="grade_{trainee.military_number}_{sub_ml.id}"', html_ml)
        # مادة المعلم الآخر لا تظهر كحقل إدخال إطلاقاً
        self.assertNotIn(f'name="grade_{trainee.military_number}_{sub_it.id}"', html_ml)
        # المواظبة لا تظهر كحقل إدخال للمعلم
        self.assertNotIn(f'name="att_{trainee.military_number}"', html_ml)

        # المعلم يحفظ درجات مادته بنجاح دون الحاجة لملء مادة غيره
        res_post_ml = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub_ml.id}': '85.0',
        })
        self.assertEqual(res_post_ml.status_code, 302)

        # التحقق من حفظ درجة المادة
        g_ml = TraineeSubjectGrade.objects.filter(enrollment=enrollment, subject=sub_ml).first()
        self.assertIsNotNone(g_ml)
        self.assertEqual(float(g_ml.score), 85.0)

        # التحقق من أن حالة الدارس لم تُعتمد بعد لأن باقي المواد قيد الرصد
        enrollment.refresh_from_db()
        self.assertFalse(enrollment.is_graded)

        # 2. تسجيل دخول مشرف الدورة
        self.client.login(username='supervisor_user', password='Password123!')
        res_get_sup = self.client.get(url)
        self.assertEqual(res_get_sup.status_code, 200)
        html_sup = res_get_sup.content.decode('utf-8')
        # مواد المعلمين تظهر للعرض فقط للمشرف ولا يمكن تعديلها كحقول
        self.assertNotIn(f'name="grade_{trainee.military_number}_{sub_ml.id}"', html_sup)
        self.assertNotIn(f'name="grade_{trainee.military_number}_{sub_it.id}"', html_sup)
        # حقل المواظبة متاح للمشرف
        self.assertIn(f'name="att_{trainee.military_number}"', html_sup)

        # محاولة تعديل درجة مادة من قبل المشرف (محظورة ويتم تجاهلها) مع رصد المواظبة
        res_post_sup = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub_ml.id}': '20.0',
            f'att_{trainee.military_number}': '18.0',
            f'cert_note_{trainee.military_number}': 'ملحوظة تجريبية من المشرف',
        })
        self.assertEqual(res_post_sup.status_code, 302)

        # درجة المادة لم تتغير وظلت كما وضعها المعلم
        g_ml.refresh_from_db()
        self.assertEqual(float(g_ml.score), 85.0)

        # المواظبة والملحوظة تم حفظهما بنجاح
        enrollment.refresh_from_db()
        self.assertEqual(float(enrollment.attendance_score), 18.0)
        self.assertEqual(enrollment.certificate_note, 'ملحوظة تجريبية من المشرف')

        # محاولة اعتماد الدورة قبل اكتمال درجات المعلم الآخر (مرفوضة)
        res_mark_incomplete = self.client.post(url, {
            'mark_completed': '1',
        })
        self.assertEqual(res_mark_incomplete.status_code, 302)
        session.refresh_from_db()
        self.assertEqual(session.status, 'active')

        # 3. تسجيل دخول معلم الشبكات ورصد درجته
        self.client.login(username='teacher_it', password='Password123!')
        res_post_it = self.client.post(url, {
            'save_grades': '1',
            f'grade_{trainee.military_number}_{sub_it.id}': '90.0',
        })
        self.assertEqual(res_post_it.status_code, 302)
        g_it = TraineeSubjectGrade.objects.filter(enrollment=enrollment, subject=sub_it).first()
        self.assertIsNotNone(g_it)
        self.assertEqual(float(g_it.score), 90.0)

        # 4. تسجيل دخول المشرف واعتماد النتيجة نهائياً بعد اكتمال جميع الدرجات
        self.client.login(username='supervisor_user', password='Password123!')
        res_mark_complete = self.client.post(url, {
            'mark_completed': '1',
        })
        self.assertEqual(res_mark_complete.status_code, 302)
        session.refresh_from_db()
        self.assertEqual(session.status, 'completed')

        enrollment.refresh_from_db()
        self.assertTrue(enrollment.is_graded)
        self.assertEqual(float(enrollment.total_score), 193.0)
        self.assertEqual(enrollment.grade_label, 'ممتاز (أ)')


class PhoneAndEmailValidationTests(TestCase):
    """اختبارات التحقق الصارم من قيود رقم الهاتف (10 أرقام فقط) والبريد الإلكتروني (صيغة صحيحة)"""

    def test_trainee_phone_validation_ten_digits_only(self):
        from training.forms import TraineeForm
        data = {
            'military_number': '12345678',
            'category': 'officer',
            'name': 'دارس اختبار الهاتف',
            'phone': '0912345678',  # 10 أرقام صحيحة
        }
        form = TraineeForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

        # 1. إدخال أقل من 10 أرقام (9 أرقام)
        data['phone'] = '091234567'
        form_short = TraineeForm(data=data)
        self.assertFalse(form_short.is_valid())
        self.assertIn('phone', form_short.errors)
        self.assertIn('10 أرقام', form_short.errors['phone'][0])

        # 2. إدخال أكثر من 10 أرقام (11 رقماً)
        data['phone'] = '09123456789'
        form_long = TraineeForm(data=data)
        self.assertFalse(form_long.is_valid())
        self.assertIn('phone', form_long.errors)

        # 3. إدخال حروف أو رموز
        data['phone'] = '091234567a'
        form_letters = TraineeForm(data=data)
        self.assertFalse(form_letters.is_valid())
        self.assertIn('phone', form_letters.errors)

        # 4. ترك الحقل فارغاً (مسموح لأنه اختياري)
        data['phone'] = ''
        form_empty = TraineeForm(data=data)
        self.assertTrue(form_empty.is_valid())

    def test_trainee_relative_phone_validation(self):
        from training.forms import TraineeForm
        data = {
            'military_number': '88776655',
            'category': 'nco',
            'name': 'دارس أقارب الهاتف',
            'relative_1_name': 'محمد علي',
            'relative_1_kinship': 'أخ',
            'relative_1_phone': '0123456789',  # 10 أرقام
        }
        form = TraineeForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

        # هاتف قريب 9 أرقام
        data['relative_1_phone'] = '012345678'
        form_invalid = TraineeForm(data=data)
        self.assertFalse(form_invalid.is_valid())
        self.assertIn('relative_1_phone', form_invalid.errors)

    def test_instructor_phone_validation(self):
        from training.forms import InstructorForm
        data = {
            'military_number': '33221100',
            'category': 'officer',
            'rank': 'نقيب',
            'name': 'معلم اختبار الهاتف',
            'phone': '0987654321',  # 10 أرقام
        }
        form = InstructorForm(data=data)
        self.assertTrue(form.is_valid(), form.errors)

        # إدخال رقم هاتف غير صالح (8 أرقام)
        data['phone'] = '09876543'
        form_invalid = InstructorForm(data=data)
        self.assertFalse(form_invalid.is_valid())
        self.assertIn('phone', form_invalid.errors)

    def test_user_create_and_edit_phone_and_email_validation(self):
        from training.forms import UserCreateForm, UserEditForm
        # 1. إنشاء مستخدم ببريد صالح وهاتف 10 أرقام
        create_data = {
            'username': 'phone_user_test',
            'password': 'Password123!',
            'first_name': 'مستخدم',
            'last_name': 'تجربة',
            'email': 'valid.user@example.com',
            'role': 'regular',
            'phone': '0911223344',
            'is_active': True,
        }
        form_create = UserCreateForm(data=create_data)
        self.assertTrue(form_create.is_valid(), form_create.errors)

        # بريد إلكتروني غير صالح
        create_data['email'] = 'invalid-email-format'
        form_bad_email = UserCreateForm(data=create_data)
        self.assertFalse(form_bad_email.is_valid())
        self.assertIn('email', form_bad_email.errors)

        # هاتف غير صالح (حروف)
        create_data['email'] = 'valid@example.com'
        create_data['phone'] = '09112233aa'
        form_bad_phone = UserCreateForm(data=create_data)
        self.assertFalse(form_bad_phone.is_valid())
        self.assertIn('phone', form_bad_phone.errors)

        # 2. فحص نموذج تعديل المستخدم
        user = User.objects.create_user(username='edit_test_u', password='Password123!', email='old@example.com')
        edit_data = {
            'first_name': 'معدل',
            'last_name': 'تجريبي',
            'email': 'not-an-email',
            'role': 'regular',
            'phone': '12345',  # 5 أرقام
            'is_active': True,
        }
        form_edit = UserEditForm(data=edit_data, instance=user)
        self.assertFalse(form_edit.is_valid())
        self.assertIn('email', form_edit.errors)
        self.assertIn('phone', form_edit.errors)

        # تصحيح البيانات
        edit_data['email'] = 'corrected@example.com'
        edit_data['phone'] = '0123456789'
        form_edit_ok = UserEditForm(data=edit_data, instance=user)
        self.assertTrue(form_edit_ok.is_valid(), form_edit_ok.errors)


class MovementOrderTests(TestCase):
    """اختبارات استخراج وتخصيص أمر التحرك الرسمي للضباط وضباط الصف"""

    def setUp(self):
        import datetime
        from training.models import MovementOrderSettings
        self.admin = User.objects.create_superuser(username='admin_mov', password='Password123!', email='admin@test.com')
        self.regular = User.objects.create_user(username='regular_mov', password='Password123!', email='regular@test.com')
        self.cat = CourseCategory.objects.create(name='تصنيف أوامر التحرك')
        self.course = Course.objects.create(name='دورة أمن سيبراني متقدمة', category=self.cat)
        self.session = CourseSession.objects.create(
            course=self.course,
            session_code='MOV-SESSION-01',
            start_date=datetime.date(2026, 2, 1),
            end_date=datetime.date(2026, 2, 28),
            status='completed'
        )
        self.officer_trainee = Trainee.objects.create(
            military_number='1234567890',
            name='علي أحمد النيل',
            category=TraineeCategory.OFFICER
        )
        self.officer_enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.officer_trainee,
            current_rank='ملازم تقني',
            current_unit='سلاح الإشارة',
            is_graded=True
        )
        self.nco_trainee = Trainee.objects.create(
            military_number='9876543210',
            name='أحمد صديق كرار',
            category=TraineeCategory.NCO
        )
        self.nco_enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.nco_trainee,
            current_rank='رقيب أول إدارة',
            current_unit='لواء القوات الخاصة',
            is_graded=True
        )

    def test_movement_order_model_defaults(self):
        """فحص إنشاء واسترجاع إعدادات أمر التحرك بالقيم الافتراضية المعتمدة"""
        settings = MovementOrderSettings.get_settings()
        self.assertEqual(settings.security_label, 'محظور')
        self.assertEqual(settings.order_title, 'أمر تــــحـــــرك')
        self.assertIn('الصادر بأمر سيادة', settings.issuing_authority_text)
        self.assertIn('معهد', settings.from_location)
        self.assertIn('شعبـــــــــــــــــــة التدريب', settings.to_location_default)
        self.assertIn('بموجب هذا الأمر', settings.admin_instructions)

    def test_movement_order_view_for_officer(self):
        """فحص استخراج أمر التحرك لدارس ضابط والتأكد من مطابقة نموذج الضابط وتوجيه الوحدة وتقديم رقم البطاقة"""
        self.client.login(username='admin_mov', password='Password123!')
        url = reverse('training:movement_order', args=[self.officer_enrollment.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context['is_officer'])
        self.assertEqual(res.context['destination_unit'], 'سلاح الإشارة')
        self.assertIn('سلاح الإشارة', res.context['admin_instructions'])
        self.assertIn('سلاح الإشارة', res.context['copy_to_1'])

        content = res.content.decode('utf-8')
        self.assertIn('علي أحمد النيل', content)
        self.assertIn('رقم البطاقة', content)
        self.assertIn('1234567890', content)
        self.assertIn('محظور', content)
        self.assertIn('أمر تــــحـــــرك', content)

        # التأكد من أن رقم البطاقة يسبق الاسم في ترتيب العرض داخل سطر بيانات الدارس الضابط
        idx_line = content.find('officer-line')
        idx_table = content.find('details-table', idx_line)
        officer_line = content[idx_line:idx_table]
        card_idx = officer_line.find('رقم البطاقة')
        name_idx = officer_line.find('علي أحمد النيل')
        self.assertTrue(0 <= card_idx < name_idx, "يجب أن يسبق رقم البطاقة اسم الدارس في نموذج الضابط")

        # التأكد من ظهور العلامة المائية الشفافة وخاصية المزج خلف النص
        self.assertIn('movement_order_watermark.png', content)
        self.assertIn('mix-blend-mode: multiply', content)

    def test_movement_order_view_for_nco(self):
        """فحص استخراج أمر التحرك لدارس ضابط صف والتأكد من مطابقة نموذج ضابط الصف"""
        self.client.login(username='admin_mov', password='Password123!')
        url = reverse('training:movement_order', args=[self.nco_enrollment.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context['is_officer'])
        content = res.content.decode('utf-8')
        self.assertIn('أحمد صديق كرار', content)
        self.assertIn('الأشخاص', content)
        self.assertIn('نمرة', content)
        self.assertIn('9876543210', content)

    def test_movement_order_type_toggle(self):
        """فحص إمكانية تبديل النموذج عبر المعلمة type"""
        self.client.login(username='admin_mov', password='Password123!')
        url = reverse('training:movement_order', args=[self.officer_enrollment.id])
        res = self.client.get(url + '?type=nco')
        self.assertEqual(res.status_code, 200)
        self.assertFalse(res.context['is_officer'])

    def test_movement_order_settings_update(self):
        """فحص تعديل وحفظ إعدادات أمر التحرك من لوحة تحكم الإدارة"""
        self.client.login(username='admin_mov', password='Password123!')
        url = reverse('training:movement_order_settings_update')
        post_data = {
            'bismillah_text': 'بسم الله الرحمن الرحيم',
            'security_label': 'سري جداً',
            'order_title': 'أمر تحرك عسكري',
            'issuing_authority_text': 'نص ديباجة تجريبي جديد',
            'from_location': 'معهد الحاسوب',
            'to_location_default': 'القيادة العامة',
            'arms_default': 'مسدس',
            'ammunition_default': '10 طلقات',
            'purpose_prefix': 'إكمال دورة ',
            'clothing_instructions': 'الميداني',
            'travel_means': 'طيران عسكري',
            'ratification_text': 'رئيس هيئة الأركان',
            'admin_instructions': 'تعليمات تجريبية محدثة',
            'certificate_declaration': 'إقرار المسافر المحدث',
            'signer_rank': 'لواء ركن',
            'signer_name': 'محمد الفاتح',
            'signer_title': 'ع/قائد القوات',
            'signer_dept': 'هيئة العمليات',
            'copy_to_1': 'نسخة للقيادة',
            'copy_to_2': 'نسخة للفرع',
            'watermark_opacity': 0.20
        }
        res = self.client.post(url, post_data)
        self.assertEqual(res.status_code, 302)
        settings = MovementOrderSettings.get_settings()
        self.assertEqual(settings.security_label, 'سري جداً')
        self.assertEqual(settings.order_title, 'أمر تحرك عسكري')
        self.assertEqual(settings.arms_default, 'مسدس')

    def test_movement_order_for_dropped_trainee(self):
        """فحص استخراج أمر التحرك للدارس المقطوع عن الدورة أثناء انعقادها والتأكد من صيغة الغرض (قطع دورة)"""
        # تجهيز دارس مقطوع عن الدورة
        dropped_trainee = Trainee.objects.create(
            military_number='5554443322',
            name='طارق عبد الرحمن حسن',
            category=TraineeCategory.OFFICER
        )
        dropped_enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=dropped_trainee,
            current_rank='نقيب',
            current_unit='سلاح المهندسين',
            is_dropped=True,
            drop_reason='ظروف إدارية عاجلة'
        )

        self.client.login(username='admin_mov', password='Password123!')
        url = reverse('training:movement_order', args=[dropped_enrollment.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertIn('قطع', res.context['purpose'])
        self.assertIn('دورة أمن سيبراني متقدمة', res.context['purpose'])
        self.assertEqual(res.context['destination_unit'], 'سلاح المهندسين')

        content = res.content.decode('utf-8')
        self.assertIn('طارق عبد الرحمن حسن', content)
        self.assertIn('5554443322', content)
        self.assertIn('سلاح المهندسين', content)
        self.assertIn('قطع دورة', content)

    def test_course_session_manage_shows_movement_order_button_beside_drop(self):
        """فحص ظهور زر أمر التحرك بجانب حالة قطع الدورة في صفحة إدارة الدورة"""
        dropped_trainee = Trainee.objects.create(
            military_number='7778889900',
            name='خالد عثمان إبراهيم',
            category=TraineeCategory.NCO
        )
        dropped_en = CourseEnrollment.objects.create(
            session=self.session,
            trainee=dropped_trainee,
            current_rank='مساعد',
            current_unit='سلاح المدرعات',
            is_dropped=True,
            drop_reason='أمر تحرك'
        )

        self.client.login(username='admin_mov', password='Password123!')
        url = reverse('training:course_session_manage', args=[self.session.id])
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)

        content = res.content.decode('utf-8')
        self.assertIn('تم قطع الدورة', content)
        # التحقق من وجود رابط استخراج أمر التحرك للدارس المقطوع
        mov_url = reverse('training:movement_order', args=[dropped_en.id])
        self.assertIn(mov_url, content)
        self.assertIn('أمر التحرك', content)


class ComprehensiveReportsAndExcelTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username='admin_report',
            password='Password123!',
            email='admin@report.com'
        )
        self.category = CourseCategory.objects.create(name='تصنيف القيادة والسيطرة')
        self.course = Course.objects.create(name='دورة أركان متقدمة', category=self.category)
        self.supervisor = Instructor.objects.create(
            name='عقيد ركن محمد سالم',
            military_number='112233',
            rank='عقيد ركن'
        )
        today = timezone.now().date()
        self.session = CourseSession.objects.create(
            course=self.course,
            session_code='دورة 101 أركان',
            start_date=today - timedelta(days=20),
            end_date=today + timedelta(days=10),
            supervisor=self.supervisor,
            status='completed'
        )
        self.active_session = CourseSession.objects.create(
            course=self.course,
            session_code='دورة 102 أركان جارية',
            start_date=today - timedelta(days=5),
            end_date=today + timedelta(days=25),
            supervisor=self.supervisor,
            status='active'
        )
        self.trainee_active = Trainee.objects.create(
            military_number='99112299',
            name='ملازم أول سامر فؤاد',
            category=TraineeCategory.OFFICER,
            force='القوات الجوية',
            unit='قاعدة الشهيد الجوية'
        )
        self.enrollment_active = CourseEnrollment.objects.create(
            session=self.active_session,
            trainee=self.trainee_active,
            current_rank='ملازم أول',
            current_force='القوات الجوية',
            current_unit='قاعدة الشهيد الجوية'
        )
        self.trainee1 = Trainee.objects.create(
            military_number='99112233',
            name='رائد خالد أحمد',
            category=TraineeCategory.OFFICER,
            force='القوات البرية',
            unit='اللواء الأول مشاة'
        )
        self.enrollment1 = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee1,
            current_rank='رائد',
            current_force='القوات البرية',
            current_unit='اللواء الأول مشاة',
            is_graded=True,
            percentage=88.5,
            grade_label='ممتاز'
        )
        self.trainee2 = Trainee.objects.create(
            military_number='99112244',
            name='نقيب حسام الدين',
            category=TraineeCategory.OFFICER,
            force='الدفاع الجوي',
            unit='كتيبة الصواريخ'
        )
        self.enrollment2 = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee2,
            current_rank='نقيب',
            current_force='الدفاع الجوي',
            current_unit='كتيبة الصواريخ',
            is_dropped=True,
            drop_reason='أسباب طارئة'
        )
        self.trainee3 = Trainee.objects.create(
            military_number='99112255',
            name='محمد علي إدريس',
            category=TraineeCategory.CIVILIAN
        )
        self.enrollment3 = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee3,
            current_rank='',
            current_force='',
            current_unit=''
        )

    def test_default_date_range_is_90_days(self):
        """التحقق من أن النطاق الزمني الافتراضي هو 3 أشهر (90 يوماً حتى اليوم)"""
        start, end = get_default_date_range()
        self.assertEqual((end - start).days, 90)
        self.assertEqual(end, timezone.now().date())

    def test_get_report_data_trainees(self):
        """التحقق من تجميع واستخراج تقرير الدارسين الشامل مع النسب والفلاتر ومراعاة الرتب الفارغة"""
        data = get_report_data({'report_type': 'trainees'})
        self.assertEqual(data['report_type'], 'trainees')
        self.assertEqual(len(data['records']), 3)
        self.assertEqual(data['stats']['total'], 3)
        self.assertEqual(data['stats']['passed'], 1)
        self.assertEqual(data['stats']['dropped'], 1)
        # التحقق من أن الدارس صاحب الرتبة الفارغة يعرض '---' دون التسبب في خطأ
        blank_rank_trainee = next(r for r in data['records'] if r['military_number'] == '99112255')
        self.assertEqual(blank_rank_trainee['rank'], '---')

    def test_get_report_data_filter_by_force_and_unit(self):
        """التحقق من فلترة تقرير الدارسين بالقوة والوحدة"""
        data = get_report_data({
            'report_type': 'trainees',
            'force': 'القوات البرية',
            'unit': 'اللواء الأول مشاة'
        })
        self.assertEqual(len(data['records']), 1)
        self.assertEqual(data['records'][0]['military_number'], '99112233')

    def test_get_report_data_sessions(self):
        """التحقق من استخراج تقرير الدورات المنعقدة ونسب النجاح"""
        data = get_report_data({'report_type': 'sessions'})
        self.assertEqual(data['report_type'], 'sessions')
        self.assertGreaterEqual(len(data['records']), 1)
        self.assertIn('دورة أركان متقدمة', [r['course_name'] for r in data['records']])

    def test_get_report_data_units_forces(self):
        """التحقق من استخراج تقرير توزيع الوحدات والقوى العسكرية"""
        data = get_report_data({'report_type': 'units_forces'})
        self.assertEqual(data['report_type'], 'units_forces')
        self.assertGreaterEqual(len(data['records']), 1)

    def test_get_report_data_dropped_trainees(self):
        """التحقق من استخراج تقرير الدارسين المقطوعين وأوامر التحرك"""
        data = get_report_data({'report_type': 'dropped_trainees'})
        self.assertEqual(data['report_type'], 'dropped_trainees')
        self.assertEqual(len(data['records']), 1)
        self.assertEqual(data['records'][0]['military_number'], '99112244')

    def test_get_report_data_instructors(self):
        """التحقق من استخراج تقرير هيئة التعليم وتكليفات المعلمين"""
        data = get_report_data({'report_type': 'instructors'})
        self.assertEqual(data['report_type'], 'instructors')
        self.assertGreaterEqual(len(data['records']), 1)

    def test_export_report_to_excel_structure(self):
        """التحقق من توليد ملف إكسل سليم ومنسق بالكامل واتجاه من اليمين لليسار RTL"""
        data = get_report_data({'report_type': 'trainees'})
        excel_bytes = export_report_to_excel(data)
        self.assertTrue(len(excel_bytes) > 0)
        
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        self.assertTrue(ws.views.sheetView[0].rightToLeft)
        # التحقق من وجود الترويسة العسكرية
        self.assertIn('معهد نظم المعلومات', ws.cell(row=1, column=1).value)

    def test_reports_hub_view_access(self):
        """التحقق من صلاحيات الوصول لقسم التقارير الشاملة وعرض الصفحة"""
        # غير مسجل
        res = self.client.get(reverse('training:reports_hub'))
        self.assertEqual(res.status_code, 302)

        # مسجل كمدير نظام
        self.client.login(username='admin_report', password='Password123!')
        res = self.client.get(reverse('training:reports_hub'))
        self.assertEqual(res.status_code, 200)
        self.assertIn('report_data', res.context)
        self.assertIn('categories', res.context)
        self.assertIn('courses', res.context)
        self.assertIn('sessions', res.context)
        self.assertContains(res, 'منظومة التقارير الشاملة')

    def test_reports_export_excel_view_download(self):
        """التحقق من استجابة تنزيل ملف الإكسل عبر الرابط"""
        self.client.login(username='admin_report', password='Password123!')
        res = self.client.get(reverse('training:reports_export_excel'), {'report_type': 'trainees'})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertIn('attachment;', res['Content-Disposition'])

    def test_filter_by_session_status(self):
        """التحقق من فلترة التقارير بحالة الدورة: معتمدة ومحفوظة (الافتراضي) أو منعقدة حالياً أو الكل"""
        # الافتراضي: المعتمدة والمحفوظة فقط
        data_default = get_report_data({'report_type': 'trainees'})
        self.assertEqual(data_default['session_status'], 'completed')
        mils_default = [r['military_number'] for r in data_default['records']]
        self.assertIn('99112233', mils_default)
        self.assertNotIn('99112299', mils_default)

        # المنعقدة حالياً فقط
        data_active = get_report_data({'report_type': 'trainees', 'session_status': 'active'})
        self.assertEqual(data_active['session_status'], 'active')
        mils_active = [r['military_number'] for r in data_active['records']]
        self.assertIn('99112299', mils_active)
        self.assertNotIn('99112233', mils_active)

        # الكل: المعتمدة والمنعقدة
        data_all = get_report_data({'report_type': 'trainees', 'session_status': 'all'})
        self.assertEqual(data_all['session_status'], 'all')
        mils_all = [r['military_number'] for r in data_all['records']]
        self.assertIn('99112233', mils_all)
        self.assertIn('99112299', mils_all)

    def test_reports_hub_cascading_and_searchable_dropdowns(self):
        """التحقق من بيانات الترابط الديناميكي وظهور كافة القوى والبحث في القوائم المنسدلة"""
        self.client.force_login(self.admin)
        res = self.client.get(reverse('training:reports_hub'))
        self.assertEqual(res.status_code, 200)

        # 1. التحقق من وجود كافة القوى العسكرية القياسية في القائمة دائماً
        forces = res.context['forces']
        for std_force in ['القوات البرية', 'القوات البحرية', 'القوات الجوية', 'قوات الدفاع الجوي']:
            self.assertIn(std_force, forces)

        # 2. التحقق من وجود خريطة الربط بين القوى والوحدات
        force_units_map = json.loads(res.context['force_units_map_json'])
        self.assertIn('القوات البرية', force_units_map)
        self.assertIn('القوات البحرية', force_units_map)
        self.assertIn('القوات الجوية', force_units_map)
        self.assertIn('قوات الدفاع الجوي', force_units_map)
        self.assertTrue(len(force_units_map['القوات البرية']) > 0)

        # 3. التحقق من بيانات ترابط الدورات والدفعات
        courses_data = json.loads(res.context['courses_json'])
        self.assertTrue(any(c['category_id'] == self.category.id for c in courses_data))

        sessions_data = json.loads(res.context['sessions_json'])
        self.assertTrue(any(s['course_id'] == self.course.id for s in sessions_data))

        # 4. التحقق من اشتمال القالب على فئات البحث المنسدل
        content = res.content.decode('utf-8')
        self.assertIn('searchable-select', content)
        self.assertIn('filter_category', content)
        self.assertIn('filter_course', content)
        self.assertIn('filter_session', content)
        self.assertIn('filter_force', content)
        self.assertIn('filter_unit', content)

    def test_admin_report_print_official_layout(self):
        """التحقق من مطابقة تقرير الطباعة الرسمي للتصميم العسكري المعتمد وتطبيق الفلاتر"""
        self.client.force_login(self.admin)
        res = self.client.get(reverse('training:admin_report_print'))
        self.assertEqual(res.status_code, 200)

        content = res.content.decode('utf-8')
        # التحقق من نصوص العناوين الرئيسية في الترويسة
        self.assertIn('التقرير الإحصائي والتحليلي العام لمؤشرات التدريب والنتائج', content)
        self.assertIn('أولاً: ملخص المؤشرات العامة ومخرجات التأهيل (KPIs)', content)
        self.assertIn('ثانياً: التوزيع التكراري للتقديرات والنتائج المعتمدة', content)
        self.assertIn('ثالثاً: توزيع الدارسين بحسب القوات والتشكيلات', content)
        self.assertIn('إعداد وضبط الإحصاء', content)
        self.assertIn('رئيس فرع الإحصاء والنتائج', content)
        self.assertIn('قائد معهد نظم المعلومات والإحصاء', content)

        # التحقق من تطبيق الفلاتر عند تمريرها
        res_filtered = self.client.get(reverse('training:admin_report_print'), {
            'force': 'القوات البرية',
            'session_status': 'completed',
        })
        self.assertEqual(res_filtered.status_code, 200)
        self.assertEqual(res_filtered.context['trainees_total'], 1)
        self.assertIn('القوات البرية', res_filtered.context['filters_summary'])

















