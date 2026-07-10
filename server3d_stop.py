"""Stop the running 3-D app server (asks it to exit via /api3d/shutdown)."""
import urllib.request

try:
    urllib.request.urlopen("http://127.0.0.1:8766/api3d/shutdown", data=b"{}", timeout=3)
    print("3D server stopped.")
except Exception:
    print("3D server was not running.")
