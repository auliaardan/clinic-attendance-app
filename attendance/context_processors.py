from .views import _employee_session_employee, is_manager, editable_divisions_for


def navigation(request):
    employee = _employee_session_employee(request)
    can_access_roster = False
    if getattr(request, "user", None) and request.user.is_authenticated:
        try:
            can_access_roster = editable_divisions_for(request.user).exists()
        except Exception:
            can_access_roster = False
    return {
        "nav_employee": employee,
        "nav_employee_url_name": "employee_dashboard" if employee else "employee_login",
        "nav_employee_label": employee.name if employee else "Login Staff",
        "nav_can_access_roster": can_access_roster,
        "nav_is_manager": is_manager(request.user) if getattr(request, "user", None) else False,
    }
