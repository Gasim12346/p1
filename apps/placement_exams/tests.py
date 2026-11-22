"""
اختبارات شاملة لخدمات وقواعد عمل امتحانات تحديد المستوى.
تغطي:
1. الترقيم السنوي وتوليد الأكواد المستقلة لكل معهد وسنة.
2. إعادة استخدام الرقم المحذوف قبل تأكيد الانعقاد.
3. منع حذف الطلبات المؤكدة أو المعتمدة.
4. حساب الأشهر التقويمية الستة وحالات الأهلية والذكرى السادسة بدقة.
5. البحث عن النتائج المؤهلة والفرز للأحدث.
6. الاحتساب النسبي للدرجات المنقولة وعدم المساس بالسجل السابق إطلاقاً.
7. استبدال النتيجة المنقولة عند إعادة الدارس للامتحان.
"""

from datetime import date
from decimal import Decimal
from django.test import TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User

from apps.core.models import Institute
from apps.trainees.models import Trainee, TraineeCategory
from apps.academic.models import Instructor, InstructorCategory

from .models import (
    PlacementExamOrder,
    PlacementExamCandidate,
    PlacementExamStatus,
    AttendanceStatus,
    CandidateActionType,
    AssessmentType,
)
from .services import (
    get_next_order_number,
    delete_placement_order,
    is_eligible_calendar_months,
    get_six_month_anniversary,
    find_eligible_previous_result,
    calculate_transferred_scores,
    apply_transfer_to_candidate,
    replace_transferred_with_new_exam,
)


