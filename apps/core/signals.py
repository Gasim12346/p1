import os
import logging
from django.db.models.signals import post_delete, pre_save
from django.dispatch import receiver

from apps.academic.models import CourseSession, CourseEnrollment
from apps.core.models import SystemSettings, Institute
from apps.documents.models import CertificateSettings, MovementOrderSettings

logger = logging.getLogger('training')


def delete_file_safely(file_field):
    """حذف الملف الفعلي من وسائط التخزين عند حذف أو تعديل السجل لمنع تراكم الملفات المهملة"""
    if file_field and hasattr(file_field, 'path') and os.path.isfile(file_field.path):
        try:
            os.remove(file_field.path)
            logger.info(f"تم حذف الملف القديم من التخزين بنجاح: {file_field.path}")
        except OSError as e:
            logger.warning(f"تعذر حذف الملف من التخزين: {file_field.path} - الخطأ: {e}")


@receiver(post_delete, sender=CourseSession)
def cleanup_session_file_on_delete(sender, instance, **kwargs):
    delete_file_safely(instance.movement_order_file)


@receiver(post_delete, sender=CourseEnrollment)
def cleanup_enrollment_file_on_delete(sender, instance, **kwargs):
    delete_file_safely(instance.movement_order_file)


@receiver(post_delete, sender=SystemSettings)
def cleanup_system_settings_file_on_delete(sender, instance, **kwargs):
    delete_file_safely(instance.main_logo)


@receiver(post_delete, sender=CertificateSettings)
def cleanup_cert_settings_file_on_delete(sender, instance, **kwargs):
    delete_file_safely(instance.right_logo)
    delete_file_safely(instance.left_logo)
    delete_file_safely(instance.signature_image_1)
    delete_file_safely(instance.signature_image_2)
    delete_file_safely(instance.signature_image_3)
    delete_file_safely(instance.stamp_image)


@receiver(post_delete, sender=MovementOrderSettings)
def cleanup_movement_settings_file_on_delete(sender, instance, **kwargs):
    delete_file_safely(instance.header_logo)
    delete_file_safely(instance.signature_image)
    delete_file_safely(instance.stamp_image)


@receiver(post_delete, sender=Institute)
def cleanup_institute_file_on_delete(sender, instance, **kwargs):
    delete_file_safely(instance.logo)
