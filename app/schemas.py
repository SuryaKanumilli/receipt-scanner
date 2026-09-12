from datetime import date
from typing import Literal
from pydantic import BaseModel, Field


class ReceiptItem(BaseModel):
    name: str = Field(
        description="Item description as printed on the receipt."
    )
    sku: str | None = Field(
        default=None,
        description="SKU, item number, UPC, or product code if explicitly visible."
    )
    quantity: float | None = Field(
        default=None,
        description="Quantity purchased if visible or clearly inferable."
    )
    unit_price: float | None = Field(
        default=None,
        description="Price for one unit before line-level discounts."
    )
    line_total: float | None = Field(
        default=None,
        description="Total amount charged for this line."
    )


class Discount(BaseModel):
    description: str | None = None

    amount: float = Field(
        description="Positive magnitude of the discount. Example: 3.00 for a $3 discount."
    )

    associated_item_name: str | None = Field(
        default=None,
        description="Item this discount belongs to, if clearly identifiable."
    )


class Fee(BaseModel):
    description: str
    amount: float


class ReceiptExtraction(BaseModel):
    merchant: str | None = None
    store_location: str | None = None

    purchase_date: date | None = Field(
        default=None,
        description="Purchase date in YYYY-MM-DD format."
    )

    currency: str = Field(
        default="USD",
        description="ISO currency code such as USD."
    )

    items: list[ReceiptItem] = Field(default_factory=list)
    discounts: list[Discount] = Field(default_factory=list)
    fees: list[Fee] = Field(default_factory=list)

    subtotal: float | None = None
    tax: float | None = None
    tip: float | None = None
    total: float | None = None


class ItemClassification(BaseModel):
    item_index: int

    category: str | None = None
    subcategory: str | None = None

    status: Literal[
        "MATCHED",
        "NEEDS_NEW_TAXONOMY"
    ]

    confidence: float = Field(
        ge=0,
        le=1,
    )

    proposed_category: str | None = None
    proposed_subcategory: str | None = None


class ItemClassificationBatch(BaseModel):
    classifications: list[ItemClassification]