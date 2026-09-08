from app.schemas import ReceiptExtraction


TOLERANCE = 0.05


def build_warnings(receipt: ReceiptExtraction) -> list[str]:
    warnings: list[str] = []

    if not receipt.items:
        warnings.append(
            "No receipt items were detected."
        )

    # Check subtotal + taxes + fees + tip against total.
    if receipt.subtotal is not None and receipt.total is not None:
        calculated_total = receipt.subtotal

        if receipt.tax is not None:
            calculated_total += receipt.tax

        if receipt.tip is not None:
            calculated_total += receipt.tip

        calculated_total += sum(
            fee.amount for fee in receipt.fees
        )

        if abs(calculated_total - receipt.total) > TOLERANCE:
            warnings.append(
                "Subtotal, tax, fees, and tip do not reconcile "
                "with the extracted total."
            )

    # Check item lines against subtotal when all line totals are available.
    if (
        receipt.items
        and receipt.subtotal is not None
        and all(item.line_total is not None for item in receipt.items)
    ):
        item_total = sum(
            item.line_total
            for item in receipt.items
            if item.line_total is not None
        )

        discounts = sum(
            discount.amount
            for discount in receipt.discounts
        )

        expected_subtotal = item_total - discounts

        if abs(expected_subtotal - receipt.subtotal) > TOLERANCE:
            warnings.append(
                "Extracted item lines do not reconcile with the subtotal. "
                "Review the receipt manually."
            )

    return warnings