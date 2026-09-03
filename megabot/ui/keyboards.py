# Inline keyboard builders — callback data format:  action:job_id[:extra]
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def cancel_kb(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🛑 Cancel", callback_data=f"cancel:{job_id}")
    ]])


def archive_choice_kb(job_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Upload archive", callback_data=f"arch:{job_id}:archive"),
            InlineKeyboardButton("📂 Decompress", callback_data=f"arch:{job_id}:extract"),
        ],
        [
            InlineKeyboardButton("🛑 Cancel", callback_data=f"cancel:{job_id}"),
        ],
    ])


def settings_kb(current: dict) -> InlineKeyboardMarkup:
    def toggle(emoji_on, emoji_off, key: str, label: str, value):
        icon = emoji_on if value else emoji_off
        return InlineKeyboardButton(f"{icon} {label}", callback_data=f"set:{key}")

    archive_labels = {"ask": "Ask me", "archive": "Archive as-is", "extract": "Always decompress"}
    return InlineKeyboardMarkup([
        [toggle("📑", "🗂️", "image_pdf", "Images → PDF", current.get("image_pdf", True))],
        [toggle("🎞️", "🎬", "video_thumbs", "Video thumbnails", current.get("video_thumbs", True))],
        [InlineKeyboardButton(f"📦 Archive mode: {archive_labels.get(current.get('archive_mode', 'ask'), 'Ask me')}",
                              callback_data="set:archive_mode")],
    ])