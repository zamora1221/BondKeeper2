from __future__ import annotations
import base64, csv, io, json
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
from django.contrib import messages
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseNotAllowed, HttpRequest, JsonResponse
from django.contrib.auth.decorators import login_required
from .models import Person, Indemnitor, Reference, Bond, CourtDate, CheckIn, Invoice, Receipt, PaymentPlan, PlanInstallment, LookupValue
from .forms import PersonForm, IndemnitorForm, ReferenceForm, BondForm, CourtDateForm, CheckInForm, InvoiceForm, ReceiptForm, PaymentPlanForm
from .utils import get_current_tenant
from decimal import Decimal
from django.db.models import Sum, Count, F, Q, Value, DecimalField, OuterRef, Subquery, ExpressionWrapper, Max
from django.utils import timezone
from django.db import transaction
from django.urls import reverse
from datetime import datetime, timedelta, date
from django.views.decorators.http import require_POST, require_http_methods
from django.db.models.deletion import ProtectedError
from calendar import monthrange
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils.html import escape
from django.db.models.functions import Coalesce
from pywebpush import webpush, WebPushException
from .models import PushSubscription
from django.conf import settings
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_exempt
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.core.files.uploadedfile import UploadedFile
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from django.contrib.auth.decorators import login_required


# CSV → model field suggestions
HEADER_SYNONYMS: Dict[str, List[str]] = {
    "first_name": ["first name","firstname","given","given_name","fname","People::Name First"],
    "last_name": ["last name","lastname","surname","family","lname", "People::Name Last"],
    "phone": ["phone","mobile","cell","phone number","phone_number"],
    "email": ["email","e-mail"],
    "dob": ["dob","date of birth","birthdate","birthday", "People::D.O.B."],
    "address": ["address","street","street address"],
    "city": ["city"],
    "state": ["state","st"],
    "zip": ["zip","zipcode","postal","postal code"],
    "notes": ["notes","note","comments"],
}
ALLOWED_FIELDS = ["first_name","last_name","phone","email","dob","address","city","state","zip","notes"]


@login_required
def people_home(request):
    return render(request, 'people/home.html', {})
@login_required
@require_GET
def person_panel(request, pk):
    # If you use per-tenant data, keep the tenant filter:
    qs = Person.objects.all()
    if hasattr(request, "tenant") and request.tenant:
        qs = qs.filter(tenant=request.tenant)
    person = get_object_or_404(qs, pk=pk)
    return render(request, "people/_tab_main.html", {"person": person})
    
@login_required
def people_tab_list(request):
    q = request.GET.get('q', '').strip()
    qs = Person.objects.filter(tenant=request.tenant)
    if q:
        qs = qs.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(phone__icontains=q) | Q(email__icontains=q))
    return render(request, 'people/_list.html', {'people': qs.order_by('last_name','first_name')[:200]})

def person_main_panel(request, pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=pk, tenant=tenant)
    invoice_rows, invoice_totals = _invoice_context(person)
    receipt_list = _receipts_for_person(person)
    return render(request, "people/_tab_main.html", {
        "person": person,
        "invoice_rows": invoice_rows,
        "invoice_totals": invoice_totals,
        "receipt_list": receipt_list,
    })


@login_required
def person_new_partial(request):
    tenant = get_current_tenant(request)
    if request.method == "POST":
        form = PersonForm(request.POST)
        if form.is_valid():
            person = form.save(commit=False)
            person.tenant = tenant
            person.save()
            # Return the main tab for the new person and trigger list refresh + auto-select + close modal
            resp = render(request, "people/_tab_main.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({
                "people_list_refresh": True,
                "people_select": {"pk": person.pk},
                "modal_close": True,
            })
            return resp
        # invalid POST -> re-render form as NEW so it posts to the create URL
        return render(request, "people/_form_person.html", {"form": form, "is_new": True}, status=400)

    # GET -> empty form as NEW
    form = PersonForm()
    return render(request, "people/_form_person.html", {"form": form, "is_new": True})

@login_required
def person_edit_partial(request, pk):
    person = get_object_or_404(Person, pk=pk, tenant=request.tenant)
    form = PersonForm(instance=person)
    return render(request, 'people/_form_person.html', {'form': form, 'person': person, 'is_new': False})

@login_required
def person_save_partial(request, pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=pk, tenant=tenant)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    form = PersonForm(request.POST, instance=person)
    if form.is_valid():
        person = form.save()
        resp = render(request, "people/_tab_main.html", {"person": person})
        resp["HX-Trigger"] = json.dumps({
            "people_list_refresh": True,
            "people_select": {"pk": person.pk},
            "modal_close": True,
        })
        return resp

    # invalid edit -> render as EDIT (is_new=False) so it posts to the save URL with pk
    return render(request, "people/_form_person.html", {"form": form, "person": person, "is_new": False}, status=400)

@login_required
@require_POST
def person_delete(request, pk):
    person = get_object_or_404(Person, pk=pk)
    try:
        person.delete()
    except ProtectedError:
        return HttpResponseBadRequest("""
          <div class="alert danger">
            Cannot delete this person because related records exist (bonds, invoices, etc.).
            Remove those first, then try again.
          </div>
        """)

    # OOB updates: clear the main panel and refresh the people list
    from django.urls import reverse
    html = f"""
      <div id="tab-main" hx-swap-oob="true">
        <div class="muted">Person deleted. Select a person or create a new one.</div>
      </div>

      <div id="people-list"
           hx-get="{reverse('people_tab_list')}"
           hx-trigger="load"
           hx-swap-oob="true"></div>
    """
    return HttpResponse(html)

