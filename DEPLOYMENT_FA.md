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

## ۲-الف) رفع خطای Bitget `40012`

اگر تست Read-only پیام زیر را نشان داد:

`code=40012; message=apikey/password is incorrect`

درخواست عمومی Futures Demo موفق شده، اما درخواست خصوصی حساب احراز هویت نشده است. Endpoint عمومی Ticker به کلید خصوصی نیاز ندارد؛ پس موفقیت آن اعتبار API Key را ثابت نمی‌کند. کد `40012` در مستندات Bitget به معنی `apikey/password is incorrect` است.

این خطا را این‌گونه رفع کن:

1. وارد Bitget شو و محیط حساب را به **Demo Trading** تغییر بده.
2. از بخش API Key Management یک **Demo API Key** جدید بساز. چون برنامه از REST API نسخهٔ **Classic V2 Futures** استفاده می‌کند، کلید را برای محیط Demo و حساب/محصول Classic بساز؛ کلید Mainnet یا کلید/محیط UTA را جایگزین آن نکن.
3. API Key، API Secret و API Passphrase همان کلید جدید را با هم بردار. Passphrase، رمز ورود سایت Bitget نیست؛ همان عبارتی است که هنگام ساخت API Key تعیین کردی. اگر Passphrase را نمی‌دانی، کلید تازه بساز.
4. در GitHub → Settings → Secrets and variables → Actions، سه Secret زیر را با هم به‌روزرسانی کن: `BITGET_DEMO_API_KEY`، `BITGET_DEMO_API_SECRET` و `BITGET_DEMO_API_PASSPHRASE`. مقادیر را بدون کوتیشن، فاصلهٔ ابتدا/انتها یا خط جدید ذخیره کن.
5. برای این تست، مجوز Read روی حساب/فیوچرز فعال باشد. برداشت (Withdraw) را فعال نکن.
6. مجدداً فقط Workflow با نام **Bitget Classic Demo Read-only Check** را اجرا کن. تا وقتی این تست موفق نشده، `TRADING_ENABLED` باید `false` بماند.

اگر پس از ساخت کلید تازه هنوز `40012` دیدی، مطمئن شو سه مقدار از یک API Key واحد هستند و در حالت Demo/Classic ساخته شده‌اند. کلیدها را در چت، Issue، لاگ یا فایل مخزن ارسال نکن.

## ۳) GitHub Actions Variables

متغیرهای زیر را در `Settings → Secrets and variables → Actions → Variables` می‌توانی بسازی یا تغییر بدهی. نام‌ها و مقادیر باید دقیقاً مطابق جدول باشند:

| Variable | مقدار پیشنهادی اولیه | کاربرد |
|---|---:|---|
| `TRADING_ENABLED` | `false` | کلید روشن/خاموش‌کردن سفارش‌گذاری Bitget Classic Demo؛ فقط Bot از آن برای ورود استفاده می‌کند |
| `LIVE_TRADING` | قفل ثابت `false` | مقدار Variable با این نام نادیده گرفته می‌شود؛ Mainnet عمداً قابل فعال‌سازی نیست |
| `TRADE_TOP_COINS` | `true` | اگر true باشد، ورودها از Universe انتخابی Top-N و قراردادهای قابل‌اجرای Demo انجام می‌شوند |
| `TRADE_SYMBOLS` | `BTCUSDT` | نمادهای دستی وقتی `TRADE_TOP_COINS=false` است |
| `ANALYZE_TOP_COINS` | `true` | فعال‌بودن اسکن بازار |
| `TOP_COINS_COUNT` | `100` | سقف تعداد بازارهای اسکن‌شده |
| `MAX_NEW_ENTRIES_PER_RUN` | `4` | سقف تعداد ورودهای جدید در هر اجرای Bot؛ صفر یعنی ورود جدید ممنوع |
| `PORTFOLIO_MAX_NOTIONAL_X` | `9.0` | سقف ارزش اسمی کل پوزیشن‌ها نسبت به Equity |
| `RISK_PER_POSITION_PCT` | `6.5` | بودجهٔ ریسک تا حدضرر اولیه برای هر پوزیشن، بر حسب درصد Equity |
| `PORTFOLIO_MARGIN_BUDGET_PCT` | `100.0` | سقف بودجهٔ مارجین بر حسب درصد Equity؛ سقف است، نه هدف مصرف |
| `MAX_EXCHANGE_LEVERAGE_CAP` | `10.0` | سقف اهرم پویا در Bitget؛ محدودیت سطح قرارداد ممکن است کمتر باشد |
| `ENABLE_LONGS` | `true` | اجازهٔ بررسی سیگنال Long |
| `ENABLE_SHORTS` | `true` | اجازهٔ بررسی سیگنال Short |
| `LEN_N` | `48` | طول محاسبات استراتژی |
| `V1D_VOL_MULT` | `1.5` | ضریب حجم |
| `V1D_ADX_MAX` | `0.0` | فیلتر ADX |
| `ATR_K` | `2.5` | ضریب ATR |
| `V1D_EXIT_MODE` | `Chandelier + BE` | منطق خروج |
| `V1D_BE_AT` | `1.0` | آستانهٔ Break-even |
| `V1D_TRAIL_M` | `4.0` | ضریب Trailing |
| `V1D_DON_M` | `20` | طول Donchian |
| `RR` | `2.0` | نسبت هدف به ریسک |

