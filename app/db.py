import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.schemas import ItemClassificationBatch, ReceiptExtraction


BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "receipt_scanner.db"


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _to_cents(value: float | None) -> int | None:
    if value is None:
        return None

    return round(value * 100)


def _from_cents(value: int | None) -> float | None:
    if value is None:
        return None

    return value / 100


def init_db() -> None:
    DB_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with _connect() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id TEXT PRIMARY KEY,
                merchant TEXT,
                store_location TEXT,
                purchase_date TEXT,
                currency TEXT NOT NULL,
                subtotal_cents INTEGER,
                tax_cents INTEGER,
                tip_cents INTEGER,
                total_cents INTEGER,
                image_filename TEXT NOT NULL,
                warnings_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );


            CREATE TABLE IF NOT EXISTS receipt_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                receipt_id TEXT NOT NULL,
                position INTEGER NOT NULL,

                name TEXT NOT NULL,
                sku TEXT,

                quantity REAL,
                unit_price_cents INTEGER,
                line_total_cents INTEGER,

                category TEXT,
                subcategory TEXT,

                classification_status TEXT
                    CHECK (
                        classification_status IS NULL
                        OR classification_status IN (
                            'MATCHED',
                            'NEEDS_NEW_TAXONOMY'
                        )
                    ),

                classification_confidence REAL
                    CHECK (
                        classification_confidence IS NULL
                        OR (
                            classification_confidence >= 0
                            AND classification_confidence <= 1
                        )
                    ),

                taxonomy_version INTEGER,

                FOREIGN KEY (receipt_id)
                    REFERENCES receipts(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS discounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                receipt_id TEXT NOT NULL,

                description TEXT,
                amount_cents INTEGER NOT NULL,
                associated_item_name TEXT,

                FOREIGN KEY (receipt_id)
                    REFERENCES receipts(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS fees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                receipt_id TEXT NOT NULL,

                description TEXT NOT NULL,
                amount_cents INTEGER NOT NULL,

                FOREIGN KEY (receipt_id)
                    REFERENCES receipts(id)
                    ON DELETE CASCADE
            );


            CREATE TABLE IF NOT EXISTS taxonomy_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                receipt_item_id INTEGER NOT NULL,

                proposed_category TEXT NOT NULL,
                proposed_subcategory TEXT NOT NULL,

                status TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (
                        status IN (
                            'PENDING',
                            'APPROVED',
                            'REJECTED'
                        )
                    ),

                created_at TEXT NOT NULL,

                FOREIGN KEY (receipt_item_id)
                    REFERENCES receipt_items(id)
                    ON DELETE CASCADE
            );
            """
        )


def insert_receipt(
    receipt_id: str,
    image_filename: str,
    receipt: ReceiptExtraction,
    classifications: ItemClassificationBatch,
    taxonomy_version: int,
    warnings: list[str],
) -> None:

    classification_by_index = {
        classification.item_index: classification
        for classification in classifications.classifications
    }

    expected_indexes = set(
        range(len(receipt.items))
    )

    actual_indexes = set(
        classification_by_index.keys()
    )

    if actual_indexes != expected_indexes:
        raise ValueError(
            "Classifier did not return exactly one "
            "classification for every receipt item."
        )

    with _connect() as connection:

        # ---------------------------------
        # Save the receipt itself
        # ---------------------------------

        connection.execute(
            """
            INSERT INTO receipts (
                id,
                merchant,
                store_location,
                purchase_date,
                currency,
                subtotal_cents,
                tax_cents,
                tip_cents,
                total_cents,
                image_filename,
                warnings_json,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_id,
                receipt.merchant,
                receipt.store_location,
                (
                    receipt.purchase_date.isoformat()
                    if receipt.purchase_date
                    else None
                ),
                receipt.currency,
                _to_cents(receipt.subtotal),
                _to_cents(receipt.tax),
                _to_cents(receipt.tip),
                _to_cents(receipt.total),
                image_filename,
                json.dumps(warnings),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

        # ---------------------------------
        # Save every receipt item
        # ---------------------------------

        for position, item in enumerate(
            receipt.items
        ):

            classification = (
                classification_by_index[position]
            )

            cursor = connection.execute(
                """
                INSERT INTO receipt_items (
                    receipt_id,
                    position,
                    name,
                    sku,
                    quantity,
                    unit_price_cents,
                    line_total_cents,

                    category,
                    subcategory,
                    classification_status,
                    classification_confidence,
                    taxonomy_version
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    receipt_id,
                    position,
                    item.name,
                    item.sku,
                    item.quantity,
                    _to_cents(item.unit_price),
                    _to_cents(item.line_total),

                    classification.category,
                    classification.subcategory,
                    classification.status,
                    classification.confidence,
                    taxonomy_version,
                ),
            )

            receipt_item_id = cursor.lastrowid

            # ---------------------------------
            # Unknown taxonomy item?
            # Save a pending suggestion.
            # ---------------------------------

            if (
                classification.status
                == "NEEDS_NEW_TAXONOMY"
            ):

                if (
                    not classification.proposed_category
                    or not classification.proposed_subcategory
                ):
                    raise ValueError(
                        "A NEEDS_NEW_TAXONOMY item "
                        "must provide a proposed category "
                        "and subcategory."
                    )

                connection.execute(
                    """
                    INSERT INTO taxonomy_suggestions (
                        receipt_item_id,
                        proposed_category,
                        proposed_subcategory,
                        status,
                        created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_item_id,
                        classification.proposed_category,
                        classification.proposed_subcategory,
                        "PENDING",
                        datetime.now(
                            timezone.utc
                        ).isoformat(),
                    ),
                )

        # ---------------------------------
        # Discounts
        # ---------------------------------

        for discount in receipt.discounts:

            connection.execute(
                """
                INSERT INTO discounts (
                    receipt_id,
                    description,
                    amount_cents,
                    associated_item_name
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    discount.description,
                    _to_cents(discount.amount),
                    discount.associated_item_name,
                ),
            )

        # ---------------------------------
        # Fees
        # ---------------------------------

        for fee in receipt.fees:

            connection.execute(
                """
                INSERT INTO fees (
                    receipt_id,
                    description,
                    amount_cents
                )
                VALUES (?, ?, ?)
                """,
                (
                    receipt_id,
                    fee.description,
                    _to_cents(fee.amount),
                ),
            )


def list_receipts(limit: int = 25) -> list[dict]:
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT
                id,
                merchant,
                purchase_date,
                currency,
                total_cents,
                image_filename,
                warnings_json,
                created_at
            FROM receipts
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "id": row["id"],
            "merchant": row["merchant"],
            "purchase_date": row["purchase_date"],
            "currency": row["currency"],
            "total": _from_cents(row["total_cents"]),
            "image_url": f"/receipts/{row['image_filename']}",
            "warnings": json.loads(row["warnings_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def get_receipt(receipt_id: str) -> dict | None:
    with _connect() as connection:
        receipt = connection.execute(
            """
            SELECT *
            FROM receipts
            WHERE id = ?
            """,
            (receipt_id,),
        ).fetchone()

        if receipt is None:
            return None

        items = connection.execute(
            """
            SELECT *
            FROM receipt_items
            WHERE receipt_id = ?
            ORDER BY position
            """,
            (receipt_id,),
        ).fetchall()

        discounts = connection.execute(
            """
            SELECT *
            FROM discounts
            WHERE receipt_id = ?
            ORDER BY id
            """,
            (receipt_id,),
        ).fetchall()

        fees = connection.execute(
            """
            SELECT *
            FROM fees
            WHERE receipt_id = ?
            ORDER BY id
            """,
            (receipt_id,),
        ).fetchall()

    return {
        "id": receipt["id"],
        "merchant": receipt["merchant"],
        "store_location": receipt["store_location"],
        "purchase_date": receipt["purchase_date"],
        "currency": receipt["currency"],
        "subtotal": _from_cents(receipt["subtotal_cents"]),
        "tax": _from_cents(receipt["tax_cents"]),
        "tip": _from_cents(receipt["tip_cents"]),
        "total": _from_cents(receipt["total_cents"]),
        "image_url": f"/receipts/{receipt['image_filename']}",
        "warnings": json.loads(receipt["warnings_json"]),
        "items": [
            {
                "id": row["id"],

                "name": row["name"],
                "sku": row["sku"],

                "quantity": row["quantity"],

                "unit_price": _from_cents(
                    row["unit_price_cents"]
                ),

                "line_total": _from_cents(
                    row["line_total_cents"]
                ),

                "category": row["category"],
                "subcategory": row["subcategory"],

                "classification_status": (
                    row["classification_status"]
                ),

                "classification_confidence": (
                    row["classification_confidence"]
                ),

                "taxonomy_version": (
                    row["taxonomy_version"]
                ),
            }
            for row in items
        ],
        "discounts": [
            {
                "description": row["description"],
                "amount": _from_cents(row["amount_cents"]),
                "associated_item_name": row[
                    "associated_item_name"
                ],
            }
            for row in discounts
        ],
        "fees": [
            {
                "description": row["description"],
                "amount": _from_cents(row["amount_cents"]),
            }
            for row in fees
        ],
    }