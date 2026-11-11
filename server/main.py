from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from auth import current_user, profile_for_user, require_roles
from infrastructure.supabase_auth import auth_gateway, AuthServiceError
from database import DatabaseError, db
from infrastructure.supabase_storage import StorageError
from integrations import configured as integration_configured, statuses as integration_statuses
from services import active_promotions, catalog, choose_delivery_branch, date_window, log_activity, money, order_number, promotion_cards
from settings import ADMIN_SETUP_TOKEN, APP_NAME
from report_exports import financial_pdf, inventory_pdf

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "client"

app = FastAPI(title=APP_NAME, version="2.0.1")


@app.middleware("http")
async def disable_local_frontend_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/scripts/", "/styles/", "/assets/")):
        # Versioned script/style URLs and static assets can be reused by browsers.
        response.headers["Cache-Control"] = "public, max-age=86400"
    elif request.url.path in {"/", "/portal", "/login", "/workspace"}:
        response.headers["Cache-Control"] = "no-store"
    return response
app.mount("/assets", StaticFiles(directory=CLIENT / "assets"), name="assets")
app.mount("/styles", StaticFiles(directory=CLIENT / "styles"), name="styles")
app.mount("/scripts", StaticFiles(directory=CLIENT / "scripts"), name="scripts")


def safe(call):
    try:
        return call()
    except HTTPException:
        raise
    except (DatabaseError, StorageError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def record(table: str, row_id: str) -> dict[str, Any] | None:
    rows = db.select(table, {"select": "*", "id": f"eq.{row_id}", "limit": 1})
    return rows[0] if rows else None


def valid_email(email: str) -> bool:
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email)) and len(email) <= 255


USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,30}$")
STAFF_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{2,31}$")


