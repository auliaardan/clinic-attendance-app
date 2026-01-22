from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("display/", views.qr_display, name="qr_display"),
    path("api/qr/", views.api_qr, name="api_qr"),
    path("api/qr/check/", views.api_qr_check, name="api_qr_check"),
    path("api/clock/", views.api_clock, name="api_clock"),
    path("manager/", views.manager_dashboard, name="manager_dashboard"),
    path("roster/", views.roster_week, name="roster_week"),
    path("roster/approve/", views.approve_roster_week, name="approve_roster_week"),

]