# --- Indemnitors ---
@login_required
def indemnitor_new_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)
    if request.method == "POST":
        form = IndemnitorForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.person = person
            obj.tenant = tenant
            obj.save()
            # ⬇️ Only return the section (not the whole tab)
            resp = render(request, "people/_section_indemnitors.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True})
            return resp
        return render(request, "people/_form_indemnitor.html", {"form": form, "person": person})
    form = IndemnitorForm()
    return render(request, "people/_form_indemnitor.html", {"form": form, "person": person})

@login_required
def indemnitor_edit_partial(request, pk):
    tenant = get_current_tenant(request)
    obj = get_object_or_404(Indemnitor, pk=pk, tenant=tenant)
    person = obj.person
    if request.method == "POST":
        form = IndemnitorForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            resp = render(request, "people/_section_indemnitors.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True})
            return resp
        return render(request, "people/_form_indemnitor.html", {"form": form, "person": person, "indemnitor": obj})
    form = IndemnitorForm(instance=obj)
    return render(request, "people/_form_indemnitor.html", {"form": form, "person": person, "indemnitor": obj})

@login_required
def indemnitor_delete(request, pk):
    ind = get_object_or_404(Indemnitor, pk=pk)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    person = ind.person
    ind.delete()
    return render(request, "people/_section_indemnitors.html", {"person": person})

# --- References ---
@login_required
def reference_new_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)
    if request.method == "POST":
        form = ReferenceForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.person = person
            obj.tenant = tenant
            obj.save()
            # ⬇️ Only return the section (not the whole tab)
            resp = render(request, "people/_section_references.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True})
            return resp
        return render(request, "people/_form_reference.html", {"form": form, "person": person})
    form = ReferenceForm()
    return render(request, "people/_form_reference.html", {"form": form, "person": person})

@login_required
def reference_edit_partial(request, pk):
    tenant = get_current_tenant(request)
    obj = get_object_or_404(Reference, pk=pk, tenant=tenant)
    person = obj.person
    if request.method == "POST":
        form = ReferenceForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            resp = render(request, "people/_section_references.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True})
            return resp
        return render(request, "people/_form_reference.html", {"form": form, "person": person, "reference": obj})
    form = ReferenceForm(instance=obj)
    return render(request, "people/_form_reference.html", {"form": form, "person": person, "reference": obj})

@login_required
def reference_delete(request, pk):
    ref = get_object_or_404(Reference, pk=pk)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    person = ref.person
    ref.delete()
    return render(request, "people/_section_references.html", {"person": person})


@login_required
def bond_new_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)
    if request.method == "POST":
        form = BondForm(request.POST)
        if form.is_valid():
            bond = form.save(commit=False)
            bond.person = person
            bond.tenant = tenant
            bond.save()
            _remember_lookups_from_bond(bond)

            # ---- AUTO-INVOICE HERE (no signals) ----
            amount = bond.bond_amount or Decimal("0")
            if amount > 0:
                inv_number = f"BOND-{bond.pk}"
                # avoid duplicates on accidental resubmits
                inv, created = Invoice.objects.get_or_create(
                    tenant=tenant,
                    person=person,
                    number=inv_number,
                    defaults={
                        "date": bond.date or timezone.localdate(),
                        "description": f"Bond for {getattr(bond, 'offense_type', '') or 'Offense'}",
                        "amount": amount,
                        "due_date": getattr(bond, "date", None),
                        "status": Invoice.STATUS_UNPAID,
                    },
                )
                # if you want to update the amount when an existing invoice is found:
                # if not created and inv.amount != amount:
                #     inv.amount = amount
                #     inv.save(update_fields=["amount"])

            # Return the bonds section; also tell widgets to refresh
            resp = render(request, "people/_section_bonds.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "billing_changed": True})
            return resp

        return render(request, "people/_form_bond.html", {"form": form, "person": person})
    else:
        form = BondForm()
    return render(
        request,
        "people/_form_bond.html",
        {"form": form, "person": person, "lookups": _lookup_ctx()},
    )


@login_required
@require_http_methods(["GET", "POST"])
def bond_edit_partial(request, pk):
    bond = get_object_or_404(Bond, pk=pk)
    person = bond.person
    if request.method == "POST":
        form = BondForm(request.POST, instance=bond)
        if form.is_valid():
            bond = form.save()
            _remember_lookups_from_bond(bond)
            return render(request, "people/_section_bonds.html", {"person": person})
    else:
        form = BondForm(instance=bond)

    return render(
        request,
        "people/_form_bond.html",
        {"form": form, "person": person, "lookups": _lookup_ctx()},
    )

@login_required
def bond_delete(request, pk):
    b = get_object_or_404(Bond, pk=pk)
    if hasattr(request.user, "tenant_id") and getattr(b, "tenant_id", None) != request.user.tenant_id:
        return HttpResponse(status=403)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    person = b.person
    b.delete()
    return render(request, "people/_section_bonds.html", {"person": person})

def _lookup_ctx():
    """Fetch lookup values grouped by category for the template."""
    qs = LookupValue.objects.all()
    return {
        "charge":       qs.filter(category="charge"),
        "county":       qs.filter(category="county"),
        "offense_type": qs.filter(category="offense_type"),
        "jurisdiction": qs.filter(category="jurisdiction"),
    }

def _remember_lookups_from_bond(bond: Bond):
    """Store any non-empty text into the LookupValue table."""
    pairs = [
        ("charge",       bond.charge),
        ("county",       bond.county),
        ("offense_type", bond.offense_type),
        ("jurisdiction", bond.jurisdiction),
    ]
    for cat, val in pairs:
        if val:
            LookupValue.objects.get_or_create(category=cat, value=val.strip())

@login_required
def court_date_new_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)
    if request.method == "POST":
        form = CourtDateForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.person = person
            obj.tenant = tenant
            obj.save()
            resp = render(request, "people/_section_court_dates.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "court_dates_changed": True})
            return resp
        return render(request, "people/_form_court_date.html", {"form": form, "person": person})
    form = CourtDateForm()
    return render(request, "people/_form_court_date.html", {"form": form, "person": person})

@login_required
@require_http_methods(["GET", "POST"])
def court_date_edit_partial(request, pk):
    cd = get_object_or_404(CourtDate.objects.select_related("person"), pk=pk)

    if request.method == "POST":
        form = CourtDateForm(request.POST, instance=cd)
        if form.is_valid():
            form.save()
            person = cd.person
            court_dates = CourtDate.objects.filter(person=person).order_by("date", "time")
            resp = render(request, "people/_section_court_dates.html", {
                "person": person,
                "court_dates": court_dates,
            })
            # 👇 tell the frontend to refresh widgets that care about court dates
            resp["HX-Trigger"] = json.dumps({"court_dates_changed": {"person_id": person.pk}})
            return resp
    else:
        form = CourtDateForm(instance=cd)

    return render(request, "people/_form_court_date.html", {
        "form": form,
        "person": cd.person,
        "obj": cd,
    })

@login_required
def court_date_delete(request, pk):
    cd = get_object_or_404(CourtDate, pk=pk)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    person = cd.person
    cd.delete()
    return render(request, "people/_section_court_dates.html", {"person": person})

def _recent_court_date(person):
    return person.court_dates.order_by('-date', '-time', '-id').first()

# widget view
@login_required
def court_date_recent_widget(request, person_pk):
    person = get_object_or_404(Person, pk=person_pk)

    # Prefer next upcoming; fallback to most recent past
    upcoming = (
        CourtDate.objects
        .filter(person=person, date__gte=date.today())
        .order_by('date', 'time')
        .first()
    )
    recent_cd = upcoming or (
        CourtDate.objects
        .filter(person=person)
        .order_by('-date', '-time')
        .first()
    )

    return render(request, "people/_widget_recent_court_date_inner.html", {
        "person": person,
        "recent_cd": recent_cd,
    })

@login_required
def court_date_notice(request, pk):
    tenant = get_current_tenant(request)
    cd = get_object_or_404(
        CourtDate.objects.select_related("person"),
        pk=pk,
        person__tenant=tenant,
    )
    person = cd.person
    return render(request, "people/print_court_notice.html", {
        "person": person,
        "court_date": cd,
        "tenant": tenant,
    })

@login_required
def checkin_new_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)
    if request.method == "POST":
        form = CheckInForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.person = person
            obj.tenant = tenant
            obj.save()
            resp = render(request, "people/_section_checkins.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "checkins_changed": True})
            return resp
        return render(request, "people/_form_checkin.html", {"form": form, "person": person})
    form = CheckInForm()
    return render(request, "people/_form_checkin.html", {"form": form, "person": person})

@login_required
def checkin_edit_partial(request, pk):
    tenant = get_current_tenant(request)
    obj = get_object_or_404(CheckIn, pk=pk, tenant=tenant)
    person = obj.person
    if request.method == "POST":
        form = CheckInForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            resp = render(request, "people/_section_checkins.html", {"person": person})
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "checkins_changed": True})
            return resp
        return render(request, "people/_form_checkin.html", {"form": form, "person": person, "checkin": obj})
    form = CheckInForm(instance=obj)
    return render(request, "people/_form_checkin.html", {"form": form, "person": person, "checkin": obj})

@login_required
def checkin_delete(request, pk):
    ci = get_object_or_404(CheckIn, pk=pk)
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    person = ci.person
    ci.delete()
    return render(request, "people/_section_checkins.html", {"person": person})

@login_required
def checkin_last_widget(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)

    last_ci = CheckIn.objects.filter(person=person, tenant=tenant)\
                             .order_by('-created_at', '-id').first()

    days_since = None
    last_date = None
    if last_ci and last_ci.created_at:
        last_date = timezone.localdate(last_ci.created_at)
        days_since = (timezone.localdate() - last_date).days

    return render(request, "people/_widget_last_checkin.html", {
        "person": person,
        "days_since": days_since,
        "last_date": last_date,  # optional, if you want to show the date on hover, etc.
    })

@login_required
def invoice_new_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)
    if request.method == "POST":
        form = InvoiceForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.person = person
            obj.tenant = tenant
            obj.save()
            rows, totals = _invoice_context(person)
            receipts = _receipts_for_person(person)
            resp = render(request, "people/_section_invoices.html", {
                "person": person,
                "invoice_rows": rows,
                "invoice_totals": totals,
                "receipt_list": receipts,
            })
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "billing_changed": True})
            return resp
        return render(request, "people/_form_invoice.html", {"form": form, "person": person})
    form = InvoiceForm()
    return render(request, "people/_form_invoice.html", {"form": form, "person": person})

