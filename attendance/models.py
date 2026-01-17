from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from django.utils import timezone
import re
from django.core.exceptions import ValidationError

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
    witness_employee = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name="events_as_witness")

    created_at = models.DateTimeField(default=timezone.now)
    photo = models.ImageField(upload_to="attendance_photos/%Y/%m/%d/")

    client_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True, default="")
    is_proxy = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True, default="")

    def __str__(self):
        return f"{self.event_type} {self.subject_employee.name} @ {self.created_at}"
