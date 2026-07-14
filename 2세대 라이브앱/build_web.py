"""Build the static, server-free web app (Pyodide) from app.html + the kernel.

    py -3.14 build_web.py        (or: python build_web.py)

Produces docs/ :
    index.html           app.html with its HTTP layer swapped for an in-browser
                         Python kernel (Pyodide). Same UI, same physics.
    bubblesim_pkg.zip    the kernel + server_app + sim_bridge, loaded at runtime.
    .nojekyll            so GitHub Pages serves every file verbatim.

Deploy docs/ to any static host -- the simulator then runs entirely in the
visitor's browser: no server, no tunnel, no per-frame round-trip => no lag.
Edit app.html / the kernel, re-run this, re-deploy -> everyone gets the update.

Output goes to docs/ because GitHub Pages can serve "main branch /docs" with one
click (Settings -> Pages). Cloudflare Pages / Netlify can target docs/ too.
"""
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent          # this folder: app.html + server files
PROJ = ROOT.parent                              # project root: bubblesim/ and docs/
OUT = PROJ / "docs"
PYODIDE = "0.28.3"

# packed into the zip Pyodide unpacks into its virtual FS (importable at runtime)
PKG_FILES = ["server_app.py", "sim_bridge.py"]
PKG_DIRS = ["bubblesim"]

# --- injected just before </head>: load Pyodide, boot the kernel, route /api/* ---
BOOT = """
<!-- ===== Pyodide bootstrap: in-browser Python kernel (replaces the server) ===== -->
<script src="https://cdn.jsdelivr.net/pyodide/v__PYODIDE__/full/pyodide.js"></script>
<script>
"use strict";
var _realFetch = window.fetch.bind(window);
function _jsonResp(s){ return { ok:true, status:200, json:function(){ return Promise.resolve(JSON.parse(s)); } }; }
function _okResp(){ return { ok:true, status:200, json:function(){ return Promise.resolve({ok:1}); } }; }
function _boot(m){ var e=document.getElementById("bootmsg"); if(e) e.textContent=m; }

window.__readyPromise = (async function(){
  _boot("Python 런타임 다운로드 중… (최초 1회만, 이후 캐시)");
  var pyodide = await loadPyodide();
  _boot("수치 라이브러리(numpy) 로딩 중…");
  await pyodide.loadPackage("numpy");
  _boot("물리 커널 푸는 중…");
  var buf = await _realFetch("bubblesim_pkg.zip").then(function(r){ return r.arrayBuffer(); });
  await pyodide.unpackArchive(buf, "zip");
  pyodide.runPython("import sys; sys.path.insert(0, '.')");
  _boot("시뮬레이터 초기화 중…");
  window.__bridge = pyodide.runPython("import sim_bridge\\nsim_bridge");
  var pump = function(){
    try { window.__bridge.pump(performance.now()/1000); } catch(e){ console.error(e); }
    requestAnimationFrame(pump);
  };
  requestAnimationFrame(pump);
  var ov = document.getElementById("bootoverlay"); if(ov) ov.style.display="none";
  return true;
})().catch(function(err){
  console.error(err);
  var e=document.getElementById("bootmsg");
  if(e) e.innerHTML = "초기화 실패: " + String(err)
    + "<br><span style='font-size:12px'>새로고침 해보세요 (최초 로딩엔 인터넷 필요).</span>";
  throw err;
});

// route the page's /api/* calls into the in-browser kernel instead of the network
window.fetch = function(url, opts){
  if(typeof url === "string" && url.indexOf("/api/") === 0){
    return window.__readyPromise.then(function(){
      if(url === "/api/state") return _jsonResp(window.__bridge.state());
      if(url === "/api/eis")   return _jsonResp(window.__bridge.eis());
      if(url === "/api/op"){    window.__bridge.op((opts&&opts.body)||"{}"); return _okResp(); }
      if(url === "/api/reset"){ window.__bridge.reset(); return _okResp(); }
      return _okResp();
    });
  }
  return _realFetch.apply(this, arguments);
};
</script>
"""

# --- injected right after <body>: full-screen loading overlay (hidden when ready) ---
OVERLAY = """
<div id="bootoverlay" style="position:fixed;inset:0;background:#0b0f14;z-index:99999;display:flex;flex-direction:column;align-items:center;justify-content:center;color:#dbe4f0;font:15px 'Segoe UI',system-ui,sans-serif">
  <div style="font-size:21px;margin-bottom:12px">⚗️ 전기화학 버블 시뮬레이터</div>
  <div style="width:42px;height:42px;border:4px solid #1f2937;border-top-color:#4da3ff;border-radius:50%;animation:bsp .9s linear infinite"></div>
  <div id="bootmsg" style="color:#8a93a3;margin-top:16px">시작 중…</div>
  <div style="color:#5a6577;margin-top:8px;font-size:12px">브라우저 안에서 Python 물리 커널이 직접 계산합니다 — 서버 없음</div>
  <style>@keyframes bsp{to{transform:rotate(360deg)}}</style>
</div>
"""


def build():
    html = (ROOT / "app.html").read_text(encoding="utf-8")

    boot = BOOT.replace("__PYODIDE__", PYODIDE)
    if "</head>" not in html:
        raise SystemExit("app.html: no </head> to inject into")
    html = html.replace("</head>", boot + "</head>", 1)

    if "<body>" not in html:
        raise SystemExit("app.html: no <body> to inject the overlay after")
    html = html.replace("<body>", "<body>\n" + OVERLAY, 1)

    # don't start polling until the kernel is ready
    start = "poll();\npollEIS();"
    if start not in html:
        raise SystemExit("app.html: startup 'poll();\\npollEIS();' not found")
    html = html.replace(start, "window.__readyPromise.then(function(){ poll(); pollEIS(); });", 1)

    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(html, encoding="utf-8")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")

    zpath = OUT / "bubblesim_pkg.zip"
    n = 0
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in PKG_FILES:
            z.write(ROOT / f, f)
            n += 1
        for d in PKG_DIRS:
            for p in sorted((PROJ / d).rglob("*.py")):
                if "__pycache__" in p.parts:
                    continue
                z.write(p, str(p.relative_to(PROJ)).replace("\\", "/"))
                n += 1

    print("OK  ->  docs/index.html  +  docs/bubblesim_pkg.zip")
    print("    python files packed : %d" % n)
    print("    zip size            : %.0f KB" % (zpath.stat().st_size / 1024))
    print("    pyodide             : v%s (from jsdelivr CDN)" % PYODIDE)
    print()
    print("Test locally (must be over http, NOT file://):")
    print("    py -3.14 -m http.server 8123 -d docs")
    print("    -> open http://localhost:8123/")
    print()
    print("Deploy: commit docs/ and push, then GitHub Settings -> Pages ->")
    print("        Source: 'Deploy from a branch', Branch: main, Folder: /docs")


if __name__ == "__main__":
    build()
