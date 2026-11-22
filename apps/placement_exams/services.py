"""
خدمات وقواعد عمل امتحانات تحديد المستوى (Placement Exams Services).
تشمل:
1. خدمة الترقيم السنوي وتوليد أكواد الطلبات مع دعم إعادة استخدام الأرقام المحذوفة وحماية التزامن.
2. خدمة فحص الأهلية ونقل النتائج السابقة المعتمدة (< 6 أشهر تقويمية وبنسبة >= 50%) واحتسابها نسبياً.
3. إدارة دورة عمل الطلبات والحذف الآمن قبل تأكيد الانعقاد.
"""

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple, List, Dict, Any

from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import Institute
from apps.trainees.models import Trainee
from .models import (
    PlacementExamOrder,
    PlacementExamCandidate,
    PlacementExamStatus,
    AttendanceStatus,
    CandidateActionType,
    AssessmentType,
)


# =====================================================================
# 1. خدمة الترقيم السنوي والتحكم في الأكواد (Annual Sequencing Service)
# =====================================================================

def get_next_order_number(institute: Institute, year: Optional[int] = None) -> Tuple[int, str]:
    """
    توليد الرقم الداخلي السنوي التالي وكود الطلب بصيغة (001/2026).
    
    القواعد المعتمدة:
    - الترقيم مستقل لكل معهد ولكل سنة ميلادية.
    - السماح بإعادة استخدام رقم الطلب المحذوف قبل تأكيد انعقاد الامتحان (البحث عن أصغر فجوة رقمية متاحة).
    - حماية التزامن الصارمة عبر قفل سجل المعهد (select_for_update) داخل معاملة ذرية لمنع تصادم الأرقام.
    
    :param institute: معهد المنشأة التعليمية المستهدف
    :param year: السنة الميلادية للطلب (افتراضياً السنة الحالية)
    :return: زوج يتكون من (الرقم التسلسلي الصحيح, كود الطلب المنسق)
    """
    if not institute:
        raise ValidationError("يجب تحديد المعهد لتوليد الترقيم السنوي.")
        
    if year is None:
        year = timezone.now().year

    # حماية التزامن: قفل سجل المعهد في قاعدة البيانات خلال العملية
    with transaction.atomic():
        # قفل سجل المعهد لمنع عمليتي إنشاء متزامنتين من قراءة نفس الأرقام
        Institute.objects.select_for_update().get(id=institute.id)

        # استرجاع الأرقام المستخدمة حالياً لهذا المعهد وتلك السنة مع قفل الأسطر
        used_numbers = list(
            PlacementExamOrder.objects.filter(
                institute=institute,
                year=year
            ).select_for_update().values_list('internal_order_number', flat=True)
        )

        used_set = set(used_numbers)

        # البحث عن أصغر رقم موجب متاح (إعادة استخدام الفجوات الناتجة عن الحذف)
        next_num = 1
        while next_num in used_set:
            next_num += 1

        formatted_code = f"{str(next_num).zfill(3)}/{year}"
        return next_num, formatted_code


def delete_placement_order(order: PlacementExamOrder, user=None) -> bool:
    """
    حذف طلب امتحان تحديد المستوى بأمان.
    
    القاعدة الصارمة:
    - يسمح بحذف الطلب فقط إذا كان في حالة «قيد التنفيذ» (in_progress) ولم يتم تأكيد انعقاده.
    - يُمنع منعاً باتاً حذف أي طلب تم تأكيد انعقاده أو اعتماده حفاظاً على سلامة السجلات.
    - الحذف الآمن يحرر الرقم السنوي الداخلي ليصبح متاحاً لإعادة الاستخدام في الطلبات اللاحقة.
    """
    if order.is_confirmed or order.status != PlacementExamStatus.IN_PROGRESS:
        raise ValidationError("لا يمكن حذف طلب تم تأكيد انعقاده أو اعتماده رسمياً.")
        
    with transaction.atomic():
        order.delete()
        return True


