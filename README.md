## Music Bot Stable (FastAPI webhook + PTB)

### Env vars
- BOT_TOKEN — токен бота
- WEBHOOK_URL — полный URL: `https://your-domain/telegram`
- BASE_URL — базовый URL: `https://your-domain`
- ADMIN_ID — твой user id
- COOKIES_TXT — (опционально) содержимое cookies.txt

### Run locally
```bash
pip install -r requirements.txt
export BOT_TOKEN=...
export WEBHOOK_URL=https://....../telegram
export BASE_URL=https://....
export ADMIN_ID=123
uvicorn main:app --reload --port 8080
Команды
/player
/radio <query>
/skip
/stop
/status
/admin (только ADMIN_ID)