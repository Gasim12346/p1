from django.contrib import admin
from .models import PlacementExamOrder, PlacementExamCandidate


class PlacementExamCandidateInline(admin.TabularInline):
    model = PlacementExamCandidate
    extra = 0
    fields = [
        'military_number_snapshot',
        'name_snapshot',
        'rank_snapshot',
        'attendance_status',
        'action_type',
        'theory_score',
        'practical_score',
        'total_score',
        'percentage',
        'grade_label',
        'is_passed',
        'is_graded',
        'is_transferred',
    ]
    readonly_fields = [
        'total_score',
        'percentage',
        'grade_label',
        'is_passed',
        'is_graded',
    ]


@admin.register(PlacementExamOrder)
class PlacementExamOrderAdmin(admin.ModelAdmin):
    list_display = [
        'order_code',
        'institute',
        'year',
        'internal_order_number',
        'signal_number',
        'source_entity',
        'purpose',
        'exam_date',
        'status',
        'is_confirmed',
    ]
    list_filter = [
        'institute',
        'year',
        'status',
        'is_confirmed',
        'classification',
        'assessment_type',
    ]
    search_fields = [
        'order_code',
        'signal_number',
        'source_entity',
        'purpose',
        'sub_purpose',
    ]
    readonly_fields = [
        'order_code',
        'created_at',
        'updated_at',
        'confirmed_at',
        'approved_at',
    ]
    inlines = [PlacementExamCandidateInline]


@admin.register(PlacementExamCandidate)
class PlacementExamCandidateAdmin(admin.ModelAdmin):
    list_display = [
        'military_number_snapshot',
        'name_snapshot',
        'rank_snapshot',
        'order',
        'attendance_status',
        'total_score',
        'percentage',
        'grade_label',
        'is_passed',
        'is_graded',
        'is_transferred',
    ]
    list_filter = [
        'attendance_status',
        'action_type',
        'is_passed',
        'is_graded',
        'is_transferred',
        'order__institute',
        'order__year',
    ]
    search_fields = [
        'military_number_snapshot',
        'name_snapshot',
        'order__order_code',
        'order__signal_number',
    ]
    readonly_fields = [
        'total_score',
        'percentage',
        'grade_label',
        'is_passed',
        'is_graded',
        'created_at',
        'updated_at',
    ]
