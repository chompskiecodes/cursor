# Render Deployment Checklist - Windows to Linux

## 1. Create `.gitattributes` file in project root:
```gitattributes
* text=auto
*.py text eol=lf
*.txt text eol=lf
*.md text eol=lf
*.yml text eol=lf
*.yaml text eol=lf
*.json text eol=lf
*.sh text eol=lf
requirements.txt text eol=lf
```

## 2. Fix line endings (run in Git Bash or WSL):
```bash
# This will convert all files to LF endings
git add --renormalize .
git commit -m "Normalize line endings"
```

## 3. Check for hardcoded paths:
Search your code for:
- Backslashes in paths (`\`)
- Hardcoded `C:\` or similar
- String paths instead of `os.path.join()`

## 4. Case sensitivity check:
- Verify all imports match file names exactly
- Check: `from Tools import ...` vs `from tools import ...`

## 5. Create `render.yaml` for deployment:
```yaml
services:
  - type: web
    name: voice-booking-api
    runtime: python
    buildCommand: "pip install -r requirements.txt"
    startCommand: "uvicorn main:app --host 0.0.0.0 --port $PORT"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: voice-booking-db
          property: connectionString
      - key: PYTHON_VERSION
        value: 3.11.0
      - key: ENVIRONMENT
        value: production
```

## 6. Environment Variables to Set on Render:
```
DATABASE_URL=(from Supabase)
API_KEY=MS0xNzAyMDE4MzQ3NzQ0MzcyMjM4LUs2YzJodjE2TEM1OVVGM0JTRU1GMHZ1K2Y5V0VmRHNH-au4
SUPABASE_KEY=(your key)
SUPABASE_URL=(your url)
CLINIKO_API_KEY=(if using fallback)
CLINIKO_SHARD=(if using fallback)
DEFAULT_TIMEZONE=Australia/Sydney
LOG_LEVEL=INFO
CORS_ORIGINS=["*"]
```

## 7. Update logging for production:
In your code, the `payload_logger.py` creates directories:
```python
self.log_dir.mkdir(exist_ok=True)
```

Consider if you want file logging in production or use Render's logging.

## 8. Database Connection:
Your code handles both formats:
```python
if not v.startswith(("postgresql://", "postgres://")):
```
This is good - Render uses `postgres://` which your code accepts.

## 9. Port Configuration:
Your main.py correctly uses:
```python
port = int(os.environ.get("PORT", 8000))
```
Render will provide the PORT variable.

## 10. Create a simple health check script:
```python
# test_deployment.py
import httpx
import os

def test_health():
    url = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
    response = httpx.get(f"{url}/health")
    print(f"Health check: {response.status_code}")
    print(response.json())

if __name__ == "__main__":
    test_health()
```

## Common Issues & Solutions:

### Issue: "No module named 'tools'"
**Fix**: Ensure `tools/__init__.py` exists and check case sensitivity

### Issue: File not found errors
**Fix**: Use `os.path.join()` or `pathlib.Path` for all file paths

### Issue: Database connection errors
**Fix**: Render uses `postgres://` not `postgresql://` - your code handles this ✅

### Issue: Timezone errors
**Fix**: You already include `tzdata` in requirements.txt ✅

### Issue: Memory errors
**Fix**: Render free tier has 512MB RAM. Your connection pool settings are reasonable:
```python
min_size=5, max_size=20
```

## Testing Before Deploy:

1. **Run in WSL/Linux locally**:
```bash
# In WSL or Linux VM
python -m venv venv
source venv/bin/activate  # Linux activation
pip install -r requirements.txt
python main.py
```

2. **Use Docker to test Linux environment**:
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Post-Deployment:

1. Check Render logs for any errors
2. Test all endpoints with your cache testing script
3. Update ElevenLabs webhooks to use Render URL
4. Monitor performance and adjust connection pool if needed