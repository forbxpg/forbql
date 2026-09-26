from __future__ import annotations

from forbql.firewall import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo
from forbql.knowledge._search import expand, fuse, neighbours

ID = ColumnInfo(name="id", type="integer", nullable=False)


def table(*columns: str, fk: tuple[str, str] | None = None) -> TableInfo:
    return TableInfo(
        columns=(
            ID,
            *(ColumnInfo(name=c, type="integer", nullable=False) for c in columns),
        ),
        primary_key=("id",),
        foreign_keys=(
            (ForeignKey(columns=(fk[0],), table=fk[1], references=("id",)),)
            if fk
            else ()
        ),
    )


CATALOG = SchemaCatalog(
    default_schema="shop",
    tables={
        "shop.brands": table(),
        "shop.products": table("brand_id", fk=("brand_id", "shop.brands")),
        "shop.order_items": table("product_id", fk=("product_id", "shop.products")),
        "shop.carts": table(),
    },
)


def test_fusion_lifts_a_table_high_in_either_ranking():
    scores = fuse([["a", "b", "c"], ["c", "d"]])

    assert list(scores) == ["c", "a", "b", "d"]


def test_joins_follow_foreign_keys_both_ways_among_visible_columns():
    everything = dict.fromkeys(CATALOG.tables, ("id", "brand_id", "product_id"))
    visible = {name: cols for name, cols in everything.items() if name != "shop.brands"}

    assert neighbours(CATALOG, everything)["shop.products"] == {
        "shop.brands",
        "shop.order_items",
    }
    assert neighbours(CATALOG, visible)["shop.products"] == {"shop.order_items"}
    assert (
        neighbours(CATALOG, {**visible, "shop.order_items": ("id",)})["shop.products"]
        == set()
    )


def test_the_best_matches_bring_their_joined_tables():
    scores = {"shop.products": 0.3, "shop.carts": 0.2, "shop.brands": 0.1}
    joined: dict[str, set[str]] = {
        "shop.products": {"shop.brands", "shop.order_items"},
        "shop.carts": set(),
        "shop.brands": {"shop.products"},
    }

    found = expand(scores, joined, limit=8)

    assert found == [
        ("shop.products", None),
        ("shop.brands", "shop.products"),
        ("shop.order_items", "shop.products"),
        ("shop.carts", None),
    ]
    assert expand(scores, joined, limit=2) == found[:2]
