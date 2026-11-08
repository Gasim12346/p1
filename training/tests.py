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

        # التحقق من تسجيل الطالب
        enrollment = session.enrollments.filter(trainee=self.trainee).first()
        self.assertIsNotNone(enrollment)
        self.assertEqual(enrollment.current_rank, 'ملازم أول')

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







