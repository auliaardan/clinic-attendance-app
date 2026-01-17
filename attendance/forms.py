from django import forms
from .models import Employee, validate_6_digit_pin

class EmployeeAdminForm(forms.ModelForm):
    pin = forms.CharField(
        required=False,
        help_text="Enter a 6-digit PIN. Leave blank to keep existing PIN.",
        widget=forms.PasswordInput(render_value=False),
    )

    class Meta:
        model = Employee
        fields = ["name", "is_active", "pin"]

    def clean_pin(self):
        pin = self.cleaned_data.get("pin", "")
        if pin:
            validate_6_digit_pin(pin)
        return pin

    def save(self, commit=True):
        obj = super().save(commit=False)
        pin = self.cleaned_data.get("pin")
        if pin:
            obj.set_pin(pin)
        if commit:
            obj.save()
        return obj
