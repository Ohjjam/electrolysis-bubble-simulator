"""Expose the local app to the internet.

    python server_tunnel.py

Provider preference:
  1. ngrok (if installed + authtoken configured). With a claimed static domain
     in tunnel_config.json the URL is PERMANENT; without one it is random per
     start. Free-tier note: browsers see a one-click interstitial per session.
  2. Cloudflare quick tunnel fallback (no account; URL changes every start).

Config: tunnel_config.json  {"provider": "ngrok", "domain": "xxx.ngrok-free.app"}
The OFF desktop button stops the server and any tunnel.
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CFG = ROOT / "tunnel_config.json"
CLOUDFLARED = ROOT / "cloudflared.exe"
LOG = ROOT / "tunnel.log"
URL_FILE = ROOT / "tunnel_url.txt"
DL_URL = ("https://github.com/cloudflare/cloudflared/releases/latest/"
          "download/cloudflared-windows-amd64.exe")
PYW = os.path.expandvars(r"%LOCALAPPDATA%\Python\pythoncore-3.14-64\pythonw.exe")
if not os.path.exists(PYW):
    PYW = "pythonw"


def load_cfg():
    try:
        return json.loads(CFG.read_text(encoding="utf-8"))
    except Exception:
        return {"provider": "ngrok" if shutil.which("ngrok") else "cloudflare",
                "domain": ""}


def server_alive():
    try:
        return urllib.request.urlopen("http://127.0.0.1:8765/api/state",
                                      timeout=2).status == 200
    except Exception:
        return False


def ensure_server():
    if server_alive():
        return
    print("  starting the app server...")
    subprocess.Popen([PYW, str(ROOT / "server_app.py"), "--no-browser"],
                     cwd=str(ROOT), creationflags=0x208)
    for _ in range(20):
        time.sleep(0.5)
        if server_alive():
            return
    raise SystemExit("could not start the app server (see server_error.log)")


# ------------------------------------------------------------------- ngrok
def ngrok_current_url():
    """Public URL from the local ngrok agent API (None if not running)."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:4040/api/tunnels",
                                    timeout=2) as r:
            for t in json.load(r).get("tunnels", []):
                if t.get("public_url", "").startswith("https://"):
                    return t["public_url"]
    except Exception:
        pass
    return None


def start_ngrok(domain):
    url = ngrok_current_url()
    if url:
        print("  ngrok already running.")
        return url
    cmd = ["ngrok", "http", "8765", "--log", "stdout"]
    if domain:
        cmd += ["--url", domain]
    logf = open(LOG, "w", encoding="utf-8")
    subprocess.Popen(cmd, stdout=logf, stderr=subprocess.STDOUT,
                     cwd=str(ROOT), creationflags=0x208)
    print("  waiting for ngrok", end="")
    for _ in range(30):
        time.sleep(1)
        print(".", end="", flush=True)
        url = ngrok_current_url()
        if url:
            print()
            return url
    print()
    raise SystemExit("ngrok did not come up — see tunnel.log "
                     "(authtoken? domain typo? network?)")


# -------------------------------------------------------------- cloudflare
def ensure_cloudflared():
    if CLOUDFLARED.exists():
        return
    print("  downloading cloudflared (first time only, ~60 MB)...")
    tmp = CLOUDFLARED.with_suffix(".part")
    with urllib.request.urlopen(DL_URL, timeout=120) as r, open(tmp, "wb") as f:
        while True:
            chunk = r.read(1 << 18)
            if not chunk:
                break
            f.write(chunk)
    tmp.rename(CLOUDFLARED)


def start_cloudflare():
    chk = subprocess.run('tasklist /FI "IMAGENAME eq cloudflared.exe"',
                         shell=True, capture_output=True, text=True,
                         errors="replace")
    if "cloudflared.exe" in chk.stdout:
        m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com",
                       LOG.read_text(errors="replace") if LOG.exists() else "")
        if m:
            print("  tunnel already running.")
            return m[-1]
    ensure_cloudflared()
    LOG.unlink(missing_ok=True)
    logf = open(LOG, "w", encoding="utf-8")
    subprocess.Popen([str(CLOUDFLARED), "tunnel", "--url", "http://127.0.0.1:8765"],
                     stdout=logf, stderr=subprocess.STDOUT,
                     cwd=str(ROOT), creationflags=0x208)
    print("  waiting for the public URL", end="")
    for _ in range(60):
        time.sleep(1)
        print(".", end="", flush=True)
        m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com",
                       LOG.read_text(errors="replace"))
        if m:
            print()
            return m[-1]
    print()
    raise SystemExit("tunnel did not come up (network blocked? see tunnel.log)")


def main():
    ensure_server()
    cfg = load_cfg()
    if cfg.get("provider") == "ngrok" and shutil.which("ngrok"):
        url = start_ngrok(cfg.get("domain", ""))
        fixed = bool(cfg.get("domain"))
    else:
        url = start_cloudflare()
        fixed = False
    URL_FILE.write_text(url, encoding="utf-8")
    try:
        subprocess.run("clip", input=url.encode(), shell=True, check=False)
        clip = " (clipboard에 복사됨)"
    except Exception:
        clip = ""
    print()
    print("  ====================================================")
    print(f"   외부 공유 링크{clip}:")
    print(f"     {url}")
    print("  ====================================================")
    if fixed:
        print("   * 고정 주소 — 언제 켜도 같은 링크입니다")
    else:
        print("   * 임시 주소 — 터널 재시작 시 바뀝니다")
        print("     (고정: dashboard.ngrok.com > Domains에서 무료 도메인 만들고")
        print("      tunnel_config.json의 domain에 넣으면 됩니다)")
    print("   * 브라우저 첫 방문 시 ngrok 안내 페이지에서 'Visit Site' 1회 클릭")
    print("   * 끄기: 바탕화면 '서버 끄기' (서버+터널 모두 종료)")


if __name__ == "__main__":
    main()
