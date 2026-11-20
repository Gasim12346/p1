"""
Re-export all views, decorators, and permission helpers from modular apps for backward compatibility.
"""
from apps.core.permissions import *
from apps.core.views import *
from apps.trainees.views import *
from apps.academic.views import *
from apps.documents.views import *
from apps.reports.views import *
