from django.urls import path
from . import views

urlpatterns = [
    # بوابة امتحانات خاصة: امتحانات تحديد المستوى
    path('special-exams/placement/', views.placement_exams_list_view, name='placement_exams_list'),
    path('special-exams/placement/save/', views.placement_exam_save_api, name='placement_exam_save_api'),
    path('special-exams/placement/<int:exam_id>/delete/', views.placement_exam_delete_api, name='placement_exam_delete_api'),
    path('special-exams/placement/<int:exam_id>/confirm/', views.placement_exam_confirm_api, name='placement_exam_confirm_api'),
    path('special-exams/placement/trainee-quick-add/', views.placement_trainee_quick_add_api, name='placement_trainee_quick_add_api'),
    path('special-exams/placement/lookup-previous/', views.placement_lookup_previous_api, name='placement_lookup_previous_api'),
    path('results/placement/<str:exam_id>/', views.placement_results_entry_view, name='placement_results_entry'),
    path('results/placement/<str:exam_id>/sheet/', views.placement_results_sheet_view, name='placement_results_sheet'),
]
