# Settings Page Plan

## Overview

Add a Settings page for company information, logo, contact details, and default payment terms. Support per-customer net terms override, and auto-fill invoice due date from terms when creating invoices.

## 1. Company Settings Model

**New model:** `CompanySettings` (singleton pattern - one row)

| Field | Type | Description |
|-------|------|-------------|
| company_name | CharField(255) | Company display name |
| tagline | CharField(255, blank) | e.g. "Professional electrical solutions" |
| logo | ImageField(blank, null) | Company logo (stored in media/) |
| email | EmailField(blank) | Company email |
| phone | CharField(50, blank) | Company phone |
| address | TextField(blank) | Company address (multi-line) |
| default_net_terms | CharField(20) | NET_10, NET_30, DUE_ON_RECEIPT, CUSTOM |
| default_net_days | PositiveIntegerField(0) | Days when CUSTOM (e.g. 15) |

**Net terms mapping:**
- `NET_10` → due_date = invoice_date + 10 days
- `NET_30` → due_date = invoice_date + 30 days
- `DUE_ON_RECEIPT` → due_date = invoice_date (same day)
- `CUSTOM` → due_date = invoice_date + default_net_days

**Helper:** `get_due_date(invoice_date)` → returns computed due_date

## 2. Customer Model Changes

**Add to Customer:**
- `net_terms` — CharField(20, blank=True, null=True) — null = use default from settings
- `net_days` — PositiveIntegerField(0, blank=True) — used when net_terms=CUSTOM

Choices: NET_10, NET_30, DUE_ON_RECEIPT, CUSTOM (same as settings)

**Helper:** `get_effective_net_days()` — returns days from customer override or from CompanySettings default

## 3. Settings Page

**URL:** `/invoicing/settings/` or `/settings/` (config decision)

**Sections:**
1. **Company Information** — name, tagline, logo, email, phone, address
2. **Payment Terms** — default dropdown (Net 10, Net 30, Due on Receipt, Custom) + custom days input when Custom

**View:** GET renders form; POST saves. Use get_or_create for singleton.

## 4. Invoice Create Flow

**Current behavior:** `due_date` initial = today (same as date)

**New behavior:**
- When creating new invoice (GET): `due_date` = compute from CompanySettings default + `date` (today)
- Optional: add "Select Customer" dropdown — when customer selected (via JS or AJAX), pre-fill contact fields AND recompute `due_date` from customer's net terms
- User can still override due_date manually

**Implementation:** In `invoice_create` view, replace `initial={"due_date": today}` with `due_date = CompanySettings.get_due_date(today)`.

For customer selection: Add optional `?customer=<pk>` or customer dropdown. When customer selected, use `customer.get_effective_net_days()` for due_date.

## 5. Customer Form

**Add to CustomerForm:** net_terms (dropdown), net_days (number, shown when Custom). Add to customer_form.html.

## 6. Template Usage

**Invoice print, base templates:** Replace hardcoded "Manchester Electric" and "Professional electrical solutions" with `{{ company_settings.company_name }}` and `{{ company_settings.tagline }}`. Logo in header if present.

**Context processor:** Add CompanySettings to request context so templates can use it, or pass explicitly where needed.

## 7. Files to Create/Modify

| File | Action |
|------|--------|
| invoicing/models.py | Add CompanySettings; add net_terms, net_days to Customer |
| invoicing/migrations/0004_*.py | Migration for new model and fields |
| invoicing/forms.py | Add CompanySettingsForm; add net_terms, net_days to CustomerForm |
| invoicing/views.py | Add settings_view (GET/POST); update invoice_create for due_date; pass settings to invoice_print |
| invoicing/urls.py | Add settings URL |
| templates/invoicing/settings.html | New settings page template |
| templates/invoicing/customer_form.html | Add net terms section |
| templates/invoicing/invoice_print.html | Use company_settings (context) |
| templates/base.html | Add Settings link to nav |
| config/settings.py | Ensure MEDIA_URL/MEDIA_ROOT (already present) |

## 8. Due Date Logic Summary

```python
def compute_due_date(invoice_date, customer=None):
    if customer and customer.net_terms:
        days = customer.get_effective_net_days()  # from customer or settings
    else:
        days = CompanySettings.get_default_net_days()
    return invoice_date + timedelta(days=days)
```

## 9. Tests

- CompanySettings: create, get_due_date for each term type
- Customer: net_terms override, get_effective_net_days
- Settings view: GET renders, POST saves
- Invoice create: due_date initial from default terms
- Invoice create with ?customer=pk: due_date from customer terms
- Customer form: net_terms, net_days save
- Invoice print: uses company name from settings (when set)

## 10. Baseline

73 tests pass before implementation.
