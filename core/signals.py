from decimal import Decimal
from django.utils import timezone
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Bond, Invoice

@receiver(post_save, sender=Bond)
def create_invoice_for_new_bond(sender, instance: Bond, created: bool, **kwargs):
    """
    When a Bond is created, make an Invoice for the same person/tenant for the bond amount.
    We only run on create (not edits), and we skip zero/blank amounts.
    We also guard against duplicates by using a predictable invoice number.
    """
    if not created:
        return

    amt = instance.bond_amount or Decimal("0")
    if amt <= 0:
        return

    number = f"BOND-{instance.pk}"  # predictable, avoids dupes
    # If an invoice with this number already exists, do nothing
    if Invoice.objects.filter(tenant=instance.tenant, person=instance.person, number=number).exists():
        return

    Invoice.objects.create(
        tenant=instance.tenant,
        person=instance.person,
        date=instance.date or timezone.localdate(),
        number=number,
        description=f"Bond for {getattr(instance, 'offense_type', '') or 'Offense'}",
        amount=amt,
        due_date=getattr(instance, 'date', None),
        status=Invoice.STATUS_UNPAID,
    )