**فعال‌کردن سفارش‌های Demo:**

1. مطمئن شو سه Secret مربوط به Bitget با API Key مخصوص Classic Futures Demo تنظیم شده‌اند؛ کلید Mainnet را استفاده نکن.
2. Variable با نام دقیق `TRADING_ENABLED` بساز و مقدار آن را `true` (بدون کوتیشن) قرار بده.
3. Workflow با نام **Breakout V1 Dynamic Bitget Classic Demo Bot** را دستی اجرا کن.
4. در لاگ ابتدای Runner، `trading_enabled=True` و `effective_trading_enabled=True` را بررسی کن. در گزارش نهایی باید تعداد ورودی‌های جدید و وضعیت سفارش‌ها را ببینی.
5. برای توقف ورودهای جدید، مقدار Variable را دوباره `false` کن یا در Telegram دستور `/pause` بفرست. اجرای Position Monitor همچنان به مدیریت پوزیشن‌های موجود ادامه می‌دهد.

اگر می‌خواهی فقط BTCUSDT سفارش‌گذاری شود، `TRADE_TOP_COINS=false` و `TRADE_SYMBOLS=BTCUSDT` بگذار. با مقدار `TRADE_TOP_COINS=true`، مقدار `SYMBOLS=BTCUSDT` به‌تنهایی محدودیت BTC ایجاد نمی‌کند؛ Runner Universe قابل‌اجرای Demo را جایگزین فهرست دستی می‌کند. در آخرین بررسی، ۱۰۰ نماد تحلیل شده بودند و ۱۸ نماد در فهرست قابل‌اجرای Demo قرار داشتند.

**دربارهٔ Telegram:** متغیر `TELEGRAM_ENABLED` در Workflow فعلی خوانده نمی‌شود و سفارش‌گذاری را تغییر نمی‌دهد. اعلان Telegram از Script Properties با نام‌های `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID` در Google Apps Script استفاده می‌کند.

**قفل بازار واقعی:** `LIVE_TRADING` در Workflow به‌صورت ثابت `false` است و نباید آن را به Variable قابل‌تنظیم تبدیل کنی. این پروژه فقط برای Bitget Classic Demo طراحی شده است.

### اصلاح گزارش `/status`

نسخهٔ جدید `Code.gs` سه وضعیت را جداگانه نشان می‌دهد: آخرین اجرای Bot، آخرین اجرای Position Monitor و مقدار پیکربندی‌شدهٔ سفارش‌گذاری Bot در GitHub. Position Monitor ذاتاً `trading_enabled=false` دارد و نباید این مقدار را به‌عنوان وضعیت سفارش‌گذاری Bot گزارش کند. برای فعال‌شدن این قالب جدید، پس از جایگزینی فایل `google-apps-script/Code.gs` در پروژهٔ Apps Script، Web App موجود را با `New version` دوباره Deploy کن.

