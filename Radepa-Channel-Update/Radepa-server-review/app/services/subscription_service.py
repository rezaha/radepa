from __future__ import annotations
from app.db.repos import UserRepo
from app.utils.time_utils import is_expired
from app.utils.logging_utils import get_logger

logger = get_logger(__name__)

class SubscriptionService:
    @staticmethod
    def check_can_analyze(telegram_user_id: int) -> tuple[bool, str]:
        user = UserRepo.get_by_telegram_id(telegram_user_id)
        if not user: return False, "no_credits"
        if user.get("is_blocked"): return False, "blocked"
        if is_expired(user.get("subscription_expire_at")): return False, "expired"
        if user.get("credits", 0) <= 0: return False, "no_credits"
        return True, "ok"

    @staticmethod
    def apply_plan(telegram_user_id: int, plan: dict) -> str:
        from app.utils.time_utils import now_utc, from_iso, add_days
        user = UserRepo.get_by_telegram_id(telegram_user_id)
        now = now_utc()
        old = from_iso(user["subscription_expire_at"]) if user and user.get("subscription_expire_at") else now
        new_expire = add_days(max(now, old), plan["duration_days"]).isoformat()
        UserRepo.add_credits_and_extend(telegram_user_id, plan["credits"], new_expire)
        logger.info("Plan %s applied to user %d", plan["plan_code"], telegram_user_id)
        return new_expire