class PlacementExamServicesTestCase(TestCase):
    def setUp(self):
        # تجهيز المعاهد
        self.institute1 = Institute.objects.create(
            code='inst-armored',
            name='معهد المدرعات',
            parent_unit='قيادة سلاح المدرعات'
        )
        self.institute2 = Institute.objects.create(
            code='inst-infantry',
            name='معهد المشاة',
            parent_unit='قيادة سلاح المشاة'
        )

        # مستخدم للنظام
        self.user = User.objects.create_user(username='officer1', password='password123')

        # معلم مشرف
        self.instructor = Instructor.objects.create(
            institute=self.institute1,
            military_number='112233',
            name='قاسم ابوه',
            rank='مقدم',
            category=InstructorCategory.OFFICER,
            force='القوات البرية',
            unit='سلاح المدرعات'
        )

        # دارس للاختبار
        self.trainee = Trainee.objects.create(
            institute=self.institute1,
            military_number='482910',
            name='عثمان البشير فضل المولى',
            category=TraineeCategory.OFFICER,
            force='القوات البرية السودانية',
            unit='سلاح المدرعات (الشجرة)'
        )

    # -----------------------------------------------------------------
    # 1. اختبارات الترقيم السنوي
    # -----------------------------------------------------------------
    def test_get_next_order_number_basic(self):
        """يبدأ الترقيم من 1 ويولد كود بصيغة 001/2026"""
        num, code = get_next_order_number(self.institute1, year=2026)
        self.assertEqual(num, 1)
        self.assertEqual(code, '001/2026')

    def test_order_number_independent_per_institute_and_year(self):
        """الترقيم مستقل تماماً لكل معهد ولكل سنة ميلادية"""
        # معهد 1 سنة 2026
        PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=1,
            signal_number='SIG-01',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 10),
            exam_date=date(2026, 1, 20)
        )
        num1_2026, code1_2026 = get_next_order_number(self.institute1, year=2026)
        self.assertEqual(num1_2026, 2)
        self.assertEqual(code1_2026, '002/2026')

        # نفس المعهد سنة 2027 يبدأ من 1
        num1_2027, code1_2027 = get_next_order_number(self.institute1, year=2027)
        self.assertEqual(num1_2027, 1)
        self.assertEqual(code1_2027, '001/2027')

        # معهد 2 سنة 2026 يبدأ أيضاً من 1
        num2_2026, code2_2026 = get_next_order_number(self.institute2, year=2026)
        self.assertEqual(num2_2026, 1)
        self.assertEqual(code2_2026, '001/2026')

    def test_reuse_deleted_order_number_before_confirmation(self):
        """إعادة استخدام رقم الطلب المحذوف قبل تأكيد الانعقاد"""
        order1 = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=1,
            signal_number='SIG-01',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 10),
            exam_date=date(2026, 1, 20),
            status=PlacementExamStatus.IN_PROGRESS
        )
        order2 = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=2,
            signal_number='SIG-02',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 12),
            exam_date=date(2026, 1, 22),
            status=PlacementExamStatus.IN_PROGRESS
        )
        order3 = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=3,
            signal_number='SIG-03',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 14),
            exam_date=date(2026, 1, 24),
            status=PlacementExamStatus.IN_PROGRESS
        )

        # حذف الطلب رقم 2
        delete_placement_order(order2)

        # توليد الرقم التالي يجب أن يسترجع 2 كأصغر فجوة متاحة
        next_num, next_code = get_next_order_number(self.institute1, year=2026)
        self.assertEqual(next_num, 2)
        self.assertEqual(next_code, '002/2026')

    def test_prevent_delete_confirmed_or_approved_order(self):
        """منع حذف الطلب بمجرد تأكيد انعقاده أو اعتماده"""
        confirmed_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=1,
            signal_number='SIG-01',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 10),
            exam_date=date(2026, 1, 20),
            status=PlacementExamStatus.CONFIRMED,
            is_confirmed=True
        )
        with self.assertRaises(ValidationError):
            delete_placement_order(confirmed_order)

        approved_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=2,
            signal_number='SIG-02',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 10),
            exam_date=date(2026, 1, 20),
            status=PlacementExamStatus.APPROVED,
            is_confirmed=True
        )
        with self.assertRaises(ValidationError):
            delete_placement_order(approved_order)

    # -----------------------------------------------------------------
    # 2. اختبارات حساب الأشهر التقويمية
    # -----------------------------------------------------------------
    def test_six_calendar_months_anniversary_cases(self):
        """فحص دقيق لحساب الذكرى السادسة بدقة الأشهر التقويمية وليس 180 يوماً"""
        # حالة 1: امتحان 10 مايو 2026 -> الذكرى السادسة 10 نوفمبر 2026
        prev_date = date(2026, 5, 10)
        self.assertEqual(get_six_month_anniversary(prev_date), date(2026, 11, 10))

        # 9 نوفمبر مؤهل (< 6 أشهر)
        self.assertTrue(is_eligible_calendar_months(prev_date, date(2026, 11, 9)))
        # 10 نوفمبر (يوم الذكرى نفسه) غير مؤهل
        self.assertFalse(is_eligible_calendar_months(prev_date, date(2026, 11, 10)))
        # 11 نوفمبر غير مؤهل
        self.assertFalse(is_eligible_calendar_months(prev_date, date(2026, 11, 11)))

        # حالة 2: نهاية الشهر والسنوات الكبيسة (31 أغسطس 2023 -> 29 فبراير 2024 سنة كبيسة)
        prev_aug = date(2023, 8, 31)
        self.assertEqual(get_six_month_anniversary(prev_aug), date(2024, 2, 29))
        self.assertTrue(is_eligible_calendar_months(prev_aug, date(2024, 2, 28)))
        self.assertFalse(is_eligible_calendar_months(prev_aug, date(2024, 2, 29)))

        # تاريخ مرجعي يسبق الامتحان غير صالح
        self.assertFalse(is_eligible_calendar_months(date(2026, 5, 10), date(2026, 4, 1)))

    # -----------------------------------------------------------------
    # 3. اختبارات محرك نقل النتائج السابقة
    # -----------------------------------------------------------------
    def test_find_eligible_previous_result(self):
        """فحص العثور على النتيجة المؤهلة وفق المعايير والشروط"""
        # امتحان سابق معتمد وناجح وتاريخه قبل 3 أشهر (صالح)
        old_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=1,
            signal_number='SIG-OLD',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 1),
            exam_date=date(2026, 1, 15),
            status=PlacementExamStatus.APPROVED,
            is_confirmed=True
        )
        old_candidate = PlacementExamCandidate.objects.create(
            order=old_order,
            trainee=self.trainee,
            theory_score=Decimal('45.0'),
            practical_score=Decimal('35.0'),
            attendance_status=AttendanceStatus.PRESENT
        )
        # التأكد من نجاح السجل القديم واكتماله
        self.assertTrue(old_candidate.is_passed)
        self.assertEqual(old_candidate.total_score, Decimal('80.0'))

        # البحث بتاريخ طلب جديد في 1 أبريل 2026 (< 6 أشهر)
        result = find_eligible_previous_result(self.trainee, reference_date=date(2026, 4, 1))
        self.assertIsNotNone(result)
        self.assertEqual(result.id, old_candidate.id)

        # البحث بتاريخ بعد 7 أشهر (غير مؤهل)
        result_expired = find_eligible_previous_result(self.trainee, reference_date=date(2026, 8, 1))
        self.assertIsNone(result_expired)

    def test_ineligible_when_not_approved_or_failed(self):
        """لا تُنقل النتائج إذا كان الامتحان السابق غير معتمد أو كان راسباً"""
        # امتحان قيد التنفيذ (غير معتمد)
        unapproved_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=10,
            signal_number='SIG-UNAPP',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 1),
            exam_date=date(2026, 1, 15),
            status=PlacementExamStatus.IN_PROGRESS
        )
        PlacementExamCandidate.objects.create(
            order=unapproved_order,
            trainee=self.trainee,
            theory_score=Decimal('45.0'),
            practical_score=Decimal('35.0'),
            attendance_status=AttendanceStatus.PRESENT
        )
        self.assertIsNone(find_eligible_previous_result(self.trainee, reference_date=date(2026, 3, 1)))

        # امتحان معتمد لكن راسب (40%)
        failed_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=11,
            signal_number='SIG-FAIL',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 1),
            exam_date=date(2026, 1, 15),
            status=PlacementExamStatus.APPROVED,
            is_confirmed=True
        )
        failed_candidate = PlacementExamCandidate.objects.create(
            order=failed_order,
            trainee=self.trainee,
            theory_score=Decimal('20.0'),
            practical_score=Decimal('20.0'),
            attendance_status=AttendanceStatus.PRESENT
        )
        self.assertFalse(failed_candidate.is_passed)
        self.assertIsNone(find_eligible_previous_result(self.trainee, reference_date=date(2026, 3, 1)))

    def test_calculate_transferred_scores_proportional(self):
        """الاحتساب النسبي للدرجة وفق توزيع درجات الامتحان الحالي"""
        old_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=1,
            signal_number='SIG-OLD',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 1),
            exam_date=date(2026, 1, 15),
            total_max_score=Decimal('100.0'),
            theory_max_score=Decimal('50.0'),
            practical_max_score=Decimal('50.0'),
            status=PlacementExamStatus.APPROVED
        )
        old_candidate = PlacementExamCandidate.objects.create(
            order=old_order,
            trainee=self.trainee,
            theory_score=Decimal('40.0'),
            practical_score=Decimal('40.0') # الإجمالي 80%
        )

        # امتحان جديد بتوزيع مختلف (نظري 60 وعملي 40)
        target_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=2,
            signal_number='SIG-NEW',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 3, 1),
            exam_date=date(2026, 3, 15),
            assessment_type=AssessmentType.THEORY_AND_PRACTICAL,
            theory_max_score=Decimal('60.0'),
            practical_max_score=Decimal('40.0'),
            total_max_score=Decimal('100.0')
        )

        calc = calculate_transferred_scores(old_candidate, target_order)
        # 80% من 60 = 48.0
        self.assertEqual(calc['theory_score'], Decimal('48.0'))
        # 80% من 40 = 32.0
        self.assertEqual(calc['practical_score'], Decimal('32.0'))
        # الإجمالي 80.0 والنسبة 80% والتقدير جيد جداً (ب)
        self.assertEqual(calc['total_score'], Decimal('80.0'))
        self.assertEqual(calc['percentage'], Decimal('80.00'))
        self.assertEqual(calc['grade_label'], 'جيد جداً (ب)')
        self.assertTrue(calc['is_passed'])

    def test_apply_transfer_and_ensure_previous_record_untouched(self):
        """نقل النتيجة بنجاح والتأكد التام من عدم تعديل سجل الامتحان السابق"""
        old_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=1,
            signal_number='SIG-OLD',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 1),
            exam_date=date(2026, 1, 15),
            status=PlacementExamStatus.APPROVED
        )
        old_candidate = PlacementExamCandidate.objects.create(
            order=old_order,
            trainee=self.trainee,
            theory_score=Decimal('42.5'),
            practical_score=Decimal('42.5')
        )
        old_candidate_original_updated_at = old_candidate.updated_at
        old_total = old_candidate.total_score

        new_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=2,
            signal_number='SIG-NEW',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 3, 1),
            exam_date=date(2026, 3, 15)
        )
        new_candidate = PlacementExamCandidate.objects.create(
            order=new_order,
            trainee=self.trainee
        )

        # تطبيق النقل
        apply_transfer_to_candidate(new_candidate, old_candidate)

        # التحقق من بيانات السجل الحالي
        new_candidate.refresh_from_db()
        self.assertTrue(new_candidate.is_transferred)
        self.assertEqual(new_candidate.action_type, CandidateActionType.RETAIN)
        self.assertEqual(new_candidate.transfer_source_candidate, old_candidate)
        self.assertEqual(new_candidate.transferred_original_date, old_order.exam_date)
        self.assertEqual(new_candidate.transferred_original_score, old_total)

        # التحقق الصارم من عدم تعديل سجل الامتحان السابق
        old_candidate.refresh_from_db()
        self.assertEqual(old_candidate.total_score, old_total)
        self.assertEqual(old_candidate.updated_at, old_candidate_original_updated_at)

    def test_replace_transferred_result_on_resit(self):
        """استبدال النتيجة المنقولة بدرجات الامتحان الجديد عند رغبة الدارس في إعادة الاختبار"""
        old_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=1,
            signal_number='SIG-OLD',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 1, 1),
            exam_date=date(2026, 1, 15),
            status=PlacementExamStatus.APPROVED
        )
        old_candidate = PlacementExamCandidate.objects.create(
            order=old_order,
            trainee=self.trainee,
            theory_score=Decimal('30.0'),
            practical_score=Decimal('30.0') # 60%
        )

        new_order = PlacementExamOrder.objects.create(
            institute=self.institute1,
            year=2026,
            internal_order_number=2,
            signal_number='SIG-NEW',
            source_entity='سلاح المدرعات',
            purpose='آلية',
            receipt_date=date(2026, 3, 1),
            exam_date=date(2026, 3, 15),
            theory_max_score=Decimal('50.0'),
            practical_max_score=Decimal('50.0'),
            total_max_score=Decimal('100.0')
        )
        new_candidate = PlacementExamCandidate.objects.create(
            order=new_order,
            trainee=self.trainee
        )

        # نقل النتيجة أولاً
        apply_transfer_to_candidate(new_candidate, old_candidate)
        self.assertTrue(new_candidate.is_transferred)
        self.assertEqual(new_candidate.total_score, Decimal('60.0'))

        # الدارس يعيد الامتحان ويحصل على درجة أعلى (45 نظري و 45 عملي = 90 ممتاز)
        replace_transferred_with_new_exam(
            new_candidate,
            theory_score=Decimal('45.0'),
            practical_score=Decimal('45.0')
        )

        new_candidate.refresh_from_db()
        self.assertFalse(new_candidate.is_transferred)
        self.assertEqual(new_candidate.action_type, CandidateActionType.EXAM)
        self.assertEqual(new_candidate.total_score, Decimal('90.0'))
        self.assertEqual(new_candidate.percentage, Decimal('90.00'))
        self.assertEqual(new_candidate.grade_label, 'ممتاز (أ)')
        self.assertTrue(new_candidate.is_passed)

        # التأكد من بقاء السجل السابق كما هو (60%)
        old_candidate.refresh_from_db()
        self.assertEqual(old_candidate.total_score, Decimal('60.0'))
