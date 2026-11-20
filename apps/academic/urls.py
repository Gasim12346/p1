from django.urls import path
from . import views

urlpatterns = [
    # الدورات ومفرداتها
    path('courses/', views.courses_catalog_view, name='courses_catalog'),
    path('courses/api/add-subject/', views.api_add_course_subject_view, name='api_add_course_subject'),
    path('courses/<int:course_id>/edit/', views.course_edit_view, name='course_edit'),
    path('courses/<int:course_id>/delete/', views.course_delete_view, name='course_delete'),
    path('subjects/<int:subject_id>/edit/', views.subject_edit_view, name='subject_edit'),
    path('subjects/<int:subject_id>/delete/', views.subject_delete_view, name='subject_delete'),

    # الدورات المنعقدة والدفعات
    path('sessions/', views.course_sessions_view, name='course_sessions'),
    path('sessions/create/', views.course_session_create_view, name='course_session_create'),
    path('sessions/api/next-number/', views.api_get_next_course_number_view, name='api_next_course_number'),
    path('sessions/<int:session_id>/manage/', views.course_session_manage_view, name='course_session_manage'),
    path('sessions/<int:session_id>/edit/', views.course_session_edit_view, name='course_session_edit'),
    path('sessions/<int:session_id>/delete/', views.course_session_delete_view, name='course_session_delete'),

    # النتائج ورصد الدرجات
    path('results/', views.results_center_view, name='results_center'),
    path('results/session/<int:session_id>/', views.results_entry_view, name='results_entry'),
    path('results/session/<int:session_id>/sheet/', views.session_results_sheet_view, name='session_results_sheet'),

    # إدارة المعلمين
    path('admin-portal/instructors/create/', views.instructor_create_view, name='instructor_create'),
    path('admin-portal/instructors/<str:military_number>/edit/', views.instructor_edit_view, name='instructor_edit'),
    path('admin-portal/instructors/<str:military_number>/delete/', views.instructor_delete_view, name='instructor_delete'),

    # إدارة تصنيفات الدورات
    path('admin-portal/categories/create/', views.category_create_view, name='category_create'),
    path('admin-portal/categories/<int:category_id>/edit/', views.category_edit_view, name='category_edit'),
    path('admin-portal/categories/<int:category_id>/delete/', views.category_delete_view, name='category_delete'),

    # مخالفات الضبط والربط
    path('results/api/discipline/<int:enrollment_id>/', views.api_get_discipline_infractions_view, name='api_get_discipline_infractions'),
    path('results/api/discipline/add/', views.api_add_discipline_infraction_view, name='api_add_discipline_infraction'),
    path('results/api/discipline/delete/<int:infraction_id>/', views.api_delete_discipline_infraction_view, name='api_delete_discipline_infraction'),
]
