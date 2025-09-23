
from django import forms
from .models import Person, Indemnitor, Reference, Bond, CourtDate, CheckIn, Invoice, Receipt, PaymentPlan

class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        exclude = ('tenant',)

class IndemnitorForm(forms.ModelForm):
    class Meta:
        model = Indemnitor
        exclude = ('tenant', 'person')

class ReferenceForm(forms.ModelForm):
    class Meta:
        model = Reference
        exclude = ('tenant', 'person')


class BondForm(forms.ModelForm):
    class Meta:
        model = Bond
        exclude = ('tenant', 'person')
        fields = ["date", "agency", "offense_type", "amount",
                  "jurisdiction", "county", "charge", "notes"]
        widgets = {
            # keep whatever you already had; just add the lists:
            "offense_type": forms.TextInput(attrs={"list": "dl-offense"}),
            "county": forms.TextInput(attrs={"list": "dl-county"}),
            "jurisdiction": forms.TextInput(attrs={"list": "dl-juris"}),
            "charge": forms.TextInput(attrs={"list": "dl-charge"}),
            # examples if you want pickers:
            "date": forms.DateInput(attrs={"type": "date"}),
            "amount": forms.NumberInput(attrs={"step": "0.01"}),
        }

class CourtDateForm(forms.ModelForm):
    class Meta:
        model = CourtDate
        # adjust fields to match your model
        fields = ["date", "time", "location", "county", "court", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "location": forms.TextInput(attrs={"placeholder": "Court / Address"}),
            "county": forms.TextInput(),
            "court": forms.TextInput(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Make sure POST parsing matches the widget formats
        self.fields["date"].input_formats = ["%Y-%m-%d"]
        self.fields["time"].input_formats = ["%H:%M"]

class CheckInForm(forms.ModelForm):
    class Meta:
        model = CheckIn
        exclude = ('tenant', 'person')

class InvoiceForm(forms.ModelForm):
    class Meta:
        model = Invoice
        exclude = ("tenant", "person")

class ReceiptForm(forms.ModelForm):
    class Meta:
        model = Receipt
        exclude = ("tenant", "invoice")

class PaymentPlanForm(forms.ModelForm):
    class Meta:
        model = PaymentPlan
        fields = ["invoice", "start_date", "frequency", "n_payments", "installment_amount"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
        }