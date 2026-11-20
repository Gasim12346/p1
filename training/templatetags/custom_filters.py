from decimal import Decimal
from django import template

register = template.Library()


@register.filter(name='natural_number')
def natural_number(value, max_decimals=2):
    """
    تنسيق الأرقام لتظهر بشكل طبيعي دون أصفار عشرية زائدة:
    100.00 -> 100
    400.00 -> 400
    10.00 -> 10
    84.50 -> 84.5
    0.00 -> 0
    """
    if value is None or value == '':
        return ''
    try:
        if isinstance(value, str):
            value = value.strip().replace(',', '.')
        d = Decimal(str(value))
        if d == d.to_integral():
            return str(int(d))
        formatted = f"{d:.{max_decimals}f}".rstrip('0').rstrip('.')
        return formatted
    except Exception:
        return str(value)


@register.filter(name='natural_grade')
def natural_grade(value):
    """
    اسم بديل لفلتر natural_number لتنسيق الدرجات
    """
    return natural_number(value, max_decimals=2)


@register.filter(name='natural_percent')
def natural_percent(value, max_decimals=1):
    """
    تنسيق النسب المئوية بشكل طبيعي دون أصفار زائدة:
    100.0% -> 100%
    0.0% -> 0%
    84.9% -> 84.9%
    """
    val_str = natural_number(value, max_decimals=max_decimals)
    if val_str != '':
        return f"{val_str}%"
    return ''


@register.filter(name='clean_num')
def clean_num(value):
    """
    اسم بديل لفلتر natural_number
    """
    return natural_number(value, max_decimals=2)
