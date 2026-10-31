from __future__ import annotations
import sqlite3, uuid
from typing import Any, Dict, List, Optional
from app.db.database import get_connection
from app.utils.time_utils import now_iso
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)
Row = Dict[str, Any]

def _row(row) -> Optional[Row]:
    return dict(row) if row else None

def _rows(rows) -> List[Row]:
    return [dict(r) for r in rows]


class UserRepo:
    @staticmethod
    def upsert(telegram_user_id: int, username: Optional[str], first_name: str) -> Row:
        ts = now_iso()
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO users (telegram_user_id, username, first_name, created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(telegram_user_id) DO UPDATE SET
                       username=excluded.username, first_name=excluded.first_name,
                       last_seen_at=excluded.last_seen_at""",
                (telegram_user_id, username, first_name, ts, ts))
            conn.commit()
        return UserRepo.get_by_telegram_id(telegram_user_id)

    @staticmethod
    def get_by_telegram_id(telegram_user_id: int) -> Optional[Row]:
        with get_connection() as conn:
            return _row(conn.execute("SELECT * FROM users WHERE telegram_user_id=?", (telegram_user_id,)).fetchone())

    @staticmethod
    def touch(telegram_user_id: int) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE users SET last_seen_at=? WHERE telegram_user_id=?", (now_iso(), telegram_user_id))
            conn.commit()

    @staticmethod
    def deduct_credit(telegram_user_id: int) -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                "UPDATE users SET credits=credits-1 WHERE telegram_user_id=? AND credits>0",
                (telegram_user_id,))
            conn.commit()
            return cur.rowcount == 1

    @staticmethod
    def refund_credit(telegram_user_id: int) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE users SET credits=credits+1 WHERE telegram_user_id=?", (telegram_user_id,))
            conn.commit()

    @staticmethod
    def add_credits_and_extend(telegram_user_id: int, credits: int, expire_iso: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "UPDATE users SET credits=credits+?, subscription_expire_at=? WHERE telegram_user_id=?",
                (credits, expire_iso, telegram_user_id))
            conn.commit()

    @staticmethod
    def add_days(telegram_user_id: int, days: int) -> None:
        from app.utils.time_utils import from_iso, add_days, now_utc
        user = UserRepo.get_by_telegram_id(telegram_user_id)
        if not user: return
        base = from_iso(user["subscription_expire_at"]) if user.get("subscription_expire_at") else now_utc()
        new_expire = add_days(base, days).isoformat()
        with get_connection() as conn:
            conn.execute("UPDATE users SET subscription_expire_at=? WHERE telegram_user_id=?", (new_expire, telegram_user_id))
            conn.commit()

    @staticmethod
    def add_credits(telegram_user_id: int, credits: int) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE users SET credits=credits+? WHERE telegram_user_id=?", (credits, telegram_user_id))
            conn.commit()

    @staticmethod
    def set_blocked(telegram_user_id: int, blocked: bool) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE users SET is_blocked=? WHERE telegram_user_id=?", (1 if blocked else 0, telegram_user_id))
            conn.commit()

    @staticmethod
    def count_total() -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    @staticmethod
    def count_active_since(since_iso: str) -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM users WHERE last_seen_at>=?", (since_iso,)).fetchone()[0]


class PlanRepo:
    @staticmethod
    def get_active() -> List[Row]:
        with get_connection() as conn:
            return _rows(conn.execute("SELECT * FROM plans WHERE is_active=1").fetchall())

    @staticmethod
    def get(plan_code: str) -> Optional[Row]:
        with get_connection() as conn:
            return _row(conn.execute("SELECT * FROM plans WHERE plan_code=?", (plan_code,)).fetchone())

    @staticmethod
    def upsert(plan_code, title, price_toman, credits, duration_days, is_active=1) -> None:
        with get_connection() as conn:
            conn.execute(
                """INSERT INTO plans (plan_code,title,price_toman,credits,duration_days,is_active)
                   VALUES (?,?,?,?,?,?)
                   ON CONFLICT(plan_code) DO UPDATE SET
                       title=excluded.title, price_toman=excluded.price_toman,
                       credits=excluded.credits, duration_days=excluded.duration_days,
                       is_active=excluded.is_active""",
                (plan_code, title, price_toman, credits, duration_days, is_active))
            conn.commit()


class OrderRepo:
    @staticmethod
    def get_open(telegram_user_id: int) -> List[Row]:
        with get_connection() as conn:
            return _rows(conn.execute(
                "SELECT * FROM orders WHERE telegram_user_id=? "
                "AND status IN ('awaiting_payment','awaiting_review') ORDER BY id DESC",
                (telegram_user_id,)).fetchall())

    @staticmethod
    def switch_unpaid(order_id: str, user_id: int, plan_code: str) -> Optional[Row]:
        # Switching is an explicit user action, serialized with receipt submission.
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            old = conn.execute("SELECT * FROM orders WHERE order_id=? AND telegram_user_id=? "
                               "AND status='awaiting_payment'", (order_id, user_id)).fetchone()
            plan = conn.execute("SELECT * FROM plans WHERE plan_code=? AND is_active=1", (plan_code,)).fetchone()
            if not old or not plan:
                return None
            if conn.execute("SELECT 1 FROM orders WHERE telegram_user_id=? AND id<>? "
                            "AND status IN ('awaiting_payment','awaiting_review')", (user_id, old['id'])).fetchone():
                return None
            if old['plan_code'] == plan_code:
                return dict(old)
            stamp = now_iso()
            conn.execute("UPDATE orders SET status='expired',updated_at=? WHERE id=?", (stamp, old['id']))
            new_id = f"ORD-{uuid.uuid4().hex[:10].upper()}"
            conn.execute("INSERT INTO orders (order_id,telegram_user_id,plan_code,amount_toman,created_at,updated_at) "
                         "VALUES (?,?,?,?,?,?)", (new_id, user_id, plan_code, plan['price_toman'], stamp, stamp))
            return _row(conn.execute("SELECT * FROM orders WHERE order_id=?", (new_id,)).fetchone())

    @staticmethod
    def create(telegram_user_id: int, plan_code: str, amount_toman: int) -> Row:
        order_id = f"ORD-{uuid.uuid4().hex[:10].upper()}"
        ts = now_iso()
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute("SELECT * FROM orders WHERE telegram_user_id=? AND status IN ('awaiting_payment','awaiting_review') ORDER BY id DESC LIMIT 1", (telegram_user_id,)).fetchone()
            if pending:
                if pending["plan_code"] == plan_code and pending["status"] == "awaiting_payment":
                    return dict(pending)
                return None
            conn.execute(
                """INSERT INTO orders (order_id,telegram_user_id,plan_code,amount_toman,
                   status,evidence_type,created_at,updated_at)
                   VALUES (?,?,?,?,'awaiting_payment','none',?,?)""",
                (order_id, telegram_user_id, plan_code, amount_toman, ts, ts))
            conn.commit()
        return OrderRepo.get_by_order_id(order_id)

    @staticmethod
    def get_by_order_id(order_id: str) -> Optional[Row]:
        with get_connection() as conn:
            return _row(conn.execute("SELECT * FROM orders WHERE order_id=?", (order_id,)).fetchone())

    @staticmethod
    def get_latest_awaiting_payment(telegram_user_id: int) -> Optional[Row]:
        with get_connection() as conn:
            return _row(conn.execute(
                "SELECT * FROM orders WHERE telegram_user_id=? AND status='awaiting_payment' ORDER BY created_at DESC LIMIT 1",
                (telegram_user_id,)).fetchone())

    @staticmethod
    def get_latest_awaiting_review(telegram_user_id: int) -> Optional[Row]:
        with get_connection() as conn:
            return _row(conn.execute(
                "SELECT * FROM orders WHERE telegram_user_id=? AND status='awaiting_review' ORDER BY created_at DESC LIMIT 1",
                (telegram_user_id,)).fetchone())

    @staticmethod
    def submit_evidence(order_id, evidence_type, evidence_file_id, evidence_text) -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                """UPDATE orders SET status='awaiting_review',evidence_type=?,
                   evidence_file_id=?,evidence_text=?,updated_at=?
                   WHERE order_id=? AND status='awaiting_payment'""",
                (evidence_type, evidence_file_id, evidence_text, now_iso(), order_id))
            conn.commit()
            return cur.rowcount == 1

    @staticmethod
    def approve(order_id: str, admin_id: int, note: str = "") -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                """UPDATE orders SET status='paid',reviewed_by_admin_id=?,
                   reviewed_at=?,admin_note=?,updated_at=?
                   WHERE order_id=? AND status='awaiting_review'""",
                (admin_id, now_iso(), note, now_iso(), order_id))
            conn.commit()
            return cur.rowcount == 1

    @staticmethod
    def reject(order_id: str, admin_id: int, note: str = "") -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                """UPDATE orders SET status='rejected',reviewed_by_admin_id=?,
                   reviewed_at=?,admin_note=?,updated_at=?
                   WHERE order_id=? AND status='awaiting_review'""",
                (admin_id, now_iso(), note, now_iso(), order_id))
            conn.commit()
            return cur.rowcount == 1

    @staticmethod
    def expire_old_pending(cutoff_iso: str) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                "UPDATE orders SET status='expired',updated_at=? WHERE status='awaiting_payment' AND created_at<?",
                (now_iso(), cutoff_iso))
            conn.commit()
            return cur.rowcount

    @staticmethod
    def list_awaiting_review() -> List[Row]:
        with get_connection() as conn:
            return _rows(conn.execute(
                """SELECT o.*,u.first_name,u.username FROM orders o
                   JOIN users u ON u.telegram_user_id=o.telegram_user_id
                   WHERE o.status='awaiting_review' ORDER BY o.created_at ASC""").fetchall())

    @staticmethod
    def count_by_status(status: str) -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM orders WHERE status=?", (status,)).fetchone()[0]

    @staticmethod
    def list_by_user(telegram_user_id: int) -> List[Row]:
        with get_connection() as conn:
            return _rows(conn.execute(
                "SELECT * FROM orders WHERE telegram_user_id=? ORDER BY created_at DESC",
                (telegram_user_id,)).fetchall())


class JobRepo:
    @staticmethod
    def create(telegram_user_id: int, target_instagram_username: str) -> Row:
        ts = now_iso()
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO jobs (telegram_user_id,target_instagram_username,created_at,status,credits_charged) VALUES (?,?,?,'running',0)",
                (telegram_user_id, target_instagram_username, ts))
            job_id = cur.lastrowid
            conn.commit()
        return JobRepo.get(job_id)

    @staticmethod
    def get(job_id: int) -> Optional[Row]:
        with get_connection() as conn:
            return _row(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())

    @staticmethod
    def mark_charged(job_id: int) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE jobs SET credits_charged=1 WHERE id=?", (job_id,))
            conn.commit()

    @staticmethod
    def finish(job_id: int, result_summary: str) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE jobs SET status='done',result_summary=? WHERE id=?", (result_summary, job_id))
            conn.commit()

    @staticmethod
    def fail(job_id: int) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE jobs SET status='failed', credits_charged=0 WHERE id=?", (job_id,))
            conn.commit()

    @staticmethod
    def save_sources(job_id: int, sources: list) -> None:
        with get_connection() as conn:
            conn.executemany(
                "INSERT INTO job_sources (job_id,title,link,snippet,rank,query_pattern) VALUES (?,?,?,?,?,?)",
                [(job_id, s.get("title",""), s.get("link",""), s.get("snippet",""), s.get("rank",0), s.get("query_pattern","")) for s in sources])
            conn.commit()

    @staticmethod
    def count_by_user(telegram_user_id: int) -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM jobs WHERE telegram_user_id=?", (telegram_user_id,)).fetchone()[0]

    @staticmethod
    def count_total() -> int:
        with get_connection() as conn:
            return conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]


class SearchHistoryRepo:
    @staticmethod
    def start_email(user_id, email):
        with get_connection() as conn:
            return conn.execute("INSERT INTO email_searches (telegram_user_id,target_email,created_at) VALUES (?,?,?)",
                                (user_id, email, now_iso())).lastrowid

    @staticmethod
    def finish_email(search_id, status):
        with get_connection() as conn:
            conn.execute("UPDATE email_searches SET status=? WHERE id=? AND status='running'", (status, search_id))

    @staticmethod
    def page(user_id, offset=0, limit=11):
        with get_connection() as conn:
            return _rows(conn.execute("""
                SELECT id,'instagram' AS service,target_instagram_username AS target,created_at,status
                FROM jobs WHERE telegram_user_id=?
                UNION ALL
                SELECT id,'email' AS service,target_email AS target,created_at,status
                FROM email_searches WHERE telegram_user_id=?
                ORDER BY created_at DESC,id DESC,service LIMIT ? OFFSET ?
            """, (user_id,user_id,limit,offset)).fetchall())