@login_required
def invoice_edit_partial(request, pk):
    tenant = get_current_tenant(request)
    obj = get_object_or_404(Invoice, pk=pk, tenant=tenant)
    person = obj.person
    if request.method == "POST":
        form = InvoiceForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            rows, totals = _invoice_context(person)
            receipts = _receipts_for_person(person)
            resp = render(request, "people/_section_invoices.html", {
                "person": person,
                "invoice_rows": rows,
                "invoice_totals": totals,
                "receipt_list": receipts,
            })
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "billing_changed": True})
            return resp
        return render(request, "people/_form_invoice.html", {"form": form, "person": person, "invoice": obj})
    form = InvoiceForm(instance=obj)
    return render(request, "people/_form_invoice.html", {"form": form, "person": person, "invoice": obj})

@login_required
def invoice_delete(request, pk):
    inv = get_object_or_404(Invoice, pk=pk)
    person = inv.person
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    inv.delete()
    rows, totals = _invoice_context(person)
    receipts = _receipts_for_person(person)
    return render(request, "people/_section_invoices.html", {
        "person": person,
        "invoice_rows": rows,
        "invoice_totals": totals,
        "receipt_list": receipts,
    })

def _invoice_context(person):
    rows = []
    total_amt = Decimal('0')
    total_paid = Decimal('0')
    for inv in person.invoices.all().prefetch_related('receipts'):
        paid = inv.receipts.aggregate(s=Sum('amount'))['s'] or Decimal('0')
        amt = inv.amount or Decimal('0')
        rows.append({"inv": inv, "paid": paid, "balance": amt - paid})
        total_amt += amt
        total_paid += paid
    totals = {"amount": total_amt, "paid": total_paid, "balance": total_amt - total_paid}
    return rows, totals

@login_required
def invoices_section_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)
    # reuse your helpers so totals/receipts show up
    invoice_rows, invoice_totals = _invoice_context(person)
    receipt_list = _receipts_for_person(person)
    return render(request, "people/_section_invoices.html", {
        "person": person,
        "invoice_rows": invoice_rows,
        "invoice_totals": invoice_totals,
        "receipt_list": receipt_list,
    })

@login_required
def billing_summary_widget(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)

    total_amt = person.invoices.aggregate(s=Sum('amount'))['s'] or Decimal('0')
    total_paid = Receipt.objects.filter(invoice__person=person, invoice__tenant=tenant) \
                                .aggregate(s=Sum('amount'))['s'] or Decimal('0')
    balance = total_amt - total_paid

    last_dt = Receipt.objects.filter(invoice__person=person, invoice__tenant=tenant) \
                             .aggregate(m=Max('date'))['m']
    days_since = None
    if last_dt:
        days_since = (timezone.localdate() - last_dt).days

    return render(request, "people/_widget_billing_summary.html", {
        "person": person,
        "balance": balance,
        "days_since": days_since,
    })

# ---- RECEIPTS ----

@login_required
def receipt_new_partial(request, invoice_pk):
    tenant = get_current_tenant(request)
    invoice = get_object_or_404(Invoice, pk=invoice_pk, tenant=tenant)
    person = invoice.person
    if request.method == "POST":
        form = ReceiptForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.invoice = invoice
            obj.tenant = tenant
            obj.save()
            rows, totals = _invoice_context(person)
            receipts = _receipts_for_person(person)
            resp = render(request, "people/_section_invoices.html", {
                "person": person,
                "invoice_rows": rows,
                "invoice_totals": totals,
                "receipt_list": receipts,
            })
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "billing_changed": True})
            return resp
        return render(request, "people/_form_receipt.html", {"form": form, "invoice": invoice, "person": person})
    form = ReceiptForm()
    return render(request, "people/_form_receipt.html", {"form": form, "invoice": invoice, "person": person})


@login_required
def receipt_edit_partial(request, pk):
    tenant = get_current_tenant(request)
    obj = get_object_or_404(Receipt, pk=pk, tenant=tenant)
    person = obj.invoice.person
    if request.method == "POST":
        form = ReceiptForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            rows, totals = _invoice_context(person)
            receipts = _receipts_for_person(person)
            resp = render(request, "people/_section_invoices.html", {
                "person": person,
                "invoice_rows": rows,
                "invoice_totals": totals,
                "receipt_list": receipts,
            })
            resp["HX-Trigger"] = json.dumps({"modal_close": True, "billing_changed": True})
            return resp
        return render(request, "people/_form_receipt.html", {"form": form, "invoice": obj.invoice, "person": person, "receipt": obj})
    form = ReceiptForm(instance=obj)
    return render(request, "people/_form_receipt.html", {"form": form, "invoice": obj.invoice, "person": person, "receipt": obj})

@login_required
def receipt_delete(request, pk):
    rcpt = get_object_or_404(Receipt, pk=pk)
    person = rcpt.invoice.person
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    rcpt.delete()
    rows, totals = _invoice_context(person)
    receipts = _receipts_for_person(person)

    return render(request, "people/_section_invoices.html", {
        "person": person,
        "invoice_rows": rows,
        "invoice_totals": totals,
        "receipt_list": receipts,
    })

def _receipts_for_person(person):
    # all receipts for this person (any invoice), newest first
    return Receipt.objects.select_related('invoice').filter(invoice__person=person).order_by('-date', '-id')

@login_required
def receipt_new_for_person_partial(request, person_pk):
    tenant = get_current_tenant(request)
    person = get_object_or_404(Person, pk=person_pk, tenant=tenant)

    if request.method == "POST":
        form = ReceiptForm(request.POST)
        invoice_id = request.POST.get("invoice")
        invoice = None
        if invoice_id:
            invoice = get_object_or_404(Invoice, pk=invoice_id, tenant=tenant, person=person)

        if form.is_valid() and invoice:
            obj = form.save(commit=False)
            obj.invoice = invoice
            obj.tenant = tenant
            obj.save()
            rows, totals = _invoice_context(person)
            receipts = _receipts_for_person(person)
            resp = render(request, "people/_section_invoices.html", {
                "person": person,
                "invoice_rows": rows,
                "invoice_totals": totals,
                "receipt_list": receipts,
            })
            resp["HX-Trigger"] = json.dumps({"modal_close": True})
            return resp

        if form.is_valid() and not invoice:
            form.add_error(None, "Please choose an invoice.")

        invoices = person.invoices.all().order_by('-date', '-id')
        return render(request, "people/_form_receipt_person.html", {
            "form": form, "person": person, "invoices": invoices
        })

    # GET
    form = ReceiptForm()
    invoices = person.invoices.all().order_by('-date', '-id')
    return render(request, "people/_form_receipt_person.html", {
        "form": form, "person": person, "invoices": invoices
    })

@login_required
def receipt_print(request, pk):
    tenant = get_current_tenant(request)
    receipt = get_object_or_404(
        Receipt.objects.select_related("invoice", "invoice__person"),
        pk=pk, invoice__tenant=tenant
    )
    invoice = receipt.invoice
    person = invoice.person

    invoice_total = invoice.amount or 0
    total_paid_to_date = Receipt.objects.filter(invoice=invoice).aggregate(
        s=Sum("amount")
    )["s"] or 0
    balance_after = max((invoice_total or 0) - (total_paid_to_date or 0), 0)

    return render(request, "people/print_receipt.html", {
        "tenant": tenant,
        "person": person,
        "invoice": invoice,
        "receipt": receipt,
        "invoice_total": invoice_total,
        "total_paid_to_date": total_paid_to_date,
        "balance_after": balance_after,
    })

