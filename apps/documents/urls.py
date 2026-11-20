from django.urls import path
from . import views

urlpatterns = [
    path('results/certificate/<int:enrollment_id>/', views.certificate_view, name='certificate'),
    path('results/certificate/<int:enrollment_id>/detailed/', views.certificate_detailed_view, name='certificate_detailed'),
    path('results/movement-order/<int:enrollment_id>/', views.movement_order_view, name='movement_order'),
    path('admin-portal/settings/certificate/', views.certificate_settings_update_view, name='certificate_settings_update'),
    path('admin-dashboard/certificate-settings/', views.certificate_settings_update_view),
    path('admin-portal/settings/movement-order/', views.movement_order_settings_update_view, name='movement_order_settings_update'),
]
