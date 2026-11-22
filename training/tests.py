import io
import json
from decimal import Decimal
import datetime
from datetime import date, timedelta
import openpyxl
from django.utils import timezone
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from training.models import (
    Institute, UserProfile, UserRole, CourseCategory, Course, Subject,
    CourseSession, Trainee, TraineeCategory, CourseEnrollment,
    TraineeSubjectGrade, Instructor, InstructorCategory, SessionSubjectInstructor,
    CertificateSettings, MovementOrderSettings, DisciplineInfraction, ActivityLog,
    ActivityCategory
)
from training.services import initialize_new_institute
from training.reports import (
    get_default_date_range,
    get_report_data,
    export_report_to_excel,
    get_sessions_subjects_summary,
)
from training.views import calculate_next_course_session_code
from training.forms import UserCreateForm, UserEditForm


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

    def test_results_center_trainee_category_filters(self):
        """التحقق من عمل فلتر تصنيف وفئة الدارسين في مركز النتائج والسجل التاريخي"""
        self.client.login(username='user_test', password='Password123!')
        from training.models import CourseCategory, Course, CourseSession

        cat = CourseCategory.objects.create(name="تصنيف اختبار فلاتر النتائج")
        course_officer = Course.objects.create(name="دورة قيادة ضباط", category=cat)
        course_nco = Course.objects.create(name="دورة إشارة ضباط صف", category=cat)
        course_joint = Course.objects.create(name="دورة أمن مشتركة", category=cat)

        session_officer = CourseSession.objects.create(
            course=course_officer,
            session_code="دفعة-ضباط-01",
            target_category="officer",
            start_date="2026-02-01",
            end_date="2026-02-28",
            status="active"
        )
        session_nco = CourseSession.objects.create(
            course=course_nco,
            session_code="دفعة-صف-01",
            target_category="nco",
            start_date="2026-02-01",
            end_date="2026-02-28",
            status="active"
        )
        session_joint_archived = CourseSession.objects.create(
            course=course_joint,
            session_code="دفعة-مشتركة-01",
            target_category="joint",
            start_date="2026-01-01",
            end_date="2026-01-25",
            status="completed"
        )

        # 1. فحص فلترة دورات الضباط في تبويب رصد الدرجات
        res_officer = self.client.get(reverse('training:results_center'), {'tab': 'sessions', 'session_target_cat': 'officer'})
        self.assertEqual(res_officer.status_code, 200)
        self.assertIn(session_officer, res_officer.context['sessions'])
        self.assertNotIn(session_nco, res_officer.context['sessions'])
        self.assertEqual(res_officer.context['session_target_cat'], 'officer')

        # 2. فحص فلترة دورات ضباط الصف في تبويب رصد الدرجات
        res_nco = self.client.get(reverse('training:results_center'), {'tab': 'sessions', 'session_target_cat': 'nco'})
        self.assertEqual(res_nco.status_code, 200)
        self.assertIn(session_nco, res_nco.context['sessions'])
        self.assertNotIn(session_officer, res_nco.context['sessions'])

        # 3. فحص فلترة السجل التاريخي حسب الفئة المشتركة
        res_joint_arch = self.client.get(reverse('training:results_center'), {'tab': 'archive', 'archive_target_cat': 'joint'})
        self.assertEqual(res_joint_arch.status_code, 200)
        self.assertIn(session_joint_archived, res_joint_arch.context['archive_sessions'])
        self.assertNotIn(session_officer, res_joint_arch.context['archive_sessions'])

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

        today = timezone.localdate()
        post_data = {
            'category': str(self.cat.id),
            'course': str(self.course.id),
            'session_code': 'الدفعة التجريبية 2026',
            'start_date': (today + datetime.timedelta(days=1)).strftime('%Y-%m-%d'),
            'end_date': (today + datetime.timedelta(days=30)).strftime('%Y-%m-%d'),
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

        today = timezone.localdate()
        t_num = self.trainee.military_number
        base_data = {
            'category': str(self.cat.id),
            'course': str(self.course.id),
            'session_code': 'دفعة فحص القيود',
            'start_date': (today + datetime.timedelta(days=2)).strftime('%Y-%m-%d'),
            'end_date': (today + datetime.timedelta(days=32)).strftime('%Y-%m-%d'),
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

    def test_course_session_date_constraints_model_clean(self):
        """التحقق من قيد تاريخ الدورة على مستوى النموذج: تاريخ النهاية لا يمكن أن يكون قبل أو في نفس يوم البداية"""
        from django.core.exceptions import ValidationError
        from training.models import CourseSession
        import datetime

        # 1. محاولة ضبط تاريخ النهاية في نفس يوم تاريخ البداية
        session_same_day = CourseSession(
            course=self.course,
            session_code='دفعة-اختبار-تاريخ-1',
            start_date=datetime.date(2026, 6, 1),
            end_date=datetime.date(2026, 6, 1)
        )
        with self.assertRaises(ValidationError) as ctx:
            session_same_day.clean()
        self.assertIn('end_date', ctx.exception.message_dict)

        # 2. محاولة ضبط تاريخ النهاية قبل تاريخ البداية
        session_before = CourseSession(
            course=self.course,
            session_code='دفعة-اختبار-تاريخ-2',
            start_date=datetime.date(2026, 6, 10),
            end_date=datetime.date(2026, 6, 5)
        )
        with self.assertRaises(ValidationError) as ctx:
            session_before.clean()
        self.assertIn('end_date', ctx.exception.message_dict)

        # 3. تاريخ النهاية بعد تاريخ البداية (صحيح)
        session_valid = CourseSession(
            course=self.course,
            session_code='دفعة-اختبار-تاريخ-3',
            start_date=datetime.date(2026, 6, 1),
            end_date=datetime.date(2026, 6, 2)
        )
        session_valid.clean()  # لا يرمي أي استثناء

    def test_course_session_form_date_constraints(self):
        """التحقق من قيود تواريخ الدورة في نموذج إدخال وتعديل الانعقاد"""
        from apps.academic.forms import CourseSessionForm
        from django.utils import timezone
        import datetime

        today = timezone.localdate()
        past_date = today - datetime.timedelta(days=2)
        tomorrow = today + datetime.timedelta(days=1)

        # 1. بداية الدورة في الماضي عند إنشاء دورة جديدة
        form_past_start = CourseSessionForm(data={
            'course': self.course.id,
            'target_category': 'officer',
            'session_code': '99',
            'start_date': past_date,
            'end_date': tomorrow,
            'status': 'active'
        })
        self.assertFalse(form_past_start.is_valid())
        self.assertIn('start_date', form_past_start.errors)

        # 2. تاريخ النهاية في نفس يوم البداية
        form_same_day = CourseSessionForm(data={
            'course': self.course.id,
            'target_category': 'officer',
            'session_code': '99',
            'start_date': today,
            'end_date': today,
            'status': 'active'
        })
        self.assertFalse(form_same_day.is_valid())
        self.assertIn('end_date', form_same_day.errors)

    def test_course_session_create_view_date_constraints(self):
        """التحقق من منع إنشاء دورة بتاريخ بداية في الماضي أو تاريخ نهاية يسبق أو يماثل تاريخ البداية في شاشة الإنشاء"""
        from django.utils import timezone
        import datetime

        self.client.login(username='admin_constraints', password='Password123!')
        today = timezone.localdate()
        past_date = today - datetime.timedelta(days=3)
        future_start = today + datetime.timedelta(days=5)

        # محاولة إرسال تاريخ بداية في الماضي
        res_past = self.client.post(reverse('training:course_session_create'), {
            'course': str(self.course.id),
            'target_category': 'officer',
            'session_code': '101',
            'start_date': past_date.strftime('%Y-%m-%d'),
            'end_date': (past_date + datetime.timedelta(days=10)).strftime('%Y-%m-%d'),
            'selected_trainees': [self.trainee.military_number],
        })
        self.assertEqual(res_past.status_code, 200)
        messages_past = list(res_past.context['messages'])
        self.assertTrue(any('لا يمكن اختيار تاريخ بداية قبل تاريخ اليوم الحالي' in str(m) for m in messages_past))

        # محاولة إرسال تاريخ نهاية في نفس يوم تاريخ البداية
        res_same = self.client.post(reverse('training:course_session_create'), {
            'course': str(self.course.id),
            'target_category': 'officer',
            'session_code': '102',
            'start_date': future_start.strftime('%Y-%m-%d'),
            'end_date': future_start.strftime('%Y-%m-%d'),
            'selected_trainees': [self.trainee.military_number],
        })
        self.assertEqual(res_same.status_code, 200)
        messages_same = list(res_same.context['messages'])
        self.assertTrue(any('تاريخ نهاية الدورة يجب أن يكون بعد تاريخ بداية الدورة بيوم على الأقل' in str(m) for m in messages_same))


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

        # 3. التحقق من توحيد رقم الدفعة للدورات الخاصة على مستوى التصنيف وكافة المواد والفئات
        course_pc = Course.objects.create(name='أساسيات حاسوب', category=cat_special)
        course_net = Course.objects.create(name='شبكات', category=cat_special)

        # انعقاد دورة أساسيات حاسوب (ضباط) في 2026 يأخذ رقم 1
        num_pc = calculate_next_course_session_code(course_pc, datetime.date(2026, 3, 1), target_category='officer')
        self.assertEqual(num_pc, '1')
        CourseSession.objects.create(
            course=course_pc,
            target_category='officer',
            session_code='1',
            start_date=datetime.date(2026, 3, 1),
            end_date=datetime.date(2026, 3, 30)
        )

        # انعقاد دورة شبكات (ضباط صف) في 2026 تحت نفس التصنيف يأخذ رقم 2 تلقائياً
        num_net = calculate_next_course_session_code(course_net, datetime.date(2026, 4, 1), target_category='nco')
        self.assertEqual(num_net, '2')
        CourseSession.objects.create(
            course=course_net,
            target_category='nco',
            session_code='2',
            start_date=datetime.date(2026, 4, 1),
            end_date=datetime.date(2026, 4, 30)
        )

        # انعقاد دورة ذكاء اصطناعي (مشتركة) في 2026 تحت نفس التصنيف يأخذ رقم 3 تلقائياً
        course_ai = Course.objects.create(name='ذكاء اصطناعي', category=cat_special)
        num_ai = calculate_next_course_session_code(course_ai, datetime.date(2026, 5, 1), target_category='joint')
        self.assertEqual(num_ai, '3')

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
        """التحقق من استخراج تقرير الدورات المنعقدة ونسب النجاح مع بيان المواد المنفذة"""
        data = get_report_data({'report_type': 'sessions'})
        self.assertEqual(data['report_type'], 'sessions')
        self.assertGreaterEqual(len(data['records']), 1)
        self.assertIn('دورة أركان متقدمة', [r['course_name'] for r in data['records']])
        self.assertIn('subjects_count', [c['key'] for c in data['columns']])

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
        self.assertTrue(any('target_category' in s for s in sessions_data))

        # 4. التحقق من اشتمال القالب على فئات البحث المنسدل وترتيب الحقول والربط
        content = res.content.decode('utf-8')
        self.assertIn('searchable-select', content)
        self.assertIn('filter_category', content)
        self.assertIn('filter_course', content)
        self.assertIn('filter_trainee_category', content)
        self.assertIn('filter_session', content)
        self.assertIn('onTraineeCategoryChange()', content)
        self.assertIn('رقم دفعة الدورة', content)
        self.assertIn('filter_force', content)
        self.assertIn('filter_unit', content)

    def test_reports_hub_session_filter_by_trainee_category(self):
        """التحقق من فلترة تقارير الدارسين والدفعات وفق تصنيف الدارس (ضباط أو ضباط صف)"""
        self.client.force_login(self.admin)
        res_officer = self.client.get(reverse('training:reports_hub'), {
            'report_type': 'trainees',
            'trainee_category': 'officer',
            'all_dates': '1'
        })
        self.assertEqual(res_officer.status_code, 200)
        # التحقق من أن سجلات الضباط فقط هي المعروضة
        for rec in res_officer.context['report_data']['records']:
            self.assertEqual(rec['category_label'], 'ضباط')

    def test_admin_report_print_official_layout(self):
        """التحقق من مطابقة تقرير الطباعة الرسمي للتصميم العسكري المعتمد وتطبيق الفلاتر"""
        self.client.force_login(self.admin)
        res = self.client.get(reverse('training:admin_report_print'))
        self.assertEqual(res.status_code, 200)

        content = res.content.decode('utf-8')
        # التحقق من نصوص العناوين الرئيسية في الترويسة لتقرير عام متعدد الدورات (حذف التوزيع التكراري)
        self.assertIn('التقرير الإحصائي والتحليلي العام لمؤشرات التدريب والنتائج', content)
        self.assertIn('أولاً: ملخص المؤشرات العامة ومخرجات التأهيل (KPIs)', content)
        self.assertNotIn('التوزيع التكراري للتقديرات والنتائج المعتمدة', content)
        self.assertIn('ثانياً: توزيع الدارسين بحسب القوات والتشكيلات', content)
        self.assertIn('إعداد وضبط الإحصاء', content)
        self.assertIn('رئيس فرع الإحصاء والنتائج', content)
        self.assertIn('قائد معهد نظم المعلومات والإحصاء', content)

        # التحقق من تقرير دورة واحدة محددة (ظهور التوزيع التكراري وكافة تفاصيل الدورة)
        res_filtered = self.client.get(reverse('training:admin_report_print'), {
            'force': 'القوات البرية',
            'course_id': str(self.course.id),
            'session_id': str(self.session.id),
            'category_id': str(self.category.id),
            'session_status': 'completed',
        })
        self.assertEqual(res_filtered.status_code, 200)
        self.assertEqual(res_filtered.context['trainees_total'], 1)
        self.assertIn('القوات البرية', res_filtered.context['filters_summary'])
        content_filtered = res_filtered.content.decode('utf-8')
        # التحقق من ظهور تصنيف الدورة واسم الدورة والدفعة أسفل العنوان الرئيسي
        self.assertIn(f"التصنيف: {self.category.name}", content_filtered)
        self.assertIn(f"الدورة: {self.course.name}", content_filtered)
        self.assertIn(f"الدفعة: {self.session.session_code}", content_filtered)
        # التحقق من وجود جدول التوزيع التكراري للتقديرات في تقرير الدورة الواحدة
        self.assertIn('ثانياً: التوزيع التكراري للتقديرات والنتائج المعتمدة', content_filtered)
        self.assertIn('ثالثاً: توزيع الدارسين بحسب القوات والتشكيلات', content_filtered)

    def test_trainees_report_custom_title_and_columns_exclusion(self):
        """التحقق من وضع الدورة والدفعة والقوة وحالة الدورة في العنوان وحذفها من أعمدة الجدول عند التخصيص"""
        res = get_report_data({
            'report_type': 'trainees',
            'course_id': str(self.course.id),
            'session_id': str(self.session.id),
            'force': 'القوات البرية',
            'session_status': 'completed',
        })
        # التحقق من بناء العنوان المخصص
        self.assertIn('دورة أركان متقدمة', res['report_title'])
        self.assertIn('دورة 101 أركان', res['report_title'])
        self.assertIn('القوات البرية', res['report_title'])
        self.assertIn('معتمدة ومحفوظة', res['report_title'])

        col_keys = [c['key'] for c in res['columns']]
        # التحقق من حذف الأعمدة الـ 4 من الجدول التفصيلي
        self.assertNotIn('course_name', col_keys)
        self.assertNotIn('session_code', col_keys)
        self.assertNotIn('session_status_label', col_keys)
        self.assertNotIn('force', col_keys)
        # التحقق من حذف الأعمدة المخصصة وحذف التصنيف
        self.assertNotIn('category_label', col_keys)
        # التحقق من الترتيب الدقيق للعناوين: # ثم النمرة ثم الرتبة ثم اسم الدارس
        self.assertEqual(col_keys[:4], ['index', 'military_number', 'rank', 'name'])
        # التحقق من بقاء بقية الأعمدة الأساسية
        for k in ['index', 'military_number', 'rank', 'name', 'unit', 'percentage', 'grade_label', 'result_status']:
            self.assertIn(k, col_keys)

        # التحقق من أن ملف الإكسل المصدر يحتوي على العنوان المخصص والأعمدة النظيفة بالترتيب الجديد
        excel_bytes = export_report_to_excel(res)
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        ws = wb.active
        self.assertEqual(ws.cell(row=2, column=1).value, res['report_title'])
        header_vals = [ws.cell(row=5, column=i).value for i in range(1, len(res['columns']) + 1)]
        self.assertNotIn('الدورة', header_vals)
        self.assertNotIn('الدفعة', header_vals)
        self.assertNotIn('حالة الدورة', header_vals)
        self.assertNotIn('القوة', header_vals)
        self.assertNotIn('التصنيف', header_vals)
        self.assertEqual(header_vals[:4], ['#', 'النمرة', 'الرتبة', 'اسم الدارس'])

    def test_trainee_rank_property(self):
        """التحقق من خاصية rank في نموذج Trainee لمنع حدوث AttributeError"""
        self.assertEqual(self.trainee1.rank, 'رائد')
        new_trainee = Trainee.objects.create(military_number='12345678', name='دارس تجريبي جديد')
        self.assertEqual(new_trainee.rank, '')

    def test_reports_hub_session_status_batch_linkage(self):
        """التحقق من ربط حالة الدورة برقم الدفعة وتمرير بيانات الحالة data-status في شاشة التقارير"""
        self.client.force_login(self.admin)
        res = self.client.get(reverse('training:reports_hub'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'onSessionStatusChange()')
        self.assertContains(res, 'id="filter_session_status"')
        self.assertContains(res, 'data-status="completed"')


class CourseSubjectsAndInstructorsReportTests(TestCase):
    """حزمة اختبارات شاملة لبيان المواد الدراسية وهيئة التدريس ومعدلات النجاح بالتقارير"""

    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser('admin_sub_rep', 'admin_sub@test.com', 'Pass1234!')
        self.admin.profile.role = UserRole.ADMIN
        self.admin.profile.save()

        # إنشاء تصنيف ودورة وانعقاد
        self.cat = CourseCategory.objects.create(name='دورات المرشد', description='تصنيف دورات المرشدين')
        self.course = Course.objects.create(
            name='اساسيات حاسوب',
            course_number='CRS-GUIDE-PC',
            category=self.cat,
            attendance_max_grade=Decimal('10.00')
        )
        self.session = CourseSession.objects.create(
            course=self.course,
            session_code='الدفعة 22',
            start_date=date.today() - timedelta(days=20),
            end_date=date.today() - timedelta(days=2),
            status='completed',
            attendance_max_grade=Decimal('10.00')
        )

        # معلم ومادتين
        self.instructor = Instructor.objects.create(
            military_number='771122',
            rank='نقيب',
            name='أحمد البشير محمد',
            force='القوات البرية',
            unit='إدارة نظم المعلومات'
        )
        self.sub1 = Subject.objects.create(
            course=self.course,
            code='PC-01',
            name='مقدمة الحاسوب ونظم التشغيل',
            credit_hours=3,
            max_grade=Decimal('100.00')
        )
        self.sub2 = Subject.objects.create(
            course=self.course,
            code='PC-02',
            name='صيانة الحاسب الآلي والشبكات',
            credit_hours=2,
            max_grade=Decimal('100.00')
        )

        # ربط المعلم بالمادة الأولى، والمادة الثانية بدون معلم
        SessionSubjectInstructor.objects.create(
            session=self.session,
            subject=self.sub1,
            instructor=self.instructor
        )
        SessionSubjectInstructor.objects.create(
            session=self.session,
            subject=self.sub2,
            instructor=None
        )

        # تسجيل دارسين ورصد الدرجات
        self.t1 = Trainee.objects.create(military_number='551101', name='طارق عبد الرحمن', category='officer')
        self.t2 = Trainee.objects.create(military_number='551102', name='عادل مصطفى', category='nco')

        self.en1 = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.t1,
            current_rank='ملازم أول',
            current_unit='سلاح الإشارة',
            attendance_score=Decimal('10.00'),
            is_graded=True
        )
        self.en2 = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.t2,
            current_rank='رقيب أول',
            current_unit='القوات البحرية',
            attendance_score=Decimal('9.00'),
            is_graded=True
        )

        # درجات المادة 1 (90 و 80) -> متوسط 85.0، نسبة نجاح 100%
        TraineeSubjectGrade.objects.create(enrollment=self.en1, subject=self.sub1, score=Decimal('90.00'))
        TraineeSubjectGrade.objects.create(enrollment=self.en2, subject=self.sub1, score=Decimal('80.00'))

        # درجات المادة 2 (70 و 40) -> متوسط 55.0، نسبة نجاح 50%
        TraineeSubjectGrade.objects.create(enrollment=self.en1, subject=self.sub2, score=Decimal('70.00'))
        TraineeSubjectGrade.objects.create(enrollment=self.en2, subject=self.sub2, score=Decimal('40.00'))

    def test_get_sessions_subjects_summary_calculation(self):
        """التحقق من حسابات بيان المواد الدراسية ونسب النجاح ونص التدريس"""
        summary = get_sessions_subjects_summary([self.session])
        self.assertEqual(len(summary), 1)

        s_info = summary[0]
        self.assertEqual(s_info['subjects_count'], 2)
        self.assertEqual(s_info['course_name'], 'اساسيات حاسوب')
        self.assertEqual(s_info['session_code'], 'الدفعة 22')
        self.assertIn('لقد تم تدريس 2 مواد في دورة اساسيات حاسوب (الدفعة 22)', s_info['statement'])

        # المادة 1: المعلم المكلف
        sub1_stat = s_info['subjects'][0]
        self.assertIn('أحمد البشير محمد', sub1_stat['instructor_name'])
        self.assertEqual(sub1_stat['total_graded'], 2)
        self.assertEqual(sub1_stat['passed_count'], 2)
        self.assertEqual(sub1_stat['avg_score'], 85.0)
        self.assertEqual(sub1_stat['pass_rate'], 100.0)

        # المادة 2: بدون معلم مخصص مباشرة
        sub2_stat = s_info['subjects'][1]
        self.assertEqual(sub2_stat['total_graded'], 2)
        self.assertEqual(sub2_stat['passed_count'], 1)
        self.assertEqual(sub2_stat['avg_score'], 55.0)
        self.assertEqual(sub2_stat['pass_rate'], 50.0)

    def test_report_type_course_subjects(self):
        """التحقق من استخراج التقرير المستقل للمواد وهيئة التدريس ومعدلات النجاح"""
        res = get_report_data({
            'report_type': 'course_subjects',
            'session_id': str(self.session.id),
            'all_dates': '1'
        })
        self.assertEqual(res['report_type'], 'course_subjects')
        self.assertEqual(len(res['records']), 2)
        self.assertEqual(res['stats']['total_subjects_taught'], 2)
        self.assertEqual(res['stats']['total_instructors_involved'], 1)
        self.assertEqual(res['stats']['overall_avg_pass_rate'], 75.0)

    def test_reports_hub_view_renders_subjects_summary(self):
        """التحقق من عرض شاشة التقارير لبيان المواد وهيئة التدريس ومعدلات النجاح"""
        self.client.force_login(self.admin)
        res = self.client.get(reverse('training:reports_hub'), {
            'session_id': str(self.session.id),
            'all_dates': '1'
        })
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('بيان المواد الدراسية وهيئة التدريس ومعدلات النجاح', content)
        self.assertIn('لقد تم تدريس', content)
        self.assertIn('مواد معتمدة في هذه الدورة', content)
        self.assertIn('مقدمة الحاسوب ونظم التشغيل', content)
        self.assertIn('أحمد البشير محمد', content)

    def test_reports_hub_renders_detailed_certificate_link(self):
        """التحقق من أن زر الشهادة في شاشة التقارير يفتح شهادة التفاصيل وليس الشهادة التقديرية"""
        self.en1.calculate_results()
        self.client.force_login(self.admin)
        res = self.client.get(reverse('training:reports_hub'), {
            'report_type': 'trainees',
            'session_id': str(self.session.id),
            'all_dates': '1'
        })
        self.assertEqual(res.status_code, 200)
        detailed_url = reverse('training:certificate_detailed', kwargs={'enrollment_id': self.en1.id})
        self.assertContains(res, detailed_url)

    def test_admin_report_print_subjects_section(self):
        """التحقق من طباعة قسم رابعاً: بيان المواد الدراسية وهيئة التدريس في نموذج الطباعة المعتمد"""
        self.client.force_login(self.admin)
        res = self.client.get(reverse('training:admin_report_print'), {
            'session_id': str(self.session.id),
            'all_dates': '1'
        })
        self.assertEqual(res.status_code, 200)
        content = res.content.decode('utf-8')
        self.assertIn('رابعاً: بيان المواد الدراسية وهيئة التدريس ومعدلات النجاح', content)
        self.assertIn('لقد تم تدريس', content)
        self.assertIn('مقدمة الحاسوب ونظم التشغيل', content)

    def test_export_excel_multi_sheet(self):
        """التحقق من اشتمال ملف الإكسل على ورقة المواد وهيئة التدريس المنفصلة"""
        report_data = get_report_data({
            'report_type': 'trainees',
            'session_id': str(self.session.id),
            'all_dates': '1'
        })
        excel_bytes = export_report_to_excel(report_data)
        self.assertTrue(len(excel_bytes) > 1000)

        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        sheet_names = wb.sheetnames
        self.assertIn('المواد وهيئة التدريس', sheet_names)


class DisciplineInfractionTests(TestCase):
    """اختبارات منظومة درجات ومخالفات الضبط والربط والقطع التلقائي للدورة"""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_disc',
            email='admin@test.com',
            password='password123'
        )
        self.client.login(username='admin_disc', password='password123')

        self.category = CourseCategory.objects.create(name='تصنيف الضبط والربط')
        self.course = Course.objects.create(
            name='دورة القيادة والأركان',
            course_number='C-DISC-01',
            category=self.category,
            attendance_max_grade=10.00
        )
        self.subject = Subject.objects.create(
            course=self.course,
            name='إدارة العمليات',
            max_grade=100.00,
            credit_hours=10
        )
        self.session = CourseSession.objects.create(
            course=self.course,
            session_code='D-DISC-101',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timedelta(days=30),
            attendance_max_grade=10.00
        )
        self.trainee = Trainee.objects.create(
            military_number='77889900',
            name='مقدم ركن أحمد عثمان',
            category=TraineeCategory.OFFICER,
            force='القوات البرية',
            unit='الفرقة السابعة'
        )
        self.enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank='مقدم ركن',
            current_force='القوات البرية',
            current_unit='الفرقة السابعة',
            attendance_score=10.00
        )

    def test_discipline_points_and_score_deduction(self):
        """فحص احتساب نقاط المخالفات وخصمها من درجة الضبط والربط"""
        inf1 = DisciplineInfraction.objects.create(
            enrollment=self.enrollment,
            infraction_type='delay_lecture'
        )
        self.assertEqual(inf1.points, Decimal('0.5'))
        res = self.enrollment.update_discipline_score()
        self.assertFalse(res['dropped'])
        self.assertEqual(res['score'], 9.5)
        self.assertEqual(self.enrollment.attendance_score, Decimal('9.50'))

        inf2 = DisciplineInfraction.objects.create(
            enrollment=self.enrollment,
            infraction_type='absent_full_day'
        )
        self.assertEqual(inf2.points, Decimal('2.0'))
        res = self.enrollment.update_discipline_score()
        self.assertFalse(res['dropped'])
        self.assertEqual(res['score'], 7.5)

    def test_automatic_course_drop_when_points_exceed_5(self):
        """فحص قطع الدورة تلقائياً عند تجاوز نقاط المخالفات 5 نقاط"""
        DisciplineInfraction.objects.create(
            enrollment=self.enrollment,
            infraction_type='enter_commander_office'
        )
        DisciplineInfraction.objects.create(
            enrollment=self.enrollment,
            infraction_type='enter_chief_instructor_office'
        )

        res = self.enrollment.update_discipline_score()
        self.assertTrue(res['dropped'])
        self.assertTrue(self.enrollment.is_dropped)
        self.assertIn('تجاوز حد مخالفات الضبط والربط المسموح به', self.enrollment.drop_reason)
        self.assertEqual(self.enrollment.attendance_score, Decimal('0.00'))

    def test_cancel_automatic_drop_when_infractions_deleted(self):
        """فحص إلغاء قطع الدورة تلقائياً عند حذف المخالفة وانخفاض النقاط إلى 5 أو أقل"""
        inf1 = DisciplineInfraction.objects.create(
            enrollment=self.enrollment,
            infraction_type='enter_commander_office'
        )
        inf2 = DisciplineInfraction.objects.create(
            enrollment=self.enrollment,
            infraction_type='enter_chief_instructor_office'
        )
        self.enrollment.update_discipline_score()
        self.assertTrue(self.enrollment.is_dropped)

        inf2.delete()
        res = self.enrollment.update_discipline_score()
        self.assertFalse(res['dropped'])
        self.assertFalse(self.enrollment.is_dropped)
        self.assertEqual(res['score'], 7.0)

    def test_api_discipline_endpoints(self):
        """فحص استجابة مسارات إدارة مخالفات الضبط والربط"""
        get_url = reverse('training:api_get_discipline_infractions', kwargs={'enrollment_id': self.enrollment.id})
        resp = self.client.get(get_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['trainee_name'], self.trainee.name)
        for choice in data['choices']:
            self.assertNotIn('0.5', choice['label'])
            self.assertNotIn('2', choice['label'])

        add_url = reverse('training:api_add_discipline_infraction')
        add_resp = self.client.post(add_url, {
            'enrollment_id': self.enrollment.id,
            'infraction_type': 'medical_rest',
            'date': '2026-11-18',
            'notes': 'تقرير مستشفى السلاح الطبي'
        })
        self.assertEqual(add_resp.status_code, 200)
        add_data = add_resp.json()
        self.assertTrue(add_data['success'])
        self.assertEqual(add_data['score'], 9.5)
        self.assertEqual(len(add_data['infractions']), 1)

        inf_id = add_data['infractions'][0]['id']
        del_url = reverse('training:api_delete_discipline_infraction', kwargs={'infraction_id': inf_id})
        del_resp = self.client.post(del_url)
        self.assertEqual(del_resp.status_code, 200)
        del_data = del_resp.json()
        self.assertTrue(del_data['success'])
        self.assertEqual(del_data['score'], 10.0)
        self.assertEqual(len(del_data['infractions']), 0)

    def test_session_discipline_attendance_view(self):
        """فحص شاشة رصد كشف الحضور والضبط والربط للدورة"""
        url = reverse('training:session_discipline_attendance', kwargs={'session_id': self.session.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'training/session_discipline_attendance.html')

        post_data = {
            f'att_{self.enrollment.id}_sat': 'medical_rest',
            f'att_{self.enrollment.id}_sun': 'present',
            f'att_{self.enrollment.id}_mon': 'present',
            f'att_{self.enrollment.id}_tue': 'present',
            f'att_{self.enrollment.id}_wed': 'present',
            f'att_{self.enrollment.id}_thu': 'present',
        }
        post_resp = self.client.post(url, post_data)
        self.assertEqual(post_resp.status_code, 302)

        self.enrollment.refresh_from_db()
        self.assertEqual(float(self.enrollment.attendance_score), 9.5)


class TargetCategoryAndBatchNumberingTests(TestCase):
    """اختبارات عزل ترقيم الدفعات وتصنيف الفئات المستهدفة في الدورات"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser('admin_batch', 'batch@test.com', 'pass123')
        self.client.force_login(self.user)
        self.category = CourseCategory.objects.create(name='دورات مرشد تجريبية')
        self.course = Course.objects.create(
            category=self.category,
            name='شبكات متقدمة',
            course_number='NET-101'
        )

    def test_independent_batch_numbering_per_target_category(self):
        """التحقق من أن ترقيم الدفعات مستقل تماماً بين الضباط وضباط الصف والمشتركة"""
        # دورة أولى للضباط برقم دفعة 1
        CourseSession.objects.create(
            course=self.course,
            target_category='officer',
            session_code='1',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 30)
        )
        # دورة ثانية للضباط برقم دفعة 2
        CourseSession.objects.create(
            course=self.course,
            target_category='officer',
            session_code='2',
            start_date=date(2026, 2, 1),
            end_date=date(2026, 2, 28)
        )

        # احتساب الدفعة التالية للضباط يجب أن يكون 3
        next_officer = calculate_next_course_session_code(self.course, target_category='officer')
        self.assertEqual(next_officer, '3')

        # احتساب الدفعة التالية لضباط الصف لنفس الدورة يجب أن يكون 1 لأنه تسلسل مستقل
        next_nco = calculate_next_course_session_code(self.course, target_category='nco')
        self.assertEqual(next_nco, '1')

        # إنشاء دورة لضباط الصف برقم 1
        CourseSession.objects.create(
            course=self.course,
            target_category='nco',
            session_code='1',
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 30)
        )

        # الدفعة التالية لضباط الصف الآن يجب أن تكون 2
        next_nco_2 = calculate_next_course_session_code(self.course, target_category='nco')
        self.assertEqual(next_nco_2, '2')

        # بينما المشتركة لا تزال تسلسلها المستقل عند 1
        next_joint = calculate_next_course_session_code(self.course, target_category='joint')
        self.assertEqual(next_joint, '1')

    def test_api_returns_correct_batch_number_per_category(self):
        """فحص استعلام API لرقم الدفعة المستقل بناءً على الفئة"""
        CourseSession.objects.create(
            course=self.course,
            target_category='officer',
            session_code='5',
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 30)
        )
        url = reverse('training:api_next_course_number')
        res_off = self.client.get(url, {'course_id': self.course.id, 'target_category': 'officer'})
        self.assertEqual(res_off.status_code, 200)
        self.assertEqual(res_off.json()['next_number'], '6')

        res_nco = self.client.get(url, {'course_id': self.course.id, 'target_category': 'nco'})
        self.assertEqual(res_nco.status_code, 200)
        self.assertEqual(res_nco.json()['next_number'], '1')
        self.assertEqual(res_nco.json()['target_category_display'], 'ضباط صف')


class MultiInstituteAndSuperAdminTests(TestCase):
    """اختبارات معمارية المنظومة متعددة المعاهد وصلاحيات السوبر أدمن وعزل البيانات"""

    def setUp(self):
        self.client = Client()

        # إنشاء أو جلب معهد أ ومعهد ب
        self.inst_a, _ = Institute.objects.get_or_create(
            code="issi",
            defaults={
                "name": "معهد نظم المعلومات والإحصاء",
                "parent_unit": "إدارة نظم المعلومات",
                "is_active": True
            }
        )
        self.inst_b, _ = Institute.objects.get_or_create(
            code="armor",
            defaults={
                "name": "معهد المدرعات",
                "parent_unit": "سلاح المدرعات",
                "is_active": True
            }
        )

        # حساب سوبر أدمن
        self.super_user = User.objects.create_user(
            username='super_boss',
            password='Password123!',
            is_superuser=True
        )
        self.super_profile = getattr(self.super_user, 'profile', None) or UserProfile.objects.get_or_create(user=self.super_user)[0]
        self.super_profile.role = UserRole.SUPER_ADMIN
        self.super_profile.save()

        # حساب أدمن معهد أ
        self.admin_a_user = User.objects.create_user(
            username='admin_a',
            password='Password123!',
            is_staff=True
        )
        self.admin_a_profile = getattr(self.admin_a_user, 'profile', None) or UserProfile.objects.get_or_create(user=self.admin_a_user)[0]
        self.admin_a_profile.role = UserRole.ADMIN
        self.admin_a_profile.institute = self.inst_a
        self.admin_a_profile.sync_permissions_from_role()
        self.admin_a_profile.save()

        # حساب أدمن معهد ب
        self.admin_b_user = User.objects.create_user(
            username='admin_b',
            password='Password123!',
            is_staff=True
        )
        self.admin_b_profile = getattr(self.admin_b_user, 'profile', None) or UserProfile.objects.get_or_create(user=self.admin_b_user)[0]
        self.admin_b_profile.role = UserRole.ADMIN
        self.admin_b_profile.institute = self.inst_b
        self.admin_b_profile.sync_permissions_from_role()
        self.admin_b_profile.save()

        # دارس في معهد أ
        self.trainee_a = Trainee.objects.create(
            military_number='11111',
            name='دارس معهد أ',
            institute=self.inst_a,
            category=TraineeCategory.OFFICER
        )

        # دارس في معهد ب
        self.trainee_b = Trainee.objects.create(
            military_number='22222',
            name='دارس معهد ب',
            institute=self.inst_b,
            category=TraineeCategory.OFFICER
        )

    def test_super_admin_dashboard_access_control(self):
        """فحص أمان لوحة تحكم السوبر أدمن: محصورة بالسوبر أدمن ومحظورة على الأدمن العادي وغير المسجلين"""
        # غير المسجل يحاول الدخول يتم تحويله لصفحة تسجيل دخول السوبر أدمن
        res_anon = self.client.get(reverse('training:super_admin_dashboard'))
        self.assertRedirects(res_anon, f"{reverse('training:super_admin_login')}?next={reverse('training:super_admin_dashboard')}")

        # أدمن المعهد العادي يحاول الدخول يتم رفضه وتحويله لصفحة دخول السوبر أدمن
        self.client.login(username='admin_a', password='Password123!')
        res_admin = self.client.get(reverse('training:super_admin_dashboard'))
        self.assertRedirects(res_admin, reverse('training:super_admin_login'))

        # السوبر أدمن يدخل بنجاح
        self.client.login(username='super_boss', password='Password123!')
        res_super = self.client.get(reverse('training:super_admin_dashboard'))
        self.assertEqual(res_super.status_code, 200)
        self.assertContains(res_super, 'معهد نظم المعلومات والإحصاء')
        self.assertContains(res_super, 'معهد المدرعات')
        self.assertContains(res_super, 'issi')
        self.assertContains(res_super, 'armor')

    def test_super_admin_login_and_logout_isolated(self):
        """فحص صفحة تسجيل الدخول والخروج المنفردة والمعزولة للسوبر أدمن"""
        login_url = reverse('training:super_admin_login')
        logout_url = reverse('training:super_admin_logout')

        # 1. معاينة شاشة تسجيل دخول السوبر أدمن
        res_get = self.client.get(login_url)
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, 'بوابة السوبر أدمن المركزية')
        self.assertContains(res_get, 'المنظومة المركزية الشاملة')

        # 2. محاولة الدخول بحساب مدير معهد عادي (admin_a) - يجب رفضه
        res_fail = self.client.post(login_url, {
            'username': 'admin_a',
            'password': 'Password123!',
        })
        self.assertEqual(res_fail.status_code, 200)
        self.assertContains(res_fail, 'هذا الحساب لا يملك صلاحيات السوبر أدمن')

        # 3. تسجيل الدخول بحساب السوبر أدمن بنجاح
        res_success = self.client.post(login_url, {
            'username': 'super_boss',
            'password': 'Password123!',
        })
        self.assertRedirects(res_success, reverse('training:super_admin_dashboard'))

        # 4. تسجيل الخروج عبر مسار خروج السوبر أدمن
        res_logout = self.client.get(logout_url)
        self.assertRedirects(res_logout, reverse('training:super_admin_login'))

    def test_super_admin_isolated_template_structure(self):
        """فحص عزل شاشات السوبر أدمن بحيث لا تحتوي على القوائم الجانبية الخاصة بالمعاهد"""
        self.client.login(username='super_boss', password='Password123!')
        res = self.client.get(reverse('training:super_admin_dashboard'))
        self.assertEqual(res.status_code, 200)
        # التأكد من استخدام القالب المنفصل المخصص
        self.assertContains(res, 'المنظومة المركزية لإدارة المعاهد والمنشآت التدريبية')
        self.assertContains(res, 'بوابة السوبر أدمن المركزية')
        # التأكد من خلوه من القائمة الجانبية للمعاهد (app-sidebar و sidebar-nav)
        self.assertNotContains(res, 'sidebar-page-layout')
        self.assertNotContains(res, 'app-sidebar')

    def test_initialize_new_institute_service(self):
        """فحص تهيئة نظام معهد جديد: توليد إعدادات الهوية والشهادات والدورات القياسية وحساب المدير"""
        new_inst = Institute.objects.create(
            name="معهد الطيران والدفاع الجوي",
            code="airforce",
            parent_unit="القوات الجوية",
            is_active=True
        )
        admin_data = {
            'username': 'air_commander',
            'password': 'Password123!',
            'name': 'عقيد طيار / حسام عمر',
            'rank': 'عقيد طيار',
            'military_number': '33333',
            'phone': '0912345678',
        }
        res = initialize_new_institute(new_inst, admin_data=admin_data)

        # التحقق من الإعدادات
        self.assertEqual(res['system_settings'].system_name, 'نظام معهد الطيران والدفاع الجوي')
        self.assertEqual(res['cert_settings'].header_line_2, 'معهد الطيران والدفاع الجوي')

        # التحقق من تصنيفات الدورات القياسية الجاهزة
        self.assertTrue(new_inst.categories.filter(name='دورات الحاسوب وتقنية المعلومات').exists())
        self.assertTrue(new_inst.categories.filter(name='الدورات الإدارية والقيادية').exists())

        # التحقق من حساب المدير
        user = res['admin_user']
        self.assertEqual(user.username, 'air_commander')
        self.assertEqual(user.profile.institute, new_inst)
        self.assertEqual(user.profile.role, UserRole.ADMIN)
        self.assertTrue(user.profile.can_manage_users)

    def test_super_admin_create_institute_view(self):
        """فحص إنشاء نظام معهد جديد عبر طلب POST من لوحة السوبر أدمن"""
        self.client.login(username='super_boss', password='Password123!')
        url = reverse('training:super_admin_institute_create')

        post_data = {
            'name': 'معهد المشاة المتقدم',
            'code': 'infantry',
            'parent_unit': 'سلاح المشاة',
            'admin_username': 'infantry_admin',
            'admin_password': 'AdminPassword123!',
            'admin_name': 'مقدم ركن / خليل إبراهيم',
            'admin_rank': 'مقدم ركن',
            'admin_military_number': '44444',
            'admin_phone': '0987654321',
        }
        res = self.client.post(url, post_data)
        self.assertRedirects(res, reverse('training:super_admin_dashboard'))

        # التأكد من إنشاء المعهد والمدير في قاعدة البيانات
        inst = Institute.objects.get(code='infantry')
        self.assertEqual(inst.name, 'معهد المشاة المتقدم')
        self.assertTrue(User.objects.filter(username='infantry_admin').exists())
        admin_prof = User.objects.get(username='infantry_admin').profile
        self.assertEqual(admin_prof.institute, inst)
        self.assertEqual(admin_prof.role, UserRole.ADMIN)

    def test_super_admin_switch_and_exit_institute(self):
        """فحص التبديل السريع للسوبر أدمن للدخول لأي معهد كأدمن مباشر والعودة للوحة المركزية"""
        self.client.login(username='super_boss', password='Password123!')

        # التبديل إلى معهد المدرعات
        switch_url = reverse('training:super_admin_switch_institute', kwargs={'institute_id': self.inst_b.id})
        res_switch = self.client.get(switch_url)
        self.assertRedirects(res_switch, reverse('training:home'))
        self.assertEqual(self.client.session.get('active_institute_id'), self.inst_b.id)

        # التحقق من عرض اسم المعهد المحول إليه في الصفحة الرئيسية
        res_home = self.client.get(reverse('training:home'))
        self.assertEqual(res_home.status_code, 200)
        self.assertContains(res_home, 'معهد المدرعات')

        # الخروج من سياق المعهد
        exit_url = reverse('training:super_admin_exit_switch')
        res_exit = self.client.get(exit_url)
        self.assertRedirects(res_exit, reverse('training:super_admin_dashboard'))
        self.assertNotIn('active_institute_id', self.client.session)

    def test_trainees_shared_across_all_institutes(self):
        """فحص إتاحة بيانات الدارسين لكافة المعاهد: كلا المعهدين يريان جميع الدارسين للاستفادة منهم"""
        # تسجيل الدخول كمدير معهد أ
        self.client.login(username='admin_a', password='Password123!')
        res_a = self.client.get(reverse('training:trainees_list'))
        self.assertEqual(res_a.status_code, 200)
        self.assertContains(res_a, '11111')
        self.assertContains(res_a, 'دارس معهد أ')
        self.assertContains(res_a, '22222')
        self.assertContains(res_a, 'دارس معهد ب')

        # تسجيل الدخول كمدير معهد ب
        self.client.login(username='admin_b', password='Password123!')
        res_b = self.client.get(reverse('training:trainees_list'))
        self.assertEqual(res_b.status_code, 200)
        self.assertContains(res_b, '11111')
        self.assertContains(res_b, 'دارس معهد أ')
        self.assertContains(res_b, '22222')
        self.assertContains(res_b, 'دارس معهد ب')

    def test_multi_institute_reports_isolation(self):
        """فحص العزل الصارم للتقارير: كل معهد يرى تقارير ودورات ونتائج معهده فقط"""
        import datetime
        cat_a = CourseCategory.objects.create(name='تصنيف معهد أ', institute=self.inst_a)
        course_a = Course.objects.create(name='دورة معهد أ الحصرية', category=cat_a, institute=self.inst_a)
        session_a = CourseSession.objects.create(
            course=course_a,
            institute=self.inst_a,
            session_code='BATCH-A1',
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 2, 1),
            status='completed'
        )
        CourseEnrollment.objects.create(
            session=session_a,
            trainee=self.trainee_a,
            is_graded=True,
            percentage=95.0,
            grade_label='ممتاز'
        )

        cat_b = CourseCategory.objects.create(name='تصنيف معهد ب', institute=self.inst_b)
        course_b = Course.objects.create(name='دورة معهد ب الحصرية', category=cat_b, institute=self.inst_b)
        session_b = CourseSession.objects.create(
            course=course_b,
            institute=self.inst_b,
            session_code='BATCH-B1',
            start_date=datetime.date(2025, 1, 1),
            end_date=datetime.date(2025, 2, 1),
            status='completed'
        )
        CourseEnrollment.objects.create(
            session=session_b,
            trainee=self.trainee_b,
            is_graded=True,
            percentage=88.0,
            grade_label='جيد جداً'
        )

        # استعلام التقارير لمدير معهد أ
        self.client.login(username='admin_a', password='Password123!')
        res_rep_a = self.client.get(reverse('training:reports_hub'), {'report_type': 'trainees', 'all_dates': '1'})
        self.assertEqual(res_rep_a.status_code, 200)
        self.assertContains(res_rep_a, 'دورة معهد أ الحصرية')
        self.assertNotContains(res_rep_a, 'دورة معهد ب الحصرية')

        # استعلام التقارير لمدير معهد ب
        self.client.login(username='admin_b', password='Password123!')
        res_rep_b = self.client.get(reverse('training:reports_hub'), {'report_type': 'trainees', 'all_dates': '1'})
        self.assertEqual(res_rep_b.status_code, 200)
        self.assertContains(res_rep_b, 'دورة معهد ب الحصرية')
        self.assertNotContains(res_rep_b, 'دورة معهد أ الحصرية')

    def test_multi_institute_activity_log_isolation(self):
        """فحص العزل الصارم لسجل النشاط والعمليات: كل معهد يرى عملياته الخاصة فقط"""
        from training.models import log_activity, ActivityAction, ActivityCategory

        # تسجيل عمليات منفصلة لكل معهد
        log_activity(
            user=self.admin_a_user,
            action_type=ActivityAction.UPDATE,
            action_category=ActivityCategory.SYSTEM,
            description="عملية خاصة بمعهد أ فقط",
            institute=self.inst_a
        )
        log_activity(
            user=self.admin_b_user,
            action_type=ActivityAction.UPDATE,
            action_category=ActivityCategory.SYSTEM,
            description="عملية خاصة بمعهد ب فقط",
            institute=self.inst_b
        )

        # 1. فحص لوحة إدارة معهد أ
        self.client.login(username='admin_a', password='Password123!')
        res_admin_a = self.client.get(reverse('training:admin_dashboard'))
        self.assertEqual(res_admin_a.status_code, 200)
        self.assertContains(res_admin_a, "عملية خاصة بمعهد أ فقط")
        self.assertNotContains(res_admin_a, "عملية خاصة بمعهد ب فقط")

        # 2. فحص لوحة إدارة معهد ب
        self.client.login(username='admin_b', password='Password123!')
        res_admin_b = self.client.get(reverse('training:admin_dashboard'))
        self.assertEqual(res_admin_b.status_code, 200)
        self.assertContains(res_admin_b, "عملية خاصة بمعهد ب فقط")
        self.assertNotContains(res_admin_b, "عملية خاصة بمعهد أ فقط")

        # 3. فحص عزل السجل بالسوبر أدمن عبر الفلتر
        self.client.login(username='super_boss', password='Password123!')
        res_super_a = self.client.get(reverse('training:super_admin_dashboard'), {'institute_filter': self.inst_a.id})
        self.assertEqual(res_super_a.status_code, 200)
        self.assertContains(res_super_a, "عملية خاصة بمعهد أ فقط")
        self.assertNotContains(res_super_a, "عملية خاصة بمعهد ب فقط")

        res_super_b = self.client.get(reverse('training:super_admin_dashboard'), {'institute_filter': self.inst_b.id})
        self.assertEqual(res_super_b.status_code, 200)
        self.assertContains(res_super_b, "عملية خاصة بمعهد ب فقط")
        self.assertNotContains(res_super_b, "عملية خاصة بمعهد أ فقط")

    def test_trainee_courses_isolated_per_institute(self):
        """فحص عزل دورات الطالب: إذا أكمل دورة في معهد لا تظهر في سجل الطالب بالمعهد الآخر"""
        import datetime
        cat_a = CourseCategory.objects.create(name='حاسوب معهد أ', institute=self.inst_a)
        course_a = Course.objects.create(name='دورة برمجة معهد أ', category=cat_a, institute=self.inst_a)
        session_a = CourseSession.objects.create(
            course=course_a,
            institute=self.inst_a,
            session_code='BATCH-A-PROG',
            start_date=datetime.date(2025, 2, 1),
            end_date=datetime.date(2025, 3, 1),
            status='completed'
        )
        CourseEnrollment.objects.create(
            session=session_a,
            trainee=self.trainee_a,
            is_graded=True,
            percentage=92.0,
            grade_label='ممتاز'
        )

        cat_b = CourseCategory.objects.create(name='ميكانيكا معهد ب', institute=self.inst_b)
        course_b = Course.objects.create(name='دورة دروع معهد ب', category=cat_b, institute=self.inst_b)
        session_b = CourseSession.objects.create(
            course=course_b,
            institute=self.inst_b,
            session_code='BATCH-B-ARMOR',
            start_date=datetime.date(2025, 3, 1),
            end_date=datetime.date(2025, 4, 1),
            status='completed'
        )
        CourseEnrollment.objects.create(
            session=session_b,
            trainee=self.trainee_a,
            is_graded=True,
            percentage=85.0,
            grade_label='ممتاز'
        )

        # 1. معاينة السجل التاريخي للدارس كمدير معهد أ
        self.client.login(username='admin_a', password='Password123!')
        res_a = self.client.get(reverse('training:trainee_transcript', kwargs={'military_number': self.trainee_a.military_number}))
        self.assertEqual(res_a.status_code, 200)
        self.assertContains(res_a, 'دورة برمجة معهد أ')
        self.assertNotContains(res_a, 'دورة دروع معهد ب')

        # 2. معاينة السجل التاريخي للدارس كمدير معهد ب
        self.client.login(username='admin_b', password='Password123!')
        res_b = self.client.get(reverse('training:trainee_transcript', kwargs={'military_number': self.trainee_a.military_number}))
        self.assertEqual(res_b.status_code, 200)
        self.assertContains(res_b, 'دورة دروع معهد ب')
        self.assertNotContains(res_b, 'دورة برمجة معهد أ')

    def test_super_admin_edit_user_role_and_permissions(self):
        """فحص تعديل صلاحيات حسابات المدراء والسوبر أدمن بواسطة السوبر أدمن"""
        self.client.login(username='super_boss', password='Password123!')
        url = reverse('training:super_admin_user_edit', kwargs={'user_id': self.admin_a_user.id})

        # ترقية مدير المعهد admin_a إلى سوبر أدمن
        post_data = {
            'role': UserRole.SUPER_ADMIN,
            'institute': '',
            'first_name': 'أحمد',
            'last_name': 'المهندس',
            'rank': 'عقيد مهندس',
            'military_number': '55555',
            'phone': '0912345678',
            'email': 'ahmed@army.mil',
            'new_password': 'NewPassword123!',
            'is_active': '1',
            'can_manage_users': '1',
        }
        res = self.client.post(url, post_data)
        self.assertRedirects(res, f"{reverse('training:super_admin_dashboard')}#admin_users_section")

        # التحقق من قاعدة البيانات
        self.admin_a_user.refresh_from_db()
        self.admin_a_user.profile.refresh_from_db()
        self.assertEqual(self.admin_a_user.profile.role, UserRole.SUPER_ADMIN)
        self.assertTrue(self.admin_a_user.is_superuser)
        self.assertTrue(self.admin_a_user.is_staff)
        self.assertEqual(self.admin_a_user.profile.rank, 'عقيد مهندس')
        self.assertEqual(self.admin_a_user.profile.phone, '0912345678')
        self.assertIsNone(self.admin_a_user.profile.institute)
        # التحقق من عمل كلمة المرور الجديدة
        self.assertTrue(self.admin_a_user.check_password('NewPassword123!'))

        # إعادة تعديل الدور إلى مدير معهد ونقله إلى معهد ب
        post_data_demote = {
            'role': UserRole.ADMIN,
            'institute': str(self.inst_b.id),
            'first_name': 'أحمد',
            'last_name': 'المهندس',
            'rank': 'عقيد مهندس',
            'military_number': '55555',
            'phone': '0912345678',
            'email': 'ahmed@army.mil',
            'is_active': '1',
        }
        res_demote = self.client.post(url, post_data_demote)
        self.assertRedirects(res_demote, f"{reverse('training:super_admin_dashboard')}#admin_users_section")

        self.admin_a_user.refresh_from_db()
        self.admin_a_user.profile.refresh_from_db()
        self.assertEqual(self.admin_a_user.profile.role, UserRole.ADMIN)
        self.assertFalse(self.admin_a_user.is_superuser)
        self.assertTrue(self.admin_a_user.is_staff)
        self.assertEqual(self.admin_a_user.profile.institute, self.inst_b)

    def test_super_admin_cannot_demote_or_deactivate_self(self):
        """فحص حماية السوبر أدمن من إزالة الصلاحية أو تعطيل حسابه الشخصي الحالي"""
        self.client.login(username='super_boss', password='Password123!')
        url = reverse('training:super_admin_user_edit', kwargs={'user_id': self.super_user.id})

        # محاولة إزالة صفة السوبر أدمن عن الحساب الحالي
        res = self.client.post(url, {
            'role': UserRole.ADMIN,
            'institute': str(self.inst_a.id),
            'is_active': '1',
        })
        self.super_user.refresh_from_db()
        self.super_user.profile.refresh_from_db()
        self.assertEqual(self.super_user.profile.role, UserRole.SUPER_ADMIN)
        self.assertTrue(self.super_user.is_superuser)

        # محاولة تعطيل الحساب الحالي
        res_deactivate = self.client.post(url, {
            'role': UserRole.SUPER_ADMIN,
            'is_active': '0',
        })
        self.super_user.refresh_from_db()
        self.assertTrue(self.super_user.is_active)

    def test_non_super_admin_blocked_from_editing_roles(self):
        """فحص حظر غير السوبر أدمن من الوصول لمسار تعديل الصلاحيات"""
        self.client.login(username='admin_a', password='Password123!')
        url = reverse('training:super_admin_user_edit', kwargs={'user_id': self.admin_b_user.id})
        res = self.client.post(url, {'role': UserRole.SUPER_ADMIN})
        self.assertRedirects(res, reverse('training:super_admin_login'))

    def test_super_admin_create_new_super_admin_user(self):
        """فحص إنشاء مستخدم سوبر أدمن جديد من صفحة السوبر أدمن"""
        self.client.login(username='super_boss', password='Password123!')
        url = reverse('training:super_admin_user_create')

        post_data = {
            'username': 'new_central_chief',
            'password': 'StrongPassword123!',
            'first_name': 'خالد',
            'last_name': 'سعيد',
            'role': UserRole.SUPER_ADMIN,
            'institute': '',
            'rank': 'لواء ركن',
            'military_number': '778899',
            'unit': 'هيئة العمليات المشتركة',
            'phone': '0912345678',
            'email': 'chief@army.mil',
            'is_active': '1',
        }
        res = self.client.post(url, post_data)
        self.assertRedirects(res, f"{reverse('training:super_admin_dashboard')}#admin_users_section")

        # التحقق من قاعدة البيانات
        new_user = User.objects.get(username='new_central_chief')
        self.assertTrue(new_user.is_superuser)
        self.assertTrue(new_user.is_staff)
        self.assertEqual(new_user.profile.role, UserRole.SUPER_ADMIN)
        self.assertTrue(new_user.profile.can_manage_users)
        self.assertIsNone(new_user.profile.institute)
        self.assertEqual(new_user.profile.rank, 'لواء ركن')

        # التحقق من إمكانية تسجيل دخول السوبر أدمن الجديد
        self.client.logout()
        login_res = self.client.post(reverse('training:super_admin_login'), {
            'username': 'new_central_chief',
            'password': 'StrongPassword123!',
        })
        self.assertRedirects(login_res, reverse('training:super_admin_dashboard'))

    def test_super_admin_role_hidden_and_blocked_in_institute_forms(self):
        """فحص حجب ومنع صلاحية السوبر أدمن في المعاهد الأخرى ونماذجها"""
        # 1. التحقق من عدم وجود خيار السوبر أدمن في نماذج المعاهد
        create_form = UserCreateForm()
        edit_form = UserEditForm()
        create_choice_keys = [c[0] for c in create_form.fields['role'].choices]
        edit_choice_keys = [c[0] for c in edit_form.fields['role'].choices]
        self.assertNotIn(UserRole.SUPER_ADMIN, create_choice_keys)
        self.assertNotIn(UserRole.SUPER_ADMIN, edit_choice_keys)
        self.assertIn(UserRole.ADMIN, create_choice_keys)
        self.assertIn(UserRole.REGISTRAR, create_choice_keys)

        # 2. التحقق من حظر تعيين السوبر أدمن عبر مسار إضافة المستخدمين في المعهد
        self.client.login(username='admin_a', password='Password123!')
        res_create = self.client.post(reverse('training:user_create'), {
            'username': 'attacker_admin',
            'password': 'Password123!',
            'first_name': 'محاول',
            'last_name': 'تجاوز',
            'role': UserRole.SUPER_ADMIN,  # محاولة التلاعب وتمرير سوبر أدمن
            'is_active': '1',
        })
        # يجب رفض الطلب تماماً وعدم إنشاء المستخدم
        self.assertFalse(User.objects.filter(username='attacker_admin').exists())


class DynamicPermissionsMatrixTests(TestCase):
    """اختبارات مصفوفة الأذونات والصلاحيات الديناميكية المتقدمة (Granular RBAC)"""

    def setUp(self):
        self.institute = Institute.objects.create(name='معهد اختبار الصلاحيات', code='PERM_INST')
        
        # مستخدم أدمن
        self.admin_user = User.objects.create_user(
            username='perm_admin',
            password='Password123!',
            is_staff=True
        )
        self.admin_profile, _ = UserProfile.objects.get_or_create(user=self.admin_user)
        self.admin_profile.institute = self.institute
        self.admin_profile.role = UserRole.ADMIN
        self.admin_profile.sync_permissions_from_role()
        self.admin_profile.save()

        # مستخدم مسجل
        self.registrar_user = User.objects.create_user(
            username='perm_registrar',
            password='Password123!'
        )
        self.registrar_profile, _ = UserProfile.objects.get_or_create(user=self.registrar_user)
        self.registrar_profile.institute = self.institute
        self.registrar_profile.role = UserRole.REGISTRAR
        self.registrar_profile.sync_permissions_from_role()
        self.registrar_profile.save()

        # مستخدم مخصص
        self.custom_user = User.objects.create_user(
            username='perm_custom',
            password='Password123!'
        )
        self.custom_profile, _ = UserProfile.objects.get_or_create(user=self.custom_user)
        self.custom_profile.institute = self.institute
        self.custom_profile.role = UserRole.CUSTOM
        self.custom_profile.permissions_matrix = {}
        self.custom_profile.save()

    def test_default_role_permissions_matrix(self):
        """التحقق من الأذونات القياسية الافتراضية لكل دور في المصفوفة"""
        from apps.core.permissions import get_default_permissions_for_role

        admin_perms = get_default_permissions_for_role(UserRole.ADMIN)
        self.assertTrue(admin_perms['trainees']['view'])
        self.assertTrue(admin_perms['trainees']['delete'])
        self.assertTrue(admin_perms['grades']['approve'])
        self.assertTrue(admin_perms['users']['permissions'])
        self.assertTrue(admin_perms['settings']['edit'])

        reg_perms = get_default_permissions_for_role(UserRole.REGISTRAR)
        self.assertTrue(reg_perms['trainees']['add'])
        self.assertTrue(reg_perms['sessions']['add'])
        self.assertFalse(reg_perms['users']['add'])
        self.assertFalse(reg_perms['settings']['edit'])
        self.assertFalse(reg_perms['grades']['approve'])

        inst_perms = get_default_permissions_for_role(UserRole.INSTRUCTOR)
        self.assertTrue(inst_perms['grades']['entry'])
        self.assertFalse(inst_perms['grades']['approve'])
        self.assertFalse(inst_perms['trainees']['add'])

    def test_user_effective_permissions_and_has_perm(self):
        """التحقق من طريقة حساب الأذونات الفعالة ودالة has_perm للمستخدم"""
        from apps.core.permissions import get_user_permissions_matrix, has_permission

        # الأدمن يملك كافة الصلاحيات
        self.assertTrue(self.admin_profile.has_perm('trainees', 'delete'))
        self.assertTrue(has_permission(self.admin_user, 'users', 'permissions'))

        # المسجل يملك صلاحية إضافة دارس، ولا يملك تعديل الإعدادات
        self.assertTrue(self.registrar_profile.has_perm('trainees', 'add'))
        self.assertFalse(self.registrar_profile.has_perm('settings', 'edit'))

        # تخصيص أذونات دقيقة للمستخدم المخصص عبر مصفوفة JSON
        self.custom_profile.permissions_matrix = {
            'reports': {'view': True, 'excel': True, 'print': False},
            'trainees': {'view': True, 'add': False}
        }
        self.custom_profile.save()

        self.assertTrue(self.custom_profile.has_perm('reports', 'excel'))
        self.assertFalse(self.custom_profile.has_perm('reports', 'print'))
        self.assertTrue(self.custom_profile.has_perm('trainees', 'view'))
        self.assertFalse(self.custom_profile.has_perm('trainees', 'add'))

    def test_sync_legacy_booleans_from_matrix(self):
        """التحقق من المزامنة العكسية التلقائية من المصفوفة إلى حقول الأذونات السابقة"""
        profile = self.custom_profile
        profile.permissions_matrix = {
            'trainees': {'view': True, 'add': True, 'edit': True, 'delete': False},
            'grades': {'view': True, 'entry': True, 'approve': False},
            'users': {'view': False, 'permissions': False}
        }
        profile.sync_legacy_booleans_from_matrix()
        profile.save()

        self.assertTrue(profile.can_view)
        self.assertTrue(profile.can_add)
        self.assertTrue(profile.can_edit)
        self.assertFalse(profile.can_delete)
        self.assertTrue(profile.can_grade)
        self.assertFalse(profile.can_approve_results)
        self.assertFalse(profile.can_manage_users)

    def test_user_update_permissions_matrix_ajax(self):
        """التحقق من نقطة النهاية (Endpoint) لتحديث مصفوفة الأذونات للمستخدم عبر AJAX"""
        self.client.login(username='perm_admin', password='Password123!')
        url = reverse('training:user_update_permissions_matrix', kwargs={'user_id': self.custom_user.id})

        new_matrix = {
            'trainees': {'view': True, 'add': True, 'edit': False, 'delete': False, 'export': True},
            'reports': {'view': True, 'excel': True, 'print': True}
        }
        import json
        res = self.client.post(
            url,
            data=json.dumps({'permissions_matrix': new_matrix}),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')

        self.custom_user.refresh_from_db()
        profile = self.custom_user.profile
        self.assertTrue(profile.has_perm('reports', 'excel'))
        self.assertTrue(profile.has_perm('trainees', 'export'))
        self.assertFalse(profile.has_perm('trainees', 'edit'))

    def test_api_get_permissions_matrix(self):
        """التحقق من استرجاع مصفوفة الصلاحيات عبر الـ API"""
        self.client.login(username='perm_admin', password='Password123!')
        url = reverse('training:api_permissions_matrix')
        res = self.client.get(f"{url}?user_id={self.registrar_user.id}")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data['status'], 'success')
        self.assertEqual(data['username'], 'perm_registrar')
        self.assertIn('matrix', data)
        self.assertTrue(data['matrix']['trainees']['view'])


class NaturalNumberFormattingTests(TestCase):
    """اختبارات تنسيق الأرقام والدرجات بالشكل الطبيعي دون أصفار عشرية زائدة"""

    def test_natural_number_filter(self):
        from training.templatetags.custom_filters import natural_number, natural_grade, natural_percent
        self.assertEqual(natural_number(Decimal('100.00')), '100')
        self.assertEqual(natural_number(Decimal('400.00')), '400')
        self.assertEqual(natural_number(Decimal('10.00')), '10')
        self.assertEqual(natural_number(Decimal('0.00')), '0')
        self.assertEqual(natural_number(Decimal('84.50')), '84.5')
        self.assertEqual(natural_number(Decimal('84.05')), '84.05')
        self.assertEqual(natural_number(100), '100')
        self.assertEqual(natural_number('100,00'), '100')
        self.assertEqual(natural_number('10,00'), '10')
        self.assertEqual(natural_number(None), '')

        # Alias natural_grade
        self.assertEqual(natural_grade(Decimal('100.00')), '100')

        # Alias natural_percent
        self.assertEqual(natural_percent(Decimal('100.00')), '100%')
        self.assertEqual(natural_percent(Decimal('84.50')), '84.5%')
        self.assertEqual(natural_percent(0), '0%')

    def test_template_builtin_render(self):
        from django.template import Template, Context
        t = Template("{{ num1|natural_number }} / {{ num2|natural_number }} / {{ num3|natural_number }}")
        c = Context({'num1': Decimal('400.00'), 'num2': Decimal('10.00'), 'num3': Decimal('100.00')})
        self.assertEqual(t.render(c), "400 / 10 / 100")

    def test_model_natural_properties(self):
        inst = Institute.objects.create(name="معهد الاختبار", code="INST_NUM_TEST")
        cat = CourseCategory.objects.create(institute=inst, name="تصنيف تجريبي")
        course = Course.objects.create(
            institute=inst,
            category=cat,
            name="دورة تدريب الأرقام",
            attendance_max_grade=Decimal('10.00')
        )
        s1 = Subject.objects.create(course=course, name="مادة 1", credit_hours=10, max_grade=Decimal('100.00'))
        s2 = Subject.objects.create(course=course, name="مادة 2", credit_hours=10, max_grade=Decimal('100.00'))

        self.assertEqual(course.total_max_marks, 200)
        self.assertEqual(course.natural_attendance_grade, 10)
        self.assertEqual(s1.natural_max_grade, 100)


from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.exceptions import ValidationError
from apps.core.validators import validate_movement_order_file, validate_image_file


class CriticalSecurityRemediationTests(TestCase):
    """اختبارات الحزمة الأمنية الحرجة: عزل المعاهد (IDOR)، حماية الإدارة العليا، والتحقق الصارم من الملفات"""

    def setUp(self):
        self.client = Client()

        # معهد 1 ومعهد 2
        self.inst1 = Institute.objects.create(name="معهد نظم المعلومات 1", code="SEC_INST_1", is_active=True)
        self.inst2 = Institute.objects.create(name="معهد المدرعات 2", code="SEC_INST_2", is_active=True)

        # حساب سوبر أدمن
        self.super_user = User.objects.create_user(username='sec_super', password='Password123!', is_superuser=True)
        p_super, _ = UserProfile.objects.get_or_create(user=self.super_user)
        p_super.role = UserRole.SUPER_ADMIN
        p_super.save()

        # حساب أدمن معهد 1
        self.admin1 = User.objects.create_user(username='sec_admin1', password='Password123!', is_staff=True)
        p1, _ = UserProfile.objects.get_or_create(user=self.admin1)
        p1.role = UserRole.ADMIN
        p1.institute = self.inst1
        p1.sync_permissions_from_role()
        p1.save()

        # حساب أدمن معهد 2
        self.admin2 = User.objects.create_user(username='sec_admin2', password='Password123!', is_staff=True)
        p2, _ = UserProfile.objects.get_or_create(user=self.admin2)
        p2.role = UserRole.ADMIN
        p2.institute = self.inst2
        p2.sync_permissions_from_role()
        p2.save()

        # بيانات تابعة لمعهد 2
        self.cat2 = CourseCategory.objects.create(name="تصنيف معهد 2", institute=self.inst2)
        self.course2 = Course.objects.create(name="دورة معهد 2", course_number="SEC-002", category=self.cat2, institute=self.inst2)
        self.subject2 = Subject.objects.create(course=self.course2, name="مادة 2", code="S2-01", max_grade=Decimal('100.00'))
        self.session2 = CourseSession.objects.create(
            course=self.course2, institute=self.inst2, session_code="1",
            start_date=date.today(), end_date=date.today() + timedelta(days=30)
        )
        self.trainee2 = Trainee.objects.create(
            name="دارس معهد 2", military_number="SEC9999", institute=self.inst2, category=TraineeCategory.OFFICER
        )
        self.enrollment2 = CourseEnrollment.objects.create(session=self.session2, trainee=self.trainee2)

    def test_idor_prevented_course_edit_across_institutes(self):
        """منع تعديل دورة تتبع معهداً آخر بواسطة مدير معهد منافس (IDOR)"""
        self.client.login(username='sec_admin1', password='Password123!')
        session = self.client.session
        session['active_institute_id'] = self.inst1.id
        session.save()

        # محاولة تعديل دورة معهد 2
        res = self.client.post(reverse('training:course_edit', args=[self.course2.id]), {
            'name': 'اختراق دورة معهد 2',
            'course_number': 'HACK-01',
            'category': self.cat2.id,
            'attendance_max_grade': 10
        })
        self.assertEqual(res.status_code, 403)

    def test_idor_prevented_course_delete_across_institutes(self):
        """منع حذف دورة تتبع معهداً آخر بواسطة مدير معهد منافس (IDOR)"""
        self.client.login(username='sec_admin1', password='Password123!')
        session = self.client.session
        session['active_institute_id'] = self.inst1.id
        session.save()

        res = self.client.post(reverse('training:course_delete', args=[self.course2.id]))
        self.assertEqual(res.status_code, 403)

    def test_idor_prevented_trainee_edit_and_delete_across_institutes(self):
        """منع تعديل أو حذف دارس يتبع معهداً آخر (IDOR)"""
        self.client.login(username='sec_admin1', password='Password123!')
        session = self.client.session
        session['active_institute_id'] = self.inst1.id
        session.save()

        # محاولة تعديل دارس معهد 2
        res_edit = self.client.post(reverse('training:trainee_edit', args=[self.trainee2.military_number]), {
            'name': 'تعديل مخترق',
            'category': TraineeCategory.OFFICER
        })
        self.assertEqual(res_edit.status_code, 403)

        # محاولة حذف دارس معهد 2
        res_del = self.client.post(reverse('training:trainee_delete', args=[self.trainee2.military_number]))
        self.assertEqual(res_del.status_code, 403)

    def test_idor_prevented_certificate_view_across_institutes(self):
        """منع استعراض شهادة تسجيل يتبع دورة معهد آخر (IDOR)"""
        self.client.login(username='sec_admin1', password='Password123!')
        session = self.client.session
        session['active_institute_id'] = self.inst1.id
        session.save()

        res_cert = self.client.get(reverse('training:certificate', args=[self.enrollment2.id]))
        self.assertEqual(res_cert.status_code, 403)

    def test_super_admin_protection_from_institute_admin(self):
        """منع مدراء المعاهد من تعديل أو حذف حساب السوبر أدمن أو تغيير حالته"""
        self.client.login(username='sec_admin1', password='Password123!')
        session = self.client.session
        session['active_institute_id'] = self.inst1.id
        session.save()

        # محاولة تعديل بيانات أو كلمة مرور السوبر أدمن
        res_edit = self.client.post(reverse('training:user_edit', args=[self.super_user.id]), {
            'first_name': 'Hacked',
            'role': 'regular'
        })
        self.assertEqual(res_edit.status_code, 403)

        # محاولة حذف السوبر أدمن
        res_del = self.client.post(reverse('training:user_delete', args=[self.super_user.id]))
        self.assertEqual(res_del.status_code, 403)

        # محاولة تعطيل حساب السوبر أدمن
        res_toggle = self.client.post(reverse('training:user_toggle_active', args=[self.super_user.id]))
        self.assertEqual(res_toggle.status_code, 403)

    def test_file_upload_validation_strict(self):
        """فحص الرفض الأمني لملفات الترويسة والمسح المخالفة أو المزورة"""
        # 1. ملف بامتداد غير مسموح به (تنفيذي exe)
        fake_exe = SimpleUploadedFile("malware.exe", b"MZ\x90\x00\x03\x00\x00\x00", content_type="application/x-msdownload")
        with self.assertRaises(ValidationError):
            validate_movement_order_file(fake_exe)

        # 2. ملف بامتداد pdf ولكنه نص عادي بدون ترويسة PDF حقيقية (Spoofed file)
        fake_pdf = SimpleUploadedFile("fake.pdf", b"echo 'malicious script'", content_type="application/pdf")
        with self.assertRaises(ValidationError):
            validate_movement_order_file(fake_pdf)

        # 3. ملف PDF سليم يبدأ بـ %PDF
        valid_pdf = SimpleUploadedFile("order.pdf", b"%PDF-1.4 real pdf content", content_type="application/pdf")
        validate_movement_order_file(valid_pdf)

        # 4. ملف PNG سليم يبدأ بـ \x89PNG
        valid_png = SimpleUploadedFile("scan.png", b"\x89PNG\r\n\x1a\nimage data", content_type="image/png")
        validate_movement_order_file(valid_png)


class DataIntegrityAndPerformanceRemediationTests(TestCase):
    """اختبارات مسار أداء قاعدة البيانات وسلامة العمليات الحسابية والذرية"""

    def setUp(self):
        self.inst = Institute.objects.create(name="معهد الاتصالات التجريبي", code="TEST-COMM", is_active=True)
        self.cat = CourseCategory.objects.create(name="دورات تقنية", institute=self.inst)
        self.course = Course.objects.create(name="هندسة شبكات", category=self.cat, institute=self.inst, attendance_max_grade=Decimal('10.00'))
        self.sub1 = Subject.objects.create(course=self.course, name="راوترات", max_grade=Decimal('100.00'), credit_hours=30)
        self.sub2 = Subject.objects.create(course=self.course, name="سويتشات", max_grade=Decimal('100.00'), credit_hours=30)
        self.sub3 = Subject.objects.create(course=self.course, name="أمن شبكات", max_grade=Decimal('100.00'), credit_hours=30)

        self.trainee = Trainee.objects.create(
            institute=self.inst,
            military_number="PERF-9901",
            name="طارق الأحمدي",
            category=TraineeCategory.OFFICER,
            force="القوات البرية",
            unit="سلاح الإشارة"
        )
        self.session = CourseSession.objects.create(
            institute=self.inst,
            course=self.course,
            session_code="NET-P01",
            start_date=date.today(),
            end_date=date.today() + timedelta(days=60),
            status="active",
            attendance_max_grade=Decimal('10.00')
        )
        self.enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank="نقيب",
            current_force="القوات البرية",
            current_unit="سلاح الإشارة",
            attendance_score=Decimal('9.75')
        )

    def test_calculate_results_exact_decimal_precision(self):
        """التحقق من دقة الحساب العشري للنتائج وتجنب تقريب الفلوت"""
        # مجموع المواد: 300 + 10 مواظبة = 310
        # درجات: 91.33 + 87.25 + 95.10 + 9.75 مواظبة = 283.43
        # النسبة: (283.43 * 100) / 310 = 91.429032... -> 91.43
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.sub1, score=Decimal('91.33'))
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.sub2, score=Decimal('87.25'))
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.sub3, score=Decimal('95.10'))

        res = self.enrollment.calculate_results()
        self.assertIsNotNone(res)
        self.enrollment.refresh_from_db()
        self.assertEqual(self.enrollment.total_score, Decimal('283.43'))
        self.assertEqual(self.enrollment.percentage, Decimal('91.43'))
        self.assertEqual(self.enrollment.grade_label, 'ممتاز (أ)')
        self.assertTrue(self.enrollment.is_graded)

    def test_models_database_indexes_registered(self):
        """التحقق من إنشاء وتسجيل الفهارس في نماذج النظام الأساسية"""
        session_idx_fields = [tuple(idx.fields) for idx in CourseSession._meta.indexes]
        self.assertIn(('status', '-start_date'), session_idx_fields)
        self.assertIn(('target_category',), session_idx_fields)
        self.assertIn(('institute', 'status'), session_idx_fields)
        self.assertIn(('start_date', 'end_date'), session_idx_fields)

        enrollment_idx_fields = [tuple(idx.fields) for idx in CourseEnrollment._meta.indexes]
        self.assertIn(('session', 'is_graded'), enrollment_idx_fields)
        self.assertIn(('session', 'is_dropped'), enrollment_idx_fields)
        self.assertIn(('is_graded', 'is_dropped'), enrollment_idx_fields)
        self.assertIn(('percentage',), enrollment_idx_fields)

        trainee_idx_fields = [tuple(idx.fields) for idx in Trainee._meta.indexes]
        self.assertIn(('military_number',), trainee_idx_fields)
        self.assertIn(('category',), trainee_idx_fields)
        self.assertIn(('institute', 'category'), trainee_idx_fields)

        grade_idx_fields = [tuple(idx.fields) for idx in TraineeSubjectGrade._meta.indexes]
        self.assertIn(('enrollment', 'subject'), grade_idx_fields)
        self.assertIn(('score',), grade_idx_fields)

        activity_idx_fields = [tuple(idx.fields) for idx in ActivityLog._meta.indexes]
        self.assertIn(('action_type', '-timestamp'), activity_idx_fields)
        self.assertIn(('institute', '-timestamp'), activity_idx_fields)

    def test_prefetched_grades_in_has_complete_data_and_grades(self):
        """التحقق من استغلال التخزين المسبق للدرجات لتفادي استعلامات N+1"""
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.sub1, score=Decimal('90.00'))
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.sub2, score=Decimal('85.00'))
        TraineeSubjectGrade.objects.create(enrollment=self.enrollment, subject=self.sub3, score=Decimal('95.00'))
        self.enrollment.calculate_results()

        # استعلام مسبق
        en_qs = CourseEnrollment.objects.filter(pk=self.enrollment.pk).prefetch_related('grades').first()
        self.assertTrue(en_qs.has_complete_data_and_grades)


class ProductionHardeningAndSecurityTests(TestCase):
    """اختبارات الجاهزية التشغيلية للإنتاج وحماية تسجيل الدخول والتسجيلات وصفحات الأخطاء"""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='lockout_target', password='CorrectPassword123!')
        self.profile = self.user.profile
        self.profile.role = UserRole.REGULAR
        self.profile.save()

    def test_login_rate_limiting_locks_out_after_five_failed_attempts(self):
        """التحقق من قفل تسجيل الدخول بعد 5 محاولات خاطئة متتالية وتدوينها في سجل النشاط"""
        from django.core.cache import cache
        cache.clear()
        login_url = reverse('training:login')

        # 4 محاولات فاشلة
        for i in range(1, 5):
            res = self.client.post(login_url, {'username': 'lockout_target', 'password': 'WrongPassword!'})
            self.assertEqual(res.status_code, 200)

        # المحاولة الخامسة تؤدي للقفل
        res_lockout = self.client.post(login_url, {'username': 'lockout_target', 'password': 'WrongPassword!'})
        self.assertEqual(res_lockout.status_code, 200)

        # التحقق من وجود سجل في ActivityLog
        failed_log = ActivityLog.objects.filter(username='lockout_target', action_category=ActivityCategory.AUTH).first()
        self.assertIsNotNone(failed_log)

        # المحاولة السادسة حتى بكلمة المرور الصحيحة يتم حظرها أثناء فترة القفل
        res_blocked = self.client.post(login_url, {'username': 'lockout_target', 'password': 'CorrectPassword123!'})
        self.assertEqual(res_blocked.status_code, 200)
        self.assertFalse('_auth_user_id' in self.client.session)

    def test_custom_error_views_status_codes(self):
        """التحقق من عمل صفحات الخطأ 404 و 500 المخصصة بهوية المنظومة"""
        from apps.core.views import custom_404_view, custom_500_view
        from django.test.client import RequestFactory

        rf = RequestFactory()
        req404 = rf.get('/nonexistent-path-test/')
        res404 = custom_404_view(req404)
        self.assertEqual(res404.status_code, 404)

        req500 = rf.get('/test-500/')
        res500 = custom_500_view(req500)
        self.assertEqual(res500.status_code, 500)

    def test_whitenoise_and_session_settings(self):
        """التحقق من تفعيل خادم وايت نويز وضبط أمان الجلسات للبيئة الإنتاجية"""
        from django.conf import settings
        if getattr(settings, 'HAS_WHITENOISE', False):
            self.assertIn('whitenoise.middleware.WhiteNoiseMiddleware', settings.MIDDLEWARE)
        self.assertEqual(settings.SESSION_COOKIE_AGE, 28800)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)


class CourseSessionDateAndStatusConstraintTests(TestCase):
    """فحص قيود تواريخ بداية ونهاية الدورات وربطها بحالة الدورة (جارية / مخطط لها / مكتملة)"""

    def setUp(self):
        self.inst = Institute.objects.create(name="معهد اختبار القيود", code="INST-DATE-TEST")
        self.cat = CourseCategory.objects.create(name="تصنيف اختبار القيود", institute=self.inst)
        self.course = Course.objects.create(name="دورة اختبار القيود", course_number="DTEST-01", category=self.cat, institute=self.inst)
        self.today = timezone.localdate()
        self.past_date = self.today - timedelta(days=30)
        self.past_end_date = self.today - timedelta(days=10)
        self.future_start_date = self.today + timedelta(days=1)
        self.future_end_date = self.today + timedelta(days=30)

    def test_active_and_planned_sessions_block_past_start_date(self):
        """التحقق من منع اختيار تاريخ بداية في الماضي للدورات الجارية حالياً أو المخطط لها"""
        from apps.academic.forms import CourseSessionForm
        from django.core.files.uploadedfile import SimpleUploadedFile

        pdf_dummy = SimpleUploadedFile("order.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")

        # 1. دورة جارية بتاريخ في الماضي -> يجب أن تفشل
        form_active = CourseSessionForm(data={
            'course': self.course.id,
            'target_category': 'officer',
            'session_code': 'BATCH-ACT-PAST',
            'start_date': self.past_date,
            'end_date': self.past_end_date,
            'movement_order_date': self.past_date,
            'status': 'active',
            'attendance_max_grade': 10,
        }, files={'movement_order_file': pdf_dummy})
        self.assertFalse(form_active.is_valid())
        self.assertIn('start_date', form_active.errors)

        # 2. دورة مخطط لها بتاريخ في الماضي -> يجب أن تفشل
        form_planned = CourseSessionForm(data={
            'course': self.course.id,
            'target_category': 'officer',
            'session_code': 'BATCH-PLN-PAST',
            'start_date': self.past_date,
            'end_date': self.past_end_date,
            'movement_order_date': self.past_date,
            'status': 'planned',
            'attendance_max_grade': 10,
        }, files={'movement_order_file': pdf_dummy})
        self.assertFalse(form_planned.is_valid())
        self.assertIn('start_date', form_planned.errors)

    def test_completed_session_allows_past_start_date(self):
        """التحقق من السماح باختيار تاريخ بداية في الماضي للدورات المكتملة للأرشفة والتوثيق"""
        from apps.academic.forms import CourseSessionForm
        from django.core.files.uploadedfile import SimpleUploadedFile

        pdf_dummy = SimpleUploadedFile("order.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")

        form_completed = CourseSessionForm(data={
            'course': self.course.id,
            'target_category': 'officer',
            'session_code': 'BATCH-CMP-PAST',
            'start_date': self.past_date,
            'end_date': self.past_end_date,
            'movement_order_date': self.past_date,
            'status': 'completed',
            'attendance_max_grade': 10,
        }, files={'movement_order_file': pdf_dummy})
        self.assertTrue(form_completed.is_valid(), form_completed.errors)

    def test_end_date_must_be_strictly_after_start_date_for_all_statuses(self):
        """التحقق من أن تاريخ نهاية الدورة يجب أن يكون بعد تاريخ البداية بيوم على الأقل لكافة الحالات"""
        from apps.academic.forms import CourseSessionForm
        from django.core.files.uploadedfile import SimpleUploadedFile

        pdf_dummy = SimpleUploadedFile("order.pdf", b"%PDF-1.4 dummy", content_type="application/pdf")

        # نفس اليوم للدورة المكتملة
        form_same_day = CourseSessionForm(data={
            'course': self.course.id,
            'target_category': 'officer',
            'session_code': 'BATCH-CMP-SAME',
            'start_date': self.past_date,
            'end_date': self.past_date,
            'movement_order_date': self.past_date,
            'status': 'completed',
            'attendance_max_grade': 10,
        }, files={'movement_order_file': pdf_dummy})
        self.assertFalse(form_same_day.is_valid())
        self.assertIn('end_date', form_same_day.errors)

        # نهاية قبل البداية
        form_before = CourseSessionForm(data={
            'course': self.course.id,
            'target_category': 'officer',
            'session_code': 'BATCH-CMP-BEFORE',
            'start_date': self.past_date,
            'end_date': self.past_date - timedelta(days=1),
            'movement_order_date': self.past_date,
            'status': 'completed',
            'attendance_max_grade': 10,
        }, files={'movement_order_file': pdf_dummy})
        self.assertFalse(form_before.is_valid())
        self.assertIn('end_date', form_before.errors)


class UserInstructorLinkAutoFillTests(TestCase):
    """فحص مزامنة وتعبئة بيانات المعلم تلقائياً عند ربط الحساب به"""

    def setUp(self):
        self.inst = Institute.objects.create(name="معهد فحص المعلمين", code="INST-INST-01")
        self.admin = User.objects.create_superuser(username="admin_super", password="SuperPassword123!")
        self.client = Client()
        self.client.login(username="admin_super", password="SuperPassword123!")

        self.instructor = Instructor.objects.create(
            military_number="778899",
            name="طارق زياد عبد الرحمن",
            rank="مقدم",
            unit="سلاح المهندسين",
            phone="0911223344",
            institute=self.inst,
        )

    def test_user_creation_with_instructor_populates_missing_fields(self):
        """التحقق من أن ربط الحساب بالمعلم يقوم بمزامنة وتعبئة النمرة والرتبة والوحدة والهاتف والاسم"""
        url = reverse('training:user_create')
        res = self.client.post(url, {
            'username': 'tariq_user',
            'password': 'TariqPassword123!',
            'first_name': '',  # فارغ ليتم استيراده من المعلم
            'last_name': '',   # فارغ
            'role': UserRole.INSTRUCTOR,
            'instructor': self.instructor.military_number,
            'military_number': '',
            'rank': '',
            'unit': '',
            'phone': '',
            'is_active': 'on',
        })
        self.assertEqual(res.status_code, 302)
        created_user = User.objects.filter(username='tariq_user').first()
        self.assertIsNotNone(created_user)
        self.assertEqual(created_user.first_name, 'طارق')
        self.assertEqual(created_user.last_name, 'زياد عبد الرحمن')
        self.assertEqual(created_user.profile.military_number, '778899')
        self.assertEqual(created_user.profile.rank, 'مقدم')
        self.assertEqual(created_user.profile.unit, 'سلاح المهندسين')
        self.assertEqual(created_user.profile.phone, '0911223344')


class UniqueEmailAndPhoneValidationTests(TestCase):
    """فحص قيود فرادة البريد الإلكتروني ورقم الهاتف عبر نماذج المنظومة"""

    def setUp(self):
        self.inst = Institute.objects.create(name="معهد فحص الفرادة", code="INST-UNIQ-01")
        self.user1 = User.objects.create_user(
            username='user_unique_1',
            password='Password123!',
            email='unique1@example.com'
        )
        self.user1.profile.phone = '0123456781'
        self.user1.profile.save()

        self.instructor1 = Instructor.objects.create(
            military_number="112233",
            name="معلم تجريبي",
            rank="نقيب",
            phone="0123456782",
            institute=self.inst
        )

        self.trainee1 = Trainee.objects.create(
            military_number="445566",
            name="دارس تجريبي",
            phone="0123456783",
            institute=self.inst
        )

    def test_user_create_duplicate_email_fails(self):
        """التحقق من منع تكرار البريد الإلكتروني عند إنشاء مستخدم جديد"""
        from apps.core.forms import UserCreateForm
        form = UserCreateForm(data={
            'username': 'new_user_dup_email',
            'password': 'Password123!',
            'first_name': 'تجربة',
            'email': 'unique1@example.com',  # مكرر
            'phone': '0123456789',
            'role': 'regular',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('email', form.errors)

    def test_user_create_duplicate_phone_fails(self):
        """التحقق من منع تكرار رقم الهاتف عند إنشاء مستخدم جديد"""
        from apps.core.forms import UserCreateForm
        form = UserCreateForm(data={
            'username': 'new_user_dup_phone',
            'password': 'Password123!',
            'first_name': 'تجربة',
            'email': 'unique_new@example.com',
            'phone': '0123456781',  # مكرر لمستخدم 1
            'role': 'regular',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('phone', form.errors)

    def test_user_edit_unique_email_and_phone(self):
        """التحقق من فحص فرادة البريد والهاتف عند تعديل بيانات المستخدم"""
        from apps.core.forms import UserEditForm
        user2 = User.objects.create_user(
            username='user_unique_2',
            password='Password123!',
            email='unique2@example.com'
        )
        user2.profile.phone = '0123456789'
        user2.profile.save()

        # احتفاظ المستخدم ببريده وهاتفه الشخصي ينجح
        form_self = UserEditForm(data={
            'first_name': 'تجربة 2',
            'email': 'unique2@example.com',
            'phone': '0123456789',
            'role': 'regular',
        }, instance=user2)
        self.assertTrue(form_self.is_valid(), form_self.errors)

        # تغيير البريد لبريد مستخدم آخر يفشل
        form_dup_email = UserEditForm(data={
            'first_name': 'تجربة 2',
            'email': 'unique1@example.com',
            'phone': '0123456789',
            'role': 'regular',
        }, instance=user2)
        self.assertFalse(form_dup_email.is_valid())
        self.assertIn('email', form_dup_email.errors)

        # تغيير الهاتف لهاتف مستخدم آخر يفشل
        form_dup_phone = UserEditForm(data={
            'first_name': 'تجربة 2',
            'email': 'unique2@example.com',
            'phone': '0123456781',
            'role': 'regular',
        }, instance=user2)
        self.assertFalse(form_dup_phone.is_valid())
        self.assertIn('phone', form_dup_phone.errors)

    def test_instructor_and_trainee_duplicate_phone_fails(self):
        """التحقق من منع تكرار رقم الهاتف في نماذج المعلمين والدارسين"""
        from apps.academic.forms import InstructorForm
        from apps.trainees.forms import TraineeForm

        inst_form = InstructorForm(data={
            'military_number': '998877',
            'name': 'معلم جديد',
            'rank': 'مقدم',
            'phone': '0123456782',  # مكرر لمعلم 1
        })
        self.assertFalse(inst_form.is_valid())
        self.assertIn('phone', inst_form.errors)

        trainee_form = TraineeForm(data={
            'military_number': '998866',
            'name': 'دارس جديد',
            'rank': 'ملازم',
            'category': 'officer',
            'phone': '0123456783',  # مكرر لدارس 1
        })
        self.assertFalse(trainee_form.is_valid())
        self.assertIn('phone', trainee_form.errors)


class MessageAlertStylingAndDangerTagTests(TestCase):
    """اختبارات مطابقة وسوم ورسائل التنبيهات مع فئات التنبيه باللون الأحمر"""

    def test_message_tags_mapping_in_settings(self):
        """التحقق من تعيين وسم الخطأ إلى danger لتفعيل اللون الأحمر"""
        from django.conf import settings
        from django.contrib.messages import constants as messages_constants
        self.assertTrue(hasattr(settings, 'MESSAGE_TAGS'))
        self.assertEqual(settings.MESSAGE_TAGS.get(messages_constants.ERROR), 'danger')

    def test_admin_portal_error_alert_renders_danger_and_red_icon(self):
        """التحقق من أن رسائل الخطأ تظهر في لوحة الأدمن بفئة alert-danger وأيقونة التحذير الحمراء"""
        from django.template import Context, Template
        template_str = """
        {% load static %}
        {% if messages %}
            {% for message in messages %}
                <div class="alert {% if 'error' in message.tags or 'danger' in message.tags %}alert-danger{% elif 'success' in message.tags %}alert-success{% elif 'warning' in message.tags %}alert-warning{% else %}alert-info{% endif %}">
                    <i class="bi {% if 'error' in message.tags or 'danger' in message.tags %}bi-exclamation-triangle-fill text-danger{% else %}bi-check-circle-fill text-success{% endif %}"></i>
                    <div>{{ message }}</div>
                </div>
            {% endfor %}
        {% endif %}
        """
        class DummyMessage:
            def __init__(self, message, tags):
                self.message = message
                self.tags = tags
            def __str__(self):
                return self.message

        # حالة وسم error أو danger
        dummy_err = DummyMessage("اسم المستخدم هذا مسجل مسبقاً، الرجاء اختيار اسم آخر.", "error")
        rendered = Template(template_str).render(Context({'messages': [dummy_err]}))
        self.assertIn('alert-danger', rendered)
        self.assertIn('bi-exclamation-triangle-fill text-danger', rendered)
        self.assertNotIn('alert-error', rendered)


class CourseEnrollmentCompositeRankTests(TestCase):
    """اختبارات تركيب وحفظ الرتبة العسكرية المتكاملة للدارس (رتبة + مهنة + ركن)"""

    def setUp(self):
        from apps.trainees.models import Trainee
        from apps.academic.models import Course, CourseCategory, CourseSession
        self.trainee = Trainee.objects.create(
            military_number='12345678',
            name='ضابط اختبار الرتبة',
            category='officer'
        )
        self.category = CourseCategory.objects.create(
            name='دورات الضباط'
        )
        self.course = Course.objects.create(
            name='دورة القيادة والأركان',
            category=self.category
        )
        self.session = CourseSession.objects.create(
            course=self.course,
            session_code='80',
            status='active',
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=30),
            attendance_max_grade=10
        )

    def test_composite_rank_storage_with_profession_and_staff(self):
        """التحقق من حفظ الرتبة المتكاملة: رائد مهندس ركن"""
        from apps.academic.models import CourseEnrollment
        enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank='رائد مهندس ركن',
            current_unit='سلاح المهندسين'
        )
        self.assertEqual(enrollment.current_rank, 'رائد مهندس ركن')

    def test_composite_rank_storage_with_profession_only(self):
        """التحقق من حفظ الرتبة المتكاملة: ملازم تقني"""
        from apps.academic.models import CourseEnrollment
        enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank='ملازم تقني',
            current_unit='إدارة نظم المعلومات'
        )
        self.assertEqual(enrollment.current_rank, 'ملازم تقني')

    def test_composite_rank_storage_with_staff_only(self):
        """التحقق من حفظ الرتبة المتكاملة: مقدم ركن"""
        from apps.academic.models import CourseEnrollment
        enrollment = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank='مقدم ركن',
            current_unit='الفرقة المدرعة'
        )
        self.assertEqual(enrollment.current_rank, 'مقدم ركن')

    def test_full_rank_property_and_discrete_fields(self):
        """التحقق من حقول صفة أركان الحرب والمهنة وخاصية full_rank"""
        from apps.trainees.models import Trainee
        from apps.academic.models import CourseEnrollment
        en = CourseEnrollment.objects.create(
            session=self.session,
            trainee=self.trainee,
            current_rank='مقدم',
            profession='مهندس',
            staff_status='ركن'
        )
        self.assertEqual(en.staff_status, 'ركن')
        self.assertEqual(en.profession, 'مهندس')
        self.assertEqual(en.full_rank, 'مقدم مهندس ركن')

        t2 = Trainee.objects.create(
            military_number='12345679',
            name='ضابط ثان',
            category='officer'
        )
        # ضابط غير ركن لا تضاف له صفة غير ركن في اللقب
        en2 = CourseEnrollment.objects.create(
            session=self.session,
            trainee=t2,
            current_rank='نقيب',
            profession='طبيب',
            staff_status='غير ركن'
        )
        self.assertEqual(en2.full_rank, 'نقيب طبيب')

        t3 = Trainee.objects.create(
            military_number='12345680',
            name='ضابط صف اختبار',
            category='nco'
        )
        # ضابط صف مع مهنة فني
        en3 = CourseEnrollment.objects.create(
            session=self.session,
            trainee=t3,
            current_rank='مساعد',
            profession='فني'
        )
        self.assertEqual(en3.full_rank, 'مساعد فني')


class CertificateAndMovementOrderLayoutTests(TestCase):
    """اختبارات تخصيص أبعاد ومسافات ومواقع نصوص الشهادات وأمر التحرك"""

    def setUp(self):
        from apps.documents.models import CertificateSettings, MovementOrderSettings
        self.cert_settings = CertificateSettings.objects.create(
            header_line_1='إدارة نظم المعلومات',
            header_line_2='معهد نظم المعلومات'
        )
        self.movement_settings = MovementOrderSettings.objects.create(
            order_title='أمر تحرك رسمي'
        )

    def test_cert_default_layout(self):
        """التحقق من الحصول على المسافات الافتراضية للشهادة عند عدم وجود تخصيص"""
        layout = self.cert_settings.get_layout()
        self.assertEqual(layout['page_padding_top'], 12)
        self.assertEqual(layout['page_padding_horizontal'], 18)
        self.assertEqual(layout['title_size'], 32)
        self.assertEqual(layout['title_align'], 'center')

    def test_cert_custom_layout_override(self):
        """التحقق من دمج التخصيصات المحفوظة مع القيم الافتراضية للشهادة"""
        self.cert_settings.layout_config = {
            'page_padding_top': 20,
            'title_size': 44,
            'title_align': 'right',
        }
        self.cert_settings.save()
        layout = self.cert_settings.get_layout()
        self.assertEqual(layout['page_padding_top'], 20)
        self.assertEqual(layout['title_size'], 44)
        self.assertEqual(layout['title_align'], 'right')
        # تحقق من بقاء الحقول الأخرى على قيمها الافتراضية
        self.assertEqual(layout['page_padding_horizontal'], 18)

    def test_movement_order_default_layout(self):
        """التحقق من الحصول على المسافات الافتراضية لأمر التحرك عند عدم وجود تخصيص"""
        layout = self.movement_settings.get_layout()
        self.assertEqual(layout['page_padding_top'], 20)
        self.assertEqual(layout['page_padding_horizontal'], 22)
        self.assertEqual(layout['table_label_width'], 135)
        self.assertEqual(layout['trainee_line_layout'], 'side_by_side_right')
        self.assertEqual(layout['trainee_line_gap'], 20)
        self.assertEqual(layout['footer_layout'], 'copies_first')
        self.assertEqual(layout['signer_box_align'], 'right')

    def test_reverse_copies_and_signatures_layout(self):
        """التحقق من عكس ترتيب النسخ والتواقيع ومحاذاة التوقيعات لليمين"""
        layout = self.movement_settings.get_layout()
        self.assertEqual(layout['footer_layout'], 'copies_first')
        self.assertEqual(layout['signer_box_align'], 'right')
        # تحقق من إمكانية التبديل إلى signer_first
        self.movement_settings.layout_config = {'footer_layout': 'signer_first', 'signer_box_align': 'center'}
        self.movement_settings.save()
        updated = self.movement_settings.get_layout()
        self.assertEqual(updated['footer_layout'], 'signer_first')
        self.assertEqual(updated['signer_box_align'], 'center')

    def test_movement_order_custom_layout_override(self):
        """التحقق من دمج التخصيصات المحفوظة مع القيم الافتراضية لأمر التحرك"""
        self.movement_settings.layout_config = {
            'page_padding_top': 25,
            'table_label_width': 160,
            'trainee_line_layout': 'reverse',
            'issuing_align': 'right',
        }
        self.movement_settings.save()
        layout = self.movement_settings.get_layout()
        self.assertEqual(layout['page_padding_top'], 25)
        self.assertEqual(layout['table_label_width'], 160)
        self.assertEqual(layout['trainee_line_layout'], 'reverse')
        self.assertEqual(layout['issuing_align'], 'right')
        self.assertEqual(layout['page_padding_horizontal'], 22)

    def test_cert_form_layout_json_parsing(self):
        """التحقق من معالجة حقل التنسيقات عند الإرسال عبر نموذج الاستمارة للشهادة"""
        from apps.documents.forms import CertificateSettingsForm
        from django.forms.models import model_to_dict
        import json
        form_data = model_to_dict(self.cert_settings)
        form_data['layout_config'] = json.dumps({'title_size': 38, 'body_align': 'center'})
        form = CertificateSettingsForm(data=form_data, instance=self.cert_settings)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.layout_config.get('title_size'), 38)
        self.assertEqual(saved.layout_config.get('body_align'), 'center')

    def test_movement_form_layout_json_parsing(self):
        """التحقق من معالجة حقل التنسيقات عند الإرسال عبر نموذج استمارة أمر التحرك"""
        from apps.documents.forms import MovementOrderSettingsForm
        from django.forms.models import model_to_dict
        import json
        form_data = model_to_dict(self.movement_settings)
        form_data['layout_config'] = json.dumps({'page_padding_top': 18, 'trainee_line_layout': 'center'})
        form = MovementOrderSettingsForm(data=form_data, instance=self.movement_settings)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.layout_config.get('page_padding_top'), 18)
        self.assertEqual(saved.layout_config.get('trainee_line_layout'), 'center')

    def test_form_invalid_json_fallback(self):
        """التحقق من المعالجة الآمنة للقيم غير الصالحة كـ JSON"""
        from apps.documents.forms import MovementOrderSettingsForm
        from django.forms.models import model_to_dict
        form_data = model_to_dict(self.movement_settings)
        form_data['layout_config'] = 'invalid-not-json'
        form = MovementOrderSettingsForm(data=form_data, instance=self.movement_settings)
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertEqual(saved.layout_config, {})

    def test_side_by_side_trainee_layout(self):
        """التحقق من وضع اسم الطالب بجانب البطاقة مع المسافة الفاصلة ومحاذاة العناوين"""
        self.movement_settings.layout_config = {
            'trainee_line_layout': 'side_by_side_right',
            'trainee_line_gap': 35,
            'bismillah_align': 'right',
            'title_align': 'right',
            'declaration_header_align': 'right',
            'traveler_sig_align': 'right',
        }
        self.movement_settings.save()
        layout = self.movement_settings.get_layout()
        self.assertEqual(layout['trainee_line_layout'], 'side_by_side_right')
        self.assertEqual(layout['trainee_line_gap'], 35)
        self.assertEqual(layout['bismillah_align'], 'right')
        self.assertEqual(layout['title_align'], 'right')
        self.assertEqual(layout['declaration_header_align'], 'right')
        self.assertEqual(layout['traveler_sig_align'], 'right')

    def test_traveler_sig_position_settings_and_rendering(self):
        """التحقق من خيارات موضع سطر توقيع المسافر في أمر التحرك الرسمي"""
        layout = self.movement_settings.get_layout()
        self.assertEqual(layout['traveler_sig_position'], 'top_left')
        self.assertEqual(layout['traveler_sig_size'], 14)
        self.assertEqual(layout['traveler_sig_margin_top'], 4)

        # تغيير الموضع إلى بداية الصفحة
        self.movement_settings.layout_config = {
            'traveler_sig_position': 'top',
            'traveler_sig_align': 'right',
            'traveler_sig_size': 16,
            'traveler_sig_margin_top': 10,
        }
        self.movement_settings.save()
        updated_top = self.movement_settings.get_layout()
        self.assertEqual(updated_top['traveler_sig_position'], 'top')
        self.assertEqual(updated_top['traveler_sig_align'], 'right')
        self.assertEqual(updated_top['traveler_sig_size'], 16)
        self.assertEqual(updated_top['traveler_sig_margin_top'], 10)

        # تغيير الموضع إلى وسط الصفحة بعد الجدول
        self.movement_settings.layout_config = {'traveler_sig_position': 'after_table'}
        self.movement_settings.save()
        updated_middle = self.movement_settings.get_layout()
        self.assertEqual(updated_middle['traveler_sig_position'], 'after_table')
































