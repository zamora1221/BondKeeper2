
from django.db import models
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

class Tenant(models.Model):
    name = models.CharField(max_length=200)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name='tenant_profile')

    def __str__(self):
        return self.name

class Person(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='people')
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    zip = models.CharField(max_length=20, blank=True)
    dob = models.DateField(null=True, blank=True)
    alias = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    @property
    def full_name(self):
        return (self.first_name + " " + self.last_name).strip()

    def __str__(self):
        return self.full_name or f"Person {self.pk}"

class Indemnitor(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='indemnitors')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='indemnitors')
    name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.name

class Reference(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='references')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='references')
    name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)

    def __str__(self):
        return self.name


class Bond(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='bonds')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='bonds')
    date = models.DateField(null=True, blank=True)
    agency = models.CharField(max_length=200, blank=True)
    offense_type = models.CharField(max_length=200, blank=True)
    bond_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    jurisdiction = models.CharField(max_length=200, blank=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    notes = models.TextField(blank=True, default="")
    county = models.CharField(max_length=200, blank=True)
    charge = models.CharField(max_length=255, blank=True)

    def __str__(self):
        base = self.offense_type or self.charge or 'Bond'
        return f"{base} - {self.person.full_name if hasattr(self.person, 'full_name') else self.person_id}"

class CourtDate(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='court_dates')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='court_dates')
    date = models.DateField(null=True, blank=True)
    time = models.TimeField(null=True, blank=True)
    court = models.CharField(max_length=200, blank=True)
    county = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    case_number = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        base = self.court or 'Court'
        return f"{self.date or ''} {self.time or ''} - {base}"

# add near your other models
class CheckIn(models.Model):
    METHOD_PHONE = 'phone'
    METHOD_ONLINE = 'online'
    METHOD_IN_PERSON = 'in_person'
    METHOD_CHOICES = [
        (METHOD_PHONE, 'Phone'),
        (METHOD_ONLINE, 'Online'),
        (METHOD_IN_PERSON, 'In-person'),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='checkins')
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name='checkins')
    phone = models.CharField(max_length=50, blank=True)
    address = models.CharField(max_length=255, blank=True)
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_IN_PERSON)
    created_at = models.DateTimeField(default=timezone.now, editable=False, db_index=True,)

    class Meta:
        ordering = ['-id']  # newest first

    def __str__(self):
        return f"{self.person_id} - {self.get_method_display()}"

class Invoice(models.Model):
    STATUS_UNPAID = "unpaid"
    STATUS_PARTIAL = "partial"
    STATUS_PAID = "paid"
    STATUS_CHOICES = [
        (STATUS_UNPAID, "Unpaid"),
        (STATUS_PARTIAL, "Partial"),
        (STATUS_PAID, "Paid"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="invoices")
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="invoices")
    date = models.DateField(null=True, blank=True)
    number = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    due_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_UNPAID)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.number or 'Invoice'} - {self.person_id}"


class Receipt(models.Model):
    METHOD_CASH = "cash"
    METHOD_CARD = "card"
    METHOD_ONLINE = "online"
    METHOD_OTHER = "other"
    METHOD_CHOICES = [
        (METHOD_CASH, "Cash"),
        (METHOD_CARD, "Card"),
        (METHOD_ONLINE, "Online"),
        (METHOD_OTHER, "Other"),
    ]

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="receipts")
    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="receipts")
    date = models.DateField(null=True, blank=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=METHOD_OTHER)
    reference = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"Receipt {self.pk} - {self.invoice_id}"

class PaymentPlan(models.Model):
    FREQ_WEEKLY = "weekly"
    FREQ_BIWEEKLY = "biweekly"
    FREQ_MONTHLY = "monthly"
    FREQ_CHOICES = [
        (FREQ_WEEKLY, "Weekly"),
        (FREQ_BIWEEKLY, "Biweekly"),
        (FREQ_MONTHLY, "Monthly"),
    ]

    person = models.ForeignKey("core.Person", on_delete=models.CASCADE, related_name="payment_plans")
    invoice = models.ForeignKey("core.Invoice", on_delete=models.SET_NULL, null=True, blank=True, related_name="payment_plans")
    start_date = models.DateField(default=timezone.localdate)
    frequency = models.CharField(max_length=16, choices=FREQ_CHOICES, default=FREQ_WEEKLY)
    n_payments = models.PositiveIntegerField(default=4)
    installment_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Plan #{self.pk} for {self.person}"

    @property
    def total_amount(self):
        return self.installment_amount * self.n_payments

    def next_due(self):
        return self.installments.filter(status=PlanInstallment.STATUS_DUE).order_by("due_date").first()

    def recalc_status(self):
        if not self.installments.exclude(status=PlanInstallment.STATUS_PAID).exists():
            self.active = False
            self.save(update_fields=["active"])


class PlanInstallment(models.Model):
    STATUS_DUE = "due"
    STATUS_PAID = "paid"
    STATUS_LATE = "late"
    STATUS_CHOICES = [
        (STATUS_DUE, "Due"),
        (STATUS_PAID, "Paid"),
        (STATUS_LATE, "Late"),
    ]

    plan = models.ForeignKey(PaymentPlan, on_delete=models.CASCADE, related_name="installments")
    sequence = models.PositiveIntegerField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=8, choices=STATUS_CHOICES, default=STATUS_DUE)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = [("plan", "sequence")]
        ordering = ["due_date"]

    def __str__(self):
        return f"{self.plan} / #{self.sequence} {self.due_date} {self.amount}"

    def mark_paid(self):
        self.status = self.STATUS_PAID
        self.paid_at = timezone.now()
        self.save(update_fields=["status", "paid_at"])
        self.plan.recalc_status()

class LookupValue(models.Model):
    CATEGORY_CHOICES = [
        ("charge", "Charge"),
        ("county", "County"),
        ("offense_type", "Offense Type"),
        ("jurisdiction", "Jurisdiction"),
    ]
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    value = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("category", "value")
        ordering = ["category", "value"]

    def __str__(self):
        return f"{self.category}: {self.value}"

# models.py
class PushSubscription(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="push_subs")
    user   = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, null=True, blank=True, on_delete=models.CASCADE, related_name="push_subs")
    endpoint = models.URLField(unique=True)
    p256dh   = models.CharField(max_length=255)
    auth     = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

