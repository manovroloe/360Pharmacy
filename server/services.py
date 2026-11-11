from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
import secrets

from database import db


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def money(value: Any) -> float:
    return float(Decimal(str(value or 0)))


def _aware_utc_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        # Legacy timestamps may not include timezone information.
        # This application stores service timestamps in UTC, so interpret
        # those naive database values as UTC before comparing them.
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def active_promotions() -> list[dict[str, Any]]:
    now = utcnow()
    promos = db.select("promotions", {"select": "*", "is_active": "eq.true", "order": "priority.desc,created_at.desc"})
    result = []
    for promo in promos:
        start = _aware_utc_datetime(promo.get("starts_at"))
        end = _aware_utc_datetime(promo.get("ends_at"))
        if start and now < start:
            continue
        if end and now > end:
            continue
        result.append(promo)
    return result


def catalog() -> list[dict[str, Any]]:
    products = db.select("products", {"select": "*", "is_active": "eq.true", "order": "name.asc"})
    categories = {x["id"]: x for x in db.select("categories", {"select": "*", "is_active": "eq.true"})}
    manufacturers = {x["id"]: x for x in db.select("manufacturers", {"select": "*", "is_active": "eq.true"})}
    inventory = db.select("branch_inventory", {"select": "product_id,on_hand,reserved"})
    stock = defaultdict(int)
    for row in inventory:
        stock[row["product_id"]] += max(int(row.get("on_hand") or 0) - int(row.get("reserved") or 0), 0)

    promos = active_promotions()
    promo_ids = [p["id"] for p in promos]
    mappings: list[dict[str, Any]] = []
    if promo_ids:
        ids = ",".join(promo_ids)
        mappings = db.select("promotion_products", {"select": "promotion_id,product_id", "promotion_id": f"in.({ids})"})
    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    promo_map = {p["id"]: p for p in promos}
    for row in mappings:
        if row["promotion_id"] in promo_map:
            by_product[row["product_id"]].append(promo_map[row["promotion_id"]])

    output = []
    for product in products:
        base = money(product.get("selling_price"))
        best_price = base
        best_promo = None
        for promo in by_product.get(product["id"], []):
            if promo.get("discount_type") == "percentage":
                price = max(0, base * (1 - money(promo.get("discount_value")) / 100))
            else:
                price = max(0, base - money(promo.get("discount_value")))
            if price < best_price:
                best_price, best_promo = price, promo
        available = stock[product["id"]]
        category = categories.get(product.get("category_id"), {})
        manufacturer = manufacturers.get(product.get("manufacturer_id"), {})
        output.append({
            **product,
            "category_name": category.get("name"),
            "category_slug": category.get("slug"),
            "manufacturer_name": manufacturer.get("name"),
            "available_quantity": available,
            "stock_label": "Out of stock" if available <= 0 else "Limited" if available <= 10 else "In stock",
            "sale_price": round(best_price, 2),
            "promotion": best_promo,
        })
    return output


def promotion_cards() -> list[dict[str, Any]]:
    promos = active_promotions()
    links = db.select("promotion_products", {"select": "promotion_id,product_id"}) if promos else []
    counts = defaultdict(int)
    for link in links:
        counts[link["promotion_id"]] += 1
    return [{**p, "product_count": counts[p["id"]]} for p in promos]


def choose_delivery_branch(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    branches = db.select("branches", {"select": "*", "is_active": "eq.true", "is_delivery_enabled": "eq.true", "order": "name.asc"})
    for branch in branches:
        inventory = db.select("branch_inventory", {"select": "product_id,on_hand,reserved", "branch_id": f"eq.{branch['id']}"})
        available = {r["product_id"]: int(r.get("on_hand") or 0) - int(r.get("reserved") or 0) for r in inventory}
        if all(available.get(str(i["product_id"]), 0) >= int(i["quantity"]) for i in items):
            return branch
    return None


def date_window(period: str, reference: str | None) -> tuple[datetime, datetime]:
    today = date.fromisoformat(reference) if reference else date.today()
    if period == "year":
        start = date(today.year, 1, 1)
        end = date(today.year + 1, 1, 1)
    elif period == "month":
        start = date(today.year, today.month, 1)
        end = date(today.year + (1 if today.month == 12 else 0), 1 if today.month == 12 else today.month + 1, 1)
    else:
        start = today
        end = today + timedelta(days=1)
    return datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc), datetime.combine(end, datetime.min.time(), tzinfo=timezone.utc)


def order_number() -> str:
    return f"360-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2).upper()}"


def log_activity(actor_id: str | None, actor_role: str, action: str, entity_type: str, entity_id: str | None = None, details: dict[str, Any] | None = None) -> None:
    db.insert("activity_logs", {
        "actor_id": actor_id,
        "actor_role": actor_role,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "details": details or {},
    })
