from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from training.models import UserProfile, UserRole


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
        """التحقق من حظر الوصول غير المصرح به لجميع الواجهات الرئيسية والتحويل لصفحة تسجيل الدخول"""
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
        """تسجيل دخول الأدمن يحوله مباشرة وبشكل منعزل إلى واجهة الأدمن المنفصلة"""
        response = self.client.post(reverse('training:login'), {
            'username': 'admin_test',
            'password': 'Password123!',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('training:admin_dashboard'))

        # الدخول إلى واجهة الأدمن بنجاح
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
        """حظر المستخدم العادي بشكل صارم وتام من الدخول إلى واجهة الأدمن المنفصلة"""
        self.client.login(username='user_test', password='Password123!')
        response = self.client.get(reverse('training:admin_dashboard'))
        # يتم تحويله إلى الرئيسية
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('training:home'))

    def test_home_page_does_not_contain_admin_banner(self):
        """التحقق من إزالة أي بنر أو عناصر تحكم خاصة بالأدمن من الواجهة الرئيسية"""
        self.client.login(username='admin_test', password='Password123!')
        response = self.client.get(reverse('training:home'))
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # التأكد من إزالة البنر المدموج
        self.assertNotIn('لوحة القيادة المنفصلة، إدارة المستخدمين', content)
        self.assertNotIn('دخول لوحة تحكم الأدمن المنفصلة', content)

    def test_home_page_contains_logout_button(self):
        """التحقق من وجود زر تسجيل الخروج في الواجهة الرئيسية للمستخدم"""
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
            rank='ملازم',
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

