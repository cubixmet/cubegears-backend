"""Read-only Job Card to invoice *suggestions*, never a financial posting.

Values originate from actual recorded job charges. Do not conflate purchase
costs, payroll, pending supplier quotes, or an approved estimate with income.
These lines are intentionally not linked as new invoice stock issues: a job
issue has already decremented inventory and a later invoice must not do it again.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from apps.jobs.models import OutsideLabourCharge

CENT = Decimal("0.01")


def amount(value):
    try:
        result = Decimal(str(value if value is not None else ""))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() and result >= 0 else None


def suggested_job_invoice(job):
    registered = bool(str(job.company.gstin or "").strip())
    items, notices = [], []
    seen_stock = set()

    def append(kind, key, description, quantity, rate, hsn="", tax=None, unit="PCS"):
        qty, price = amount(quantity), amount(rate)
        if not description or qty is None or price is None or qty <= 0:
            notices.append(f"{kind} {key}: check its recorded selling quantity and rate.")
            return
        # Item totals use the invoice engine; this is a read-only draft.
        items.append({
            "id": f"job-{kind}-{key}", "type": kind,
            "description": str(description).strip()[:250],
            "qty": str(qty), "rate": str(price.quantize(CENT, rounding=ROUND_HALF_UP)),
            "unit": unit or "PCS", "hsnCode": str(hsn or "").strip()[:30],
            "taxRate": str(tax) if registered and tax is not None and amount(tax) is not None
                and amount(tax) > 0 else ("" if registered else "0"),
            "discount": "0", "inventoryId": "",
        })

    def item_rate(item):
        return getattr(item, "tax", None), getattr(item, "hsn_code", "") or ""

    # JobPart captures confirmed issued quantities and customer selling rates.
    for part in job.parts.filter(issued=True).select_related("item").order_by("created_at"):
        stock = part.item
        if stock.company_id != job.company_id:
            continue
        seen_stock.add(str(stock.pk))
        tax, hsn = item_rate(stock)
        append("Stock Part", str(part.pk), stock.name, part.quantity,
               part.unit_price, hsn, tax, stock.unit)

    # The other supported issue path stores signed issue/return events in
    # parts_workflow JSON and StockMovement, but not a JobPart row.
    workflow = job.parts_workflow or {}
    for row in workflow.get("lines") or []:
        if not isinstance(row, dict) or not row.get("partId"):
            continue
        if str(row["partId"]) in seen_stock:
            # Never bill a single stock item again through both issue paths.
            continue
        qty = sum((amount(x.get("qty")) or Decimal("0")
                   for x in row.get("issues", []) if isinstance(x, dict)), Decimal("0"))
        qty -= sum((amount(x.get("qty")) or Decimal("0")
                    for x in row.get("returns", []) if isinstance(x, dict)), Decimal("0"))
        if qty <= 0:
            continue
        from apps.inventory.models import StockItem
        stock = StockItem.objects.filter(company=job.company, pk=row["partId"]).first()
        if stock is None:
            notices.append("A recorded stock issue no longer matches an inventory item.")
            continue
        tax, hsn = item_rate(stock)
        append("Stock Part", str(row.get("id") or stock.pk),
               row.get("partName") or stock.name, qty, row.get("sellingPrice"),
               hsn, tax, stock.unit)

    for row in workflow.get("outsideParts") or []:
        if not isinstance(row, dict) or row.get("status", "Purchased") != "Purchased":
            continue
        if row.get("billable") is False:
            continue
        selling = amount(row.get("sellingPrice"))
        if selling is None or selling <= 0:
            notices.append("Outside purchase needs an explicitly recorded customer selling rate before billing.")
            continue
        append("Outside Purchase", str(row.get("id") or len(items)),
               row.get("partName") or row.get("name"), row.get("quantity"),
               selling, row.get("hsnCode") or row.get("hsnSac"), row.get("taxRate"))

    for labour in OutsideLabourCharge.objects.filter(
        company=job.company, job=job
    ).order_by("created_at"):
        if labour.customer_charge <= 0:
            continue
        append("Labour", str(labour.pk), labour.work_description or "Outside service",
               1, labour.customer_charge)

    for row in job.work or []:
        if not isinstance(row, dict):
            continue
        # Explicit customer-billable records only. Never import mechanic wages.
        if row.get("billable") is not True:
            continue
        append("Labour", str(row.get("id") or len(items)),
               row.get("service") or row.get("description"),
               row.get("quantity") or 1,
               row.get("customerRate") or row.get("unitPrice") or row.get("customerCharge"),
               row.get("hsnSac"), row.get("taxRate"), row.get("unit") or "Job")

    if not items:
        notices.append("No verified billable Job Card items. Add customer charges manually; no invoice was created.")

    vehicle = job.vehicle
    customer = job.customer
    return {
        "jobId": str(job.pk), "jobNumber": job.job_number,
        "customer": {
            "name": customer.name, "phone": customer.phone or "",
            "address": customer.address or "", "gstin": customer.gstin or "",
            "state": customer.state or "",
        },
        "vehicle": {
            "registration": vehicle.registration,
            "makeModel": " ".join(filter(None, [vehicle.make, vehicle.model])),
            "vin": vehicle.vin or "", "odometer": str(job.odometer or ""),
        },
        "items": items, "warnings": notices,
        "stockAlreadyIssued": True, "created": False, "finalized": False,
    }
