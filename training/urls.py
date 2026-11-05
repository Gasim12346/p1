from django.urls import path
from . import views

app_name = 'training'

urlpatterns = [
    # الواجهة 1: الواجهة الرئيسية
    path('', views.home_view, name='home'),

    # الواجهة 2: واجهة الدارسين
    path('trainees/', views.trainees_list_view, name='trainees_list'),
    path('trainees/<str:military_number>/edit/', views.trainee_edit_view, name='trainee_edit'),
    path('trainees/<str:military_number>/delete/', views.trainee_delete_view, name='trainee_delete'),
    path('trainees/<str:military_number>/transcript/', views.trainee_transcript_view, name='trainee_transcript'),

    # الواجهة 3: واجهة الدورات ومفرداتها
    path('courses/', views.courses_catalog_view, name='courses_catalog'),
    path('courses/<int:course_id>/edit/', views.course_edit_view, name='course_edit'),
    path('courses/<int:course_id>/delete/', views.course_delete_view, name='course_delete'),
    path('subjects/<int:subject_id>/edit/', views.subject_edit_view, name='subject_edit'),
    path('subjects/<int:subject_id>/delete/', views.subject_delete_view, name='subject_delete'),

    # الواجهة 4: واجهة الدورة التي يتم دراستها (انعقاد الدورات وربط الدارسين)
    path('sessions/', views.course_sessions_view, name='course_sessions'),
    path('sessions/create/', views.course_session_create_view, name='course_session_create'),
    path('sessions/<int:session_id>/manage/', views.course_session_manage_view, name='course_session_manage'),
    path('sessions/<int:session_id>/edit/', views.course_session_edit_view, name='course_session_edit'),
    path('sessions/<int:session_id>/delete/', views.course_session_delete_view, name='course_session_delete'),

    # الواجهة 5: واجهة النتيجة ورصد الدرجات والشهادات والسجل التاريخي
    path('results/', views.results_center_view, name='results_center'),
    path('results/session/<int:session_id>/', views.results_entry_view, name='results_entry'),
    path('results/session/<int:session_id>/sheet/', views.session_results_sheet_view, name='session_results_sheet'),
    path('results/certificate/<int:enrollment_id>/', views.certificate_view, name='certificate'),

    # الواجهة 6: المصادقة وتسجيل الدخول والخروج
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # الواجهة 7: بوابة القيادة والأدمن المنفصلة (Dedicated Admin Portal)
    path('admin-portal/login/', views.admin_login_view, name='admin_login'),
    path('admin-portal/logout/', views.admin_logout_view, name='admin_logout'),
    path('admin-portal/dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('admin-dashboard/', views.admin_dashboard_view),  # توافقية المسار السابق

    # إدارة المستخدمين والصلاحيات
    path('admin-portal/users/create/', views.user_create_view, name='user_create'),
    path('admin-portal/users/<int:user_id>/edit/', views.user_edit_view, name='user_edit'),
    path('admin-portal/users/<int:user_id>/delete/', views.user_delete_view, name='user_delete'),
    path('admin-portal/users/<int:user_id>/toggle-active/', views.user_toggle_active_view, name='user_toggle_active'),

    # هوية وشعار وألوان النظام
    path('admin-portal/settings/system/', views.system_settings_update_view, name='system_settings_update'),

    # إعدادات وتوقيعات ولوغهات الشهادة
    path('admin-portal/settings/certificate/', views.certificate_settings_update_view, name='certificate_settings_update'),
    path('admin-dashboard/certificate-settings/', views.certificate_settings_update_view),

    # إدارة تصنيفات الدورات
    path('admin-portal/categories/create/', views.category_create_view, name='category_create'),
    path('admin-portal/categories/<int:category_id>/edit/', views.category_edit_view, name='category_edit'),
    path('admin-portal/categories/<int:category_id>/delete/', views.category_delete_view, name='category_delete'),

    # التقرير الإحصائي القابل للطباعة
    path('admin-portal/report/print/', views.admin_report_print_view, name='admin_report_print'),
    path('admin-dashboard/report/print/', views.admin_report_print_view),
]
