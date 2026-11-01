# تفکیک ۴۷ فایل PR در نقطه بازبینی dfe1321

مبنای مقایسه main در commit `74cbda2884a5b50e6c9c5caea716d01fc9230b44` است. این جدول snapshot همان ۴۷ فایل پیش از اضافه‌شدن ابزارهای انتشار است؛ تعداد فایل‌های نهایی PR پس از این تغییر بیشتر می‌شود.

۳۹ فایل توسعه قبلی، ۶ فایل اختصاصی Inspector و ۲ فایل مشترک‌اند. فایل‌های قبلی از شاخه توسعه همگام شده‌اند؛ نصب چند فایل از PR روی main قدیمی، نسخه فعال ربات را بازسازی نمی‌کند.

| مسیر | منشأ |
|---|---|
| `ABSTRACTAPI_SETUP.md` | توسعه‌های قبلی |
| `SERVER_INSTALL_FA.md` | توسعه‌های قبلی |
| `app/db/database.py` | توسعه‌های قبلی |
| `app/db/repos.py` | توسعه‌های قبلی |
| `app/db/schema.sql` | توسعه‌های قبلی |
| `app/handlers/account.py` | توسعه‌های قبلی |
| `app/handlers/admin.py` | توسعه‌های قبلی |
| `app/handlers/breach.py` | توسعه‌های قبلی |
| `app/handlers/instagram_inspect.py` | Inspector |
| `app/handlers/payments.py` | توسعه‌های قبلی |
| `app/handlers/plans.py` | توسعه‌های قبلی |
| `app/handlers/start.py` | توسعه‌های قبلی |
| `app/main.py` | مشترک: توسعه قبلی + ثبت دستور Inspector |
| `app/services/abstract_email.py` | توسعه‌های قبلی |
| `app/services/credit_service.py` | توسعه‌های قبلی |
| `app/services/email_lookup.py` | توسعه‌های قبلی |
| `app/services/email_report.py` | توسعه‌های قبلی |
| `app/services/google_cse_service.py` | توسعه‌های قبلی |
| `app/services/instagram_page_inspector.py` | Inspector |
| `app/services/job_service.py` | توسعه‌های قبلی |
| `app/services/leakcheck_public.py` | توسعه‌های قبلی |
| `app/services/payment_service.py` | توسعه‌های قبلی |
| `app/services/products.py` | توسعه‌های قبلی |
| `app/services/receipt_review.py` | توسعه‌های قبلی |
| `app/services/subscription_service.py` | توسعه‌های قبلی |
| `app/utils/keyboards.py` | توسعه‌های قبلی |
| `app/utils/texts_fa.py` | توسعه‌های قبلی |
| `docs/ADMIN_RECEIPTS_FA.md` | توسعه‌های قبلی |
| `docs/ADMIN_SUPPORT_FA.md` | توسعه‌های قبلی |
| `docs/EMAIL_REPORT_EXAMPLE.txt` | توسعه‌های قبلی |
| `docs/INSTAGRAM_INSPECTOR_REVIEW_FA.md` | Inspector |
| `docs/PAYMENT_RECOVERY_FA.md` | توسعه‌های قبلی |
| `docs/SINGLE_SEARCH_UPDATE_FA.md` | توسعه‌های قبلی |
| `requirements.txt` | مشترک: وابستگی‌های قبلی + Playwright |
| `tests/test_abstract_email.py` | توسعه‌های قبلی |
| `tests/test_admin_support.py` | توسعه‌های قبلی |
| `tests/test_email_lookup.py` | توسعه‌های قبلی |
| `tests/test_inspector_serpapi_regression.py` | Inspector |
| `tests/test_instagram_inspector_runtime.py` | Inspector |
| `tests/test_instagram_page_inspector.py` | Inspector |
| `tests/test_order_recovery.py` | توسعه‌های قبلی |
| `tests/test_receipt_installer.py` | توسعه‌های قبلی |
| `tests/test_receipt_review.py` | توسعه‌های قبلی |
| `tests/test_single_search_payments.py` | توسعه‌های قبلی |
| `tools/check_abstract_connection.py` | توسعه‌های قبلی |
| `tools/install_receipt_review.py` | توسعه‌های قبلی |
| `tools/install_single_search.py` | توسعه‌های قبلی |