def normalize_name(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_staff_id(value: Any) -> str:
    return str(value or "").strip().upper()


def validate_password(value: Any) -> str:
    password = str(value or "")
    if len(password) < 8:
        raise HTTPException(400, "Password must contain at least 8 characters.")
    if len(password) > 128:
        raise HTTPException(400, "Password is too long.")
    return password


def auth_safe(callback):
    try:
        return callback()
    except AuthServiceError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


def _session_profile(user_data: dict[str, Any]) -> dict[str, Any]:
    """Restore a missing customer profile only for a verified Supabase login.

    Existing roles and disabled accounts are never changed. This repairs
    identities created before the auth.users -> profiles trigger was installed.
    """
    user_id = str(user_data.get("id") or "")
    try:
        return profile_for_user(user_id)
    except HTTPException as exc:
        if exc.status_code != 403 or exc.detail != "Your user profile is not available.":
            raise

    # Never create a profile for an unconfirmed identity or arbitrary user ID.
    email = str(user_data.get("email") or "").strip().lower()
    if not user_id or not user_data.get("email_confirmed_at") or not valid_email(email):
        raise HTTPException(403, "Verify your email before signing in.")

    metadata = user_data.get("user_metadata")
    full_name = normalize_name(metadata.get("full_name"))[:160] if isinstance(metadata, dict) else ""
    try:
        db.insert("profiles", {
            "id": user_id, "email": email, "full_name": full_name,
            "role": "customer", "is_active": True,
        })
    except DatabaseError:
        # A concurrent login may have inserted the same profile. Re-check,
        # but propagate real DB errors rather than silently masking them.
        if not db.select("profiles", {"select": "id", "id": f"eq.{user_id}", "limit": 1}):
            raise
    return profile_for_user(user_id)


def _session_result(response: dict[str, Any]) -> dict[str, Any]:
    user_data = response.get("user") or {}
    access_token = response.get("access_token")
    if access_token and not user_data.get("id"):
        user_data = auth_safe(lambda: auth_gateway.get_user(access_token))
    if not user_data.get("id") or not access_token:
        raise HTTPException(401, "Supabase did not return an authenticated session.")
    profile = safe(lambda: _session_profile(user_data))
    return {
        "access_token": access_token,
        "refresh_token": response.get("refresh_token"),
        "expires_in": response.get("expires_in", 3600),
        "token_type": "bearer", "user": user_data, "profile": profile,
    }


def parse_ids(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if x]
    return [str(value)]


def unique_default_address(customer_id: str, new_id: str | None = None) -> None:
    rows = db.select("customer_addresses", {"select": "id", "customer_id": f"eq.{customer_id}"})
    for row in rows:
        if row["id"] != new_id:
            db.update("customer_addresses", {"id": f"eq.{row['id']}"}, {"is_default": False})


def branch_stock(branch_id: str) -> dict[str, int]:
    rows = db.select("branch_inventory", {"select": "product_id,on_hand,reserved", "branch_id": f"eq.{branch_id}"}, for_update=True)
    return {r["product_id"]: int(r.get("on_hand") or 0) - int(r.get("reserved") or 0) for r in rows}


def consume_batches(branch_id: str, product_id: str, quantity: int, order_id: str, actor_id: str) -> None:
    """Consume oldest-expiring stock first (FEFO) and keep batch balances traceable."""
    remaining = int(quantity)
    batches = db.select("product_batches", {
        "select": "*",
        "branch_id": f"eq.{branch_id}",
        "product_id": f"eq.{product_id}",
        "quantity_remaining": "gt.0",
        "order": "expiration_date.asc.nullslast,delivery_date.asc",
    }, for_update=True)
    for batch in batches:
        if remaining <= 0:
            break
        available = int(batch.get("quantity_remaining") or 0)
        take = min(remaining, available)
        if take <= 0:
            continue
        db.update("product_batches", {"id": f"eq.{batch['id']}"}, {"quantity_remaining": available - take})
        db.insert("stock_movements", {
            "branch_id": branch_id,
            "product_id": product_id,
            "batch_id": batch["id"],
            "movement_type": "sale",
            "quantity": -take,
            "reference_type": "order",
            "reference_id": order_id,
            "actor_id": actor_id,
        })
        remaining -= take
    if remaining > 0:
        raise DatabaseError("Batch stock is inconsistent with inventory. Receive/adjust a valid batch before selling this item.")


def latest_cost(branch_id: str, product_id: str) -> float:
    rows = db.select("product_batches", {
        "select": "cost_per_unit",
        "branch_id": f"eq.{branch_id}",
        "product_id": f"eq.{product_id}",
        "quantity_remaining": "gt.0",
        "order": "expiration_date.asc.nullslast,delivery_date.asc",
        "limit": 1,
    })
    return money(rows[0].get("cost_per_unit")) if rows else 0.0


def current_price(product: dict[str, Any]) -> tuple[float, float, dict[str, Any] | None]:
    base = money(product.get("selling_price"))
    final = base
    best = None
    promos = active_promotions()
    if not promos:
        return base, final, best
    promo_ids = ",".join(p["id"] for p in promos)
    links = db.select("promotion_products", {
        "select": "promotion_id,product_id",
        "product_id": f"eq.{product['id']}",
        "promotion_id": f"in.({promo_ids})",
    })
    mapped = {r["promotion_id"] for r in links}
    for promo in promos:
        if promo["id"] not in mapped:
            continue
        if promo["discount_type"] == "percentage":
            candidate = max(0, base * (1 - money(promo["discount_value"]) / 100))
        else:
            candidate = max(0, base - money(promo["discount_value"]))
        if candidate < final:
            final, best = candidate, promo
    return base, round(final, 2), best


def approved_rx(customer_id: str, product_id: str) -> dict[str, Any] | None:
    rows = db.select("prescriptions", {
        "select": "*",
        "customer_id": f"eq.{customer_id}",
        "product_id": f"eq.{product_id}",
        "status": "eq.approved",
        "order": "reviewed_at.desc.nullslast,created_at.desc",
        "limit": 1,
    })
    return rows[0] if rows else None


def _item_map(delivery_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    if not delivery_ids:
        return {}
    joined = ",".join(delivery_ids)
    rows = db.select("stock_delivery_items", {"select": "*", "delivery_id": f"in.({joined})", "order": "created_at.asc"})
    products = {p["id"]: p for p in db.select("products", {"select": "id,name,image_url,manufacturer_id"})}
    manufacturers = {m["id"]: m for m in db.select("manufacturers", {"select": "id,name"})}
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row["product"] = products.get(row.get("product_id"))
        row["manufacturer"] = manufacturers.get(row.get("manufacturer_id"))
        grouped.setdefault(row["delivery_id"], []).append(row)
    return grouped


def stock_delivery_rows(user: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    deliveries = db.select("stock_deliveries", {"select": "*", "order": "expected_delivery_date.desc,created_at.desc"})
    if user and user["profile"].get("role") == "merchandiser":
        uid = user["profile"]["id"]
        deliveries = [d for d in deliveries if d.get("assigned_to") in {None, uid}]
    branches = {b["id"]: b for b in db.select("branches", {"select": "id,name"})}
    suppliers = {s["id"]: s for s in db.select("suppliers", {"select": "id,name"})}
    profiles = {p["id"]: p for p in db.select("profiles", {"select": "id,full_name,role,staff_id"})}
    grouped = _item_map([d["id"] for d in deliveries])
    for delivery in deliveries:
        delivery["branch"] = branches.get(delivery.get("branch_id"))
        delivery["supplier"] = suppliers.get(delivery.get("supplier_id"))
        delivery["assignee"] = profiles.get(delivery.get("assigned_to"))
        delivery["arranged_by_profile"] = profiles.get(delivery.get("arranged_by"))
        delivery["items"] = grouped.get(delivery["id"], [])
    return deliveries


def stock_delivery_detail(delivery_id: str, user: dict[str, Any] | None = None) -> dict[str, Any] | None:
    rows = stock_delivery_rows(user)
    for row in rows:
        if row["id"] == delivery_id:
            return row
    return None


def create_staff_task(assigned_to: str | None, assigned_role: str | None, title: str, details: str, created_by: str | None) -> None:
    if not assigned_to and not assigned_role:
        return
    db.insert("staff_tasks", {
        "assigned_to": assigned_to,
        "assigned_role": assigned_role,
        "title": title,
        "details": details,
        "status": "pending",
        "created_by": created_by,
    })


@app.get("/")
def index():
    return FileResponse(CLIENT / "index.html")


@app.get("/login")
def unified_login_page():
    return FileResponse(CLIENT / "login.html")


@app.get("/workspace")
def workspace():
    return FileResponse(CLIENT / "portal.html")


@app.get("/portal")
def legacy_portal_redirect():
    return RedirectResponse("/workspace", status_code=307)


@app.get("/admin")
def admin_redirect():
    return RedirectResponse("/workspace", status_code=307)


@app.get("/api/health")
def health():
    response: dict[str, Any] = {
        "status": "ok",
        "app": APP_NAME,
        "database": "supabase_postgres",
        "databaseConfigured": db.privileged_configured,
        "schemaReady": False,
    }
    if db.privileged_configured:
        try:
            db.select("profiles", {"select": "id", "limit": 1})
            response["schemaReady"] = True
        except Exception as exc:
            response["databaseMessage"] = str(exc)
    return response


@app.get("/api/catalog")
def get_catalog():
    return safe(lambda: {
        "products": catalog(),
        "categories": db.select("categories", {"select": "*", "is_active": "eq.true", "order": "sort_order.asc,name.asc"}),
        "branches": db.select("branches", {"select": "*", "is_active": "eq.true", "order": "name.asc"}),
        "deals": promotion_cards(),
        "manufacturers": db.select("manufacturers", {"select": "*", "is_active": "eq.true", "is_partner": "eq.true", "order": "name.asc"}),
    })


@app.get("/api/products")
def products():
    return safe(catalog)


@app.get("/api/categories")
def categories():
    return safe(lambda: db.select("categories", {"select": "*", "is_active": "eq.true", "order": "sort_order.asc,name.asc"}))


@app.get("/api/branches")
def branches():
    return safe(lambda: db.select("branches", {"select": "*", "is_active": "eq.true", "order": "name.asc"}))


@app.get("/api/deals")
def deals():
    return safe(promotion_cards)


# ---------- One Supabase Auth service for customer and staff identities ----------

@app.post("/api/auth/register")
def register_customer(payload: dict[str, Any]):
    email = str(payload.get("email") or "").strip().lower()
    full_name = normalize_name(payload.get("full_name"))
    password = validate_password(payload.get("password"))
    if not valid_email(email) or not 2 <= len(full_name) <= 160:
        raise HTTPException(400, "Enter a valid email address and full name.")
    auth_safe(lambda: auth_gateway.signup(email, password, full_name))
    # A database trigger assigns role=customer; metadata never controls roles.
    return {"ok": True, "email": email, "emailVerificationRequired": True,
            "message": "Check your email for the verification code. Enter it to activate your account."}


@app.post("/api/auth/verify-email")
def verify_customer_signup(payload: dict[str, Any]):
    email = str(payload.get("email") or "").strip().lower()
    token = re.sub(r"\s+", "", str(payload.get("token") or ""))
    if not valid_email(email) or not token.isdigit() or len(token) not in {6, 8}:
        raise HTTPException(400, "Enter your email address and the verification code sent to you.")
    # Verification finishes signup; it must not require an existing profile or
    # silently turn account creation into a signed-in session.
    auth_safe(lambda: auth_gateway.verify_signup(email, token))
    return {"ok": True, "message": "Email verified. Please sign in using your email and password."}


@app.post("/api/auth/resend-verification")
def resend_signup_code(payload: dict[str, Any]):
    email = str(payload.get("email") or "").strip().lower()
    if not valid_email(email):
        raise HTTPException(400, "Enter a valid email address.")
    auth_safe(lambda: auth_gateway.resend_signup(email))
    return {"ok": True, "message": "If verification is pending, another email has been sent."}


@app.post("/api/auth/login")
def unified_login(payload: dict[str, Any]):
    email = str(payload.get("email") or "").strip().lower()
    password = str(payload.get("password") or "")
    if not valid_email(email) or not password:
        raise HTTPException(400, "Email and password are required.")
    result = auth_safe(lambda: auth_gateway.password_login(email, password))
    return _session_result(result)


@app.post("/api/auth/refresh")
def refresh_session(payload: dict[str, Any]):
    refresh_token = str(payload.get("refresh_token") or "")
    if not refresh_token:
        raise HTTPException(401, "Session expired. Please log in again.")
    result = auth_safe(lambda: auth_gateway.refresh(refresh_token))
    return _session_result(result)


@app.post("/api/auth/forgot-password")
def request_password_recovery(payload: dict[str, Any]):
    email = str(payload.get("email") or "").strip().lower()
    if not valid_email(email):
        raise HTTPException(400, "Enter a valid email address.")
    auth_safe(lambda: auth_gateway.request_recovery(email))
    return {"ok": True, "message": "If an account exists, a password reset link has been sent."}


@app.post("/api/auth/update-password")
def update_own_password(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    password = validate_password(payload.get("new_password"))
    auth_safe(lambda: auth_gateway.set_password(user["token"], password))
    return {"ok": True, "message": "Password updated. You can now use the same login page."}


@app.post("/api/auth/logout")
def logout(user: dict[str, Any] = Depends(current_user)):
    auth_safe(lambda: auth_gateway.revoke_session(user["token"]))
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict[str, Any] = Depends(current_user)):
    return {"user": user["auth"], "profile": user["profile"]}


@app.get("/api/setup/status")
def setup_status():
    if not db.privileged_configured:
        return {"configured": False, "schemaReady": False, "hasAdmin": False}
    try:
        admins = db.select("profiles", {"select": "id", "role": "eq.admin", "is_active": "eq.true", "limit": 1})
        return {"configured": True, "schemaReady": True, "hasAdmin": bool(admins)}
    except Exception:
        return {"configured": True, "schemaReady": False, "hasAdmin": False}


@app.post("/api/setup/head-admin")
def bootstrap_head_admin(payload: dict[str, Any]):
    # This one-time private setup is the only way to create the first Admin.
    import secrets
    if not ADMIN_SETUP_TOKEN or len(ADMIN_SETUP_TOKEN) < 24 or not secrets.compare_digest(
        str(payload.get("setup_token") or ""), ADMIN_SETUP_TOKEN
    ):
        raise HTTPException(403, "Invalid head-admin setup token.")
    email = str(payload.get("email") or "").strip().lower()
    full_name = normalize_name(payload.get("full_name"))
    password = validate_password(payload.get("password"))
    if not valid_email(email) or not 2 <= len(full_name) <= 160:
        raise HTTPException(400, "Enter a valid name and email address.")
    with db.transaction():
        # Serialize first-run requests from different browsers.
        with db._using_conn() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(360001)")
        admins = safe(lambda: db.select("profiles", {"select": "id", "role": "eq.admin", "limit": 1}))
        if admins:
            raise HTTPException(409, "An administrator already exists. First-time setup is locked.")
        created = auth_safe(lambda: auth_gateway.create_head_admin(email, password, full_name))
        uid = created.get("id") or (created.get("user") or {}).get("id")
        if not uid:
            raise HTTPException(502, "Supabase Auth did not return the new admin ID.")
        # The auth.users trigger created the customer profile; override only server-side.
        safe(lambda: db.upsert("profiles", {
            "id": uid, "email": email, "full_name": full_name,
            "role": "admin", "is_active": True,
        }, "id"))
    return {"ok": True, "message": "Head Admin created. Log in with the email and password you just set."}


@app.get("/api/me/favorites")
def my_favorites(user: dict[str, Any] = Depends(current_user)):
    uid = user["profile"]["id"]
    rows = safe(lambda: db.select("favorites", {"select": "product_id,created_at", "user_id": f"eq.{uid}", "order": "created_at.desc"}))
    return rows


@app.post("/api/me/favorites/{product_id}")
def add_favorite(product_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"customer"})
    safe(lambda: db.upsert("favorites", {"user_id": user["profile"]["id"], "product_id": product_id}, "user_id,product_id"))
    return {"ok": True}


@app.delete("/api/me/favorites/{product_id}")
def remove_favorite(product_id: str, user: dict[str, Any] = Depends(current_user)):
    safe(lambda: db.delete("favorites", {"user_id": f"eq.{user['profile']['id']}", "product_id": f"eq.{product_id}"}))
    return {"ok": True}


@app.get("/api/me/addresses")
def addresses(user: dict[str, Any] = Depends(current_user)):
    return safe(lambda: db.select("customer_addresses", {"select": "*", "customer_id": f"eq.{user['profile']['id']}", "order": "is_default.desc,created_at.desc"}))



# Geographic reference lists are fetched on demand; no API key or schema change.
from functools import lru_cache
import httpx

_PSGC_ROOT = "https://psgc.cloud/api/v2"

@lru_cache(maxsize=600)
def _ph_locations(resource: str) -> list[dict[str, str]]:
    try:
        response = httpx.get(f"{_PSGC_ROOT}/{resource}", timeout=8.0, follow_redirects=True)
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):
            body = body.get("data", [])
        if not isinstance(body, list):
            raise ValueError("Invalid address directory response")
        return [{"code": str(x["code"]), "name": str(x["name"])}
                for x in body if isinstance(x, dict) and x.get("code") and x.get("name")]
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(503, "Address options are temporarily unavailable. Please try again.") from exc


@app.get("/api/locations/regions")
def location_regions():
    return _ph_locations("regions")


@app.get("/api/locations/regions/{region_code}/provinces")
def location_provinces(region_code: str):
    if not re.fullmatch(r"[0-9]{8,12}", region_code):
        raise HTTPException(400, "Invalid region")
    return _ph_locations(f"regions/{region_code}/provinces")


@app.get("/api/locations/regions/{region_code}/cities-municipalities")
def location_region_cities(region_code: str):
    if not re.fullmatch(r"[0-9]{8,12}", region_code):
        raise HTTPException(400, "Invalid region")
    return _ph_locations(f"regions/{region_code}/cities-municipalities")


@app.get("/api/locations/provinces/{province_code}/cities-municipalities")
def location_cities(province_code: str):
    if not re.fullmatch(r"[0-9]{8,12}", province_code):
        raise HTTPException(400, "Invalid province")
    return _ph_locations(f"provinces/{province_code}/cities-municipalities")


@app.get("/api/locations/cities-municipalities/{city_code}/barangays")
def location_barangays(city_code: str):
    if not re.fullmatch(r"[0-9]{8,12}", city_code):
        raise HTTPException(400, "Invalid city")
    return _ph_locations(f"cities-municipalities/{city_code}/barangays")

@app.post("/api/me/addresses")
def create_address(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"customer"})
    required = ["recipient_name", "recipient_phone", "province", "city", "barangay", "street_address"]
    if any(not str(payload.get(k) or "").strip() for k in required):
        raise HTTPException(400, "Recipient, phone, province, city, barangay, and street address are required.")
    row = {k: payload.get(k) for k in ["label","recipient_name","recipient_phone","province","city","barangay","postal_code","street_address","landmark","latitude","longitude","is_default"]}
    row["customer_id"] = user["profile"]["id"]
    row["label"] = row.get("label") or "Home"
    row["is_default"] = bool(row.get("is_default"))
    if row["is_default"]:
        unique_default_address(row["customer_id"])
    created = safe(lambda: db.insert("customer_addresses", row))
    return created[0] if created else row