# --- helpers ---
def _add_period(d: date, frequency: str, seq: int) -> date:
    if frequency == PaymentPlan.FREQ_WEEKLY:
        return d + timedelta(weeks=seq-1)
    if frequency == PaymentPlan.FREQ_BIWEEKLY:
        return d + timedelta(weeks=(2*(seq-1)))
    # monthly (simple month add: 30 days per step to avoid dateutil dep)
    return d + timedelta(days=30*(seq-1))


@login_required
def payment_plan_section_partial(request, person_pk):
    person = get_object_or_404(Person, pk=person_pk)
    plans = person.payment_plans.order_by("-created_at")
    return render(request, "people/_section_payment_plan.html",
                  {"person": person, "plans": plans, "today": timezone.localdate()})


@login_required
@require_http_methods(["GET","POST"])
@transaction.atomic
def payment_plan_new_partial(request, person_pk):
    person = get_object_or_404(Person, pk=person_pk)

    if request.method == "GET":
        form = PaymentPlanForm()
        form.fields["invoice"].queryset = Invoice.objects.filter(person=person)
        return render(request, "people/_form_payment_plan.html", {"form": form, "person": person})

    form = PaymentPlanForm(request.POST)
    form.fields["invoice"].queryset = Invoice.objects.filter(person=person)
    if not form.is_valid():
        return render(request, "people/_form_payment_plan.html", {"form": form, "person": person})

    # create plan + installments
    plan: PaymentPlan = form.save(commit=False)
    plan.person = person
    plan.save()

    for i in range(1, plan.n_payments + 1):
        due = _add_period(plan.start_date, plan.frequency, i)
        PlanInstallment.objects.create(
            plan=plan, sequence=i, due_date=due, amount=plan.installment_amount
        )

    # Return OOB to refresh the section and close any modal/inline form
    html = f"""
      <div id="payment-plan-section"
           hx-get="{reverse('payment_plan_section_partial', args=[person.pk])}"
           hx-trigger="load"
           hx-swap-oob="true"></div>
    """
    return HttpResponse(html)


@login_required
@require_POST
def installment_mark_paid(request, pk):
    inst = get_object_or_404(PlanInstallment, pk=pk)
    inst.mark_paid()
    # return refreshed section
    html = f"""
      <div id="payment-plan-section"
           hx-get="{reverse('payment_plan_section_partial', args=[inst.plan.person_id])}"
           hx-trigger="load"
           hx-swap-oob="true"></div>
    """
    return HttpResponse(html)


@login_required
@require_POST
def payment_plan_cancel(request, pk):
    plan = get_object_or_404(PaymentPlan, pk=pk)
    plan.active = False
    plan.save(update_fields=["active"])
    html = f"""
      <div id="payment-plan-section"
           hx-get="{reverse('payment_plan_section_partial', args=[plan.person_id])}"
           hx-trigger="load"
           hx-swap-oob="true"></div>
    """
    return HttpResponse(html)

# --- Court calendar + ICS ---

def _court_dt(cd) -> datetime:
    """Get a datetime for a CourtDate record regardless of field naming."""
    for fld in ("scheduled_at", "hearing_at", "datetime", "date_time"):
        if hasattr(cd, fld) and getattr(cd, fld):
            return getattr(cd, fld)
    d = getattr(cd, "date", None)
    t = getattr(cd, "time", None)
    if d and t:
        return datetime.combine(d, t)
    if d:
        return datetime.combine(d, datetime.min.time())
    return timezone.now()

@login_required
def court_calendar(request):
    qs = CourtDate.objects.select_related("person").all()
    agency = request.GET.get("agency") or ""
    county = request.GET.get("county") or ""
    if agency:
        # adjust to your field name
        qs = qs.filter(agency__icontains=agency)
    if county:
        # adjust to your field name
        qs = qs.filter(county__icontains=county)

    # Upcoming first
    qs = sorted(qs, key=_court_dt)
    return render(request, "calendar/main.html", {"items": qs, "agency": agency, "county": county})


@login_required
def person_calendar_partial(request, person_pk):
    person = get_object_or_404(Person, pk=person_pk)

    today = timezone.localdate()
    y = int(request.GET.get("y", today.year))
    m = int(request.GET.get("m", today.month))

    # Normalize y/m
    if m < 1:
        y -= 1; m = 12
    elif m > 12:
        y += 1; m = 1

    first_day = date(y, m, 1)
    _, days_in_month = monthrange(y, m)
    last_day = date(y, m, days_in_month)

    # Pull this person's court dates and filter to this month
    cds = CourtDate.objects.select_related("person").filter(person_id=person.pk)
    month_items = []
    for cd in cds:
        dt = _court_dt(cd)
        if first_day <= dt.date() <= last_day:
            month_items.append((dt, cd))
    month_items.sort(key=lambda x: x[0])

    # Group into a structure that's easy for templates (avoid dict lookups by var key)
    items_by_day = {}
    for dt, cd in month_items:
        items_by_day.setdefault(dt.day, []).append((dt, cd))
    days_data = [{"day": d, "items": items_by_day.get(d, [])} for d in range(1, days_in_month + 1)]

    # Prev/Next helpers
    prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
    next_y, next_m = (y + 1, 1)  if m == 12 else (y, m + 1)

    ctx = {
        "person": person,
        "year": y,
        "month": m,
        "offset_range": range(first_day.weekday()),  # Monday=0
        "days_data": days_data,
        "prev_y": prev_y, "prev_m": prev_m,
        "next_y": next_y, "next_m": next_m,
        "today": today,
    }
    return render(request, "people/_tab_calendar.html", ctx)

@login_required
def calendar_partial(request):
    """Global month grid of all CourtDate items (does not replace other tabs)."""
    today = timezone.localdate()
    y = int(request.GET.get("y", today.year))
    m = int(request.GET.get("m", today.month))

    # normalize month bounds
    if m < 1:
        y -= 1; m = 12
    elif m > 12:
        y += 1; m = 1

    first_day = date(y, m, 1)
    _, days_in_month = monthrange(y, m)
    last_day = date(y, m, days_in_month)

    # Collect all court dates in this month
    items = []
    for cd in CourtDate.objects.select_related("person"):
        dt = _court_dt(cd)
        if first_day <= dt.date() <= last_day:
            items.append((dt, cd))
    items.sort(key=lambda x: x[0])

    # Group by day number for template
    by_day = {}
    for dt, cd in items:
        by_day.setdefault(dt.day, []).append((dt, cd))
    days_data = [{"day": d, "items": by_day.get(d, [])} for d in range(1, days_in_month + 1)]

    # Prev/Next helpers
    prev_y, prev_m = (y - 1, 12) if m == 1 else (y, m - 1)
    next_y, next_m = (y + 1, 1)  if m == 12 else (y, m + 1)

    ctx = {
        "year": y,
        "month": m,
        "offset_range": range(first_day.weekday()),  # Monday=0
        "days_data": days_data,
        "prev_y": prev_y, "prev_m": prev_m,
        "next_y": next_y, "next_m": next_m,
        "today": today,
    }
    return render(request, "people/_tab_calendar_global.html", ctx)

@login_required
def person_calendar_ics(request, person_pk):
    """ICS feed for a single person's court dates."""
    person = get_object_or_404(Person, pk=person_pk)
    cds = CourtDate.objects.filter(person_id=person.pk)
    now = timezone.now()

    def _ics_dt(dt: datetime) -> str:
        # Use UTC; if your datetimes are naive/local, this is fine for a simple feed
        return dt.strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BondKeeper//Person Court Calendar//EN",
    ]
    for cd in cds:
        dt = _court_dt(cd)
        uid = f"court-{person.pk}-{cd.pk}@bondkeeper"
        loc = getattr(cd, "location", "") or getattr(cd, "court", "") or ""
        title = f"Court: {person}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_ics_dt(now)}",
            f"DTSTART:{_ics_dt(dt)}",
            f"SUMMARY:{title}",
            f"LOCATION:{loc}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")

    return HttpResponse("\r\n".join(lines), content_type="text/calendar; charset=utf-8")

