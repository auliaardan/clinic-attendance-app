from django.contrib import admin

from .forms import EmployeeAdminForm
from .models import (
    Division, EmployeeProfile, DivisionRosterEditor,
    ShiftTemplate, ShiftAssignment, LeaveRequest
)
from .models import Employee, AttendanceSession, AttendanceEvent


@admin.register(Division)
class DivisionAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ("employee", "division", "is_rostered")
    list_filter = ("division", "is_rostered")
    search_fields = ("employee__name",)


@admin.register(DivisionRosterEditor)
class DivisionRosterEditorAdmin(admin.ModelAdmin):
    list_display = ("user", "division")
    list_filter = ("division",)
    search_fields = ("user__username", "division__name")


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ("division", "name", "start_time", "end_time", "is_active")
    list_filter = ("division", "is_active")
    search_fields = ("division__name", "name")


@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ("date", "division", "employee", "start_time", "end_time", "status", "entered_by", "approved_by")
    list_filter = ("division", "status", "date")
    search_fields = ("employee__name", "division__name")


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ("employee", "date_from", "date_to", "leave_type", "status", "approved_by")
    list_filter = ("status", "leave_type")
    search_fields = ("employee__name",)


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
