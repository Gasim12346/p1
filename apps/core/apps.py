from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.core'
    verbose_name = 'النواة والهوية'

    def ready(self):
        import apps.core.signals  # noqa
        self._patch_template_engine_for_multiline_tags()

    def _patch_template_engine_for_multiline_tags(self):
        """
        معالجة واستيعاب الوسوم والمتغيرات متعددة الأسطر تلقائياً
        لمنع ظهور متغيرات القوالب كنص خام أو حدوث أخطاء نتيجة التفاف الأسطر.
        """
        import re
        from django.template.base import Template

        if getattr(Template, '_safe_multiline_patched', False):
            return

        original_init = Template.__init__

        def safe_template_init(self_tpl, template_string, origin=None, name=None, engine=None):
            if isinstance(template_string, str):
                def clean_tag(m):
                    content = m.group(0)
                    if content.startswith('{#'):
                        return content
                    # توحيد المسافات والأسطر داخل الوسم إلى سطر واحد
                    content = re.sub(r'\s+', ' ', content)
                    # إزالة المسافة غير القياسية بعد نقطتي الفلتر مثل |default: 0 -> |default:0
                    content = re.sub(r'\|\s*([a-zA-Z0-9_]+)\s*:\s+', r'|\1:', content)
                    # ضبط المسافات حول معاملات المقارنة في وسوم if
                    if content.startswith('{%'):
                        content = re.sub(r'(\S)==', r'\1 == ', content)
                        content = re.sub(r'==(\S)', r' == \1', content)
                        content = re.sub(r'(\S)!=', r'\1 != ', content)
                        content = re.sub(r'!=(\S)', r' != \1', content)
                        content = re.sub(r' {2,}', ' ', content)
                    return content

                template_string = re.sub(r'(\{\{.*?\}\}|\{%.*?%\})', clean_tag, template_string, flags=re.DOTALL)

            original_init(self_tpl, template_string, origin=origin, name=name, engine=engine)

        Template.__init__ = safe_template_init
        Template._safe_multiline_patched = True

