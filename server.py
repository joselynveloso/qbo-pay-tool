#!/usr/bin/env python3
"""
QBO MCP Server — Mark invoices as paid, look up invoices, list open invoices.

Run with: python server.py
Or configure in Claude Code's MCP settings.
"""

import os
import sys
from datetime import date

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from quickbooks import QuickBooks
from quickbooks.objects.invoice import Invoice
from quickbooks.objects.payment import Payment, PaymentLine
from quickbooks.objects.base import LinkedTxn, Ref
from quickbooks.objects.paymentmethod import PaymentMethod
from quickbooks.objects.account import Account

from qbo_auth import get_tokens

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

mcp = FastMCP("qbo")

PAYMENT_METHODS = {
    "check": "Check",
    "ach": "ACH",
    "wire": "ACH",
    "credit_card": "Credit Card",
    "cc": "Credit Card",
    "cash": "Cash",
    "other": "Other",
}


def get_qb_client():
    auth_client = get_tokens()
    return QuickBooks(
        auth_client=auth_client,
        refresh_token=os.getenv("QBO_REFRESH_TOKEN"),
        company_id=os.getenv("QBO_REALM_ID"),
    )


def _find_payment_method_ref(client, method_name):
    methods = PaymentMethod.all(qb=client)
    target = PAYMENT_METHODS.get(method_name.lower(), method_name)
    for m in methods:
        if m.Name.lower() == target.lower():
            return Ref(value=m.Id, name=m.Name)
    available = [m.Name for m in methods]
    return None, available


def _find_deposit_account(client):
    accounts = Account.filter(Name="Undeposited Funds", qb=client)
    if accounts:
        return Ref(value=accounts[0].Id, name=accounts[0].Name)
    return None


@mcp.tool()
def mark_invoice_paid(
    invoice_number: str,
    amount: float,
    payment_method: str,
    reference_number: str = "",
    payment_date: str = "",
    memo: str = "",
) -> str:
    """Mark a QuickBooks Online invoice as paid by recording a payment.

    Args:
        invoice_number: The invoice number (DocNumber) as shown in QBO.
        amount: Payment amount in dollars.
        payment_method: How the customer paid — check, ach, wire, credit_card, cc, cash, or other.
        reference_number: Optional check number, ACH transaction ID, or other reference.
        payment_date: Optional payment date as YYYY-MM-DD. Defaults to today.
        memo: Optional private memo/note on the payment.
    """
    client = get_qb_client()

    # Find the invoice
    invoices = Invoice.filter(DocNumber=invoice_number, qb=client)
    if not invoices:
        return f"Invoice #{invoice_number} not found in QuickBooks."

    invoice = invoices[0]
    invoice_balance = float(invoice.Balance)
    customer_name = invoice.CustomerRef.name

    if invoice_balance <= 0:
        return f"Invoice #{invoice_number} ({customer_name}) is already fully paid."

    if abs(amount - invoice_balance) > 0.01:
        return (
            f"Warning: Invoice #{invoice_number} ({customer_name}) has a balance of "
            f"${invoice_balance:,.2f} but you specified ${amount:,.2f}. "
            f"Please confirm the correct amount and try again, or if this is intentional, "
            f"let me know and I'll proceed."
        )

    # Build and save payment
    payment = Payment()
    payment.TotalAmt = amount
    payment.CustomerRef = invoice.CustomerRef
    payment.TxnDate = payment_date or date.today().isoformat()

    method_result = _find_payment_method_ref(client, payment_method)
    if isinstance(method_result, tuple):
        _, available = method_result
        method_note = f" (payment method '{payment_method}' not found in QBO, available: {', '.join(available)})"
    else:
        payment.PaymentMethodRef = method_result
        method_note = ""

    if reference_number:
        payment.PaymentRefNum = reference_number

    if memo:
        payment.PrivateNote = memo

    deposit_ref = _find_deposit_account(client)
    if deposit_ref:
        payment.DepositToAccountRef = deposit_ref

    line = PaymentLine()
    line.Amount = amount
    line.LinkedTxn = [LinkedTxn(TxnId=invoice.Id, TxnType="Invoice")]
    payment.Line = [line]

    payment.save(qb=client)

    display_method = PAYMENT_METHODS.get(payment_method.lower(), payment_method)
    parts = [
        f"Payment recorded for Invoice #{invoice_number}:",
        f"  Customer: {customer_name}",
        f"  Amount: ${amount:,.2f}",
        f"  Method: {display_method}",
    ]
    if reference_number:
        parts.append(f"  Reference: {reference_number}")
    parts.append(f"  Date: {payment.TxnDate}")
    parts.append(f"  QBO Payment ID: {payment.Id}")
    if method_note:
        parts.append(method_note)

    return "\n".join(parts)


@mcp.tool()
def lookup_invoice(invoice_number: str) -> str:
    """Look up an invoice in QuickBooks Online by its invoice number.

    Args:
        invoice_number: The invoice number (DocNumber) as shown in QBO.
    """
    client = get_qb_client()
    invoices = Invoice.filter(DocNumber=invoice_number, qb=client)
    if not invoices:
        return f"Invoice #{invoice_number} not found in QuickBooks."

    inv = invoices[0]
    status = "PAID" if float(inv.Balance) <= 0 else "OPEN"
    lines = [
        f"Invoice #{invoice_number}:",
        f"  Customer: {inv.CustomerRef.name}",
        f"  Status: {status}",
        f"  Total: ${float(inv.TotalAmt):,.2f}",
        f"  Balance Due: ${float(inv.Balance):,.2f}",
        f"  Date: {inv.TxnDate}",
    ]
    if inv.DueDate:
        lines.append(f"  Due Date: {inv.DueDate}")
    if inv.EmailStatus:
        lines.append(f"  Email Status: {inv.EmailStatus}")

    return "\n".join(lines)


@mcp.tool()
def list_open_invoices(customer_name: str = "") -> str:
    """List all unpaid/open invoices in QuickBooks Online.

    Args:
        customer_name: Optional — filter to a specific customer name (partial match).
    """
    client = get_qb_client()

    # Query for unpaid invoices
    if customer_name:
        query = (
            f"SELECT * FROM Invoice WHERE Balance > '0' "
            f"AND CustomerRef.name LIKE '%{customer_name}%' "
            f"ORDERBY DueDate"
        )
    else:
        query = "SELECT * FROM Invoice WHERE Balance > '0' ORDERBY DueDate"

    invoices = Invoice.query(query, qb=client)

    if not invoices:
        filter_msg = f" for '{customer_name}'" if customer_name else ""
        return f"No open invoices found{filter_msg}."

    lines = [f"Open invoices ({len(invoices)} total):", ""]
    for inv in invoices:
        overdue = ""
        if inv.DueDate and inv.DueDate < date.today().isoformat():
            overdue = " [OVERDUE]"
        lines.append(
            f"  #{inv.DocNumber}  |  {inv.CustomerRef.name}  |  "
            f"${float(inv.Balance):,.2f}  |  Due: {inv.DueDate or 'N/A'}{overdue}"
        )

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
