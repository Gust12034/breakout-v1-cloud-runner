# راهنمای استقرار Breakout V1 Dynamic روی GitHub Actions + Google Apps Script

این مخزن عمومی فقط فایل‌های زمان‌بندی و payload رمزگذاری‌شده را نگه می‌دارد. موتور Python، فایل Pine، تست‌ها و تنظیمات ریسک داخل `private_bundle/bot_payload.bin` با AES-256-GCM رمزگذاری شده‌اند. فایل جداگانهٔ `BOT_BUNDLE_PASSPHRASE.txt` کلید بازگشایی است و **نباید به مخزن اضافه شود**.

## ۱) بارگذاری payload رمزگذاری‌شده

1. ZIP استقرار را از حالت فشرده خارج کن.
2. از داخل آن فقط فایل `private_bundle/bot_payload.bin` را انتخاب کن.
3. در همین مخزن، `Add file → Upload files` را بزن و فایل را دقیقاً در مسیر `private_bundle/bot_payload.bin` بارگذاری کن. اگر GitHub پوشه را نساخته، ساختار `private_bundle` را در مسیر مقصد ایجاد کن.
4. فقط همین فایل رمزگذاری‌شده را Commit کن. فایل رمز، فایل `.env` یا API key را بارگذاری نکن.

## ۲) GitHub Actions Secrets

از `Settings → Secrets and variables → Actions → New repository secret` این شش مورد را بساز:

| نام Secret | مقدار |
|---|---|
| `BITGET_DEMO_API_KEY` | API Key حساب Bitget Classic Futures Demo |
| `BITGET_DEMO_API_SECRET` | API Secret همان کلید |
| `BITGET_DEMO_API_PASSPHRASE` | Passphrase همان کلید |
| `BOT_BUNDLE_PASSPHRASE` | متن فایل جداگانهٔ BOT_BUNDLE_PASSPHRASE.txt |
| `GOOGLE_APPS_SCRIPT_URL` | URL وب‌اپ فعلی Apps Script که به `/exec` ختم می‌شود |
| `CONTROL_PLANE_TOKEN` | همان توکن کنترل تعریف‌شده در Script Properties پروژهٔ Apps Script |

برای کلید Bitget، فقط دسترسی لازم برای معاملهٔ Futures و خواندن حساب را فعال کن و **برداشت (Withdraw) را غیرفعال نگه دار**. این پروژه فقط برای Classic Futures Demo است، نه UTA و نه Mainnet.

## ۳) GitHub Actions Variables

در `Settings → Secrets and variables → Actions → Variables` این مقادیر را اضافه کن:

| Variable | مقدار اولیه |
|---|---|
| `TRADING_ENABLED` | `false` |
| `ANALYZE_TOP_COINS` | `true` |
| `TRADE_TOP_COINS` | `true` |
| `TOP_COINS_COUNT` | `100` |
| `BITGET_MARGIN_MODE` | `isolated` |
| `SIGNAL_DATA_SOURCE` | `binance_spot` |
| `TRADE_SYMBOLS` | `BTCUSDT` |
| `ALLOW_POSITION_RECOVERY` | `false` |
| `LEN_N` | `48` |
| `V1D_VOL_MULT` | `1.5` |
| `V1D_ADX_MAX` | `0.0` |
| `ENABLE_LONGS` | `true` |
| `ENABLE_SHORTS` | `true` |
| `ATR_K` | `2.5` |
| `V1D_EXIT_MODE` | `Chandelier + BE` |
| `V1D_BE_AT` | `1.0` |
| `V1D_TRAIL_M` | `4.0` |
| `V1D_DON_M` | `20` |
| `RR` | `2.0` |

تنظیمات سبد در payload رمزگذاری‌شده باقی مانده است: حداکثر ۳ پوزیشن، حداکثر ۱ ورودی جدید در هر اجرای تحلیل و ریسک تنظیمی ۶٫۵٪ برای هر پوزیشن. این سطح ریسک زیاد است؛ سقف ریسک نظری سه پوزیشن در صورت برخورد همه به حد ضرر اولیه تا ۱۹٫۵٪ سرمایه است.

## ۴) ساخت Fine-grained Personal Access Token

در همان حساب GitHub برو به `Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token`:

- Resource owner: `Gust12034`
- Repository access: `Only select repositories` و فقط `breakout-v1-cloud-runner`
- Repository permissions: فقط `Actions: Read and write`
- سپس توکن را بساز و مقدار آن را کپی کن؛ مقدار کامل بعداً دوباره نمایش داده نمی‌شود.

این توکن برای خواندن وضعیت Workflowها و اجرای `workflow_dispatch` از Apps Script لازم است. توکن را داخل GitHub Variable یا فایل کد قرار نده.

## ۵) افزودن زمان‌بند به Google Apps Script

در همان Google Sheet و پروژهٔ Apps Script فعلی (همانی که فایل `Code.gs`، وب‌اپ `/exec`، توکن کنترل و تب‌های وضعیت را دارد):