@app.patch("/api/me/addresses/{address_id}")
def update_address(address_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    rows = safe(lambda: db.select("customer_addresses", {"select": "id", "id": f"eq.{address_id}", "customer_id": f"eq.{user['profile']['id']}", "limit": 1}))
    if not rows:
        raise HTTPException(404, "Address not found.")
    allowed = {k: payload[k] for k in ["label","recipient_name","recipient_phone","province","city","barangay","postal_code","street_address","landmark","latitude","longitude","is_default"] if k in payload}
    if allowed.get("is_default"):
        unique_default_address(user["profile"]["id"], address_id)
    updated = safe(lambda: db.update("customer_addresses", {"id": f"eq.{address_id}"}, allowed))
    return updated[0] if updated else {"ok": True}


@app.delete("/api/me/addresses/{address_id}")
def delete_address(address_id: str, user: dict[str, Any] = Depends(current_user)):
    safe(lambda: db.delete("customer_addresses", {"id": f"eq.{address_id}", "customer_id": f"eq.{user['profile']['id']}"}))
    return {"ok": True}


@app.post("/api/me/prescriptions")
async def upload_prescription(
    product_id: str = Form(...),
    file: UploadFile = File(...),
    user: dict[str, Any] = Depends(current_user),
):
    require_roles(user, {"customer"})
    if file.content_type not in {"image/jpeg", "image/png", "image/webp", "application/pdf"}:
        raise HTTPException(400, "Prescription must be JPG, PNG, WEBP, or PDF.")
    data = await file.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(400, "Prescription file must be 10 MB or smaller.")
    uid = user["profile"]["id"]
    ext = (Path(file.filename or "prescription").suffix or ".bin").lower()
    path = f"{uid}/{uuid4().hex}{ext}"
    safe(lambda: db.upload("prescriptions", path, data, file.content_type or "application/octet-stream", False))
    created = safe(lambda: db.insert("prescriptions", {
        "customer_id": uid,
        "product_id": product_id,
        "storage_path": path,
        "original_filename": file.filename,
        "status": "pending",
    }))
    return created[0]


@app.get("/api/me/prescriptions")
def my_prescriptions(user: dict[str, Any] = Depends(current_user)):
    return safe(lambda: db.select("prescriptions", {"select": "*", "customer_id": f"eq.{user['profile']['id']}", "order": "created_at.desc"}))


@app.post("/api/me/consultations")
def create_consultation(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"customer"})
    subject = str(payload.get("subject") or "").strip()
    message = str(payload.get("message") or "").strip()
    if not subject or not message:
        raise HTTPException(400, "Subject and message are required.")
    created = safe(lambda: db.insert("consultations", {
        "customer_id": user["profile"]["id"],
        "product_id": payload.get("product_id") or None,
        "prescription_id": payload.get("prescription_id") or None,
        "subject": subject,
        "status": "waiting_pharmacist",
    }))
    consultation = created[0]
    safe(lambda: db.insert("consultation_messages", {
        "consultation_id": consultation["id"],
        "sender_id": user["profile"]["id"],
        "sender_role": "customer",
        "message": message,
    }))
    return consultation


@app.get("/api/me/consultations")
def my_consultations(user: dict[str, Any] = Depends(current_user)):
    consultations = safe(lambda: db.select("consultations", {"select": "*", "customer_id": f"eq.{user['profile']['id']}", "order": "updated_at.desc"}))
    for item in consultations:
        item["messages"] = safe(lambda i=item: db.select("consultation_messages", {"select": "*", "consultation_id": f"eq.{i['id']}", "order": "created_at.asc"}))
    return consultations


@app.post("/api/me/consultations/{consultation_id}/messages")
def customer_message(consultation_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    owned = safe(lambda: db.select("consultations", {"select": "id", "id": f"eq.{consultation_id}", "customer_id": f"eq.{user['profile']['id']}", "limit": 1}))
    if not owned:
        raise HTTPException(404, "Consultation not found.")
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty.")
    safe(lambda: db.insert("consultation_messages", {"consultation_id": consultation_id, "sender_id": user["profile"]["id"], "sender_role": "customer", "message": message}))
    safe(lambda: db.update("consultations", {"id": f"eq.{consultation_id}"}, {"status": "waiting_pharmacist"}))
    return {"ok": True}


@app.post("/api/checkout")
def checkout(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"customer"})
    with db.transaction():
        items = payload.get("items") or []
        if not items:
            raise HTTPException(400, "Your basket is empty.")
        fulfillment = payload.get("fulfillment")
        if fulfillment not in {"pickup", "delivery"}:
            raise HTTPException(400, "Choose pickup or delivery.")
        payment_method = str(payload.get("payment_method") or "").strip()
        if payment_method not in {"cash_on_pickup", "cash_on_delivery", "online"}:
            raise HTTPException(400, "Choose a valid payment method.")
        if payment_method == "online":
            raise HTTPException(503, "Verified online payment checkout is not connected yet. Please choose cash on pickup or cash on delivery.")

        normalized = [{"product_id": str(i.get("product_id")), "quantity": int(i.get("quantity") or 0)} for i in items]
        if any(i["quantity"] <= 0 for i in normalized):
            raise HTTPException(400, "Every item quantity must be greater than zero.")

        branch = None
        address_id = None
        if fulfillment == "pickup":
            branch_id = str(payload.get("branch_id") or "")
            rows = safe(lambda: db.select("branches", {"select": "*", "id": f"eq.{branch_id}", "is_active": "eq.true", "is_pickup_enabled": "eq.true", "limit": 1}))
            if not rows:
                raise HTTPException(400, "Choose one of the pickup addresses configured by the admin.")
            branch = rows[0]
        else:
            address_id = str(payload.get("address_id") or "")
            owned = safe(lambda: db.select("customer_addresses", {"select": "*", "id": f"eq.{address_id}", "customer_id": f"eq.{user['profile']['id']}", "limit": 1}))
            if not owned:
                raise HTTPException(400, "Choose or add a delivery address.")
            branch = safe(lambda: choose_delivery_branch(normalized))
            if not branch:
                raise HTTPException(409, "No delivery-enabled branch currently has enough stock for the entire order.")

        stock = safe(lambda: branch_stock(branch["id"]))
        product_rows: list[dict[str, Any]] = []
        subtotal = discount = 0.0
        for item in normalized:
            p_rows = safe(lambda i=item: db.select("products", {"select": "*", "id": f"eq.{i['product_id']}", "is_active": "eq.true", "limit": 1}))
            if not p_rows:
                raise HTTPException(404, "One medicine in your basket is no longer available.")
            product = p_rows[0]
            if stock.get(product["id"], 0) < item["quantity"]:
                raise HTTPException(409, f"Not enough branch stock for {product['name']}.")
            rx = None
            if product.get("requires_prescription"):
                rx = safe(lambda p=product: approved_rx(user["profile"]["id"], p["id"]))
                if not rx:
                    raise HTTPException(409, f"{product['name']} needs an approved prescription before checkout.")
            base, final, promo = safe(lambda p=product: current_price(p))
            subtotal += base * item["quantity"]
            discount += (base - final) * item["quantity"]
            product_rows.append({"product": product, "qty": item["quantity"], "base": base, "final": final, "promo": promo, "rx": rx})

        delivery_fee = 0.0
        if fulfillment == "delivery":
            # Replaced by the delivery/maps microservices when connected.
            delivery_fee = 0.0
        total = round(subtotal - discount + delivery_fee, 2)
        order_created = safe(lambda: db.insert("orders", {
            "order_number": order_number(),
            "customer_id": user["profile"]["id"],
            "branch_id": branch["id"],
            "address_id": address_id,
            "fulfillment": fulfillment,
            "status": "placed",
            "subtotal": round(subtotal, 2),
            "discount_amount": round(discount, 2),
            "delivery_fee": delivery_fee,
            "total_amount": total,
            "payment_method": payment_method,
            "payment_status": "pending" if payment_method == "online" else "unpaid",
            "notes": payload.get("notes") or None,
        }))
        order = order_created[0]

        for row in product_rows:
            p, qty = row["product"], row["qty"]
            cost = safe(lambda p=p: latest_cost(branch["id"], p["id"]))
            safe(lambda p=p, qty=qty, row=row, cost=cost: db.insert("order_items", {
                "order_id": order["id"],
                "product_id": p["id"],
                "prescription_id": row["rx"]["id"] if row["rx"] else None,
                "product_name_snapshot": p["name"],
                "unit_price": row["base"],
                "final_unit_price": row["final"],
                "unit_cost_snapshot": cost,
                "quantity": qty,
                "line_discount": round((row["base"] - row["final"]) * qty, 2),
                "line_total": round(row["final"] * qty, 2),
            }))
            inv = safe(lambda p=p: db.select("branch_inventory", {"select": "*", "branch_id": f"eq.{branch['id']}", "product_id": f"eq.{p['id']}", "limit": 1}))[0]
            safe(lambda p=p, qty=qty, inv=inv: db.update("branch_inventory", {"branch_id": f"eq.{branch['id']}", "product_id": f"eq.{p['id']}"}, {"on_hand": int(inv["on_hand"]) - qty}))
            safe(lambda p=p, qty=qty: consume_batches(branch["id"], p["id"], qty, order["id"], user["profile"]["id"]))

        safe(lambda: db.insert("payments", {"order_id": order["id"], "method": payment_method, "status": order["payment_status"], "amount": total, "paid_at": datetime.now(timezone.utc).isoformat() if order["payment_status"] == "paid" else None}))
        safe(lambda: db.insert("order_status_history", {"order_id": order["id"], "status": "placed", "note": "Order placed by customer", "actor_id": user["profile"]["id"]}))
        if fulfillment == "delivery":
            safe(lambda: db.insert("deliveries", {"order_id": order["id"], "status": "queued", "provider": "external" if integration_configured("delivery") else "pending-integration"}))
        log_activity(user["profile"]["id"], "customer", "placed_order", "order", order["id"], {"order_number": order["order_number"]})
        return {"order": order, "branch": branch, "message": "Order placed successfully."}

@app.get("/api/me/orders")
def my_orders(user: dict[str, Any] = Depends(current_user)):
    rows = safe(lambda: db.select("orders", {"select": "*", "customer_id": f"eq.{user['profile']['id']}", "order": "created_at.desc"}))
    for order in rows:
        order["items"] = safe(lambda o=order: db.select("order_items", {"select": "*", "order_id": f"eq.{o['id']}"}))
    return rows


@app.get("/api/me/orders/{order_id}/tracking")
def tracking(order_id: str, user: dict[str, Any] = Depends(current_user)):
    owned = safe(lambda: db.select("orders", {"select": "*", "id": f"eq.{order_id}", "customer_id": f"eq.{user['profile']['id']}", "limit": 1}))
    if not owned:
        raise HTTPException(404, "Order not found.")
    order = owned[0]
    history = safe(lambda: db.select("order_status_history", {"select": "*", "order_id": f"eq.{order_id}", "order": "created_at.asc"}))
    delivery = safe(lambda: db.select("deliveries", {"select": "*", "order_id": f"eq.{order_id}", "limit": 1}))
    branch_rows = safe(lambda: db.select("branches", {"select": "*", "id": f"eq.{order.get('branch_id')}", "limit": 1})) if order.get("branch_id") else []
    address_rows = safe(lambda: db.select("customer_addresses", {"select": "*", "id": f"eq.{order.get('address_id')}", "customer_id": f"eq.{user['profile']['id']}", "limit": 1})) if order.get("address_id") else []
    return {
        "order": order,
        "history": history,
        "delivery": delivery[0] if delivery else None,
        "branch": branch_rows[0] if branch_rows else None,
        "address": address_rows[0] if address_rows else None,
    }


@app.get("/api/storage/private")
def legacy_private_storage():
    raise HTTPException(410, "Local prescription file links are retired. Request a new Supabase signed URL.")



@app.post("/api/me/orders/{order_id}/confirm-receipt")
def customer_confirm_order(order_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"customer"})
    rows = safe(lambda: db.select("orders", {"select": "*", "id": f"eq.{order_id}", "customer_id": f"eq.{user['profile']['id']}", "limit": 1}))
    if not rows:
        raise HTTPException(404, "Order not found.")
    order = rows[0]
    if order["fulfillment"] == "pickup":
        if order["status"] != "ready_for_pickup":
            raise HTTPException(409, "This pickup order is not ready to be marked Picked Up.")
        status, note = "picked_up", "Customer confirmed the package was picked up."
    else:
        if order["status"] != "delivered":
            raise HTTPException(409, "This delivery is not yet marked Delivered by the delivery staff.")
        status, note = "order_received", "Customer confirmed the delivered package was received."
    safe(lambda: db.update("orders", {"id": f"eq.{order_id}"}, {"status": status}))
    safe(lambda: db.insert("order_status_history", {"order_id": order_id, "status": status, "note": note, "actor_id": user["profile"]["id"]}))
    log_activity(user["profile"]["id"], "customer", "confirmed_order_receipt", "order", order_id, {"status": status})
    return {"ok": True, "status": status}


