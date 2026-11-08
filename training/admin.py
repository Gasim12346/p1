from django.contrib import admin
from .models import (
    Instructor, CourseCategory, Course, Subject, CourseSession,
    SessionSubjectInstructor, Trainee, CourseEnrollment, TraineeSubjectGrade,
    CertificateSettings, SystemSettings, UserProfile
)


@admin.register(Instructor)
class InstructorAdmin(admin.ModelAdmin):
    list_display = ('military_number', 'category', 'rank', 'name', 'force', 'unit', 'phone', 'is_active', 'created_at')
    search_fields = ('military_number', 'name', 'rank', 'force', 'unit', 'phone')
    list_filter = ('category', 'is_active', 'force', 'rank')
    ordering = ('name',)


@admin.register(SessionSubjectInstructor)
class SessionSubjectInstructorAdmin(admin.ModelAdmin):
    list_display = ('session', 'subject', 'instructor')
    list_filter = ('session', 'instructor')
    search_fields = ('session__session_code', 'subject__name', 'instructor__name')


@admin.register(CourseCategory)
class CourseCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('course_number', 'name', 'category')
    list_filter = ('category',)
    search_fields = ('name', 'course_number')


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'course', 'credit_hours', 'max_grade')
    list_filter = ('course',)
    search_fields = ('name', 'code')


@admin.register(CourseSession)
class CourseSessionAdmin(admin.ModelAdmin):
    list_display = ('session_code', 'course', 'supervisor', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'course')
    search_fields = ('session_code', 'course__name', 'supervisor__name')


@admin.register(Trainee)
class TraineeAdmin(admin.ModelAdmin):
    list_display = ('military_number', 'name', 'category', 'unit', 'force')
    list_filter = ('category', 'force')
    search_fields = ('military_number', 'name', 'unit', 'force')


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = ('trainee', 'session', 'current_rank', 'current_force', 'current_unit', 'total_score', 'percentage', 'grade_label', 'is_graded')
    list_filter = ('session', 'is_graded')
    search_fields = ('trainee__name', 'trainee__military_number', 'current_rank')


@admin.register(CertificateSettings)
class CertificateSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'cert_title', 'station_text', 'header_line_1')


@admin.register(SystemSettings)
class SystemSettingsAdmin(admin.ModelAdmin):
    list_display = ('id', 'system_name', 'system_subheading')


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'role', 'military_number', 'rank')
    list_filter = ('role',)