1. Apps Script Editor → دکمهٔ `+` → `Script`؛ نام فایل جدید را `CloudScheduler` بگذار.
2. فایل `google-apps-script/CloudScheduler.gs` همین مخزن را کامل در آن کپی و Save کن. `Code.gs` فعلی را حذف یا جایگزین نکن.
3. به `Project Settings → Script properties` برو و موارد زیر را اضافه کن:

| Property | Value |
|---|---|
| `B1D_GITHUB_TOKEN` | Fine-grained token ساخته‌شده |
| `B1D_GITHUB_OWNER` | `Gust12034` |
| `B1D_GITHUB_REPO` | `breakout-v1-cloud-runner` |
| `B1D_GITHUB_REF` | `main` |
| `B1D_BOT_WORKFLOW` | `bot.yml` |
| `B1D_MONITOR_WORKFLOW` | `position-monitor.yml` |

4. Propertyهای موجود مثل `SPREADSHEET_ID`، `CONTROL_PLANE_TOKEN`، `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID` را دست نزن.
5. از فهرست توابع Apps Script، `testBreakoutGitHubConnection` را اجرا کن. باید `ok: true` و وضعیت `active` برای هر دو Workflow بگیری.
6. بعد `installBreakoutCloudScheduler` را اجرا کن و دسترسی Trigger را تأیید کن. این تابع دقیقاً یک Trigger پنج‌دقیقه‌ای ایجاد می‌کند.
7. برای بررسی، `getBreakoutCloudSchedulerStatus` و برای توقف زمان‌بند `removeBreakoutCloudScheduler` را اجرا کن.

نیازی به Deploy مجدد وب‌اپ قبلی نیست؛ این فایل صرفاً GitHub را زمان‌بندی و Dispatch می‌کند.

## ۶) آزمون اجباری، پیش از هر معامله

1. اطمینان بگیر فایل `private_bundle/bot_payload.bin` وجود دارد و هر شش Secret تنظیم شده‌اند.
2. در Actions، Workflow با نام `Bitget Classic Demo Read-only Check` را دستی اجرا کن. این تست باید API Classic Demo را تأیید کند و هیچ سفارشی نمی‌فرستد.
3. `TRADING_ENABLED` را همچنان `false` نگه دار. Workflow `Breakout V1 Dynamic Bitget Classic Demo Bot` را دستی اجرا کن؛ چون قفل خاموش است، اجرای بررسی/تحلیل مجاز است اما سفارش جدید نباید باز شود. خروجی خصوصی را در Google Sheets/Telegram بررسی کن.
4. فقط پس از موفقیت کامل تست‌های Read-only، تطبیق داده‌ها و کنترل پوزیشن‌ها، در صورت تصمیم آگاهانه `TRADING_ENABLED=true` را برای **Demo** فعال کن. `LIVE_TRADING=false` در Workflow قفل شده و موتور Mainnet را رد می‌کند.
5. زمان‌بند Apps Script را نصب کن. اجرای تحلیل هر ۴ ساعت و پایش موقعیت‌ها در فاصله‌های ۵ دقیقه‌ای هدف‌گذاری شده‌اند.

## ۷) جلوگیری از اجرای دوگانه

در مخزن خصوصی قدیمی `Breakout-V1-Dynamic`، Workflowهای زمان‌بندی‌شدهٔ قدیمی Bot و Position Monitor را در تب Actions غیرفعال کن تا دو موتور هم‌زمان اجرا نشوند. مخزن قدیمی را خصوصی نگه دار.

## محدودیت‌های عملی

- GitHub زمان تخصیص Runner را در ثانیهٔ مشخص تضمین نمی‌کند. Trigger پنج‌دقیقه‌ای Apps Script نیز ممکن است کمی زودتر یا دیرتر اجرا شود.
- اگر Workflow قبلی هنوز در حال اجرا باشد، زمان‌بند اجرای جدیدی Dispatch نمی‌کند؛ تیک‌های مانیتور در این حالت ممکن است از دست بروند یا به اجرای بعد موکول شوند.
- منطق Chandelier و Break-even همچنان بر اساس کندل بسته‌شدهٔ ۴ساعته به‌روزرسانی می‌شود؛ مانیتور ۵دقیقه‌ای به معنی Trailing بلادرنگ نیست. حد ضرر ثبت‌شده در صرافی، حفاظت اصلی بین اجراهای دوره‌ای است.
- سهمیهٔ Google Apps Script برای حساب مصرفی محدود است؛ سقف زمان اجرای Trigger روزانه ۹۰ دقیقه و زمان هر اجرای اسکریپت ۶ دقیقه است. در این معماری Apps Script فقط چند درخواست سبک GitHub می‌فرستد.
- مخزن عمومی فقط payload رمزگذاری‌شده را نگه می‌دارد، اما نام Workflowها، زمان و وضعیت اجراها عمومی‌اند. هنگام اجرا، متن اصلی فقط در فضای موقت Runner باز می‌شود.
- هیچ سرویس رایگان ابری، تأخیر صفر یا دسترس‌پذیری ۱۰۰٪ تضمین نمی‌کند. این پروژه برای Bitget Classic Futures Demo است و سودآوری را تضمین نمی‌کند.
