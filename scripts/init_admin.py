"""
التحقق من وجود حساب مدير للمنظومة وإنشاء حساب افتراضي عند التثبيت الجديد
"""
import os
import sys
from pathlib import Path

# Add project root to path
root_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root_dir))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from apps.core.models import UserProfile, UserRole

if not User.objects.filter(is_superuser=True).exists():
    admin = User.objects.create_superuser('admin', 'admin@academy.local', 'Admin@123456')
    profile, _ = UserProfile.objects.get_or_create(user=admin, defaults={'role': UserRole.SUPER_ADMIN})
    profile.role = UserRole.SUPER_ADMIN
    profile.sync_permissions_from_role()
    profile.save()
    print("[OK] تم إنشاء حساب المدير الافتراضي: admin / كلمة المرور: Admin@123456")
else:
    print("[OK] حساب المدير موجود وجاهز في قاعدة البيانات.")
