from datetime import timedelta
from django import forms
from django.conf import settings
from django.utils import timezone
from .models import Employee, validate_6_digit_pin, LeaveRequest, AttendanceCorrectionRequest, AttendanceSession

class EmployeeAdminForm(forms.ModelForm):
    pin = forms.CharField(required=False, help_text="Enter a 6-digit PIN. Leave blank to keep existing PIN.", widget=forms.PasswordInput(render_value=False))
    class Meta:
        model = Employee
        fields = ["name", "is_active", "pin"]
    def clean_pin(self):
        pin = self.cleaned_data.get("", "") or self.cleaned_data.get("pin", "")
        if pin: validate_6_digit_pin(pin)
        return pin
    def save(self, commit=True):
        obj = super().save(commit=False); pin = self.cleaned_data.get("pin")
        if pin: obj.set_pin(pin)
        if commit: obj.save()
        return obj

class EmployeeLoginForm(forms.Form):
    employee = forms.ModelChoiceField(queryset=Employee.objects.filter(is_active=True).order_by("name"), label="Nama Staff")
    pin = forms.CharField(label="PIN", widget=forms.PasswordInput(attrs={"inputmode":"numeric", "autocomplete":"current-password"}))

class EmployeeLeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ["date_from", "date_to", "leave_type", "note"]
        widgets = {"date_from": forms.DateInput(attrs={"type":"date"}), "date_to": forms.DateInput(attrs={"type":"date"}), "note": forms.Textarea(attrs={"rows":3, "maxlength":255})}
    def __init__(self, *args, employee=None, **kwargs):
        self.employee = employee; super().__init__(*args, **kwargs)
    def clean(self):
        cleaned = super().clean(); df=cleaned.get("date_from"); dt=cleaned.get("date_to")
        max_days = getattr(settings, "EMPLOYEE_LEAVE_MAX_DAYS", 31)
        if df and dt:
            if dt < df: raise forms.ValidationError("Tanggal selesai tidak boleh sebelum tanggal mulai.")
            if (dt - df).days + 1 > max_days: raise forms.ValidationError(f"Maksimal {max_days} hari per pengajuan.")
            if self.employee and LeaveRequest.objects.filter(employee=self.employee,date_from=df,date_to=dt,leave_type=cleaned.get("leave_type"),status__in=["SUBMITTED","APPROVED"]).exists():
                raise forms.ValidationError("Pengajuan cuti yang sama sudah ada.")
        return cleaned
    def save(self, commit=True):
        obj=super().save(commit=False); obj.employee=self.employee; obj.status="SUBMITTED"; obj.approved_by=None
        if commit: obj.save()
        return obj

class AttendanceCorrectionRequestForm(forms.ModelForm):
    requested_clock_in = forms.DateTimeField(required=False, input_formats=["%Y-%m-%dT%H:%M"])
    requested_clock_out = forms.DateTimeField(required=False, input_formats=["%Y-%m-%dT%H:%M"])
    session = forms.ModelChoiceField(queryset=AttendanceSession.objects.none(), required=False, label="Sesi terkait")
    class Meta:
        model = AttendanceCorrectionRequest
        fields = ["session", "request_type", "requested_clock_in", "requested_clock_out", "reason"]
        widgets = {"requested_clock_in": forms.DateTimeInput(attrs={"type":"datetime-local"}), "requested_clock_out": forms.DateTimeInput(attrs={"type":"datetime-local"}), "reason": forms.Textarea(attrs={"rows":4, "maxlength":1000})}
    def __init__(self,*args,employee=None,**kwargs):
        self.employee=employee; super().__init__(*args,**kwargs)
        if employee: self.fields["session"].queryset=AttendanceSession.objects.filter(employee=employee).order_by("-clock_in_time")
    def clean_reason(self):
        reason=self.cleaned_data["reason"].strip()
        if len(reason)>1000: raise forms.ValidationError("Alasan maksimal 1000 karakter.")
        return reason
    def clean(self):
        c=super().clean(); sess=c.get("session"); typ=c.get("request_type")
        if self.employee and typ and AttendanceCorrectionRequest.objects.filter(employee=self.employee,session=sess,request_type=typ,status="SUBMITTED").exists():
            raise forms.ValidationError("Pengajuan koreksi yang sama masih menunggu review.")
        return c
    def save(self,commit=True):
        obj=super().save(commit=False); obj.employee=self.employee; obj.status="SUBMITTED"
        if commit: obj.save()
        return obj

from .models import FixedScheduleRule, ScheduleException, Division
class FixedScheduleRuleForm(forms.ModelForm):
    class Meta:
        model = FixedScheduleRule
        fields = ["is_workday", "start_time", "end_time"]
        widgets = {"start_time": forms.TimeInput(attrs={"type":"time"}), "end_time": forms.TimeInput(attrs={"type":"time"})}

class ScheduleExceptionForm(forms.ModelForm):
    class Meta:
        model = ScheduleException
        fields = ["division", "date", "is_workday", "start_time", "end_time", "note"]
        widgets = {"date": forms.DateInput(attrs={"type":"date"}), "start_time": forms.TimeInput(attrs={"type":"time"}), "end_time": forms.TimeInput(attrs={"type":"time"})}
