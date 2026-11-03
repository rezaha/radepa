"""Persistent routing metadata; support message bodies are not retained here."""
import uuid

from app.db.database import get_connection
from app.utils.time_utils import now_iso


class SupportRepo:
    @staticmethod
    def create(user_id: int, message_id: int) -> str:
        ticket_id = uuid.uuid4().hex
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO support_tickets (id,telegram_user_id,user_message_id,created_at) VALUES (?,?,?,?)",
                (ticket_id, user_id, message_id, now_iso()),
            )
        return ticket_id

    @staticmethod
    def get(ticket_id: str):
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,)).fetchone()
        return dict(row) if row else None

    @staticmethod
    def record_delivery(chat_id: int, message_id: int, ticket_id: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO support_deliveries (admin_chat_id,admin_message_id,ticket_id) VALUES (?,?,?)",
                (chat_id, message_id, ticket_id),
            )

    @staticmethod
    def for_reply(chat_id: int, message_id: int):
        with get_connection() as conn:
            row = conn.execute(
                """SELECT t.* FROM support_deliveries d JOIN support_tickets t ON t.id=d.ticket_id
                   WHERE d.admin_chat_id=? AND d.admin_message_id=?""", (chat_id, message_id),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def username_matches(username: str):
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM users WHERE lower(ltrim(username,'@'))=? LIMIT 2",
                (username.lower(),),
            ).fetchall()
        return [dict(row) for row in rows]
