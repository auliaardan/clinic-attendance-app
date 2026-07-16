from django.urls import path

from . import qr_views, views

urlpatterns = [
    path("", views.home, name="home"),
    path("attendance/", views.attendance_page, name="attendance_page"),
    path("display/", views.qr_display, name="qr_display"),
    path("api/qr/", views.api_qr, name="api_qr"),
    path("api/qr/image/", qr_views.qr_image, name="qr_image"),
    path("api/qr/check/", views.api_qr_check, name="api_qr_check"),
    path("api/clock/", views.api_clock, name="api_clock"),
    path("manager/", views.manager_dashboard, name="manager_dashboard"),
    path("manager/export.csv", views.manager_attendance_csv, name="manager_attendance_csv"),
    path("manager/photos/<int:event_id>/", views.attendance_photo, name="attendance_photo"),
    path("manager/requests/", views.manager_requests, name="manager_requests"),
    path("manager/schedules/", views.manager_schedules, name="manager_schedules"),
    path("manager/alerts/", views.manager_alerts, name="manager_alerts"),
    path("manager/leave/<int:pk>/<str:action>/", views.manager_leave_action, name="manager_leave_action"),
    path("manager/corrections/<int:pk>/<str:action>/", views.manager_correction_action, name="manager_correction_action"),
    path("api/employee/status/", views.api_employee_status, name="api_employee_status"),
    path("roster/", views.roster_week, name="roster_week"),
    path("roster/approve/", views.approve_roster_week, name="approve_roster_week"),
    path("employee/login/", views.employee_login, name="employee_login"),
    path("employee/", views.employee_dashboard, name="employee_dashboard"),
    path("employee/logout/", views.employee_logout, name="employee_logout"),
    path("employee/leave/new/", views.employee_leave_new, name="employee_leave_new"),
    path("employee/corrections/new/", views.employee_correction_new, name="employee_correction_new"),
    path("employee/corrections/<int:pk>/cancel/", views.employee_correction_cancel, name="employee_correction_cancel"),
]
