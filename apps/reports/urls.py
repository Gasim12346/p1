from django.urls import path
from . import views

urlpatterns = [
    path('reports/', views.reports_hub_view, name='reports_hub'),
    path('reports/export/excel/', views.reports_export_excel_view, name='reports_export_excel'),
    path('admin-portal/report/print/', views.admin_report_print_view, name='admin_report_print'),
    path('admin-dashboard/report/print/', views.admin_report_print_view),
]
