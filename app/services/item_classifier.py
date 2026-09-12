import json

from ollama import chat

from app.schemas import (
    ItemClassificationBatch,
    ReceiptExtraction,
)
from app.services.receipt_extractor import MODEL_NAME
from app.services.taxonomy_service import (
    load_taxonomy,
    taxonomy_pair_exists,
)


def classify_items(
    receipt: ReceiptExtraction,
) -> ItemClassificationBatch:

    taxonomy = load_taxonomy()

    items = [
        {
            "item_index": index,
            "name": item.name,
            "sku": item.sku,
            "unit_price": item.unit_price,
            "line_total": item.line_total,
        }
        for index, item in enumerate(receipt.items)
    ]

    prompt = f"""
You classify purchased items into a predefined taxonomy.

Merchant:
{receipt.merchant}

Existing taxonomy:
{json.dumps(taxonomy["categories"], indent=2)}

Items:
{json.dumps(items, indent=2)}

Rules:

1. Classify EVERY item.

2. If an item clearly fits an existing category/subcategory,
   status must be MATCHED.

3. For MATCHED items, category and subcategory MUST exactly match
   values from the supplied taxonomy.

4. Do not invent synonyms for existing taxonomy values.

5. If no existing category/subcategory is appropriate,
   use status NEEDS_NEW_TAXONOMY.

6. For NEEDS_NEW_TAXONOMY:
   - category = null
   - subcategory = null
   - proposed_category should contain the best category name.
   - proposed_subcategory should contain the best subcategory name.

7. Prefer adding a new subcategory to an existing category rather
   than creating a completely new top-level category when reasonable.

8. Classify based on what the purchased product actually is,
   not merely the merchant.

9. Receipt abbreviations may be interpreted when the meaning is
   reasonably clear.

10. Preserve item_index exactly.
"""

    response = chat(
        model=MODEL_NAME,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
        format=ItemClassificationBatch.model_json_schema(),
        think=False,
        stream=False,
        options={
            "temperature": 0.1,
        },
    )

    result = ItemClassificationBatch.model_validate_json(
        response.message.content
    )

    #
    # Never trust the LLM to enforce our taxonomy.
    # Verify MATCHED classifications programmatically.
    #
    for classification in result.classifications:

        if classification.status != "MATCHED":
            continue

        if (
            classification.category is None
            or classification.subcategory is None
            or not taxonomy_pair_exists(
                classification.category,
                classification.subcategory,
            )
        ):
            classification.status = "NEEDS_NEW_TAXONOMY"

            classification.proposed_category = (
                classification.category
            )

            classification.proposed_subcategory = (
                classification.subcategory
            )

            classification.category = None
            classification.subcategory = None

    return result