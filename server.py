import os
import secrets
import uuid
from datetime import datetime

import httpx
from fastapi import Depends, FastAPI, Form, HTTPException, status
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

MODAL_URL = os.environ["MODAL_URL"]
MODAL_API_KEY = os.environ["MODAL_API_KEY"]
APP_USER = os.environ.get("APP_USER", "admin")
APP_PASSWORD = os.environ["APP_PASSWORD"]
HISTORY_DIR = os.environ.get("HISTORY_DIR", "/app/history")

os.makedirs(HISTORY_DIR, exist_ok=True)

app = FastAPI()
security = HTTPBasic()


def auth(creds: HTTPBasicCredentials = Depends(security)) -> str:
    user_ok = secrets.compare_digest(creds.username.encode(), APP_USER.encode())
    pw_ok = secrets.compare_digest(creds.password.encode(), APP_PASSWORD.encode())
    if not (user_ok and pw_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return creds.username


app.mount("/history", StaticFiles(directory=HISTORY_DIR), name="history")


HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Image Generator</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; max-width: 760px; margin: 2rem auto; padding: 1rem;
         background: #0f0f10; color: #e8e8e8; }
  h1 { font-weight: 600; margin-bottom: 0.2rem; }
  .sub { color: #888; font-size: 0.9rem; margin-bottom: 1.5rem; }
  form { display: flex; gap: 0.5rem; }
  input[type=text] { flex: 1; padding: 0.7rem 0.9rem; font-size: 1rem; border-radius: 8px;
                     border: 1px solid #333; background: #1a1a1c; color: #fff; }
  button { padding: 0.7rem 1.2rem; font-size: 1rem; border-radius: 8px; border: none;
           background: #4a9d6a; color: white; cursor: pointer; }
  button:disabled { opacity: 0.5; cursor: not-allowed; }
  .status { margin-top: 1rem; color: #aaa; font-size: 0.9rem; min-height: 1.4rem; }
  .grid { margin-top: 1.5rem; display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 0.7rem; }
  .grid img { width: 100%; border-radius: 8px; cursor: pointer; transition: transform 0.15s; }
  .grid img:hover { transform: scale(1.03); }
  .latest { margin-top: 1.5rem; }
  .latest img { width: 100%; max-width: 512px; border-radius: 12px; display: block; }
  .prompt-tag { display: block; color: #888; font-size: 0.8rem; margin-top: 0.3rem; word-break: break-word; }
</style>
</head>
<body>
<h1>Image Generator</h1>
<div class="sub">FLUX.1-schnell · 4 steps · L4 on Modal</div>

<form id="genForm">
  <input id="prompt" type="text" placeholder="A cat astronaut on Mars, cinematic lighting" required autofocus>
  <button type="submit" id="btn">Generate</button>
</form>
<div class="status" id="status"></div>
<div class="latest" id="latest"></div>

<h2 style="margin-top:2rem;font-size:1.1rem;color:#aaa;">History</h2>
<div class="grid" id="grid"></div>

<script>
const form = document.getElementById('genForm');
const btn = document.getElementById('btn');
const statusEl = document.getElementById('status');
const latest = document.getElementById('latest');
const grid = document.getElementById('grid');

async function loadHistory() {
  const res = await fetch('/api/history');
  const items = await res.json();
  grid.innerHTML = items.map(i =>
    `<div><a href="${i.url}" target="_blank"><img src="${i.url}" loading="lazy"></a>
     <span class="prompt-tag">${i.prompt || ''}</span></div>`
  ).join('');
}

form.onsubmit = async (e) => {
  e.preventDefault();
  const prompt = document.getElementById('prompt').value.trim();
  if (!prompt) return;
  btn.disabled = true;
  statusEl.textContent = 'Generating… cold start can take ~30s, warm ~7s.';
  const t0 = performance.now();
  try {
    const fd = new FormData();
    fd.append('prompt', prompt);
    const res = await fetch('/generate', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.url) {
      const dt = ((performance.now() - t0) / 1000).toFixed(1);
      statusEl.textContent = `Done in ${dt}s.`;
      latest.innerHTML = `<img src="${data.url}"><span class="prompt-tag">${prompt}</span>`;
      loadHistory();
    } else {
      statusEl.textContent = 'Error: ' + (data.error || 'failed');
    }
  } catch (err) {
    statusEl.textContent = 'Error: ' + err.message;
  }
  btn.disabled = false;
};

loadHistory();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def home(_user: str = Depends(auth)) -> str:
    return HTML_PAGE


@app.get("/api/history")
def list_history(_user: str = Depends(auth)) -> list[dict]:
    items = []
    for name in sorted(os.listdir(HISTORY_DIR), reverse=True):
        if not name.endswith(".png"):
            continue
        prompt_path = os.path.join(HISTORY_DIR, name + ".txt")
        prompt = ""
        if os.path.exists(prompt_path):
            with open(prompt_path) as f:
                prompt = f.read().strip()
        items.append({"url": f"/history/{name}", "prompt": prompt})
    return items[:48]


@app.post("/generate")
async def generate(prompt: str = Form(...), _user: str = Depends(auth)) -> dict:
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(
            MODAL_URL,
            params={"prompt": prompt, "api_key": MODAL_API_KEY},
        )
    if r.status_code != 200:
        return {"error": f"Modal returned {r.status_code}: {r.text[:200]}"}

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    name = f"{stamp}_{uuid.uuid4().hex[:6]}.png"
    path = os.path.join(HISTORY_DIR, name)
    with open(path, "wb") as f:
        f.write(r.content)
    with open(path + ".txt", "w") as f:
        f.write(prompt)
    return {"url": f"/history/{name}"}
