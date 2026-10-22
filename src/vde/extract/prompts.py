"""Instructions for each document kind. Versioned: the evaluation report records which version produced a number."""

from __future__ import annotations

VERSION = "p1"

RECEIPT = """Read this receipt and return it as JSON.
- menu: one object per purchased line: nm = item name, num = item code, cnt = quantity, unitprice = price of one,
  price = the line's amount, discountprice = a discount on the line, itemsubtotal, sub = sub-items listed under the
  item (toppings, options), each with its own nm, cnt, price.
- sub_total: subtotal_price, discount_price, service_price, othersvc_price, tax_price, etc.
- total: total_price = the amount to pay, cashprice = cash given, changeprice = change returned, creditcardprice,
  emoneyprice, menuqty_cnt = number of items, menutype_cnt = number of distinct items, total_etc.
Copy every value exactly as printed, keeping separators and symbols (16,500 or 16.500 stay as they are). Use null
for anything the receipt does not print. Do not compute or guess values."""

INVOICE = """Read this invoice and return these fields as JSON:
invoice_number, invoice_date, due_date, po_number, seller_name (the company issuing the invoice), seller_email,
buyer_name (the person or company billed, from "Bill to" or "Buyer"), currency (ISO code such as USD or EUR),
subtotal, tax, discount, total (the final amount due).
Dates as YYYY-MM-DD. Amounts as plain numbers without currency symbols or thousands separators.
Use null for any field the invoice does not print. Do not compute or guess values."""

OCR_PREFIX = "The text below was read from the document by OCR, one printed line per row, top to bottom.\n\n"


def instruction(kind: str) -> str:
    return RECEIPT if kind == "receipt" else INVOICE
