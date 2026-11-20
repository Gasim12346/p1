from django.utils.deprecation import MiddlewareMixin
from apps.core.models import Institute, UserRole


class InstituteMiddleware(MiddlewareMixin):
    """
    طبقة وسيطة لتحديد المعهد النشط في كل طلب، ودعم تصفح وتبديل المعاهد للسوبر أدمن.
    """
    def process_request(self, request):
        request.institute = None
        request.is_super_admin = False
        request.super_admin_switched = False

        if request.user.is_authenticated:
            profile = getattr(request.user, 'profile', None)
            is_super = bool(request.user.is_superuser or (profile and profile.role == UserRole.SUPER_ADMIN))
            request.is_super_admin = is_super

            if is_super:
                active_id = request.session.get('active_institute_id')
                if active_id:
                    inst = Institute.objects.filter(id=active_id, is_active=True).first()
                    if inst:
                        request.institute = inst
                        request.super_admin_switched = True
                    else:
                        request.session.pop('active_institute_id', None)
                        request.institute = None
                else:
                    request.institute = None
            else:
                if profile and profile.institute and profile.institute.is_active:
                    request.institute = profile.institute
                else:
                    request.institute = Institute.objects.filter(is_active=True).first()
