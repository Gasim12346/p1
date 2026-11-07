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
            rank='نقيب',
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
        self.client.login(username='user_test', password='Password123!')
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
            rank='نقيب',
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
            rank='رائد',
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
            rank='نقيب',
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





