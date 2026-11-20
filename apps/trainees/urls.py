from django.urls import path
from . import views

urlpatterns = [
    path('trainees/', views.trainees_list_view, name='trainees_list'),
    path('trainees/<str:military_number>/edit/', views.trainee_edit_view, name='trainee_edit'),
    path('trainees/<str:military_number>/delete/', views.trainee_delete_view, name='trainee_delete'),
    path('trainees/<str:military_number>/transcript/', views.trainee_transcript_view, name='trainee_transcript'),
]
