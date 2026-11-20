from django.urls import path
from . import views

urlpatterns = [
    # الصفحة الرئيسية والمصادقة
    path('', views.home_view, name='home'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),

    # إدارة السوبر أدمن المركزية
    path('super-admin/login/', views.super_admin_login_view, name='super_admin_login'),
    path('super-admin/logout/', views.super_admin_logout_view, name='super_admin_logout'),
    path('super-admin/', views.super_admin_dashboard_view, name='super_admin_dashboard'),
    path('super-admin/institutes/create/', views.super_admin_institute_create_view, name='super_admin_institute_create'),
    path('super-admin/institutes/<int:institute_id>/edit/', views.super_admin_institute_edit_view, name='super_admin_institute_edit'),
    path('super-admin/institutes/<int:institute_id>/toggle-status/', views.super_admin_institute_toggle_status_view, name='super_admin_institute_toggle_status'),
    path('super-admin/users/create/', views.super_admin_user_create_view, name='super_admin_user_create'),
    path('super-admin/users/<int:user_id>/edit/', views.super_admin_user_edit_view, name='super_admin_user_edit'),
    path('super-admin/switch/<int:institute_id>/', views.super_admin_switch_institute_view, name='super_admin_switch_institute'),
    path('super-admin/exit-switch/', views.super_admin_exit_switch_view, name='super_admin_exit_switch'),

    # بوابة القيادة والأدمن
    path('admin-portal/login/', views.admin_login_view, name='admin_login'),
    path('admin-portal/logout/', views.admin_logout_view, name='admin_logout'),
    path('admin-portal/dashboard/', views.admin_dashboard_view, name='admin_dashboard'),
    path('admin-dashboard/', views.admin_dashboard_view),

    # إدارة المستخدمين والصلاحيات
    path('admin-portal/users/create/', views.user_create_view, name='user_create'),
    path('admin-portal/users/<int:user_id>/edit/', views.user_edit_view, name='user_edit'),
    path('admin-portal/users/<int:user_id>/update-role/', views.user_update_role_view, name='user_update_role'),
    path('admin-portal/users/<int:user_id>/delete/', views.user_delete_view, name='user_delete'),
    path('admin-portal/users/<int:user_id>/toggle-active/', views.user_toggle_active_view, name='user_toggle_active'),

    # هوية وشعار وألوان النظام
    path('admin-portal/settings/system/', views.system_settings_update_view, name='system_settings_update'),

    # سجل النشاط والعمليات
    path('admin-portal/activity-log/clear/', views.admin_clear_activity_logs_view, name='admin_clear_activity_logs'),
]