# =====================================================================
# 2. حسابات الأشهر التقويمية (Calendar Month Math)
# =====================================================================

def get_six_month_anniversary(start_date: date) -> date:
    """
    حساب تاريخ الذكرى الشهرية السادسة بدقة التقويم الشمسي (Calendar Months):
    - إضافة 6 أشهر إلى الشهر الأساسي.
    - ضبط السنة بدقة.
    - مراعاة الأيام القصوى للشهر المستهدف (مثال: 31 أغسطس -> 28 أو 29 فبراير).
    """
    target_month = start_date.month + 6
    target_year = start_date.year + (target_month - 1) // 12
    target_month = (target_month - 1) % 12 + 1
    _, max_days = calendar.monthrange(target_year, target_month)
    target_day = min(start_date.day, max_days)
    return date(target_year, target_month, target_day)


def is_eligible_calendar_months(prev_date: date, reference_date: date) -> bool:
    """
    التحقق من أن النتيجة السابقة صالحة وأقل تماماً من ستة أشهر تقويمية (< 6 calendar months).
    
    القاعدة الصارمة المعتمدة:
    - الحساب وفق تقويم الأشهر (Calendar Months) وليس 180 يوماً.
    - يوم الذكرى الشهرية السادسة نفسه يعتبر غير صالح (Strictly < 6 months).
    """
    if not prev_date or not reference_date:
        return False
        
    if reference_date < prev_date:
        return False
        
    exact_anniversary = get_six_month_anniversary(prev_date)
    return reference_date < exact_anniversary


# =====================================================================
# 3. محرك فحص ونقل النتائج السابقة (Previous Results Transfer Engine)
# =====================================================================

def find_eligible_previous_result(
    trainee: Trainee,
    reference_date: date,
    subject_name: str = 'حاسوب'
) -> Optional[PlacementExamCandidate]:
    """
    البحث عن أحدث نتيجة امتحان سابقة مؤهلة للنقل للدارس.
    
    شروط الأهلية المعتمدة:
    1. من امتحانات تحديد المستوى السابقة المعتمدة فقط (status = approved).
    2. خاصة بنفس المادة (افتراضياً حاسوب).
    3. نسبة النجاح 50% فأكثر (is_passed = True).
    4. تاريخ الامتحان السابق أقل تماماً من ستة أشهر تقويمية من تاريخ الاستلام المرجعي.
    5. في حال وجود أكثر من نتيجة مطابقة، يتم اختيار الأحدث تاريخاً.
    """
    if not trainee or not reference_date:
        return None

    # استعلام المرشحين في امتحانات معتمدة لنفس الدارس والمادة وناجحين
    previous_attempts = PlacementExamCandidate.objects.filter(
        trainee=trainee,
        order__status=PlacementExamStatus.APPROVED,
        order__subject_name=subject_name,
        is_graded=True,
        is_passed=True
    ).select_related('order').order_by('-order__exam_date', '-created_at')

    for attempt in previous_attempts:
        exam_date = attempt.order.exam_date
        if is_eligible_calendar_months(exam_date, reference_date):
            return attempt

    return None


