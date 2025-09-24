
from django.urls import path, include
from . import views_people as views
from .views_health import health_ok

urlpatterns = [
    path('', views.people_home, name='people_home'),
    path("people/<int:pk>/panel/", views.person_panel, name="person_panel"),
    path('tab/list/', views.people_tab_list, name='people_tab_list'),
    path('accounts/', include('django.contrib.auth.urls')),  # provides /accounts/login/
    path('tab/main/<int:pk>/', views.person_main_panel, name='people_tab_main'),
    path('new/partial/', views.person_new_partial, name='person_new_partial'),
    path('edit/<int:pk>/', views.person_edit_partial, name='person_edit_partial'),
    path('save/<int:pk>/', views.person_save_partial, name='person_save_partial'),
    path("inline/<int:pk>/field/<str:field>/save/",    views.person_field_save,    name="person_field_save_inline"),
    path("people/<int:pk>/delete/", views.person_delete, name="person_delete"),
    path('indemnitors/new/<int:person_pk>/', views.indemnitor_new_partial, name='indemnitor_new_partial'),
    path('references/new/<int:person_pk>/', views.reference_new_partial, name='reference_new_partial'),
    path('indemnitors/<int:pk>/edit/', views.indemnitor_edit_partial, name='indemnitor_edit_partial'),
    path('references/<int:pk>/edit/', views.reference_edit_partial, name='reference_edit_partial'),
    path("people/<int:pk>/field/<str:field>/edit/", views.person_field_edit, name="person_field_edit"),
    path("people/<int:pk>/field/<str:field>/save/", views.person_field_save, name="person_field_save"),
    path("people/<int:pk>/field/<str:field>/display/", views.person_field_display, name="person_field_display"),
# Indemnitors
    path("people/<int:person_pk>/indemnitors/new/partial/", views.indemnitor_new_partial, name="indemnitor_new_partial"),
    path("indemnitors/<int:pk>/edit/partial/", views.indemnitor_edit_partial, name="indemnitor_edit_partial"),
    path("people/indemnitors/<int:pk>/delete/", views.indemnitor_delete, name="indemnitor_delete"),
    path("people/references/<int:pk>/delete/",  views.reference_delete,  name="reference_delete"),
    # References
    path("people/<int:person_pk>/references/new/partial/", views.reference_new_partial, name="reference_new_partial"),
    path("references/<int:pk>/edit/partial/", views.reference_edit_partial, name="reference_edit_partial"),
    # Court Dates
    path("people/<int:person_pk>/court-dates/new/partial/", views.court_date_new_partial, name="court_date_new_partial"),
    path("court-dates/<int:pk>/edit/partial/",            views.court_date_edit_partial, name="court_date_edit_partial"),
    path("people/court-dates/<int:pk>/delete/",            views.court_date_delete,       name="court_date_delete"),
    path("people/<int:person_pk>/court-dates/recent/partial/", views.court_date_recent_widget, name="court_date_recent_widget"),
    # Bonds
    path("people/<int:person_pk>/bonds/new/partial/", views.bond_new_partial, name="bond_new_partial"),
    path("bonds/<int:pk>/edit/partial/", views.bond_edit_partial, name="bond_edit_partial"),
    path("people/bonds/<int:pk>/delete/", views.bond_delete, name="bond_delete"),
    path("people/<int:person_pk>/checkins/new/partial/", views.checkin_new_partial, name="checkin_new_partial"),
    path("checkins/<int:pk>/edit/partial/",              views.checkin_edit_partial, name="checkin_edit_partial"),
    path("people/checkins/<int:pk>/delete/",             views.checkin_delete,       name="checkin_delete"),
    path("people/<int:person_pk>/checkins/last/partial/",views.checkin_last_widget,name="checkin_last_widget",),
    # Invoices
    path("people/<int:person_pk>/invoices/new/partial/", views.invoice_new_partial, name="invoice_new_partial"),
    path("invoices/<int:pk>/edit/partial/",              views.invoice_edit_partial, name="invoice_edit_partial"),
    path("people/invoices/<int:pk>/delete/",             views.invoice_delete,       name="invoice_delete"),
    path("people/<int:person_pk>/invoices/section/partial/",views.invoices_section_partial,name="invoices_section_partial",),

    # Receipts
    path("invoices/<int:invoice_pk>/receipts/new/partial/", views.receipt_new_partial, name="receipt_new_partial"),
    path("receipts/<int:pk>/edit/partial/",                 views.receipt_edit_partial, name="receipt_edit_partial"),
    path("people/receipts/<int:pk>/delete/",                views.receipt_delete,       name="receipt_delete"),
    path("people/<int:person_pk>/receipts/new/partial/",    views.receipt_new_for_person_partial, name="receipt_new_for_person_partial"),
    path("people/<int:person_pk>/billing/summary/partial/",views.billing_summary_widget,name="billing_summary_widget",),
    # Payment plans
    path("people/<int:person_pk>/plans/section/partial/", views.payment_plan_section_partial, name="payment_plan_section_partial"),
    path("people/<int:person_pk>/plans/new/partial/", views.payment_plan_new_partial, name="payment_plan_new_partial"),
    path("plans/<int:pk>/cancel/", views.payment_plan_cancel, name="payment_plan_cancel"),
    path("installments/<int:pk>/mark-paid/", views.installment_mark_paid, name="installment_mark_paid"),

    # Calendar
    path("calendar/", views.court_calendar, name="court_calendar"),
    # Court Calendar tab (per person) + ICS
    path("people/<int:person_pk>/calendar/partial/", views.person_calendar_partial, name="person_calendar_partial"),
    # Global Calendar (all people)
    path("calendar/partial/", views.calendar_partial, name="calendar_partial"),

    # Court date printable notice
    path("court-dates/<int:pk>/notice/", views.court_date_notice, name="court_date_notice"),

    # Receipt printable
    path("receipts/<int:pk>/print/", views.receipt_print, name="receipt_print"),

    path("people/import/", views.person_import, name="people_import"),

    # Reports menu + endpoints
    path("reports/panel/", views.reports_panel, name="reports_panel"),
    path("reports/bonds-by-date/", views.report_bonds_by_date, name="report_bonds_by_date"),
    path("reports/people-with-balance/", views.report_people_with_balance, name="report_people_with_balance"),
    path("reports/bonds-by-county/", views.report_bonds_by_county, name="report_bonds_by_county"),

    # (Optional but useful extras)
    path("reports/upcoming-court-dates/", views.report_upcoming_court_dates, name="report_upcoming_court_dates"),
    path("reports/missed-checkins/",views.report_people_without_recent_checkin,name="report_missed_checkins",),

    path("reports/no-recent-checkin/", views.report_people_without_recent_checkin, name="report_people_without_recent_checkin"),
    path("reports/overdue-invoices/", views.report_overdue_invoices, name="report_overdue_invoices"),

    # core/urls.py (add)
    path("push/vapid.json", views.vapid_public, name="vapid_public"),
    path("push/subscribe/", views.push_subscribe, name="push_subscribe"),
    path("push/unsubscribe/", views.push_unsubscribe, name="push_unsubscribe"),
    path("push/test/", views.push_test, name="push_test"),  # optional

    # core/urls.py
    path("checkin/self/<str:token>/", views.self_checkin, name="self_checkin"),
    path("people/<int:person_pk>/checkin/selflink/", views.person_selfcheck_link, name="person_selfcheck_link"),
    # urls.py
    path("push/def/<str:token>/subscribe/", views.push_subscribe_defendant, name="push_subscribe_def"),
    # staff trigger to a specific person
    path("push/test/person/<int:person_pk>/", views.push_test_person, name="push_test_person"),
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("push/debug/person/<int:person_pk>/", views.push_debug_person, name="push_debug_person"),
    path("kaithhealthcheck", health_ok, name="health_ok"),
    path("kaithheathcheck", health_ok),  # handle their typo too

]