@login_required
def calendar_ics(request):
    """ICS feed for ALL court dates (global)."""
    now = timezone.now()
    qs = CourtDate.objects.select_related("person")

    def _ics_dt(dt: datetime) -> str:
        return dt.strftime("%Y%m%dT%H%M%SZ")  # simple UTC stamp

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//BondKeeper//Global Court Calendar//EN",
    ]
    for cd in qs:
        dt = _court_dt(cd)
        person = getattr(cd, "person", None)
        display_person = str(person) if person else "Unknown"
        uid = f"court-{getattr(person,'pk',0)}-{cd.pk}@bondkeeper"
        loc = getattr(cd, "location", "") or getattr(cd, "court", "") or ""
        title = f"Court: {display_person}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{_ics_dt(now)}",
            f"DTSTART:{_ics_dt(dt)}",
            f"SUMMARY:{title}",
            f"LOCATION:{loc}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return HttpResponse("\r\n".join(lines), content_type="text/calendar; charset=utf-8")

def _norm(s: str) -> str: return (s or "").strip().lower()
def _best_guess_field(header: str) -> Optional[str]:
    h = _norm(header)
    if h in ALLOWED_FIELDS: return h
    for field, syns in HEADER_SYNONYMS.items():
        if h == field or h in (_norm(x) for x in syns): return field
    return None

def _read_csv_to_rows(b64: str) -> List[List[str]]:
    raw = base64.b64decode(b64.encode("utf-8"))
    try: text = raw.decode("utf-8-sig")
    except UnicodeDecodeError: text = raw.decode("latin-1", errors="ignore")
    try:
        dialect = csv.Sniffer().sniff(text[:2048])
    except Exception:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(text), dialect)]

@dataclass
class RowResult:
    ok: bool
    msg: str
    data: Dict[str, Any]

@login_required
@require_http_methods(["GET","POST"])
def person_import(request: HttpRequest) -> HttpResponse:
    import datetime  # for DOB parsing

    def _clean_quotes(s: str) -> str:
        return (s or "").strip().strip('"').strip("'").strip("“").strip("”").strip()

    def parse_date_flex(s: str):
        s = _clean_quotes(s).replace("—", "-").replace("–", "-")
        if not s:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d %Y"):
            try:
                return datetime.datetime.strptime(s, fmt).date()
            except ValueError:
                pass
        return None

    step = request.POST.get("step")
    if request.method == "GET" or not step:
        return render(request, "people/_subtab_import_upload.html", {})

    if step == "preview":
        f = request.FILES.get("file")
        if not f:
            messages.error(request, "Please choose a CSV file.")
            return render(request, "people/_subtab_import_upload.html", {})
        b64 = base64.b64encode(f.read()).decode("utf-8")
        rows = _read_csv_to_rows(b64)
        if not rows:
            messages.error(request, "The file appears to be empty.")
            return render(request, "people/_subtab_import_upload.html", {})
        headers, data_rows = rows[0], rows[1:]
        guesses = [_best_guess_field(h) for h in headers]
        cols = [
            {"i": i, "header": h, "guess": (guesses[i] or "")}
            for i, h in enumerate(headers)
        ]
        return render(request, "people/_subtab_import_preview.html", {
            "csv_b64": b64,
            "headers": headers,
            "guesses": guesses,
            "cols": cols,
            "allowed_fields": ALLOWED_FIELDS,
            "preview_rows": data_rows[:8],
        })

    if step == "import":
        # Resolve tenant (required on Person)
        tenant = getattr(request.user, "tenant", None)
        if tenant is None and hasattr(request, "tenant"):
            tenant = request.tenant
        if tenant is None:
            messages.error(request, "No tenant associated with your user; cannot import.")
            return render(request, "people/_subtab_import_upload.html", {})

        csv_b64 = request.POST.get("csv_b64", "")
        rows = _read_csv_to_rows(csv_b64)
        if not rows:
            messages.error(request, "Could not read the uploaded file.")
            return render(request, "people/_subtab_import_upload.html", {})
        headers, data_rows = rows[0], rows[1:]

        mapping = {}
        for i in range(len(headers)):
            field = request.POST.get(f"map_field_{i}", "")
            if field in ALLOWED_FIELDS:
                mapping[i] = field

        commit = request.POST.get("commit") == "1"
        dedupe_by_phone = request.POST.get("dedupe_by_phone") == "1"

        results: List[RowResult] = []
        created = updated = failed = 0

        @transaction.atomic
        def _perform(commit_flag: bool):
            nonlocal created, updated, failed
            for idx, row in enumerate(data_rows, start=2):
                # Build record dict for this row based on mapping
                record = {
                    field: _clean_quotes(row[i]) if i < len(row) and row[i] is not None else ""
                    for i, field in mapping.items()
                }

                # Normalize/validate DOB (if present)
                # DOB cleanup (treat blank as None; parse if non-blank)
                if "dob" in record:
                    raw = record["dob"]
                    if not raw:  # after cleaning, it's empty -> allow null
                        record["dob"] = None
                    else:
                        d = parse_date_flex(raw)
                        if d is None:
                            failed += 1
                            results.append(
                                RowResult(False, f"Row {idx}: Invalid DOB format (try YYYY-MM-DD or MM/DD/YYYY).",
                                          record))
                            continue
                        record["dob"] = d  # store actual date object

                # Minimal required fields
                if not record.get("first_name") or not record.get("last_name"):
                    failed += 1
                    results.append(RowResult(False, f"Row {idx}: Missing first/last name", record))
                    continue

                try:
                    person = None
                    if dedupe_by_phone and record.get("phone"):
                        # Match within same tenant
                        person = Person.objects.filter(tenant=tenant, phone__iexact=record["phone"]).first()

                    if person:
                        for k, v in record.items():
                            setattr(person, k, v)
                        if commit_flag:
                            person.full_clean()
                            person.save()
                        updated += 1
                        results.append(RowResult(True, f"Row {idx}: updated", record))
                    else:
                        # Pass tenant on create
                        person = Person(tenant=tenant, **record)
                        if commit_flag:
                            person.full_clean()
                            person.save()
                        created += 1
                        results.append(RowResult(True, f"Row {idx}: created", record))
                except Exception as e:
                    failed += 1
                    results.append(RowResult(False, f"Row {idx}: {e}", record))

            if not commit_flag:
                transaction.set_rollback(True)

        _perform(commit)

        return render(request, "people/_subtab_import_results.html", {
            "headers": headers,
            "results": results[:200],
            "created": created,
            "updated": updated,
            "failed": failed,
            "committed": commit,
        })

    return render(request, "people/_subtab_import_upload.html", {})

@login_required
@require_http_methods(["GET"])
def person_field_edit(request, pk: int, field: str):
    if field not in ALLOWED_INLINE_FIELDS:
        return HttpResponseBadRequest("Field not allowed")

    person = _get_person_scoped(request, pk)
    meta = ALLOWED_INLINE_FIELDS[field]
    val = getattr(person, field, "")
    if meta["input"] == "date" and val:
        try:
            val = val.strftime("%Y-%m-%d")
        except Exception:
            val = ""

    return render(request, "people/_person_field_edit.html", {
        "person": person,
        "field": field,
        "meta": meta,
        "value": val or "",
        "autofocus": True,   # only on first load
    })


def _resolve_tenant(request):
    tenant = getattr(request.user, "tenant", None)
    if tenant is None and hasattr(request, "tenant"):
        tenant = request.tenant
    return tenant