**تنظیمات عددی اکنون واقعاً از GitHub Variables وارد runtime می‌شوند.** Bot و Position Monitor هر دو این پنج مقدار را به موتور Python می‌رسانند و snapshot آن‌ها را ذخیره می‌کند؛ `/status` نیز مقادیر مصرف‌شده را نشان می‌دهد. پیش‌فرض‌ها همان ۴ ورود، ۹x Notional، ۶٫۵٪ ریسک هر پوزیشن، ۱۰۰٪ بودجه مارجین و ۱۰x سقف اهرم هستند. اگر Variable ساخته نشده باشد، همین پیش‌فرض به کار می‌رود. ورودی نامعتبر یا خارج از دامنه باعث توقف امن پیش از اتصال/معامله می‌شود.

**حداکثر پوزیشن هم‌زمان** همچنان ۷ و `STRATEGY_MAX_NOTIONAL_X` همچنان ۳x ثابت است؛ این دو مورد جزو Variableهای درخواست‌شده نیستند. با ریسک ۶٫۵٪ برای هر یک از ۷ جایگاه، ریسک نظری تجمیعی ۴۵٫۵٪ Equity است و بسیار تهاجمی محسوب می‌شود. سقف Notional کل ۹x نیز بین جایگاه‌ها تقسیم می‌شود و می‌تواند مقدار ریسک تحقق‌یافته را از بودجهٔ ۶٫۵٪ کمتر کند. بودجهٔ مارجین ۱۰۰٪ به معنی استفادهٔ اجباری از کل موجودی نیست.

**نکته دربارهٔ مقادیر تصویر:** `ANALYZE_TOP_COINS`، `TOP_COINS_COUNT`، `TRADE_SYMBOLS`، `TRADE_TOP_COINS` و `TRADING_ENABLED` از Repository Variables خوانده می‌شوند. `LIVE_TRADING` عمداً متغیر قابل‌اجرا نیست و در Workflow به‌صورت ثابت `false` باقی می‌ماند؛ آن را true نکن. `TELEGRAM_ENABLED` نیز در کد این Workflow خوانده نمی‌شود و کنترل سفارش‌گذاری نیست.

## ۴) ساخت Fine-grained Personal Access Token

در همان حساب GitHub برو به `Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token`:

- Resource owner: `Gust12034`
- Repository access: `Only select repositories` و فقط `breakout-v1-cloud-runner`
- Repository permissions: فقط `Actions: Read and write`
- سپس توکن را بساز و مقدار آن را کپی کن؛ مقدار کامل بعداً دوباره نمایش داده نمی‌شود.

این توکن برای خواندن وضعیت Workflowها و اجرای `workflow_dispatch` از Apps Script لازم است. توکن را داخل GitHub Variable یا فایل کد قرار نده.

## ۵) به‌روزرسانی Control Plane و افزودن زمان‌بند در Google Apps Script

در همان Google Sheet و پروژهٔ Apps Script فعلی کار کن؛ همان پروژه‌ای که وب‌اپ `/exec`، توکن کنترل، تب‌های وضعیت و تنظیمات Telegram را دارد. در این مخزن دو فایل Apps Script وظایف جدا دارند: `Code.gs` برای دریافت گزارش‌ها و ذخیره در Sheets/Telegram، و `CloudScheduler.gs` برای زمان‌بندی و Dispatch کردن Workflowها.

1. در Apps Script Editor فایل موجود `Code.gs` را باز کن و محتوای کامل آن را با فایل `google-apps-script/Code.gs` همین مخزن جایگزین کن. فقط کد را جایگزین کن، نه Script Properties یا داده‌های Google Sheet را. سپس Save کن.
2. از `Deploy → Manage deployments`، Web App فعلی را Edit کن، گزینهٔ `New version` را انتخاب و Deploy کن. Deployment موجود را ویرایش کن تا URL فعلی `/exec` ثابت بماند؛ Deployment تازه نساز. اگر URL ناخواسته تغییر کرد، Secret مربوط به `GOOGLE_APPS_SCRIPT_URL` در GitHub باید با URL جدید به‌روزرسانی شود.
3. در همان پروژه، از Apps Script Editor روی `+` → `Script` بزن و فایل جدیدی به نام `CloudScheduler` بساز.
4. محتوای کامل فایل `google-apps-script/CloudScheduler.gs` همین مخزن را در فایل جدید کپی و Save کن. این فایل باید جدا از `Code.gs` باقی بماند؛ آن را روی `Code.gs` کپی نکن.
5. به `Project Settings → Script properties` برو و موارد زیر را اضافه کن:

| Property | Value |
|---|---|
| `B1D_GITHUB_TOKEN` | Fine-grained token ساخته‌شده |
| `B1D_GITHUB_OWNER` | `Gust12034` |
| `B1D_GITHUB_REPO` | `breakout-v1-cloud-runner` |
| `B1D_GITHUB_REF` | `main` |
| `B1D_BOT_WORKFLOW` | `bot.yml` |
| `B1D_MONITOR_WORKFLOW` | `position-monitor.yml` |

6. Propertyهای موجود مثل `SPREADSHEET_ID`، `CONTROL_PLANE_TOKEN`، `TELEGRAM_BOT_TOKEN` و `TELEGRAM_CHAT_ID` را دست نزن.
7. از فهرست توابع Apps Script، `testBreakoutGitHubConnection` را اجرا کن. باید `ok: true` و وضعیت `active` برای هر دو Workflow بگیری.
8. بعد `installBreakoutCloudScheduler` را اجرا کن و دسترسی Trigger را تأیید کن. این تابع دقیقاً یک Trigger پنج‌دقیقه‌ای ایجاد می‌کند.
9. برای بررسی، `getBreakoutCloudSchedulerStatus` و برای توقف زمان‌بند `removeBreakoutCloudScheduler` را اجرا کن.

با تغییر `Code.gs` باید نسخهٔ جدید Web App Deploy شود؛ افزودن یا تغییر `CloudScheduler.gs` به‌تنهایی نیازی به Deploy مجدد Web App ندارد.

## ۶) آزمون اجباری، پیش از هر معامله

1. اطمینان بگیر فایل `private_bundle/bot_payload.bin` وجود دارد و هر شش Secret تنظیم شده‌اند.
2. در Actions، Workflow با نام `Bitget Classic Demo Read-only Check` را دستی اجرا کن. این تست باید API Classic Demo را تأیید کند و هیچ سفارشی نمی‌فرستد.
3. `TRADING_ENABLED` را همچنان `false` نگه دار. Workflow `Breakout V1 Dynamic Bitget Classic Demo Bot` را دستی اجرا کن؛ چون قفل خاموش است، اجرای بررسی/تحلیل مجاز است اما سفارش جدید نباید باز شود. خروجی خصوصی را در Google Sheets/Telegram بررسی کن.
4. فقط پس از موفقیت کامل تست‌های Read-only، تطبیق داده‌ها و کنترل پوزیشن‌ها، در صورت تصمیم آگاهانه `TRADING_ENABLED=true` را برای **Demo** فعال کن. `LIVE_TRADING=false` در Workflow قفل شده و موتور Mainnet را رد می‌کند.
5. زمان‌بند Apps Script را نصب کن. اجرای تحلیل هر ۴ ساعت و پایش موقعیت‌ها در فاصله‌های ۵ دقیقه‌ای هدف‌گذاری شده‌اند.

## ۶-الف) اعتبارسنجی گزارش، لاگ و ایمنی

نسخهٔ فعلی Cloud Runner پس از هر اجرای Bot یا Position Monitor چند کنترل اضافه انجام می‌دهد:

