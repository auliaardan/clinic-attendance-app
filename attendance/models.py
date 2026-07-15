import re

from django.conf import settings
from django.contrib.auth.hashers import make_password, check_password
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone



def validate_6_digit_pin(pin: str):
    if not re.fullmatch(r"\d{6}", pin or ""):
        raise ValidationError("PIN must be exactly 6 digits.")


class Employee(models.Model):
    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    pin_hash = models.CharField(max_length=255)

    def set_pin(self, raw_pin: str):
        validate_6_digit_pin(raw_pin)
        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin: str) -> bool:
        return check_password(raw_pin, self.pin_hash)

    def __str__(self):
        return self.name


class AttendanceSession(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="sessions")
    clock_in_time = models.DateTimeField(null=True, blank=True)
    clock_out_time = models.DateTimeField(null=True, blank=True)
    is_open = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee"], condition=Q(is_open=True), name="uniq_open_session_per_employee"),
        ]

    def __str__(self):
        return f"{self.employee.name} ({'OPEN' if self.is_open else 'CLOSED'})"


class AttendanceEvent(models.Model):
    EVENT_TYPES = (
        ("IN", "Clock In"),
        ("OUT", "Clock Out"),
    )

    event_type = models.CharField(max_length=3, choices=EVENT_TYPES)
    session = models.ForeignKey(AttendanceSession, on_delete=models.CASCADE, related_name="events")

    # Subject = person being clocked
    subject_employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="events_as_subject")

    # Witness (required if proxy)
    witness_employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name="events_as_witness")

    created_at = models.DateTimeField(default=timezone.now)
    photo = models.ImageField(upload_to="attendance_photos/%Y/%m/%d/")

    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    is_proxy = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.event_type} {self.subject_employee.name} @ {self.created_at}"


class Division(models.Model):
    name = models.CharField(max_length=120, unique=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class EmployeeProfile(models.Model):
    employee = models.OneToOneField("Employee", on_delete=models.CASCADE, related_name="profile")
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True)
    is_rostered = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.employee.name} ({self.division or '-'})"


class DivisionRosterEditor(models.Model):
    """
    Django auth user who can edit roster for a division (NOT manager dashboard).
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    division = models.ForeignKey(Division, on_delete=models.CASCADE)

    class Meta:
        unique_together = ("user", "division")


class ShiftTemplate(models.Model):
    """
    Standard shift options per division (Morning/Afternoon/Middle/Long).
    """
    division = models.ForeignKey(Division, on_delete=models.CASCADE, related_name="shift_templates")
    name = models.CharField(max_length=60)  # e.g. "Morning"
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("division", "name")

    def __str__(self):
        return f"{self.division.name}: {self.name} ({self.start_time}-{self.end_time})"


class ShiftAssignment(models.Model):
    STATUS = (
        ("DRAFT", "Draft"),
        ("SUBMITTED", "Submitted"),
        ("APPROVED", "Approved"),
    )

    employee = models.ForeignKey("Employee", on_delete=models.CASCADE, related_name="shift_assignments")
    division = models.ForeignKey(Division, on_delete=models.CASCADE, related_name="shift_assignments")
    date = models.DateField()

    template = models.ForeignKey(ShiftTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    # snapshot times so history stays stable even if template changes later
    start_time = models.TimeField()
    end_time = models.TimeField()

    status = models.CharField(max_length=12, choices=STATUS, default="DRAFT")
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="shifts_entered")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="shifts_approved")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # allow multiple shifts per day per staff
        unique_together = ("employee", "date", "start_time", "end_time")
        indexes = [
            models.Index(fields=["date", "division", "status"]),
            models.Index(fields=["employee", "date"]),
        ]

    def __str__(self):
        return f"{self.employee.name} {self.date} {self.start_time}-{self.end_time} ({self.status})"


class LeaveRequest(models.Model):
    LEAVE_TYPES = (
        ("ANNUAL", "Annual"),
        ("SICK", "Sick"),
        ("UNPAID", "Unpaid"),
        ("TRAINING", "Training"),
        ("OTHER", "Other"),
    )
    STATUS = (
        ("SUBMITTED", "Submitted"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    )

    employee = models.ForeignKey("Employee", on_delete=models.CASCADE, related_name="leave_requests")
    date_from = models.DateField()
    date_to = models.DateField()
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPES, default="ANNUAL")
    status = models.CharField(max_length=20, choices=STATUS, default="SUBMITTED")
    note = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.employee.name} {self.date_from}→{self.date_to} ({self.status})"


class PinAttempt(models.Model):
    PURPOSES = (("SUBJECT", "Subject"), ("WITNESS", "Witness"))
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="pin_attempts")
    client_ip = models.GenericIPAddressField()
    purpose = models.CharField(max_length=16, choices=PURPOSES)
    failures = models.PositiveIntegerField(default=0)
    first_failed_at = models.DateTimeField(default=timezone.now)
    last_failed_at = models.DateTimeField(default=timezone.now)
    locked_until = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("employee", "client_ip", "purpose")
        indexes = [models.Index(fields=["employee", "client_ip", "purpose"]), models.Index(fields=["last_failed_at"])]

class AttendanceCorrectionRequest(models.Model):
    REQUEST_TYPES = (("FORGOT_CLOCK_IN","Forgot clock in"),("FORGOT_CLOCK_OUT","Forgot clock out"),("WRONG_TIME","Wrong time"),("WRONG_ACTION","Wrong action"),("OTHER","Other"))
    STATUS = (("SUBMITTED","Submitted"),("APPROVED","Approved"),("REJECTED","Rejected"),("CANCELLED","Cancelled"))
    employee = models.ForeignKey("Employee", on_delete=models.CASCADE, related_name="correction_requests")
    session = models.ForeignKey("AttendanceSession", on_delete=models.SET_NULL, null=True, blank=True, related_name="correction_requests")
    request_type = models.CharField(max_length=32, choices=REQUEST_TYPES)
    requested_clock_in = models.DateTimeField(null=True, blank=True)
    requested_clock_out = models.DateTimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS, default="SUBMITTED")
    created_at = models.DateTimeField(default=timezone.now)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    manager_note = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["employee", "session", "request_type"], condition=Q(status="SUBMITTED"), name="uniq_submitted_correction_per_session_type"),
        ]
        indexes = [models.Index(fields=["employee", "status", "created_at"]), models.Index(fields=["status", "created_at"])]

    def __str__(self):
        return f"{self.employee.name} {self.request_type} ({self.status})"
