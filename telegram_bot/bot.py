"""
AthenaX Telegram Admin Bot — Method 1: Polling AthenaX API.

Flow:
  1. JobQueue polls GET /api/v1/outreach?status=pending every POLL_INTERVAL seconds.
  2. New drafts (not yet notified) are sent to TELEGRAM_ADMIN_CHAT_ID with inline buttons.
  3. Admin taps ✅ Approve or ❌ Reject → bot calls PATCH /api/v1/outreach/{id}.
  4. Bot confirms the action and updates the message.

Setup:
  TELEGRAM_BOT_TOKEN    — from @BotFather
  TELEGRAM_ADMIN_CHAT_ID — your Telegram user ID (get it from @userinfobot)
  ATHENAX_API_URL       — AthenaX backend URL (default: http://localhost:8000)
"""

import logging
import os

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("BOT_POLL_INTERVAL", "60"))  # seconds
ADMIN_CHAT_ID = int(os.getenv("TELEGRAM_ADMIN_CHAT_ID", "0"))

# Track outreach IDs already sent to Telegram (in-memory; resets on restart)
_notified: set[str] = set()


# ── Helpers ───────────────────────────────────────────────────────────────────


def _get_client():
    from athenax.api.athenax_client import AthenaXClient
    return AthenaXClient()


def _channel_emoji(channel: str) -> str:
    return "🐦" if channel == "twitter_dm" else "📧"


def _format_draft(draft: dict) -> str:
    ch = _channel_emoji(draft.get("channel", "email"))
    channel_label = "Twitter DM" if draft.get("channel") == "twitter_dm" else "Email"
    score = draft.get("compatibility_score")
    score_str = f"⭐ Score: {score}/100\n" if score is not None else ""
    subject = draft.get("subject")
    subject_str = f"📌 Subject: {subject}\n" if subject else ""
    body = draft.get("body", "")
    lead_name = draft.get("lead_name") or draft.get("lead_id", "unknown")

    return (
        f"🔔 <b>New Draft — {lead_name}</b>\n"
        f"{ch} Channel: {channel_label}\n"
        f"{score_str}"
        f"{subject_str}"
        f"\n<i>{body}</i>"
    )


def _approve_reject_keyboard(outreach_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Approve", callback_data=f"approve:{outreach_id}"),
        InlineKeyboardButton("❌ Reject",  callback_data=f"reject:{outreach_id}"),
    ]])


# ── Handlers ──────────────────────────────────────────────────────────────────


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "👋 AthenaX Partnership Bot is running.\n\n"
        "I'll notify you here whenever new outreach drafts are ready for review.\n"
        "Use /status to check pending drafts now."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        pending = _get_client().get_pending_outreach()
    except Exception as exc:
        await update.message.reply_text(f"❌ Could not reach AthenaX API: {exc}")
        return

    if not pending:
        await update.message.reply_text("✅ No pending drafts right now.")
        return

    await update.message.reply_text(
        f"📋 <b>{len(pending)} pending draft(s)</b> — sending them now…",
        parse_mode="HTML",
    )
    for draft in pending:
        oid = draft["outreach_id"]
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=_format_draft(draft),
            parse_mode="HTML",
            reply_markup=_approve_reject_keyboard(oid),
        )
        _notified.add(oid)


async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    action, outreach_id = query.data.split(":", 1)
    status = "approved" if action == "approve" else "rejected"
    emoji = "✅" if status == "approved" else "❌"

    try:
        _get_client().patch_outreach_status(outreach_id, status)
    except Exception as exc:
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(f"❌ API error: {exc}")
        return

    # Replace inline buttons with a status badge
    original_text = query.message.text or query.message.caption or ""
    await query.edit_message_text(
        text=f"{original_text}\n\n{emoji} <b>{status.capitalize()}</b>",
        parse_mode="HTML",
        reply_markup=None,
    )


# ── Polling job ───────────────────────────────────────────────────────────────


async def poll_pending(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not ADMIN_CHAT_ID:
        logger.warning("TELEGRAM_ADMIN_CHAT_ID not set — skipping poll")
        return

    try:
        pending = _get_client().get_pending_outreach()
    except Exception as exc:
        logger.warning("AthenaX API unreachable: %s", exc)
        return

    new_drafts = [d for d in pending if d["outreach_id"] not in _notified]
    if not new_drafts:
        return

    logger.info("Found %d new pending draft(s) — notifying admin", len(new_drafts))
    for draft in new_drafts:
        oid = draft["outreach_id"]
        try:
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=_format_draft(draft),
                parse_mode="HTML",
                reply_markup=_approve_reject_keyboard(oid),
            )
            _notified.add(oid)
        except Exception as exc:
            logger.error("Failed to send draft %s: %s", oid, exc)


# ── Entry point ───────────────────────────────────────────────────────────────


def run_bot() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set in .env")
    if not ADMIN_CHAT_ID:
        raise ValueError("TELEGRAM_ADMIN_CHAT_ID is not set in .env")

    app = (
        Application.builder()
        .token(token)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CallbackQueryHandler(handle_button))

    # Schedule the polling job
    app.job_queue.run_repeating(
        poll_pending,
        interval=POLL_INTERVAL,
        first=5,  # first run 5 seconds after startup
    )

    logger.info(
        "Bot started — polling AthenaX API every %ds, admin chat=%d",
        POLL_INTERVAL,
        ADMIN_CHAT_ID,
    )
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    run_bot()
