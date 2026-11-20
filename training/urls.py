"""
تجميع وتوجيه مسارات النظام (URLs) من التطبيقات المصغرة المنظمة
مع الحفاظ الكامل على اسم النطاق (namespace: 'training') وجميع أسماء المسارات
لضمان التوافقية بنسبة 100% وعدم كسر أي رابط أو تحويل في المنظومة.
"""
from apps.core.urls import urlpatterns as core_urls
from apps.trainees.urls import urlpatterns as trainees_urls
from apps.academic.urls import urlpatterns as academic_urls
from apps.documents.urls import urlpatterns as documents_urls
from apps.reports.urls import urlpatterns as reports_urls

app_name = 'training'

urlpatterns = [
    *core_urls,
    *trainees_urls,
    *academic_urls,
    *documents_urls,
    *reports_urls,
]