# ---------- Staff / shared portal ----------

@app.get("/api/portal/bootstrap")
def portal_bootstrap(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist", "merchandiser", "delivery"})
    return safe(lambda: {
        "profile": user["profile"],
        "branches": db.select("branches", {"select": "*", "order": "name.asc"}),
        "categories": db.select("categories", {"select": "*", "order": "sort_order.asc,name.asc"}),
        "manufacturers": db.select("manufacturers", {"select": "*", "order": "name.asc"}),
        "suppliers": db.select("suppliers", {"select": "*", "order": "name.asc"}),
        "products": db.select("products", {"select": "*", "order": "name.asc"}),
        "integrations": integration_statuses(),
    })


@app.get("/api/portal/reports")
def staff_reports(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist", "merchandiser"})
    params: dict[str, Any] = {"select": "*", "order": "created_at.desc", "limit": 200}
    if user["profile"]["role"] != "admin":
        params["staff_id"] = f"eq.{user['profile']['id']}"
    rows = safe(lambda: db.select("staff_reports", params))
    profiles = {p["id"]: p for p in safe(lambda: db.select("profiles", {"select": "id,staff_id,full_name,role"}))}
    for row in rows:
        row["staff"] = profiles.get(row.get("staff_id"))
    return rows


@app.post("/api/portal/reports")
def submit_staff_report(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"pharmacist", "merchandiser"})
    title = str(payload.get("title") or "").strip()
    details = str(payload.get("details") or "").strip()
    report_date = str(payload.get("report_date") or datetime.now().date().isoformat()).strip()
    if not title or not details:
        raise HTTPException(400, "Report title and accomplished-work details are required.")
    attendance = safe(lambda: db.select("attendance_records", {
        "select": "id,clock_in,clock_out", "employee_id": f"eq.{user['profile']['id']}",
        "order": "clock_in.desc", "limit": 1,
    }))
    row = safe(lambda: db.insert("staff_reports", {
        "staff_id": user["profile"]["id"], "attendance_id": attendance[0]["id"] if attendance else None,
        "report_date": report_date, "title": title, "details": details, "status": "submitted",
    }))[0]
    log_activity(user["profile"]["id"], user["profile"]["role"], "submitted_staff_report", "staff_report", row["id"])
    return row


@app.patch("/api/admin/reports/{report_id}")
def review_staff_report(report_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    rows = safe(lambda: db.update("staff_reports", {"id": f"eq.{report_id}"}, {
        "status": "reviewed", "reviewed_by": user["profile"]["id"],
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }))
    if not rows:
        raise HTTPException(404, "Staff report not found.")
    log_activity(user["profile"]["id"], "admin", "reviewed_staff_report", "staff_report", report_id)
    return rows[0]


@app.get("/api/portal/badges")
def portal_badges(user: dict[str, Any] = Depends(current_user)):
    role = user["profile"]["role"]
    require_roles(user, {"admin", "pharmacist", "merchandiser", "delivery"})
    counts: dict[str, int] = {}
    if role == "admin":
        counts["reports"] = len(safe(lambda: db.select("staff_reports", {"select": "id", "status": "eq.submitted"})))
        counts["attendance"] = len(safe(lambda: db.select("attendance_records", {"select": "id", "status": "eq.pending"})))
        all_orders = safe(lambda: db.select("orders", {"select": "id,fulfillment,status"}))
        counts["orders"] = sum(1 for o in all_orders if o.get("status") not in {"completed", "cancelled"})
        counts["stockdeliveries"] = len([d for d in safe(lambda: db.select("stock_deliveries", {"select": "id,status"})) if d.get("status") not in {"completed", "cancelled"}])
    elif role == "pharmacist":
        counts["prescriptions"] = len(safe(lambda: db.select("prescriptions", {"select": "id", "status": "in.(pending,needs_information)"})))
        counts["support"] = len(safe(lambda: db.select("consultations", {"select": "id", "status": "in.(open,waiting_pharmacist)"})))
        counts["attendance"] = len(safe(lambda: db.select("attendance_records", {"select": "id", "employee_id": f"eq.{user['profile']['id']}", "status": "eq.pending"})))
        counts["reports"] = len(safe(lambda: db.select("staff_reports", {"select": "id", "staff_id": f"eq.{user['profile']['id']}", "status": "eq.submitted"})))
    elif role == "merchandiser":
        inv = safe(lambda: db.select("branch_inventory", {"select": "on_hand,reorder_level"}))
        counts["inventory"] = sum(1 for x in inv if int(x.get("on_hand") or 0) <= int(x.get("reorder_level") or 0))
        counts["attendance"] = len(safe(lambda: db.select("attendance_records", {"select": "id", "employee_id": f"eq.{user['profile']['id']}", "status": "eq.pending"})))
        counts["reports"] = len(safe(lambda: db.select("staff_reports", {"select": "id", "staff_id": f"eq.{user['profile']['id']}", "status": "eq.submitted"})))
        deliveries = safe(lambda: db.select("stock_deliveries", {"select": "id,status,assigned_to"}))
        counts["incoming"] = len([d for d in deliveries if d.get("status") not in {"completed", "cancelled"} and d.get("assigned_to") in {None, user['profile']['id']}])
    else:
        deliveries = safe(lambda: db.select("deliveries", {"select": "id,assigned_to,status"}))
        counts["packages"] = sum(1 for d in deliveries if d.get("status") not in {"delivered","failed","cancelled"} and (not d.get("assigned_to") or d.get("assigned_to") == user["profile"]["id"]))
    return counts


@app.get("/api/portal/notifications")
def portal_notifications(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist", "merchandiser", "delivery"})
    profile = user["profile"]
    rows = safe(lambda: db.select("staff_tasks", {"select": "*", "status": "eq.pending", "order": "created_at.desc", "limit": 150}))
    return [row for row in rows if row.get("assigned_to") == profile["id"] or (not row.get("assigned_to") and row.get("assigned_role") == profile["role"])][:30]


@app.patch("/api/portal/notifications/{task_id}")
def acknowledge_notification(task_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist", "merchandiser", "delivery"})
    row = record("staff_tasks", task_id)
    if not row or not (row.get("assigned_to") == user["profile"]["id"] or (not row.get("assigned_to") and row.get("assigned_role") == user["profile"]["role"])):
        raise HTTPException(404, "Notification not found.")
    safe(lambda: db.update("staff_tasks", {"id": f"eq.{task_id}"}, {"status": "completed"}))
    return {"ok": True}


@app.get("/api/portal/attendance")
def portal_attendance(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist", "merchandiser"})
    params: dict[str, Any] = {"select": "*", "order": "clock_in.desc", "limit": 200}
    if user["profile"]["role"] != "admin":
        params["employee_id"] = f"eq.{user['profile']['id']}"
    rows = safe(lambda: db.select("attendance_records", params))
    profiles = {p["id"]: p for p in safe(lambda: db.select("profiles", {"select": "id,staff_id,full_name,role"}))}
    for row in rows:
        row["employee"] = profiles.get(row.get("employee_id"))
    return rows


@app.post("/api/portal/attendance/clock-in")
def attendance_clock_in(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"pharmacist", "merchandiser"})
    uid = user["profile"]["id"]
    open_rows = safe(lambda: db.select("attendance_records", {"select": "id,clock_in", "employee_id": f"eq.{uid}", "clock_out": "eq.null", "order": "clock_in.desc", "limit": 1}))
    if open_rows:
        raise HTTPException(409, "You are already clocked in. Clock out before starting another attendance record.")
    row = safe(lambda: db.insert("attendance_records", {"employee_id": uid, "clock_in": datetime.now(timezone.utc).isoformat(), "status": "pending"}))[0]
    log_activity(uid, user["profile"]["role"], "clocked_in", "attendance_record", row.get("id"))
    return row


@app.post("/api/portal/attendance/clock-out")
def attendance_clock_out(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"pharmacist", "merchandiser"})
    uid = user["profile"]["id"]
    open_rows = safe(lambda: db.select("attendance_records", {"select": "*", "employee_id": f"eq.{uid}", "clock_out": "eq.null", "order": "clock_in.desc", "limit": 1}))
    if not open_rows:
        raise HTTPException(409, "No open attendance record was found. Clock in first.")
    attendance_id = open_rows[0]["id"]
    updated = safe(lambda: db.update("attendance_records", {"id": f"eq.{attendance_id}"}, {"clock_out": datetime.now(timezone.utc).isoformat(), "status": "pending", "verified_by": None, "verified_at": None, "admin_note": None}))
    log_activity(uid, user["profile"]["role"], "clocked_out", "attendance_record", attendance_id)
    return updated[0] if updated else {"ok": True}


@app.patch("/api/admin/attendance/{attendance_id}")
def verify_attendance(attendance_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    status = str(payload.get("status") or "").lower()
    if status not in {"verified", "rejected"}:
        raise HTTPException(400, "Attendance status must be verified or rejected.")
    current = record("attendance_records", attendance_id)
    if not current:
        raise HTTPException(404, "Attendance record not found.")
    if not current.get("clock_out"):
        raise HTTPException(409, "Staff must clock out before Admin can verify this attendance record.")
    updated = safe(lambda: db.update("attendance_records", {"id": f"eq.{attendance_id}"}, {
        "status": status,
        "verified_by": user["profile"]["id"],
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "admin_note": str(payload.get("admin_note") or "").strip() or None,
    }))
    log_activity(user["profile"]["id"], "admin", "verified_attendance", "attendance_record", attendance_id, {"status": status})
    return updated[0] if updated else {"ok": True}




# ---------- Pharmacist ----------

@app.get("/api/pharmacist/prescriptions")
def pharmacist_prescriptions(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist"})
    rows = safe(lambda: db.select("prescriptions", {"select": "*", "order": "created_at.desc"}))
    products = {p["id"]: p for p in safe(lambda: db.select("products", {"select": "id,name,generic_name"}))}
    profiles = {p["id"]: p for p in safe(lambda: db.select("profiles", {"select": "id,full_name,email"}))}
    for row in rows:
        row["product"] = products.get(row.get("product_id"))
        row["customer"] = profiles.get(row.get("customer_id"))
    return rows


@app.get("/api/pharmacist/prescriptions/{prescription_id}/file")
def prescription_file(prescription_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist"})
    rx = record("prescriptions", prescription_id)
    if not rx:
        raise HTTPException(404, "Prescription not found.")
    return {"url": safe(lambda: db.signed_storage_url("prescriptions", rx["storage_path"]))}


@app.patch("/api/pharmacist/prescriptions/{prescription_id}")
def review_prescription(prescription_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist"})
    status = payload.get("status")
    if status not in {"approved", "rejected", "needs_information"}:
        raise HTTPException(400, "Choose approved, rejected, or needs_information.")
    updated = safe(lambda: db.update("prescriptions", {"id": f"eq.{prescription_id}"}, {
        "status": status,
        "pharmacist_id": user["profile"]["id"],
        "pharmacist_note": payload.get("pharmacist_note") or None,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }))
    log_activity(user["profile"]["id"], user["profile"]["role"], "reviewed_prescription", "prescription", prescription_id, {"status": status})
    return updated[0] if updated else {"ok": True}


@app.get("/api/pharmacist/consultations")
def pharmacist_consultations(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist"})
    rows = safe(lambda: db.select("consultations", {"select": "*", "order": "updated_at.desc"}))
    profiles = {p["id"]: p for p in safe(lambda: db.select("profiles", {"select": "id,full_name,email"}))}
    for row in rows:
        row["customer"] = profiles.get(row.get("customer_id"))
        row["messages"] = safe(lambda r=row: db.select("consultation_messages", {"select": "*", "consultation_id": f"eq.{r['id']}", "order": "created_at.asc"}))
    return rows


@app.post("/api/pharmacist/consultations/{consultation_id}/messages")
def pharmacist_reply(consultation_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist"})
    message = str(payload.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "Message cannot be empty.")
    safe(lambda: db.insert("consultation_messages", {"consultation_id": consultation_id, "sender_id": user["profile"]["id"], "sender_role": user["profile"]["role"], "message": message}))
    safe(lambda: db.update("consultations", {"id": f"eq.{consultation_id}"}, {"status": payload.get("status") or "waiting_customer", "assigned_pharmacist_id": user["profile"]["id"]}))
    log_activity(user["profile"]["id"], user["profile"]["role"], "replied_consultation", "consultation", consultation_id)
    return {"ok": True}


@app.patch("/api/pharmacist/products/{product_id}")
def pharmacist_product_edit(product_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist"})
    # Pharmacist intentionally has only professional classification/details + image access.
    allowed = {k: payload[k] for k in ["requires_prescription", "short_use", "description", "image_url"] if k in payload}
    if not allowed:
        raise HTTPException(400, "Pharmacists may edit Rx/OTC status, medicine description/use details, and product image.")
    updated = safe(lambda: db.update("products", {"id": f"eq.{product_id}"}, allowed))
    log_activity(user["profile"]["id"], user["profile"]["role"], "updated_medicine_guidance", "product", product_id, allowed)
    return updated[0] if updated else {"ok": True}


# ---------- Merchandiser / inventory ----------

@app.get("/api/inventory")
def inventory(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "merchandiser"})
    inv = safe(lambda: db.select("branch_inventory", {"select": "*", "order": "updated_at.desc"}))
    batches = safe(lambda: db.select("product_batches", {"select": "*", "order": "expiration_date.asc.nullslast,delivery_date.desc"}))
    products = {p["id"]: p for p in safe(lambda: db.select("products", {"select": "id,name,manufacturer_id,image_url"}))}
    branches = {b["id"]: b for b in safe(lambda: db.select("branches", {"select": "id,name"}))}
    manufacturers = {m["id"]: m for m in safe(lambda: db.select("manufacturers", {"select": "id,name"}))}
    for row in inv:
        row["product"] = products.get(row["product_id"])
        row["branch"] = branches.get(row["branch_id"])
    for batch in batches:
        batch["product"] = products.get(batch["product_id"])
        batch["branch"] = branches.get(batch["branch_id"])
        batch["manufacturer"] = manufacturers.get(batch.get("manufacturer_id"))
    return {"inventory": inv, "batches": batches}


@app.post("/api/inventory/receive")
def receive_stock(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "merchandiser"})
    raise HTTPException(410, "Direct stock posting is disabled. Use Admin > Stock Deliveries and Merchandiser > Incoming Stocks.")


@app.get("/api/stock-deliveries")
def stock_deliveries(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "merchandiser"})
    return safe(lambda: stock_delivery_rows(user))


@app.post("/api/admin/stock-deliveries")
def create_stock_delivery(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    with db.transaction():
        items = payload.get("items") or []
        if not isinstance(items, list) or len(items) > 100:
            raise HTTPException(400, "Delivery items must be a list of 1-100 entries.")
        if not payload.get("branch_id") or not payload.get("expected_delivery_date") or not items:
            raise HTTPException(400, "Branch, expected delivery date, and at least one item are required.")
        branch = record("branches", str(payload["branch_id"]))
        if not branch or not branch.get("is_active", True):
            raise HTTPException(400, "Choose an active receiving branch.")
        assigned_to = payload.get("assigned_to") or None
        if assigned_to:
            profile = record("profiles", str(assigned_to))
            if not profile or profile.get("role") != "merchandiser" or not profile.get("is_active", True):
                raise HTTPException(400, "Assign an active merchandiser account.")
        delivery = safe(lambda: db.insert("stock_deliveries", {
            "branch_id": payload["branch_id"],
            "supplier_id": payload.get("supplier_id") or None,
            "assigned_to": payload.get("assigned_to") or None,
            "arranged_by": user["profile"]["id"],
            "delivery_reference": payload.get("delivery_reference") or None,
            "expected_delivery_date": payload["expected_delivery_date"],
            "status": "scheduled",
            "notes": payload.get("notes") or None,
        }))[0]
        for item in items:
            qty = int(item.get("expected_quantity") or 0)
            if qty <= 0 or qty > 100000 or not item.get("product_id"):
                raise HTTPException(400, "Each item needs a valid product and quantity between 1 and 100,000.")
            if not record("products", str(item["product_id"])):
                raise HTTPException(400, "Unknown product in delivery plan.")
            safe(lambda item=item, qty=qty: db.insert("stock_delivery_items", {
                "delivery_id": delivery["id"],
                "product_id": item["product_id"],
                "manufacturer_id": item.get("manufacturer_id") or None,
                "batch_number": item.get("batch_number") or None,
                "expiration_date": item.get("expiration_date") or None,
                "expected_quantity": qty,
                "received_quantity": 0,
                "cost_per_unit": money(item.get("cost_per_unit") or 0),
                "receiving_note": item.get("note") or None,
                "status": "pending",
            }))
        if delivery.get("assigned_to"):
            assignee = record("profiles", delivery["assigned_to"])
            if assignee:
                safe(lambda: create_staff_task(assignee["id"], "merchandiser", "Incoming stock delivery scheduled", f"{payload.get('delivery_reference') or 'Stock delivery'} is expected on {payload['expected_delivery_date']}. Receive and arrange the stock for inventory posting.", user["profile"]["id"]))
        log_activity(user["profile"]["id"], "admin", "created_stock_delivery", "stock_delivery", delivery["id"], {"item_count": len(items)})
        return safe(lambda: stock_delivery_detail(delivery["id"], user))

@app.patch("/api/admin/stock-deliveries/{delivery_id}")
def update_stock_delivery(delivery_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    allowed = {k: payload[k] for k in ["assigned_to", "delivery_reference", "expected_delivery_date", "notes", "status", "supplier_id"] if k in payload}
    if "status" in allowed and allowed["status"] not in {"scheduled", "arrived", "receiving", "cancelled"}:
        raise HTTPException(400, "Complete stock delivery through the receiving workflow.")
    if "assigned_to" in allowed and allowed["assigned_to"]:
        p = record("profiles", str(allowed["assigned_to"]))
        if not p or p.get("role") != "merchandiser" or not p.get("is_active", True):
            raise HTTPException(400, "Assigned staff must be an active merchandiser.")
    if not allowed:
        raise HTTPException(400, "Nothing to update.")
    rows = safe(lambda: db.update("stock_deliveries", {"id": f"eq.{delivery_id}"}, allowed))
    if not rows:
        raise HTTPException(404, "Stock delivery not found.")
    if allowed.get("assigned_to"):
        safe(lambda: create_staff_task(allowed["assigned_to"], "merchandiser", "Stock delivery updated", f"A stock delivery assignment was updated. Review the inbound delivery schedule for {allowed.get('expected_delivery_date') or 'the expected date'}.", user["profile"]["id"]))
    log_activity(user["profile"]["id"], "admin", "updated_stock_delivery", "stock_delivery", delivery_id, allowed)
    return safe(lambda: stock_delivery_detail(delivery_id, user))


@app.post("/api/stock-deliveries/{delivery_id}/receive")
def receive_planned_stock_delivery(delivery_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "merchandiser"})
    with db.transaction():
        locked = safe(lambda: db.select("stock_deliveries", {"select": "id,status", "id": f"eq.{delivery_id}"}, for_update=True))
        if not locked:
            raise HTTPException(404, "Stock delivery not found.")
        delivery = safe(lambda: stock_delivery_detail(delivery_id, user))
        if not delivery:
            raise HTTPException(404, "Stock delivery not found.")
        if user["profile"]["role"] == "merchandiser" and delivery.get("assigned_to") and delivery["assigned_to"] != user["profile"]["id"]:
            raise HTTPException(403, "This stock delivery is assigned to another merchandiser.")
        if str(delivery.get("status") or "").lower() in {"completed", "cancelled"}:
            raise HTTPException(409, "This stock delivery is already closed.")
        provided = {str(item.get("item_id")): item for item in (payload.get("items") or []) if item.get("item_id")}
        if not provided or set(provided) != {str(item["id"]) for item in delivery.get("items") or []}:
            raise HTTPException(400, "Submit a receiving decision for every planned delivery item.")
        receipt = safe(lambda: db.insert("stock_receipts", {
            "branch_id": delivery["branch_id"],
            "supplier_id": delivery.get("supplier_id") or None,
            "delivery_reference": delivery.get("delivery_reference") or None,
            "delivery_date": datetime.now().date().isoformat(),
            "received_by": user["profile"]["id"],
            "notes": payload.get("notes") or delivery.get("notes") or None,
        }))[0]
        for planned in delivery.get("items") or []:
            row = provided.get(planned["id"])
            if not row:
                continue
            received_qty = int(row.get("received_quantity") or 0)
            if received_qty < 0:
                raise HTTPException(400, "Received quantity cannot be negative.")
            expected_qty = int(planned.get("expected_quantity") or 0)
            item_status = str(row.get("status") or ("received" if received_qty >= expected_qty else "short" if received_qty > 0 else "damaged")).strip().lower()
            manufacturer_id = row.get("manufacturer_id") or planned.get("manufacturer_id") or planned.get("product", {}).get("manufacturer_id")
            batch_number = row.get("batch_number") or planned.get("batch_number") or None
            expiration_date = row.get("expiration_date") or planned.get("expiration_date") or None
            cost_per_unit = money(row.get("cost_per_unit") or planned.get("cost_per_unit") or 0)
            if item_status == "damaged" and received_qty != 0:
                raise HTTPException(400, "Damaged or rejected stock must have accepted quantity 0.")
            if item_status not in {"received", "short", "damaged"}:
                raise HTTPException(400, "Invalid receiving status.")
            if received_qty > expected_qty:
                raise HTTPException(400, "Received quantity exceeds the planned quantity.")
            if item_status == "received" and received_qty != expected_qty:
                raise HTTPException(400, "Full receipt quantity must match expected quantity.")
            if item_status == "short" and received_qty >= expected_qty:
                raise HTTPException(400, "Short receipt quantity must be less than expected quantity.")
            if received_qty > 0 and expiration_date and str(expiration_date) < datetime.now().date().isoformat():
                raise HTTPException(409, "Expired stock cannot be released to sellable inventory.")
            if received_qty > 0:
                batch = safe(lambda: db.insert("product_batches", {
                    "receipt_id": receipt["id"],
                    "branch_id": delivery["branch_id"],
                    "product_id": planned["product_id"],
                    "manufacturer_id": manufacturer_id or None,
                    "batch_number": batch_number,
                    "delivery_date": datetime.now().date().isoformat(),
                    "expiration_date": expiration_date,
                    "quantity_received": received_qty,
                    "quantity_remaining": received_qty,
                    "cost_per_unit": cost_per_unit,
                    "received_by": user["profile"]["id"],
                }))[0]
                existing = safe(lambda: db.select("branch_inventory", {"select": "*", "branch_id": f"eq.{delivery['branch_id']}", "product_id": f"eq.{planned['product_id']}", "limit": 1}, for_update=True))
                if existing:
                    safe(lambda existing=existing: db.update("branch_inventory", {"branch_id": f"eq.{delivery['branch_id']}", "product_id": f"eq.{planned['product_id']}"}, {"on_hand": int(existing[0]["on_hand"]) + received_qty}))
                else:
                    safe(lambda: db.insert("branch_inventory", {"branch_id": delivery["branch_id"], "product_id": planned["product_id"], "on_hand": received_qty, "reserved": 0, "reorder_level": 10}))
                safe(lambda: db.insert("stock_movements", {
                    "branch_id": delivery["branch_id"],
                    "product_id": planned["product_id"],
                    "batch_id": batch["id"],
                    "movement_type": "receive",
                    "quantity": received_qty,
                    "reference_type": "stock_delivery",
                    "reference_id": delivery_id,
                    "note": row.get("note") or payload.get("notes") or None,
                    "actor_id": user["profile"]["id"],
                }))
            safe(lambda row=row, received_qty=received_qty, item_status=item_status, manufacturer_id=manufacturer_id, batch_number=batch_number, expiration_date=expiration_date, cost_per_unit=cost_per_unit: db.update("stock_delivery_items", {"id": f"eq.{planned['id']}"}, {
                "manufacturer_id": manufacturer_id or None,
                "batch_number": batch_number,
                "expiration_date": expiration_date,
                "received_quantity": received_qty,
                "cost_per_unit": cost_per_unit,
                "receiving_note": row.get("note") or None,
                "status": item_status or "received",
            }))
        safe(lambda: db.update("stock_deliveries", {"id": f"eq.{delivery_id}"}, {"status": "completed", "notes": payload.get("notes") or delivery.get("notes") or None}))
        if delivery.get("arranged_by"):
            safe(lambda: create_staff_task(delivery["arranged_by"], "admin", "Stock delivery received", f"{delivery.get('delivery_reference') or 'A stock delivery'} has been received and posted to inventory.", user["profile"]["id"]))
        log_activity(user["profile"]["id"], user["profile"]["role"], "received_stock_delivery", "stock_delivery", delivery_id, {"receipt_id": receipt["id"]})
        return {"receipt": receipt, "delivery": safe(lambda: stock_delivery_detail(delivery_id, user))}

@app.patch("/api/inventory/products/{product_id}")
def merchandiser_product_edit(product_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "merchandiser"})
    allowed = {k: payload[k] for k in ["manufacturer_id", "image_url"] if k in payload}
    if not allowed:
        raise HTTPException(400, "Merchandiser may edit manufacturer and product image here.")
    result = safe(lambda: db.update("products", {"id": f"eq.{product_id}"}, allowed))
    log_activity(user["profile"]["id"], user["profile"]["role"], "updated_inventory_product", "product", product_id, allowed)
    return result[0] if result else {"ok": True}


@app.post("/api/portal/product-image")
async def upload_product_image(product_id: str = Form(...), file: UploadFile = File(...), user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "pharmacist", "merchandiser"})
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(400, "Product image must be JPG, PNG, or WEBP.")
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(400, "Product image must be 5 MB or smaller.")
    ext = (Path(file.filename or "product.jpg").suffix or ".jpg").lower()
    path = f"products/{product_id}/{uuid4().hex}{ext}"
    safe(lambda: db.upload("product-images", path, data, file.content_type or "image/jpeg", True))
    url = db.public_storage_url("product-images", path)
    safe(lambda: db.update("products", {"id": f"eq.{product_id}"}, {"image_url": url}))
    log_activity(user["profile"]["id"], user["profile"]["role"], "uploaded_product_image", "product", product_id)
    return {"url": url}


# ---------- Delivery staff ----------

@app.get("/api/delivery/packages")
def delivery_packages(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"delivery"})
    uid = user["profile"]["id"]
    deliveries = safe(lambda: db.select("deliveries", {"select": "*", "order": "created_at.desc"}))
    orders = {o["id"]: o for o in safe(lambda: db.select("orders", {"select": "*", "fulfillment": "eq.delivery", "order": "created_at.desc"}))}
    result = []
    for delivery in deliveries:
        order = orders.get(delivery.get("order_id"))
        if not order or order.get("status") == "cancelled":
            continue
        assigned = delivery.get("assigned_to")
        if assigned == uid or (not assigned and order.get("status") == "handed_to_courier"):
            delivery["order"] = order
            result.append(delivery)
    return result


@app.post("/api/delivery/packages/{delivery_id}/claim")
def claim_delivery_package(delivery_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"delivery"})
    rows = safe(lambda: db.select("deliveries", {"select": "*", "id": f"eq.{delivery_id}", "limit": 1}))
    if not rows:
        raise HTTPException(404, "Package not found.")
    delivery = rows[0]
    order = record("orders", delivery["order_id"])
    if not order or order.get("status") != "handed_to_courier":
        raise HTTPException(409, "This package is not available for delivery selection.")
    if delivery.get("assigned_to") and delivery.get("assigned_to") != user["profile"]["id"]:
        raise HTTPException(409, "Another delivery staff member already selected this package.")
    updated = safe(lambda: db.update("deliveries", {"id": f"eq.{delivery_id}"}, {"assigned_to": user["profile"]["id"], "status": "assigned", "rider_reference": user["profile"].get("staff_id")}))
    log_activity(user["profile"]["id"], "delivery", "claimed_delivery_package", "delivery", delivery_id)
    return updated[0] if updated else {"ok": True}


@app.patch("/api/delivery/packages/{delivery_id}/status")
def update_delivery_progress(delivery_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"delivery"})
    target = str(payload.get("status") or "").strip().lower()
    allowed = {"in_transit", "out_for_delivery", "delivered"}
    if target not in allowed:
        raise HTTPException(400, "Delivery status must be Transit, Out for Delivery, or Delivered.")
    rows = safe(lambda: db.select("deliveries", {"select": "*", "id": f"eq.{delivery_id}", "assigned_to": f"eq.{user['profile']['id']}", "limit": 1}))
    if not rows:
        raise HTTPException(403, "Select this package before updating delivery progress.")
    delivery = rows[0]
    order = record("orders", delivery["order_id"])
    if not order:
        raise HTTPException(404, "Order not found.")
    transitions = {
        "handed_to_courier": {"in_transit"},
        "in_transit": {"out_for_delivery"},
        "out_for_delivery": {"delivered"},
    }
    if target not in transitions.get(order.get("status"), set()):
        raise HTTPException(409, f"Cannot change {order.get('status')} to {target}.")
    changes: dict[str, Any] = {"status": target}
    if target == "in_transit": changes["picked_up_at"] = datetime.now(timezone.utc).isoformat()
    if target == "delivered": changes["delivered_at"] = datetime.now(timezone.utc).isoformat()
    safe(lambda: db.update("deliveries", {"id": f"eq.{delivery_id}"}, changes))
    safe(lambda: db.update("orders", {"id": f"eq.{order['id']}"}, {"status": target}))
    safe(lambda: db.insert("order_status_history", {"order_id": order["id"], "status": target, "note": f"Delivery staff updated status to {target.replace('_',' ')}.", "actor_id": user["profile"]["id"]}))
    log_activity(user["profile"]["id"], "delivery", "updated_delivery_status", "order", order["id"], {"status": target})
    return {"ok": True, "status": target}


@app.post("/api/delivery/packages/{delivery_id}/location")
def update_rider_gps(delivery_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    """Opt-in GPS reporting from an active rider's open mobile web page."""
    require_roles(user, {"delivery"})
    try:
        latitude = float(payload["latitude"])
        longitude = float(payload["longitude"])
        accuracy = float(payload.get("accuracy") or 0)
    except (ValueError, TypeError, KeyError) as exc:
        raise HTTPException(400, "Valid GPS latitude and longitude are required.") from exc
    import math
    if not all(map(math.isfinite, [latitude, longitude, accuracy])) or not (-90 <= latitude <= 90 and -180 <= longitude <= 180 and 0 <= accuracy <= 10000):
        raise HTTPException(400, "Invalid GPS coordinates or accuracy.")
    rows = safe(lambda: db.select("deliveries", {"select": "id,order_id,assigned_to", "id": f"eq.{delivery_id}", "assigned_to": f"eq.{user['profile']['id']}", "limit": 1}))
    if not rows:
        raise HTTPException(403, "Only the assigned rider can share this location.")
    order = record("orders", rows[0]["order_id"])
    if not order or order.get("status") not in {"handed_to_courier", "in_transit", "out_for_delivery"}:
        raise HTTPException(409, "GPS sharing is allowed only during an active delivery.")
    now = datetime.now(timezone.utc).isoformat()
    safe(lambda: db.update("deliveries", {"id": f"eq.{delivery_id}"}, {
        "last_latitude": latitude, "last_longitude": longitude, "last_location_at": now,
    }))
    return {"ok": True, "recorded_at": now}


@app.post("/api/delivery/packages/{delivery_id}/payment-sent")
def delivery_payment_sent(delivery_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"delivery"})
    rows = safe(lambda: db.select("deliveries", {
        "select": "*", "id": f"eq.{delivery_id}",
        "assigned_to": f"eq.{user['profile']['id']}", "limit": 1,
    }))
    if not rows:
        raise HTTPException(403, "Select this package before sending its payment.")
    delivery = rows[0]
    order = record("orders", delivery["order_id"])
    if not order:
        raise HTTPException(404, "Order not found.")
    if order.get("payment_status") == "paid":
        return {"ok": True, "payment_sent_at": delivery.get("payment_sent_at"), "already_paid": True}
    if order.get("payment_method") != "cash_on_delivery":
        raise HTTPException(409, "Payment Sent is only required for cash-on-delivery packages.")
    if order.get("status") not in {"delivered", "order_received"}:
        raise HTTPException(409, "Payment can be sent only after the package is marked Delivered.")
    if delivery.get("payment_sent_at"):
        return {"ok": True, "payment_sent_at": delivery.get("payment_sent_at")}
    sent_at = datetime.now(timezone.utc).isoformat()
    safe(lambda: db.update("deliveries", {"id": f"eq.{delivery_id}"}, {"payment_sent_at": sent_at}))
    log_activity(user["profile"]["id"], "delivery", "payment_sent", "order", order["id"], {"amount": money(order.get("total_amount"))})
    return {"ok": True, "payment_sent_at": sent_at}


# ---------- Admin ----------

@app.get("/api/admin/dashboard")
def dashboard(period: str = "day", date: str | None = None, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    if period not in {"day", "month", "year"}:
        raise HTTPException(400, "Period must be day, month, or year.")
    start, end = date_window(period, date)
    start_iso, end_iso = start.isoformat(), end.isoformat()
    paid = safe(lambda: db.select("payments", [("select", "order_id,amount,paid_at"), ("status", "eq.paid"), ("paid_at", f"gte.{start_iso}"), ("paid_at", f"lt.{end_iso}")]))
    income = sum(money(p["amount"]) for p in paid)
    order_ids = [p["order_id"] for p in paid]
    cogs = 0.0
    if order_ids:
        ids = ",".join(order_ids)
        items = safe(lambda: db.select("order_items", {"select": "quantity,unit_cost_snapshot", "order_id": f"in.({ids})"}))
        cogs = sum(int(i["quantity"]) * money(i["unit_cost_snapshot"]) for i in items)
    expenses = safe(lambda: db.select("operating_expenses", [("select", "amount,expense_date"), ("expense_date", f"gte.{start.date().isoformat()}"), ("expense_date", f"lt.{end.date().isoformat()}")]))
    expense_total = sum(money(x["amount"]) for x in expenses)
    payroll = safe(lambda: db.select("payroll_entries", [("select", "net_amount,paid_at"), ("status", "eq.paid"), ("paid_at", f"gte.{start_iso}"), ("paid_at", f"lt.{end_iso}")]))
    wages = sum(money(x["net_amount"]) for x in payroll)
    receipts = safe(lambda: db.select("product_batches", [("select", "quantity_received,cost_per_unit,delivery_date"), ("delivery_date", f"gte.{start.date().isoformat()}"), ("delivery_date", f"lt.{end.date().isoformat()}")]))
    stock_purchases = sum(int(x["quantity_received"]) * money(x["cost_per_unit"]) for x in receipts)
    gross_profit = income - cogs
    cash_outflow = stock_purchases + expense_total + wages
    operating_result = gross_profit - expense_total - wages
    all_inventory = safe(lambda: db.select("branch_inventory", {"select": "on_hand,reserved,reorder_level"}))
    low_stock = sum(1 for x in all_inventory if int(x["on_hand"]) - int(x["reserved"]) <= int(x["reorder_level"]))
    orders = safe(lambda: db.select("orders", [("select", "*"), ("created_at", f"gte.{start_iso}"), ("created_at", f"lt.{end_iso}"), ("order", "created_at.desc")]))
    prescriptions = safe(lambda: db.select("prescriptions", {"select": "id", "status": "eq.pending"}))
    consultations = safe(lambda: db.select("consultations", {"select": "id", "status": "in.(open,waiting_pharmacist)"}))
    recent_activity = safe(lambda: db.select("activity_logs", {"select": "*", "order": "created_at.desc", "limit": 20}))
    return {
        "period": period,
        "referenceDate": (start.date().isoformat()),
        "income": round(income, 2),
        "cogs": round(cogs, 2),
        "grossProfit": round(gross_profit, 2),
        "stockPurchases": round(stock_purchases, 2),
        "operatingExpenses": round(expense_total, 2),
        "wages": round(wages, 2),
        "cashOutflow": round(cash_outflow, 2),
        "operatingResult": round(operating_result, 2),
        "salesCount": len(set(order_ids)),
        "ordersCount": len(orders),
        "lowStockCount": low_stock,
        "pendingPrescriptionCount": len(prescriptions),
        "openConsultationCount": len(consultations),
        "orders": orders[:20],
        "activity": recent_activity,
    }


@app.get("/api/admin/staff")
def admin_staff(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    return safe(lambda: db.select("profiles", {
        "select": "id,staff_id,full_name,email,phone,role,is_active,created_at",
        "role": "in.(pharmacist,merchandiser,delivery)",
        "order": "role.asc,full_name.asc",
    }))


@app.post("/api/admin/staff")
def create_staff_account(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    role = str(payload.get("role") or "").lower().strip()
    email = str(payload.get("email") or "").lower().strip()
    staff_id = normalize_staff_id(payload.get("staff_id"))
    full_name = normalize_name(payload.get("full_name"))
    if role not in {"pharmacist", "merchandiser", "delivery"}:
        raise HTTPException(400, "Choose Pharmacist, Merchandiser, or Delivery staff.")
    if not valid_email(email) or not 2 <= len(full_name) <= 160:
        raise HTTPException(400, "A valid staff email address and full name are required.")
    if not STAFF_ID_RE.fullmatch(staff_id):
        raise HTTPException(400, "Staff ID must have 3–32 letters, numbers, hyphens or underscores.")
    password = validate_password(payload.get("password"))
    if "confirm_password" in payload and password != str(payload["confirm_password"]):
        raise HTTPException(400, "Initial passwords do not match.")
    if safe(lambda: db.select("profiles", {"select": "id", "staff_id": f"eq.{staff_id}", "limit": 1})):
        raise HTTPException(409, "That Staff ID is already assigned.")
    if safe(lambda: db.select("profiles", {"select": "id", "email": f"eq.{email}", "limit": 1})):
        raise HTTPException(409, "That email belongs to an existing account. Use a different email.")
    created = auth_safe(lambda: auth_gateway.create_staff_account(email, password, full_name))
    uid = created.get("id") or (created.get("user") or {}).get("id")
    if not uid:
        raise HTTPException(502, "Supabase did not return the new staff account ID.")
    try:
        # The auth.users trigger may have inserted a default customer profile.
        # Upsert replaces it with the Admin's selected staff role before login.
        rows = safe(lambda: db.upsert("profiles", {
            "id": uid, "staff_id": staff_id, "username": None,
            "full_name": full_name, "email": email, "phone": payload.get("phone") or None,
            "role": role, "is_active": True,
        }, "id"))
        if not rows:
            raise HTTPException(503, "Staff account could not be saved to PostgreSQL.")
    except Exception:
        # Prevent an orphaned, auto-confirmed user from accidentally signing
        # in as a customer if staff profile creation failed.
        try:
            auth_gateway.delete_staff_identity(str(uid))
        except AuthServiceError as exc:
            raise HTTPException(503, "Staff profile could not be saved. The Auth account may still exist; check Authentication > Users before retrying.") from exc
        raise
    row = rows[0]
    log_activity(user["profile"]["id"], "admin", "created_staff_account", "profile", uid,
                 {"role": role, "staff_id": staff_id})
    return {**row, "created": True}


@app.patch("/api/admin/staff/{profile_id}")
def update_staff(profile_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    rows = safe(lambda: db.select("profiles", {
        "select": "id,staff_id,role,email", "id": f"eq.{profile_id}",
        "role": "in.(pharmacist,merchandiser,delivery)", "limit": 1,
    }))
    if not rows:
        raise HTTPException(404, "Staff account not found.")
    if "password" in payload:
        raise HTTPException(400, "Staff set their own passwords. Send a reset link instead.")
    allowed = {k: payload[k] for k in ["phone", "is_active"] if k in payload}
    if "role" in payload:
        new_role = str(payload["role"]).strip().lower()
        if new_role not in {"pharmacist", "merchandiser", "delivery"}:
            raise HTTPException(400, "Choose a permitted staff role.")
        allowed["role"] = new_role
    if "full_name" in payload:
        name = normalize_name(payload.get("full_name"))
        if not 2 <= len(name) <= 160:
            raise HTTPException(400, "Enter a valid name.")
        allowed["full_name"] = name
    if not allowed:
        raise HTTPException(400, "No staff details to update.")
    result = safe(lambda: db.update("profiles", {"id": f"eq.{profile_id}"}, allowed))
    log_activity(user["profile"]["id"], "admin", "updated_staff_account", "profile", profile_id,
                 {k: v for k, v in allowed.items()})
    return result[0] if result else {"ok": True}


@app.post("/api/admin/staff/{profile_id}/password-link")
def send_staff_password_link(profile_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    rows = safe(lambda: db.select("profiles", {
        "select": "id,email", "id": f"eq.{profile_id}",
        "role": "in.(pharmacist,merchandiser,delivery)", "limit": 1,
    }))
    if not rows or not rows[0].get("email"):
        raise HTTPException(404, "Staff email not found.")
    auth_safe(lambda: auth_gateway.request_recovery(rows[0]["email"]))
    return {"ok": True, "message": "Password recovery email requested for this staff member."}


@app.get("/api/admin/promotions")
def admin_promotions(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    promos = safe(lambda: db.select("promotions", {"select": "*", "order": "created_at.desc"}))
    links = safe(lambda: db.select("promotion_products", {"select": "promotion_id,product_id"}))
    for promo in promos:
        promo["product_ids"] = [x["product_id"] for x in links if x["promotion_id"] == promo["id"]]
    return promos


@app.post("/api/admin/promotions")
def create_promotion(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    if payload.get("kind") not in {"hot_deal", "sale", "promo"}:
        raise HTTPException(400, "Promotion kind must be hot_deal, sale, or promo.")
    if payload.get("discount_type") not in {"percentage", "fixed"}:
        raise HTTPException(400, "Discount type must be percentage or fixed.")
    row = safe(lambda: db.insert("promotions", {
        "kind": payload["kind"], "title": payload.get("title") or "Promotion", "subtitle": payload.get("subtitle") or None,
        "banner_image_url": payload.get("banner_image_url") or None, "discount_type": payload["discount_type"],
        "discount_value": money(payload.get("discount_value")), "starts_at": payload.get("starts_at") or None,
        "ends_at": payload.get("ends_at") or None, "priority": int(payload.get("priority") or 0),
        "is_active": bool(payload.get("is_active", True)), "created_by": user["profile"]["id"],
    }))[0]
    for pid in parse_ids(payload.get("product_ids")):
        safe(lambda pid=pid: db.upsert("promotion_products", {"promotion_id": row["id"], "product_id": pid}, "promotion_id,product_id"))
    log_activity(user["profile"]["id"], "admin", "created_promotion", "promotion", row["id"], {"kind": row["kind"]})
    return row


@app.patch("/api/admin/promotions/{promotion_id}")
def update_promotion(promotion_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    allowed_names = ["kind","title","subtitle","banner_image_url","discount_type","discount_value","starts_at","ends_at","priority","is_active"]
    allowed = {k: payload[k] for k in allowed_names if k in payload}
    if "discount_value" in allowed:
        allowed["discount_value"] = money(allowed["discount_value"])
    result = safe(lambda: db.update("promotions", {"id": f"eq.{promotion_id}"}, allowed))
    if "product_ids" in payload:
        safe(lambda: db.delete("promotion_products", {"promotion_id": f"eq.{promotion_id}"}))
        for pid in parse_ids(payload.get("product_ids")):
            safe(lambda pid=pid: db.insert("promotion_products", {"promotion_id": promotion_id, "product_id": pid}))
    log_activity(user["profile"]["id"], "admin", "updated_promotion", "promotion", promotion_id)
    return result[0] if result else {"ok": True}


@app.delete("/api/admin/promotions/{promotion_id}")
def delete_promotion(promotion_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    safe(lambda: db.delete("promotions", {"id": f"eq.{promotion_id}"}))
    log_activity(user["profile"]["id"], "admin", "deleted_promotion", "promotion", promotion_id)
    return {"ok": True}


MASTER_TABLES = {
    "branches": {"name","address_line","barangay","city","province","postal_code","phone","latitude","longitude","pickup_instructions","is_pickup_enabled","is_delivery_enabled","is_active"},
    "categories": {"name","slug","icon","sort_order","is_active"},
    "manufacturers": {"name","logo_url","website_url","is_partner","is_active"},
    "suppliers": {"name","contact_name","email","phone","is_active"},
}


@app.get("/api/admin/master/{table}")
def get_master(table: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    if table not in MASTER_TABLES:
        raise HTTPException(404, "Unsupported master-data table.")
    return safe(lambda: db.select(table, {"select": "*", "order": "created_at.desc"}))


@app.post("/api/admin/master/{table}")
def create_master(table: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    if table not in MASTER_TABLES:
        raise HTTPException(404, "Unsupported master-data table.")
    row = {k: payload[k] for k in MASTER_TABLES[table] if k in payload}
    result = safe(lambda: db.insert(table, row))
    log_activity(user["profile"]["id"], "admin", "created_master_data", table, result[0].get("id") if result else None)
    return result[0] if result else row


@app.patch("/api/admin/master/{table}/{row_id}")
def update_master(table: str, row_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    if table not in MASTER_TABLES:
        raise HTTPException(404, "Unsupported master-data table.")
    row = {k: payload[k] for k in MASTER_TABLES[table] if k in payload}
    result = safe(lambda: db.update(table, {"id": f"eq.{row_id}"}, row))
    log_activity(user["profile"]["id"], "admin", "updated_master_data", table, row_id)
    return result[0] if result else {"ok": True}


@app.post("/api/admin/products")
def create_product(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    if not str(payload.get("name") or "").strip():
        raise HTTPException(400, "Medicine/product name is required.")
    allowed = ["sku","category_id","manufacturer_id","name","generic_name","brand","dosage_form","strength","short_use","description","selling_price","requires_prescription","image_url","is_active"]
    row = {k: payload.get(k) for k in allowed if k in payload}
    row["selling_price"] = money(row.get("selling_price"))
    row["created_by"] = user["profile"]["id"]
    result = safe(lambda: db.insert("products", row))
    log_activity(user["profile"]["id"], "admin", "created_product", "product", result[0].get("id") if result else None)
    return result[0]


@app.patch("/api/admin/products/{product_id}")
def admin_product_update(product_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    allowed = ["sku","category_id","manufacturer_id","name","generic_name","brand","dosage_form","strength","short_use","description","selling_price","requires_prescription","image_url","is_active"]
    row = {k: payload[k] for k in allowed if k in payload}
    if "selling_price" in row:
        row["selling_price"] = money(row["selling_price"])
    result = safe(lambda: db.update("products", {"id": f"eq.{product_id}"}, row))
    log_activity(user["profile"]["id"], "admin", "updated_product", "product", product_id)
    return result[0] if result else {"ok": True}


@app.post("/api/admin/expenses")
def add_expense(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    result = safe(lambda: db.insert("operating_expenses", {
        "expense_date": payload.get("expense_date"), "category": payload.get("category"),
        "description": payload.get("description"), "amount": money(payload.get("amount")), "recorded_by": user["profile"]["id"],
    }))
    log_activity(user["profile"]["id"], "admin", "recorded_expense", "operating_expense", result[0].get("id") if result else None)
    return result[0]


@app.post("/api/admin/payroll")
def add_payroll(payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    gross = money(payload.get("gross_wage")); deductions = money(payload.get("deductions")); net = max(0, gross - deductions)
    status = payload.get("status") if payload.get("status") in {"pending", "paid"} else "pending"
    result = safe(lambda: db.insert("payroll_entries", {
        "employee_id": payload.get("employee_id"), "period_start": payload.get("period_start"), "period_end": payload.get("period_end"),
        "gross_wage": gross, "deductions": deductions, "net_amount": net, "status": status,
        "paid_at": datetime.now(timezone.utc).isoformat() if status == "paid" else None, "recorded_by": user["profile"]["id"],
    }))
    log_activity(user["profile"]["id"], "admin", "recorded_payroll", "payroll_entry", result[0].get("id") if result else None)
    return result[0]


@app.get("/api/admin/orders")
def admin_orders(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    rows = safe(lambda: db.select("orders", {"select": "*", "order": "created_at.desc", "limit": 100}))
    delivery_rows = safe(lambda: db.select("deliveries", {"select": "id,order_id,assigned_to,status,rider_reference,payment_sent_at"}))
    delivery_by_order = {d["order_id"]: d for d in delivery_rows}
    for row in rows:
        row["delivery"] = delivery_by_order.get(row.get("id"))
    return rows


@app.patch("/api/admin/orders/{order_id}/status")
def update_order_status(order_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    target = str(payload.get("status") or "").strip().lower()
    current = record("orders", order_id)
    if not current:
        raise HTTPException(404, "Order not found.")
    if target == "completed" and current.get("payment_status") != "paid":
        raise HTTPException(409, "Mark this order Paid before marking it Completed.")
    if target == "cancelled":
        allowed = True
    elif current["fulfillment"] == "pickup":
        allowed = target in {
            "placed": {"preparing"}, "confirmed": {"preparing"}, "preparing": {"ready_for_pickup"},
            "picked_up": {"completed"},
        }.get(current["status"], set())
    else:
        allowed = target in {
            "placed": {"preparing"}, "confirmed": {"preparing"}, "preparing": {"handed_to_courier"},
            "order_received": {"completed"},
        }.get(current["status"], set())
    if not allowed:
        raise HTTPException(409, f"That status change is not allowed from {current['status']} for this {current['fulfillment']} order.")
    safe(lambda: db.update("orders", {"id": f"eq.{order_id}"}, {"status": target}))
    safe(lambda: db.insert("order_status_history", {"order_id": order_id, "status": target, "note": payload.get("note") or None, "actor_id": user["profile"]["id"]}))
    if current["fulfillment"] == "delivery" and target == "handed_to_courier":
        existing = safe(lambda: db.select("deliveries", {"select": "id", "order_id": f"eq.{order_id}", "limit": 1}))
        if existing:
            safe(lambda: db.update("deliveries", {"order_id": f"eq.{order_id}"}, {"status": "queued", "assigned_to": None}))
        else:
            safe(lambda: db.insert("deliveries", {"order_id": order_id, "status": "queued", "provider": "staff-delivery"}))
    if target == "cancelled" and current["status"] != "cancelled":
        safe(lambda: db.update("deliveries", {"order_id": f"eq.{order_id}"}, {"status": "cancelled"}))
        items = safe(lambda: db.select("order_items", {"select": "product_id,quantity", "order_id": f"eq.{order_id}"}))
        for item in items:
            inv = safe(lambda i=item: db.select("branch_inventory", {"select": "*", "branch_id": f"eq.{current['branch_id']}", "product_id": f"eq.{i['product_id']}", "limit": 1}))
            if inv:
                safe(lambda i=item, inv=inv: db.update("branch_inventory", {"branch_id": f"eq.{current['branch_id']}", "product_id": f"eq.{i['product_id']}"}, {"on_hand": int(inv[0]["on_hand"]) + int(i["quantity"])}))
                sale_moves = safe(lambda i=item: db.select("stock_movements", {"select": "*", "branch_id": f"eq.{current['branch_id']}", "product_id": f"eq.{i['product_id']}", "movement_type": "eq.sale", "reference_id": f"eq.{order_id}"}))
                for move in sale_moves:
                    restore_qty = abs(int(move.get("quantity") or 0))
                    if move.get("batch_id") and restore_qty:
                        batch_rows = safe(lambda m=move: db.select("product_batches", {"select": "*", "id": f"eq.{m['batch_id']}", "limit": 1}))
                        if batch_rows:
                            safe(lambda b=batch_rows[0], q=restore_qty: db.update("product_batches", {"id": f"eq.{b['id']}"}, {"quantity_remaining": int(b.get("quantity_remaining") or 0) + q}))
                    safe(lambda m=move, q=restore_qty: db.insert("stock_movements", {"branch_id": current["branch_id"], "product_id": i["product_id"], "batch_id": m.get("batch_id"), "movement_type": "cancel_restore", "quantity": q, "reference_type": "order", "reference_id": order_id, "actor_id": user["profile"]["id"]}))
    log_activity(user["profile"]["id"], "admin", "updated_order_status", "order", order_id, {"status": target})
    return {"ok": True, "status": target}


@app.patch("/api/admin/orders/{order_id}/payment")
def update_payment(order_id: str, payload: dict[str, Any], user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    status = payload.get("status")
    if status not in {"paid", "failed", "refunded", "pending", "unpaid"}:
        raise HTTPException(400, "Invalid payment status.")
    order = record("orders", order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    if status == "paid" and order.get("fulfillment") == "delivery" and order.get("payment_method") == "cash_on_delivery":
        delivery_rows = safe(lambda: db.select("deliveries", {"select": "id,payment_sent_at", "order_id": f"eq.{order_id}", "limit": 1}))
        if not delivery_rows or not delivery_rows[0].get("payment_sent_at"):
            raise HTTPException(409, "Wait for the delivery staff to click Payment Sent before marking this delivery Paid.")
    paid_at = datetime.now(timezone.utc).isoformat() if status == "paid" else None
    safe(lambda: db.update("orders", {"id": f"eq.{order_id}"}, {"payment_status": status}))
    payments = safe(lambda: db.select("payments", {"select": "id", "order_id": f"eq.{order_id}", "limit": 1}))
    if payments:
        safe(lambda: db.update("payments", {"id": f"eq.{payments[0]['id']}"}, {"status": status, "paid_at": paid_at}))
    log_activity(user["profile"]["id"], "admin", "updated_payment_status", "order", order_id, {"status": status})
    return {"ok": True}


@app.get("/api/admin/activity")
def activity(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    return safe(lambda: db.select("activity_logs", {"select": "*", "order": "created_at.desc", "limit": 100}))


@app.get("/api/admin/integrations")
def admin_integrations(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    return integration_statuses()


@app.get("/api/admin/financial-report.pdf")
def download_financial_report(period: str = "day", date: str | None = None, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin"})
    report = dashboard(period, date, user)
    pdf = financial_pdf(report)
    name = f"pharmacy360-financial-{period}-{report['referenceDate']}.pdf"
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@app.get("/api/inventory/report.pdf")
def download_inventory_report(user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"admin", "merchandiser"})
    data = inventory(user)
    pdf = inventory_pdf(data)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="pharmacy360-inventory.pdf"', "Cache-Control": "no-store"})


@app.get("/api/delivery/packages/{delivery_id}/receipt")
def delivery_receipt_data(delivery_id: str, user: dict[str, Any] = Depends(current_user)):
    require_roles(user, {"delivery"})
    rows = safe(lambda: db.select("deliveries", {"select": "id,order_id,assigned_to", "id": f"eq.{delivery_id}", "limit": 1}))
    if not rows or rows[0].get("assigned_to") != user["profile"]["id"]:
        raise HTTPException(403, "Only the assigned rider can access this receipt.")
    order = record("orders", rows[0]["order_id"])
    if not order or order.get("fulfillment") != "delivery":
        raise HTTPException(404, "Delivery order not found.")
    items = safe(lambda: db.select("order_items", {"select": "product_name_snapshot,quantity,final_unit_price,line_total", "order_id": f"eq.{order['id']}"}))
    return {"order_number": order.get("order_number"), "created_at": order.get("created_at"),
            "payment_method": order.get("payment_method"), "payment_status": order.get("payment_status"),
            "total_amount": order.get("total_amount"), "items": items}


@app.post("/api/webhooks/delivery/{provider}")
def delivery_webhook(provider: str, payload: dict[str, Any], x_webhook_secret: str | None = Header(default=None)):
    # Integration boundary only: provider-specific signature validation belongs in the adapter.
    # This route intentionally refuses unsigned updates until a provider is configured.
    if not integration_configured("delivery"):
        raise HTTPException(503, "Delivery microservice is not configured.")
    if not x_webhook_secret:
        raise HTTPException(401, "Missing delivery webhook signature/secret.")
    return {"accepted": True, "provider": provider, "note": "Connect provider-specific verification in server/integrations.py"}