1. پیش از اجرای runtime، Syntax فایل \`google-apps-script/Code.gs\` و تست‌های گزارش‌دهی Apps Script بررسی می‌شوند.
2. خروجی runtime در فضای موقت Runner ثبت می‌شود. فقط نسخهٔ پاک‌سازی‌شده در لاگ عمومی نمایش داده و به‌صورت Artifact با نگهداری ۱۴روزه ذخیره می‌شود؛ فایل خام runtime در مخزن یا Artifact عمومی قرار نمی‌گیرد.
3. پس از پایان برنامه، \`scripts/verify_report.py\` وضعیت ذخیره‌شده را دوباره از Apps Script می‌خواند و \`run_status\`، \`run_mode\`، تعداد رویدادهای دریافت/ذخیره، وجود \`run_end\`، وضعیت ارسال Telegram، تعداد تحلیل بازار و قفل‌های ورود را کنترل می‌کند.
4. Workflow جداگانهٔ **Cloud Runner Reporting Validation** به تغییر فایل‌های Apps Script، تست‌ها، اسکریپت‌ها و Workflowها واکنش نشان می‌دهد. این Workflow فقط تست آفلاین و استاتیک انجام می‌دهد و به API صرافی متصل نمی‌شود.
5. Workflow پایش پوزیشن از \`SIGNAL_DATA_SOURCE=bitget_linear\` استفاده می‌کند تا دادهٔ کندل مدیریت پوزیشن از همان بازار Futures مربوط به Bitget خوانده شود؛ اسکن Universe و ورود جدید در مسیر Monitor خاموش است.

### به‌روزرسانی ضروری Apps Script بعد از انتشار Code.gs جدید

تغییر فایل GitHub پروژهٔ مستقرشدهٔ Google Apps Script را خودکار تغییر نمی‌دهد. برای فعال‌شدن batch persistence، گزارش \`report_delivery\` و اعلان‌های اصلاح‌شده:

1. پروژهٔ Apps Script متصل به Google Sheet را باز کن.
2. فایل \`Code.gs\` را با نسخهٔ همین مخزن در مسیر \`google-apps-script/Code.gs\` به‌طور کامل جایگزین کن و Save بزن.
3. \`Deploy → Manage deployments\` را باز کن، Web App فعلی را Edit کن، \`New version\` را انتخاب و Deploy کن.
4. URL فعلی \`/exec\` را حفظ کن؛ Secretها و Script Properties را پاک یا بازسازی نکن.

بعد از Deploy، اجرای Bot یا Monitor باید در snapshot فیلد \`report_delivery\` داشته باشد. وجود این فیلد و تأیید ذخیرهٔ همهٔ رویدادها و ارسال Telegram توسط مرحلهٔ نهایی Workflow کنترل می‌شود. اگر فیلد وجود نداشته باشد، معمولاً نسخهٔ قدیمی Web App هنوز مستقر است یا ذخیرهٔ metadata کامل نشده؛ جزئیات اجرای Apps Script را بررسی کن.

**مهم:** تا زمان تأیید نهایی، مقادیر ثابت \`TRADING_ENABLED=false\` و \`LIVE_TRADING=false\` را تغییر نده. بررسی گزارش به معنی فعال‌سازی سفارش‌گذاری نیست.

## ۷) جلوگیری از اجرای دوگانه

در مخزن خصوصی قدیمی `Breakout-V1-Dynamic`، Workflowهای زمان‌بندی‌شدهٔ قدیمی Bot و Position Monitor را در تب Actions غیرفعال کن تا دو موتور هم‌زمان اجرا نشوند. مخزن قدیمی را خصوصی نگه دار.

## محدودیت‌های عملی

- GitHub زمان تخصیص Runner را در ثانیهٔ مشخص تضمین نمی‌کند. Trigger پنج‌دقیقه‌ای Apps Script نیز ممکن است کمی زودتر یا دیرتر اجرا شود.
- اگر Workflow قبلی هنوز در حال اجرا باشد، زمان‌بند اجرای جدیدی Dispatch نمی‌کند؛ تیک‌های مانیتور در این حالت ممکن است از دست بروند یا به اجرای بعد موکول شوند.
- منطق Chandelier و Break-even همچنان بر اساس کندل بسته‌شدهٔ ۴ساعته به‌روزرسانی می‌شود؛ مانیتور ۵دقیقه‌ای به معنی Trailing بلادرنگ نیست. حد ضرر ثبت‌شده در صرافی، حفاظت اصلی بین اجراهای دوره‌ای است.
- سهمیهٔ Google Apps Script برای حساب مصرفی محدود است؛ سقف زمان اجرای Trigger روزانه ۹۰ دقیقه و زمان هر اجرای اسکریپت ۶ دقیقه است. در این معماری Apps Script فقط چند درخواست سبک GitHub می‌فرستد.
- مخزن عمومی فقط payload رمزگذاری‌شده را نگه می‌دارد، اما نام Workflowها، زمان و وضعیت اجراها عمومی‌اند. هنگام اجرا، متن اصلی فقط در فضای موقت Runner باز می‌شود.
- هیچ سرویس رایگان ابری، تأخیر صفر یا دسترس‌پذیری ۱۰۰٪ تضمین نمی‌کند. این پروژه برای Bitget Classic Futures Demo است و سودآوری را تضمین نمی‌کند.
