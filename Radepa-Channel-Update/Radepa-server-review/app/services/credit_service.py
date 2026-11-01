"""Atomic per-service reservations, completion and idempotent refunds."""
import uuid
from app.db.database import get_connection
from app.utils.time_utils import now_iso, is_expired

class CreditService:
    @staticmethod
    def reserve(user_id, service):
        if service not in ("email", "instagram"):
            raise ValueError("Unknown service")
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            user = conn.execute("SELECT * FROM users WHERE telegram_user_id=?", (user_id,)).fetchone()
            if not user or user["is_blocked"]:
                return None
            if conn.execute("SELECT 1 FROM search_charges WHERE telegram_user_id=? AND service=? AND status='reserved'",
                            (user_id, service)).fetchone():
                return None
            column = service + "_credits"
            if user[column] <= 0:
                if service != "instagram" or user["credits"] <= 0 or is_expired(user["subscription_expire_at"]):
                    return None
                column = "credits"  # Historical Instagram balance keeps its expiry.
            charge_id = uuid.uuid4().hex
            conn.execute(f"UPDATE users SET {column}={column}-1 WHERE telegram_user_id=?", (user_id,))
            conn.execute("INSERT INTO search_charges (id, telegram_user_id, service, balance_column, created_at) VALUES (?, ?, ?, ?, ?)",
                         (charge_id, user_id, service, column, now_iso()))
            return charge_id

    @staticmethod
    def complete(charge_id):
        with get_connection() as conn:
            conn.execute("UPDATE search_charges SET status='completed' WHERE id=? AND status='reserved'", (charge_id,))

    @staticmethod
    def refund(charge_id):
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            charge = conn.execute("SELECT * FROM search_charges WHERE id=? AND status='reserved'", (charge_id,)).fetchone()
            if not charge:
                return False
            column = charge["balance_column"]
            if column not in ("credits", "email_credits", "instagram_credits"):
                raise ValueError("Unknown balance")
            conn.execute(f"UPDATE users SET {column}={column}+1 WHERE telegram_user_id=?", (charge["telegram_user_id"],))
            conn.execute("UPDATE search_charges SET status='refunded' WHERE id=?", (charge_id,))
            return True

    @staticmethod
    def recover_interrupted():
        """Call only on startup before polling, with no other bot process running."""
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute("SELECT * FROM search_charges WHERE status='reserved'").fetchall()
            for row in rows:
                column = row["balance_column"]
                if column not in ("credits", "email_credits", "instagram_credits"):
                    raise ValueError("Unknown balance")
                conn.execute(f"UPDATE users SET {column}={column}+1 WHERE telegram_user_id=?", (row["telegram_user_id"],))
            conn.execute("UPDATE search_charges SET status='refunded' WHERE status='reserved'")
            conn.execute("UPDATE jobs SET status='failed', credits_charged=0 WHERE status='running'")
            return len(rows)
