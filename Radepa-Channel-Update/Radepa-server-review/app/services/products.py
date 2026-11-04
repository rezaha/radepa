"""Single-search catalog; historical plans are retained for existing orders."""
EMAIL_PLAN = "EMAIL_SINGLE"
INSTAGRAM_PLAN = "INSTAGRAM_SINGLE"
PRODUCTS = {
    EMAIL_PLAN: ("email", "بررسی نشت یک ایمیل", 199_000),
    INSTAGRAM_PLAN: ("instagram", "تحلیل ردپای عمومی یک آیدی اینستاگرام", 299_000),
}

def seed_products():
    from app.db.database import get_connection
    from app.db.repos import PlanRepo
    with get_connection() as conn:
        conn.execute("UPDATE plans SET is_active=0 WHERE plan_code NOT IN (?, ?)",
                     (EMAIL_PLAN, INSTAGRAM_PLAN))
    for code, (_, title, price) in PRODUCTS.items():
        PlanRepo.upsert(code, title, price, 1, 0, 1)
