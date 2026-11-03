"""
web/app.py — FastAPI application for the Sollunga shop owner dashboard.

Reuses core/inventory.py business logic and database models directly.
Never exposes Telegram API tokens or LLM credentials to the frontend.
"""

import asyncio
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Request, Form, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

from core.inventory import (
    add_new_item,
    clear_sales_history,
    delete_item,
    get_low_stock_items,
    get_order_detail,
    get_orders_list,
    get_sales_for_date,
    get_sales_summary,
    get_stock_list,
    get_todays_orders,
    get_todays_sales_total,
    reset_sales,
    update_item,
    update_order_status,
)
from web.auth import (
    _COOKIE_NAME,
    create_session_token,
    get_current_user,
    get_dashboard_password,
    require_auth,
)
from core.analytics import get_dashboard_data

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
# Pick up template edits without restarting the server
templates.env.auto_reload = True

app = FastAPI(title="Sollunga Shop Owner Dashboard")

STATIC_DIR = os.path.join(BASE_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------------------------------------------------------------------------
# Favicon
# ---------------------------------------------------------------------------

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Serve the branded SVG icon for browsers requesting /favicon.ico."""
    return FileResponse(
        os.path.join(STATIC_DIR, "favicon.svg"),
        media_type="image/svg+xml",
    )


# ---------------------------------------------------------------------------
# Health & Status Endpoint
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """System health check endpoint."""
    import sqlite3
    from core.db import get_conn, get_all_items, get_all_shops

    db_ok = False
    item_count = 0
    shop_count = 0
    try:
        with get_conn() as con:
            cur = con.execute("SELECT 1")
            db_ok = cur.fetchone()[0] == 1
        items = get_all_items()
        item_count = len(items)
        shops = get_all_shops()
        shop_count = len(shops)
    except Exception as exc:
        db_ok = False

    return {
        "status": "healthy" if db_ok else "unhealthy",
        "service": "Sollunga AI Order Bot & Dashboard",
        "database": "connected" if db_ok else "error",
        "total_items": item_count,
        "total_shops": shop_count,
        "channels": {
            "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
            "whatsapp": bool(os.getenv("WHATSAPP_PHONE_NUMBER_ID")),
        },
    }


# ---------------------------------------------------------------------------
# Authentication Routes
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(request=request, name="login.html", context={"user": None})


@app.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, password: str = Form(...)):
    correct_password = get_dashboard_password()
    if password.strip() != correct_password:
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"user": None, "error": "Invalid owner password. Please try again."},
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    token = create_session_token("owner")
    response.set_cookie(
        key=_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        max_age=86400 * 7,
    )
    return response


@app.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(key=_COOKIE_NAME)
    return response


# ---------------------------------------------------------------------------
# Home Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def home_page(request: Request, user: str = Depends(require_auth)):
    recent_orders = get_todays_orders()
    today_sales = get_todays_sales_total()
    low_stock = get_low_stock_items()
    low_threshold = int(os.getenv("LOW_STOCK_THRESHOLD", "3"))

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={
            "user": user,
            "recent_orders": recent_orders,
            "today_orders_count": len(recent_orders),
            "today_sales": today_sales,
            "low_stock_items": low_stock,
            "low_threshold": low_threshold,
        },
    )


# ---------------------------------------------------------------------------
# Analytics Dashboard (Chart.js)
# ---------------------------------------------------------------------------

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(
    request: Request, shop_id: Optional[int] = None, user: str = Depends(require_auth)
):
    data = get_dashboard_data(shop_id=shop_id)
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={"user": user, "data": data},
    )


@app.get("/api/dashboard")
async def dashboard_api(
    shop_id: Optional[int] = None, days: int = 30, user: str = Depends(require_auth)
):
    """JSON feed behind the analytics dashboard (KPIs + chart series)."""
    return get_dashboard_data(shop_id=shop_id, days=days)


# ---------------------------------------------------------------------------
# Items Management
# ---------------------------------------------------------------------------

@app.get("/items", response_class=HTMLResponse)
async def items_list(request: Request, user: str = Depends(require_auth)):
    items = get_stock_list()
    return templates.TemplateResponse(
        request=request,
        name="items.html",
        context={"user": user, "items": items},
    )



@app.get("/items/new", response_class=HTMLResponse)
async def item_new_page(request: Request, user: str = Depends(require_auth)):
    return templates.TemplateResponse(
        request=request,
        name="item_new.html",
        context={"user": user},
    )


@app.post("/items/new", response_class=HTMLResponse)
async def item_create_submit(
    request: Request,
    name: str = Form(...),
    unit: str = Form(...),
    price: float = Form(...),
    stock: float = Form(...),
    aliases: str = Form(""),
    user: str = Depends(require_auth),
):
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    try:
        add_new_item(name=name, unit=unit, price=price, stock=stock, aliases=alias_list)
        return RedirectResponse(url="/items", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="item_new.html",
            context={"user": user, "error": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@app.get("/items/edit/{item_id}", response_class=HTMLResponse)
async def item_edit_page(request: Request, item_id: int, user: str = Depends(require_auth)):
    from core.db import get_item_by_id

    item = get_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return templates.TemplateResponse(
        request=request,
        name="item_edit.html",
        context={"user": user, "item": item},
    )


@app.post("/items/edit/{item_id}", response_class=HTMLResponse)
async def item_edit_submit(
    request: Request,
    item_id: int,
    price: float = Form(...),
    stock: float = Form(...),
    unit: str = Form(...),
    aliases: str = Form(""),
    user: str = Depends(require_auth),
):
    alias_list = [a.strip() for a in aliases.split(",") if a.strip()]
    try:
        update_item(item_id=item_id, price=price, stock=stock, unit=unit, aliases=alias_list)
        return RedirectResponse(url="/items", status_code=status.HTTP_303_SEE_OTHER)
    except ValueError as exc:
        from core.db import get_item_by_id

        item = get_item_by_id(item_id)
        return templates.TemplateResponse(
            request=request,
            name="item_edit.html",
            context={"user": user, "item": item, "error": str(exc)},
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@app.post("/items/delete/{item_id}")
async def item_delete_submit(item_id: int, user: str = Depends(require_auth)):
    delete_item(item_id)
    return RedirectResponse(url="/items", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Orders Management
# ---------------------------------------------------------------------------

@app.get("/orders", response_class=HTMLResponse)
async def orders_page(
    request: Request,
    status: str = "all",
    date: str = "all",
    user: str = Depends(require_auth),
):
    orders = get_orders_list(status_filter=status, date_filter=date)
    return templates.TemplateResponse(
        request=request,
        name="orders.html",
        context={
            "user": user,
            "orders": orders,
            "current_status": status,
            "current_date": date,
        },
    )



@app.post("/orders/{order_id}/status")
async def order_status_submit(
    order_id: int,
    status_val: str = Form(..., alias="status"),
    user: str = Depends(require_auth),
):
    try:
        update_order_status(order_id, status_val)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Send notification to customer via Telegram or WhatsApp
    try:
        order = get_order_detail(order_id)
        if order and order.customer_id:
            from bot.messages import format_customer_status_update
            msg_text = format_customer_status_update(order_id, status_val)
            bot_token = os.getenv("TELEGRAM_BOT_TOKEN")

            if bot_token and order.customer_id.isdigit():
                import httpx
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                async with httpx.AsyncClient(timeout=4.0) as client:
                    resp = await client.post(
                        url,
                        json={
                            "chat_id": int(order.customer_id),
                            "text": msg_text,
                            "parse_mode": "Markdown",
                        },
                    )
                    logger.info("Web dashboard notified Telegram customer %s: %s (status %s)", order.customer_id, resp.status_code, status_val)

            wa_token = os.getenv("WHATSAPP_ACCESS_TOKEN")
            wa_phone_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
            if wa_token and wa_phone_id and not order.customer_id.startswith("-"):
                from core.whatsapp import WhatsAppChannel
                wa_channel = WhatsAppChannel(phone_number_id=wa_phone_id, access_token=wa_token)
                await wa_channel.send_text(order.customer_id, msg_text)
                logger.info("Web dashboard notified WhatsApp customer %s (status %s)", order.customer_id, status_val)
    except Exception as exc:
        logger.warning("Could not notify customer about status update: %s", exc)

    return RedirectResponse(url="/orders", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Sales & Reports (resettable total, week/month/single-day views)
# ---------------------------------------------------------------------------

@app.get("/sales", response_class=HTMLResponse)
async def sales_page(
    request: Request,
    day: str = "",
    user: str = Depends(require_auth),
):
    summary = get_sales_summary()
    day_report = None
    day_error = None
    if day:
        try:
            datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            day_error = f"'{day}' is not a valid date (use YYYY-MM-DD)."
            day = ""
        else:
            day_report = get_sales_for_date(day)

    reset_done = request.query_params.get("reset") == "1"
    cleared = request.query_params.get("cleared") == "1"
    success = None
    if reset_done:
        success = "Sales reset to ₹0.00 — Total, Today, This Week and This Month now count from zero. Past orders are kept."
    elif cleared:
        success = "All sales history cleared. Your dashboard is now fresh — items and stock were kept."

    return templates.TemplateResponse(
        request=request,
        name="sales.html",
        context={
            "user": user,
            "summary": summary,
            "day": day,
            "day_report": day_report,
            "day_error": day_error,
            "success": success,
            "today_iso": date.today().isoformat(),
            "yesterday_iso": (date.today() - timedelta(days=1)).isoformat(),
        },
    )


@app.post("/sales/reset")
async def sales_reset_submit(user: str = Depends(require_auth)):
    """Zero the resettable 'total sold' counter (past orders are kept)."""
    reset_sales()
    return RedirectResponse(url="/sales?reset=1", status_code=status.HTTP_303_SEE_OTHER)


@app.post("/sales/clear-history")
async def sales_clear_history_submit(user: str = Depends(require_auth)):
    """Permanently delete all sales history (orders). Items/stock are kept."""
    clear_sales_history()
    return RedirectResponse(url="/sales?cleared=1", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# WhatsApp Cloud API Webhook (Phase 4)
# ---------------------------------------------------------------------------

@app.get("/whatsapp/webhook")
async def whatsapp_webhook_verify(request: Request):
    """
    Meta Webhook Verification endpoint.
    Meta sends GET with hub.mode, hub.verify_token, hub.challenge.
    """
    from core.whatsapp import WhatsAppChannel
    wa = WhatsAppChannel()

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == wa.verify_token:
        # Challenge must be returned as plain text integer/string
        return HTMLResponse(content=challenge, status_code=200)

    raise HTTPException(status_code=403, detail="Verification token mismatch")


@app.post("/whatsapp/webhook")
async def whatsapp_webhook_receive(request: Request):
    """
    Meta Webhook Inbound Message Receiver.
    Processes incoming text messages, button selections, and audio/voice notes.
    """
    import logging
    logger = logging.getLogger(__name__)

    # Telegram-only mode: if WhatsApp isn't configured, ignore webhook traffic.
    if not os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip():
        return {"status": "ignored", "reason": "whatsapp_disabled"}

    try:
        body = await request.json()
    except Exception:
        return {"status": "ignored"}

    from core.whatsapp import WhatsAppChannel, parse_whatsapp_webhook
    from core.service import (
        handle_customer_text,
        handle_order_confirmation,
        handle_order_cancellation,
    )
    from core.transcription import transcribe_audio_bytes

    wa_channel = WhatsAppChannel()
    events = parse_whatsapp_webhook(body)

    for ev in events:
        customer_id = ev["from"]
        customer_name = ev.get("name", customer_id)
        ev_type = ev.get("type")

        # Handle interactive button callbacks
        if ev_type == "button":
            payload = ev.get("payload", "")
            if payload == "order:confirm":
                await handle_order_confirmation(
                    channel=wa_channel,
                    customer_id=customer_id,
                    customer_display_name=f"{customer_name} (+{customer_id})",
                    original_text="",
                )
            elif payload == "order:cancel":
                await handle_order_cancellation(
                    channel=wa_channel,
                    customer_id=customer_id,
                    original_text="",
                )
            continue

        # Handle voice note / audio
        if ev_type == "audio":
            media_id = ev.get("media_id")
            if media_id:
                media_data = await wa_channel.download_media(media_id)
                if media_data:
                    raw_audio, mime_type = media_data
                    transcription = await asyncio.to_thread(
                        transcribe_audio_bytes, raw_audio, mime_type=mime_type
                    )

                    if not transcription.text:
                        await wa_channel.send_text(
                            customer_id,
                            transcription.clarification_prompt or "🎤 Could not hear clearly. Please send as text or record again!",
                        )
                        continue

                    # If unsure, ask customer to confirm
                    if not transcription.is_confident and transcription.clarification_prompt:
                        await wa_channel.send_text(
                            customer_id,
                            transcription.clarification_prompt,
                        )
                        continue

                    # Send transcribed feedback and run order flow
                    await wa_channel.send_text(
                        customer_id,
                        f"🎙️ *Heard:* _\"{transcription.text}\"_",
                    )
                    await handle_customer_text(
                        channel=wa_channel,
                        customer_id=customer_id,
                        text=transcription.text,
                    )
            continue

        # Handle plain text message
        if ev_type == "text":
            text = ev.get("text", "").strip()
            # If customer texted confirm/cancel manually
            if text.lower() in ("confirm", "yes", "sari", "ok", "confirm pannunga"):
                await handle_order_confirmation(
                    channel=wa_channel,
                    customer_id=customer_id,
                    customer_display_name=f"{customer_name} (+{customer_id})",
                    original_text=text,
                )
            elif text.lower() in ("cancel", "no", "vendaam"):
                await handle_order_cancellation(
                    channel=wa_channel,
                    customer_id=customer_id,
                    original_text=text,
                )
            else:
                await handle_customer_text(
                    channel=wa_channel,
                    customer_id=customer_id,
                    text=text,
                )

    return {"status": "ok"}


