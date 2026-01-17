from django.contrib import admin

from .forms import EmployeeAdminForm
from .models import Employee, AttendanceSession, AttendanceEvent

@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    form = EmployeeAdminForm
    list_display = ("id", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)

@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = ("id", "employee", "clock_in_time", "clock_out_time", "is_open")
    list_filter = ("is_open",)
    search_fields = ("employee__name",)

@admin.register(AttendanceEvent)
class AttendanceEventAdmin(admin.ModelAdmin):
    list_display = ("id", "event_type", "subject_employee", "witness_employee", "created_at", "is_proxy", "client_ip")
    list_filter = ("event_type", "is_proxy", "created_at")
    search_fields = ("subject_employee__name", "witness_employee__name")