def calculate_transferred_scores(
    source_candidate: PlacementExamCandidate,
    target_order: PlacementExamOrder
) -> Dict[str, Any]:
    """
    إعادة احتساب درجات النتيجة المنقولة وفق التوزيع الأقصى لدرجات الامتحان الحالي.
    
    القاعدة المعتمدة:
    - لا يُعدل سجل الامتحان السابق إطلاقاً.
    - يتم أخذ النسبة المئوية للنتيجة الأصلية وتطبيقها على الدرجات العظمى للامتحان الحالي.
    - إذا كان الامتحان الحالي نظري وعملي: تُوزع النسبة على النظري والعملي.
    - إذا كان الامتحان الحالي نظري فقط: تُطبق النسبة على النظري فقط ويكون العملي 0.
    """
    if not source_candidate or not target_order:
        raise ValidationError("بيانات الامتحان السابق أو أمر الامتحان المستهدف غير مكتملة.")

    # النسبة المئوية للنتيجة السابقة
    prev_pct = source_candidate.percentage
    if prev_pct is None:
        source_total_max = source_candidate.order.total_max_score or Decimal('100.0')
        source_score = source_candidate.total_score or Decimal('0.0')
        prev_pct = (source_score / source_total_max) * Decimal('100.0')

    prev_pct = Decimal(str(prev_pct))
    factor = prev_pct / Decimal('100.0')

    theory_max = target_order.theory_max_score or Decimal('0.0')
    practical_max = target_order.practical_max_score or Decimal('0.0')
    total_max = target_order.total_max_score or (theory_max + practical_max)

    if target_order.assessment_type == AssessmentType.THEORY_ONLY:
        trans_theory = (factor * total_max).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        trans_practical = Decimal('0.0')
        trans_total = trans_theory
    else:
        trans_theory = (factor * theory_max).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        trans_practical = (factor * practical_max).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
        trans_total = trans_theory + trans_practical

    final_pct = ((trans_total / total_max) * Decimal('100.0')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) if total_max > 0 else Decimal('0.0')
    grade_label = PlacementExamCandidate.get_grade_label_for_percentage(final_pct, is_absent=False)

    return {
        'theory_score': trans_theory,
        'practical_score': trans_practical,
        'total_score': trans_total,
        'percentage': final_pct,
        'grade_label': grade_label,
        'is_passed': final_pct >= Decimal('50.0'),
    }


def apply_transfer_to_candidate(
    candidate: PlacementExamCandidate,
    source_candidate: PlacementExamCandidate
) -> PlacementExamCandidate:
    """
    تطبيق نقل النتيجة على سجل الممتحن في الطلب الحالي.
    
    الإجراء:
    - توثيق الارتباط بالسجل السابق دون المساس به.
    - حفظ تاريخ الامتحان السابق ودرجته الأصلية.
    - تعيين action_type = 'retain' و is_transferred = True.
    - تخزين الدرجات المحتسبة نسبياً.
    """
    calc = calculate_transferred_scores(source_candidate, candidate.order)

    candidate.action_type = CandidateActionType.RETAIN
    candidate.is_transferred = True
    candidate.transfer_source_candidate = source_candidate
    candidate.transferred_original_date = source_candidate.order.exam_date
    candidate.transferred_original_score = source_candidate.total_score

    candidate.theory_score = calc['theory_score']
    candidate.practical_score = calc['practical_score']
    candidate.total_score = calc['total_score']
    candidate.percentage = calc['percentage']
    candidate.grade_label = calc['grade_label']
    candidate.is_passed = calc['is_passed']
    candidate.is_graded = True

    candidate.save()
    return candidate


def replace_transferred_with_new_exam(
    candidate: PlacementExamCandidate,
    theory_score: Decimal,
    practical_score: Optional[Decimal] = None
) -> PlacementExamCandidate:
    """
    إذا اختار الدارس إعادة الامتحان أو حضر جلسة الاختبار الفعلي:
    - تُستبدل النتيجة المنقولة بالدرجات الجديدة في الطلب الحالي.
    - يتحول إجراء الممتحن إلى action_type = 'exam'.
    - تُلغى راية النقل is_transferred = False.
    - يُحفظ السجل السابق دون أي تغيير في بياناته الأصلية.
    """
    candidate.action_type = CandidateActionType.EXAM
    candidate.is_transferred = False
    candidate.theory_score = theory_score
    candidate.practical_score = practical_score or Decimal('0.0')

    # الدالة calculate_results داخل save ستعيد حساب المجموع والنسبة والتقدير بناء على الدرجات الجديدة
    candidate.save()
    return candidate