def _get_person_scoped(request, pk: int):
    tenant = _resolve_tenant(request)
    try:
        # scope by tenant if your model has it
        return get_object_or_404(Person, pk=pk, tenant=tenant) if tenant else get_object_or_404(Person, pk=pk)
    except Exception:
        return get_object_or_404(Person, pk=pk)

ALLOWED_INLINE_FIELDS = {
    "first_name": {"label": "First Name", "input": "text"},
    "last_name":  {"label": "Last Name",  "input": "text"},
    "phone":   {"label": "Phone",  "input": "text"},
    "email":   {"label": "Email",  "input": "text"},
    "address": {"label": "Street", "input": "text"},
    "city":    {"label": "City",   "input": "text"},
    "state":   {"label": "State",  "input": "text"},
    "zip":     {"label": "ZIP",    "input": "text"},
    "dob":     {"label": "DOB",    "input": "date"},
    "alias":   {"label": "Alias",  "input": "text"},
    "notes":   {"label": "Notes",  "input": "textarea"},
}

def _clean_quotes(s: str) -> str:
    return (s or "").strip().strip('"').strip("'").strip("“").strip("”").strip()


@login_required
@require_http_methods(["POST"])
def person_field_save(request, pk: int, field: str):
    if field not in ALLOWED_INLINE_FIELDS:
        return HttpResponseBadRequest("Field not allowed")

    person = _get_person_scoped(request, pk)
    raw = _clean_quotes(request.POST.get("value", ""))

    # Coerce types
    if field == "dob":
        if raw == "":
            value = None
        else:
            d = _parse_date_flex(raw)
            if d is None:
                meta = ALLOWED_INLINE_FIELDS[field]
                return render(request, "people/_person_field_edit.html", {
                    "person": person, "field": field, "meta": meta,
                    "value": raw, "autofocus": False,
                    "error": "Invalid date (use YYYY-MM-DD or MM/DD/YYYY)."
                })
            value = d
    else:
        value = raw

    # Assign & validate
    try:
        setattr(person, field, value)
        person.full_clean()
        person.save()
    except ValidationError as e:
        meta = ALLOWED_INLINE_FIELDS[field]
        return render(request, "people/_person_field_edit.html", {
            "person": person, "field": field, "meta": meta,
            "value": raw, "autofocus": False,
            "error": "; ".join(" ".join(v) for v in e.message_dict.values())
        })

    # Re-render the EDIT fragment (keep inputs visible; NO autofocus now)
    meta = ALLOWED_INLINE_FIELDS[field]
    val = getattr(person, field, "")
    if meta.get("input") == "date" and val:
        try:
            val = val.strftime("%Y-%m-%d")
        except Exception:
            val = ""
    field_html = render_to_string(
        "people/_person_field_edit.html",
        {"person": person, "field": field, "meta": meta, "value": val or "", "autofocus": False},
        request=request,
    )

    # OOB updates so the header and list reflect the latest name
    oob_html = ""
    if field in ("first_name", "last_name"):
        full_name = getattr(person, "full_name", None) or f"{person.first_name or ''} {person.last_name or ''}".strip() or "Person"
        safe = escape(full_name)
        # Header <h3 id="person-header-name">...</h3>
        oob_html += f'<h3 id="person-header-name" hx-swap-oob="innerHTML">{safe}</h3>'
        # Left list: <span id="person-name-{{ pk }}" class="name">...</span>
        oob_html += f'<span id="person-name-{person.pk}" hx-swap-oob="innerHTML">{safe}</span>'

    return HttpResponse(field_html + oob_html)


def _parse_date_flex(s: str):
    s = _clean_quotes(s).replace("—", "-").replace("–", "-")
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%Y/%m/%d", "%d-%b-%Y", "%b %d %Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

@login_required
@require_http_methods(["GET"])
def person_field_display(request, pk: int, field: str):
    if field not in ALLOWED_INLINE_FIELDS:
        return HttpResponseBadRequest("Field not allowed")

    person = _get_person_scoped(request, pk)
    # Compute a plain string for the template
    val = getattr(person, field, "")
    if field == "dob" and val:
        try:
            val = val.strftime("%Y-%m-%d")
        except Exception:
            val = ""

    return render(request, "people/_person_field_display.html", {
        "person": person,
        "field": field,
        "value": val or "",
    })
def _tenant(request):
    return getattr(request.user, "tenant", getattr(request, "tenant", None))

def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        return None

@login_required
@require_http_methods(["GET"])
def reports_panel(request):
    # renders the reports menu partial
    return render(request, "people/_subtab_reports.html", {})

@login_required
@require_http_methods(["GET"])
def report_bonds_by_date(request):
    """
    Works with Bond.date (DateField) and sums using Coalesce(bond_amount, amount).
    """
    tenant = _tenant(request)
    start = _parse_date(request.GET.get("start")) or (date.today() - timedelta(days=30))
    end   = _parse_date(request.GET.get("end"))   or date.today()
    detailed = (request.GET.get("detailed") == "1")
    as_csv   = (request.GET.get("format") == "csv")

    amount_expr = Coalesce(
        F("bond_amount"), F("amount"),
        Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    )

    qs = Bond.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    qs = qs.filter(date__gte=start, date__lte=end).select_related("person")

    if as_csv:
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="bonds_{start}_{end}.csv"'
        w = csv.writer(resp)
        if detailed:
            w.writerow(["Date", "Defendant", "County", "Amount"])
            for b in qs.order_by("date"):
                amt = b.bond_amount if b.bond_amount is not None else (b.amount or 0)
                w.writerow([b.date, b.person.full_name or str(b.person), b.county or "", amt])
        else:
            agg = (qs.values("date")
                     .annotate(count=Count("id"), total=Sum(amount_expr))
                     .order_by("date"))
            w.writerow(["Date", "Bonds", "Total Amount"])
            for r in agg:
                w.writerow([r["date"], r["count"], r["total"]])
        return resp

    if detailed:
        headers = ["Date", "Defendant", "County", "Amount"]
        rows = []
        for b in qs.order_by("-date", "-id"):
            amt = b.bond_amount if b.bond_amount is not None else (b.amount or 0)
            rows.append([b.date, b.person.full_name or str(b.person), b.county or "-", amt])
        return render(request, "people/_report_table.html", {"headers": headers, "rows": rows})

    # grouped
    agg = (qs.values("date")
             .annotate(count=Count("id"), total=Sum(amount_expr))
             .order_by("date"))
    headers = ["Date", "Bonds", "Total Amount"]
    rows = [[r["date"], r["count"], r["total"]] for r in agg]
    totals = ["Total", sum(r["count"] for r in agg), sum(r["total"] for r in agg)]
    return render(request, "people/_report_table.html", {"headers": headers, "rows": rows, "totals": totals})


@login_required
@require_http_methods(["GET"])
def report_bonds_by_county(request):
    """
    Groups by Bond.county; sums Coalesce(bond_amount, amount). Optional date range.
    """
    tenant = _tenant(request)
    start = _parse_date(request.GET.get("start"))
    end   = _parse_date(request.GET.get("end"))
    as_csv = (request.GET.get("format") == "csv")

    amount_expr = Coalesce(
        F("bond_amount"), F("amount"),
        Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))
    )

    qs = Bond.objects.all()
    if tenant:
        qs = qs.filter(tenant=tenant)
    if start:
        qs = qs.filter(date__gte=start)
    if end:
        qs = qs.filter(date__lte=end)

    agg = qs.values("county").annotate(
        count=Count("id"),
        total=Sum(amount_expr),
    ).order_by("-count", "county")

    headers = ["County", "Bonds", "Total Amount"]
    rows = [[r["county"] or "-", r["count"], r["total"]] for r in agg]
    totals = ["All", sum(r["count"] for r in agg), sum(r["total"] for r in agg)]

    if as_csv:
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="bonds_by_county.csv"'
        w = csv.writer(resp); w.writerow(headers)
        for r in rows: w.writerow(r)
        w.writerow(totals)
        return resp

    return render(request, "people/_report_table.html", {"headers": headers, "rows": rows, "totals": totals})


