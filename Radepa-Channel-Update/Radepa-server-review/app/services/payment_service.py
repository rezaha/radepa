from __future__ import annotations
from typing import Optional
import sqlite3
from app.db.repos import OrderRepo, PlanRepo
from app.db.database import get_connection
from app.utils.time_utils import now_utc, from_iso, add_days
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

class PaymentService:
    @staticmethod
    def create_order(telegram_user_id: int, plan_code: str) -> Optional[dict]:
        plan = PlanRepo.get(plan_code)
        if not plan or not plan["is_active"]: return None
        order = OrderRepo.create(telegram_user_id, plan_code, plan["price_toman"])
        logger.info("Order created: %s", order["order_id"])
        return order

    @staticmethod
    def submit_photo_evidence(order_id: str, file_id: str) -> bool:
        order = OrderRepo.get_by_order_id(order_id)
        if not order or order["status"] != "awaiting_payment": return False
        OrderRepo.submit_evidence(order_id, "photo", file_id, None)
        return True

    @staticmethod
    def submit_text_evidence(order_id: str, text: str) -> bool:
        order = OrderRepo.get_by_order_id(order_id)
        if not order or order["status"] != "awaiting_payment": return False
        OrderRepo.submit_evidence(order_id, "text", None, text)
        return True

    @staticmethod
    def approve_order(order_id: str, admin_id: int, note: str = "") -> Optional[dict]:
        # Order transition and credit grant must commit together. BEGIN IMMEDIATE
        # serializes competing approvals against the same SQLite database.
        try:
            with get_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                order = conn.execute(
                    "SELECT * FROM orders WHERE order_id=? AND status='awaiting_review'",
                    (order_id,),
                ).fetchone()
                if not order:
                    return None
                plan = conn.execute(
                    "SELECT * FROM plans WHERE plan_code=?", (order["plan_code"],)
                ).fetchone()
                user = conn.execute(
                    "SELECT subscription_expire_at FROM users WHERE telegram_user_id=?",
                    (order["telegram_user_id"],),
                ).fetchone()
                if not plan or not user:
                    return None
                now = now_utc()
                current = from_iso(user["subscription_expire_at"]) if user["subscription_expire_at"] else now
                expire_iso = add_days(max(now, current), plan["duration_days"]).isoformat()
                stamp = now.isoformat()
                conn.execute(
                    "UPDATE orders SET status='paid', reviewed_by_admin_id=?, "
                    "reviewed_at=?, admin_note=?, updated_at=? WHERE id=?",
                    (admin_id, stamp, note, stamp, order["id"]),
                )
                updated = conn.execute(
                    "UPDATE users SET credits=credits+?, subscription_expire_at=? "
                    "WHERE telegram_user_id=?",
                    (plan["credits"], expire_iso, order["telegram_user_id"]),
                )
                if updated.rowcount != 1:
                    raise sqlite3.IntegrityError("Missing user during grant")
                conn.commit()
                return {"user_telegram_id": order["telegram_user_id"],
                        "credits": plan["credits"], "expire_iso": expire_iso, "order_id": order_id}
        except sqlite3.Error as exc:
            logger.error("Payment approval failed for order %s (%s)", order_id, type(exc).__name__)
            return None

    @staticmethod
    def reject_order(order_id: str, admin_id: int, note: str = "") -> Optional[dict]:
        order = OrderRepo.get_by_order_id(order_id)
        if not order: return None
        updated = OrderRepo.reject(order_id, admin_id, note)
        if not updated: return None
        return {"user_telegram_id": order["telegram_user_id"], "order_id": order_id, "note": note}

    @staticmethod
    def expire_old_orders() -> int:
        from app.utils.time_utils import now_utc
        from datetime import timedelta
        cutoff = (now_utc() - timedelta(hours=48)).isoformat()
        return OrderRepo.expire_old_pending(cutoff)
