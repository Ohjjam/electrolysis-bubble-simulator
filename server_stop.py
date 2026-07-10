"""Stop the running app server (asks it to exit via /api/shutdown)."""
import urllib.request

try:
    urllib.request.urlopen("http://127.0.0.1:8765/api/shutdown", data=b"{}", timeout=3)
    print("server stopped.")
except Exception:
    print("server was not running.")