@login_required
@require_http_methods(["GET"])
def report_people_with_balance(request):
    """
    People with (sum invoices.amount) - (sum receipts.amount) > 0.
    Uses subqueries to avoid double counting joins.
    """
    tenant = _tenant(request)
    only_overdue = (request.GET.get("only_overdue") == "1")
    as_csv = (request.GET.get("format") == "csv")

    inv_sum_q = (Invoice.objects
                 .filter(person=OuterRef("pk"), tenant=tenant if tenant else OuterRef("person__tenant"))
                 .values("person")
                 .annotate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))))
                 .values("total")[:1])

    rec_sum_q = (Receipt.objects
                 .filter(invoice__person=OuterRef("pk"), tenant=tenant if tenant else OuterRef("invoice__person__tenant"))
                 .values("invoice__person")
                 .annotate(total=Coalesce(Sum("amount"), Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))))
                 .values("total")[:1])

    people = Person.objects.all()
    if tenant:
        people = people.filter(tenant=tenant)

    people = (people
              .annotate(invoiced=Coalesce(Subquery(inv_sum_q, output_field=DecimalField(max_digits=12, decimal_places=2)),
                                          Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))))
              .annotate(paid=Coalesce(Subquery(rec_sum_q, output_field=DecimalField(max_digits=12, decimal_places=2)),
                                      Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))))
              .annotate(balance=ExpressionWrapper(F("invoiced") - F("paid"),
                                                 output_field=DecimalField(max_digits=12, decimal_places=2)))
              .filter(balance__gt=0))

    if only_overdue:
        # Overdue = has any invoice due_date <= today (and still balance > 0)
        people = people.filter(invoices__due_date__lte=date.today()).distinct()

    headers = ["Person", "Phone", "Balance"]
    rows = [[p.full_name or str(p), p.phone or "-", p.balance] for p in people.order_by("-balance")]

    if as_csv:
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="people_with_balance.csv"'
        w = csv.writer(resp); w.writerow(headers)
        for r in rows: w.writerow(r)
        return resp

    totals = ["", "Total", sum(r[2] for r in rows)]
    return render(request, "people/_report_table.html", {"headers": headers, "rows": rows, "totals": totals})


@login_required
@require_http_methods(["GET"])
def report_upcoming_court_dates(request):
    tenant = _tenant(request)
    days = int(request.GET.get("days") or 14)
    start = date.today()
    end = start + timedelta(days=days)
    as_csv = (request.GET.get("format") == "csv")

    qs = CourtDate.objects.all()
    if tenant: qs = qs.filter(tenant=tenant)
    qs = qs.filter(date__gte=start, date__lte=end).select_related("person").order_by("date", "time", "id")

    if as_csv:
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="upcoming_court_dates_{start}_{end}.csv"'
        w = csv.writer(resp)
        w.writerow(["Date", "Time", "Person", "County", "Court", "Case #", "Notes"])
        for cd in qs:
            w.writerow([cd.date, cd.time or "", cd.person.full_name or str(cd.person),
                        cd.county or "", cd.court or "", cd.case_number or "", cd.notes or ""])
        return resp

    headers = ["Date", "Time", "Person", "County", "Court", "Case #", "Notes"]
    rows = [[cd.date, cd.time or "-", cd.person.full_name or str(cd.person),
             cd.county or "-", cd.court or "-", cd.case_number or "-", cd.notes or ""] for cd in qs]
    return render(request, "people/_report_table.html", {"headers": headers, "rows": rows})



@login_required
@require_http_methods(["GET"])
def report_people_without_recent_checkin(request):
    tenant = _tenant(request)
    days = int(request.GET.get("days") or 14)
    cutoff_dt = timezone.now() - timedelta(days=days)
    as_csv = (request.GET.get("format") == "csv")

    people = Person.objects.all()
    if tenant: people = people.filter(tenant=tenant)
    people = (people
              .annotate(last_checkin=Max("checkins__created_at"))
              .filter(Q(last_checkin__lt=cutoff_dt) | Q(last_checkin__isnull=True))
              .order_by("last_name", "first_name"))

    if as_csv:
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="no_recent_checkin_{days}d.csv"'
        w = csv.writer(resp)
        w.writerow(["Person", "Phone", "Last Check-in"])
        for p in people:
            w.writerow([p.full_name or f"Person {p.pk}", p.phone or "", p.last_checkin or ""])
        return resp

    headers = ["Person", "Phone", "Last Check-in"]
    rows = [[p.full_name or f"Person {p.pk}", p.phone or "-", p.last_checkin or "-"] for p in people]
    return render(request, "people/_report_table.html", {"headers": headers, "rows": rows})


@login_required
@require_http_methods(["GET"])
def report_overdue_invoices(request):
    tenant = _tenant(request)
    overdue_days = int(request.GET.get("days") or 30)
    cutoff = date.today() - timedelta(days=overdue_days)
    as_csv = (request.GET.get("format") == "csv")

    inv = Invoice.objects.all()
    if tenant: inv = inv.filter(tenant=tenant)
    inv = (inv.filter(due_date__isnull=False, due_date__lte=cutoff)
              .annotate(paid=Coalesce(Sum("receipts__amount"),
                                      Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))))
              .annotate(balance=Coalesce(F("amount"), Value(0, output_field=DecimalField(max_digits=12, decimal_places=2))) - F("paid"))
              .filter(balance__gt=0)
              .select_related("person")
              .order_by("-balance", "-due_date", "-id"))

    if as_csv:
        resp = HttpResponse(content_type="text/csv")
        resp["Content-Disposition"] = f'attachment; filename="overdue_invoices_{overdue_days}d.csv"'
        w = csv.writer(resp)
        w.writerow(["Invoice #", "Person", "Due Date", "Amount", "Paid", "Balance"])
        for i in inv:
            w.writerow([i.number or i.pk, i.person.full_name or str(i.person),
                        i.due_date, i.amount or 0, i.paid or 0, i.balance or 0])
        return resp

    headers = ["Invoice #", "Person", "Due Date", "Amount", "Paid", "Balance"]
    rows = [[i.number or i.pk, i.person.full_name or str(i.person),
             i.due_date, i.amount or 0, i.paid or 0, i.balance or 0] for i in inv]
    totals = ["", "", "Totals",
              sum((i.amount or 0) for i in inv),
              sum((i.paid or 0) for i in inv),
              sum((i.balance or 0) for i in inv)]
    return render(request, "people/_report_table.html", {"headers": headers, "rows": rows, "totals": totals})

@login_required
@require_http_methods(["GET"])
def vapid_public(request):
    # also set a CSRF cookie for subsequent fetches if you like
    get_token(request)
    return JsonResponse({"publicKey": settings.VAPID_PUBLIC_KEY})

@login_required
@require_http_methods(["POST"])
def push_subscribe(request):
    import json
    try:
        data = json.loads(request.body.decode("utf-8"))
        sub = data.get("subscription") or {}
        endpoint = sub.get("endpoint")
        keys = sub.get("keys") or {}
        if not endpoint or "p256dh" not in keys or "auth" not in keys:
            return HttpResponseBadRequest("Invalid subscription")
        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "tenant": getattr(request.user, "tenant_profile", None) or request.user.tenant,  # whichever you use
                "user": request.user,
                "p256dh": keys["p256dh"],
                "auth": keys["auth"],
            },
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return HttpResponseBadRequest(str(e))

@login_required
@require_http_methods(["POST"])
def push_unsubscribe(request):
    import json
    data = json.loads(request.body.decode("utf-8"))
    endpoint = (data.get("subscription") or {}).get("endpoint")
    if endpoint:
        PushSubscription.objects.filter(endpoint=endpoint).delete()
    return JsonResponse({"ok": True})

