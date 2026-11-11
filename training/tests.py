from datetime import date
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from training.models import (
    UserProfile, UserRole, CourseCategory, Course, Subject,
    CourseSession, Trainee, TraineeCategory, CourseEnrollment,
    TraineeSubjectGrade, Instructor, InstructorCategory, SessionSubjectInstructor,
    CertificateSettings
)


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














