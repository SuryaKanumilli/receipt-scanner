import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent
TAXONOMY_PATH = BASE_DIR / "config" / "taxonomy.json"


def load_taxonomy() -> dict:
    with TAXONOMY_PATH.open(
        "r",
        encoding="utf-8",
    ) as file:
        return json.load(file)


def get_taxonomy_version() -> int:
    taxonomy = load_taxonomy()

    return int(
        taxonomy.get("version", 1)
    )


def taxonomy_pair_exists(
    category: str,
    subcategory: str,
) -> bool:

    taxonomy = load_taxonomy()

    categories = taxonomy["categories"]

    if category not in categories:
        return False

    return subcategory in categories[category]