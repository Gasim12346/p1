from django.urls import path
from . import views

urlpatterns = [
    # بوابة امتحانات خاصة: امتحانات تحديد المستوى
    path('special-exams/placement/', views.placement_exams_list_view, name='placement_exams_list'),
    path('results/placement/<str:exam_id>/', views.placement_results_entry_view, name='placement_results_entry'),
    path('results/placement/<str:exam_id>/sheet/', views.placement_results_sheet_view, name='placement_results_sheet'),
]