def _send_push_to_tenant(tenant, payload: dict):
    subs = PushSubscription.objects.filter(tenant=tenant)
    for s in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": s.endpoint,
                    "keys": {"p256dh": s.p256dh, "auth": s.auth}
                },
                data=json.dumps(payload),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_CLAIM_EMAIL},
            )
        except WebPushException:
            # remove dead endpoints
            s.delete()

@login_required
@require_http_methods(["POST"])
def push_test(request):
    tenant = getattr(request.user, "tenant_profile", None) or request.user.tenant
    _send_push_to_tenant(tenant, {"title": "Test", "body": "Hello from BailSaaS", "url": "/"})
    return JsonResponse({"ok": True})

SIGNER = TimestampSigner(salt="self-checkin")

def _make_self_link(request, person):
    # 7 days expiry token
    payload = f"{person.tenant_id}:{person.pk}"
    token = SIGNER.sign(payload)
    return request.build_absolute_uri(reverse("self_checkin", args=[token]))

@login_required
@require_http_methods(["GET"])
def person_selfcheck_link(request, person_pk: int):
    person = get_object_or_404(Person, pk=person_pk)
    # (optionally ensure person.tenant == request.user.tenant)
    token = SIGNER.sign(f"{person.tenant_id}:{person.pk}")
    path  = reverse("self_checkin", args=[token])
    # uses PUBLIC_BASE_URL when present (ngrok)
    url = _abs_url(path, request)
    return JsonResponse({"url": url})

@require_http_methods(["GET", "POST"])
def self_checkin(request, token: str):
    # validate token
    try:
        payload = SIGNER.unsign(token, max_age=7*24*3600)
        tenant_id_str, person_id_str = payload.split(":")
        tenant_id = int(tenant_id_str); person_id = int(person_id_str)
    except (BadSignature, SignatureExpired, ValueError):
        return render(request, "people/self_checkin_invalid.html", status=400)

    person = get_object_or_404(Person, pk=person_id, tenant_id=tenant_id)

    if request.method == "GET":
        return render(request, "people/self_checkin.html", {"person": person, "ok": False, "token": token})

    # POST: verify identity
    last_name = (request.POST.get("last_name") or "").strip().lower()
    dob_str = (request.POST.get("dob") or "").strip()
    method = request.POST.get("method") or CheckIn.METHOD_IN_PERSON
    phone = request.POST.get("phone") or ""
    address = request.POST.get("address") or ""

    # allow MM/DD/YYYY or YYYY-MM-DD
    def parse_dob(s):
        from datetime import datetime
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try: return datetime.strptime(s, fmt).date()
            except: pass
        return None

    if (person.last_name or "").strip().lower() != last_name:
        return render(request, "people/self_checkin.html", {
            "person": person, "error": "Last name does not match.", "ok": False
        })

    want = person.dob
    got = parse_dob(dob_str)
    if not want or not got or want != got:
        return render(request, "people/self_checkin.html", {
            "person": person, "error": "DOB does not match.", "ok": False
        })

    ci = CheckIn(
        tenant_id=tenant_id, person=person,
        method=method, phone=phone, address=address
    )

    # optional files
    photo = request.FILES.get("photo")
    doc = request.FILES.get("document")
    if photo: ci.photo = photo
    if doc: ci.document = doc
    ci.save()

    # (optional) push a notification to tenant devices
    try:
        _send_push_to_tenant(person.tenant, {
            "title": "New check-in",
            "body": f"{person.full_name} via {method.replace('_',' ')}",
            "url": f"/tab/main/{person.pk}/"
        })
    except Exception:
        pass

    return render(request, "people/self_checkin_success.html", {"person": person, "ok": True})

@csrf_exempt
@require_http_methods(["POST"])
def push_subscribe_defendant(request, token: str):
    try:
        payload = SIGNER.unsign(token, max_age=7*24*3600)  # 7 days
        tenant_id_str, person_id_str = payload.split(":")
        tenant_id = int(tenant_id_str); person_id = int(person_id_str)
    except (BadSignature, SignatureExpired, ValueError):
        return HttpResponseBadRequest("Invalid token")

    person = get_object_or_404(Person, pk=person_id, tenant_id=tenant_id)

    try:
        data = json.loads(request.body.decode("utf-8"))
        sub = data.get("subscription") or {}
        endpoint = sub.get("endpoint")
        keys = sub.get("keys") or {}
        if not endpoint or "p256dh" not in keys or "auth" not in keys:
            return HttpResponseBadRequest("Invalid subscription")

        PushSubscription.objects.update_or_create(
            endpoint=endpoint,
            defaults={
                "tenant_id": tenant_id,
                "person": person,
                "user": None,
                "p256dh": keys["p256dh"],
                "auth": keys["auth"],
            },
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return HttpResponseBadRequest(str(e))

# views_people.py or a utils module
def send_push_to_person(person, payload: dict):
    from .models import PushSubscription
    subs = list(PushSubscription.objects.filter(person=person))
    sent = 0; errors = []
    for s in subs:
        try:
            webpush(
                subscription_info={"endpoint": s.endpoint, "keys": {"p256dh": s.p256dh, "auth": s.auth}},
                data=json.dumps(payload),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": settings.VAPID_CLAIM_EMAIL},
            )
            sent += 1
        except WebPushException as e:
            errors.append(str(e))
            s.delete()  # clean dead endpoints
    return {"sent": sent, "failed": len(errors), "errors": errors}

def _abs_url(path, request=None):
    # If you're currently on an ngrok host, use it dynamically
    if request:
        host = request.get_host()
        if host.endswith(".ngrok-free.app"):
            scheme = "https"  # ngrok is https
            return f"{scheme}://{host}{path}"

    # Otherwise fall back to configured base (prod/staging) or request
    base = getattr(settings, "PUBLIC_BASE_URL", "")
    if isinstance(base, (list, tuple)):
        base = base[0] if base else ""
    base = (base or "").rstrip("/")
    return base + path if base else (request.build_absolute_uri(path) if request else path)

def _make_self_link(request, person):
    token = SIGNER.sign(f"{person.tenant_id}:{person.pk}")
    path = reverse("self_checkin", args=[token])
    return _abs_url(path, request)

@login_required
@require_http_methods(["POST"])
def push_test_person(request, person_pk: int):
    person = get_object_or_404(Person, pk=person_pk)
    res = send_push_to_person(person, {
        "title": request.POST.get("title") or "Test notification",
        "body":  request.POST.get("body")  or f"Hello {person.full_name or 'there'}!",
        "url":   request.POST.get("url")   or f"/tab/main/{person.pk}/",
    })
    return JsonResponse(res)


from django.views.decorators.http import require_GET
@require_GET
def service_worker(request):
    js = r"""
const CACHE = "bailsaas-v1";
self.addEventListener("install", (e) => { self.skipWaiting(); });
self.addEventListener("activate", (e) => { e.waitUntil(self.clients.claim()); });

self.addEventListener("push", (e) => {
  let data = {};
  try { data = e.data.json(); } catch(_) {}
  const title = data.title || "BailSaaS";
  const body  = data.body  || "";
  const url   = data.url   || "/";
  e.waitUntil(self.registration.showNotification(title, {
    body, data: { url }, icon: "/static/icons/icon-192.png", badge: "/static/icons/icon-192.png"
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = e.notification.data?.url || "/";
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then(list => {
    for (const c of list) { if ("focus" in c) return c.focus(); }
    return clients.openWindow(url);
  }));
});
"""
    resp = HttpResponse(js, content_type="application/javascript; charset=UTF-8")
    # Prevent caching old workers while you iterate
    resp["Cache-Control"] = "no-store"
    return resp

@login_required
def push_debug_person(request, person_pk: int):
    p = Person.objects.get(pk=person_pk)
    subs = list(PushSubscription.objects.filter(person=p).values("endpoint","created_at"))
    return JsonResponse({"count": len(subs), "subs": subs})
