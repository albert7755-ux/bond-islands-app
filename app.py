"""海外債知識群島 — Streamlit 外殼（公開 repo）
這個 repo 只有外殼，島的內容放在私人 repo（Secrets 的 CONTENT_REPO），
執行時用唯讀的 GitHub 通行碼（GH_TOKEN）去讀，所以內容不會公開。

- 先輸入授權碼（和投資機長箱同一組，Secrets 的 PORTAL_PASSWORD）
- 通過後載入 island.html，並把 Supabase 設定注入網頁
- ?game=coupon / stopwatch / forest 會開啟遊樂園島上的三款遊戲
- 私人 repo 的 posters 資料夾放成交故事島的戰報海報（檔名＝案例代號）
"""
import base64
import hashlib
import json

import requests
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="海外債知識群島", page_icon="🏝️", layout="wide",
                   initial_sidebar_state="collapsed")

# 遊戲檔放在私人 repo 最上層或 games 資料夾都可以，會依序找
GAMES = {
    "coupon": ["coupon.html", "games/coupon.html"],
    "stopwatch": ["stopwatch.html", "games/stopwatch.html"],
    "forest": ["forest.html", "games/forest.html"],
}

# ---------- 讀 Secrets ----------
NEED = ["PORTAL_PASSWORD", "SUPABASE_URL", "SUPABASE_ANON_KEY", "GH_TOKEN"]
try:
    have = list(st.secrets.keys())
except Exception:
    st.error("Secrets 的格式有錯，系統看不懂。最常見的原因是引號被換成彎引號（“ ”），"
             "請改成直的雙引號（\"），每一行都是 名稱 = \"值\" 的格式。")
    st.stop()
missing = [k for k in NEED if not str(st.secrets.get(k, "")).strip()]
if missing:
    st.error("Secrets 少了這幾行：" + "、".join(missing))
    st.caption("目前讀到的名稱：" + ("、".join(have) if have else "（一行都沒有，可能還沒按 Save）")
               + "。名稱要全部大寫、用底線，不能有空格或全形字。改完按 Save，等一分鐘再重新整理。")
    st.stop()
PASSWORD = str(st.secrets["PORTAL_PASSWORD"])
SB_URL = str(st.secrets["SUPABASE_URL"]).strip()
SB_KEY = str(st.secrets["SUPABASE_ANON_KEY"]).strip()
GH_TOKEN = str(st.secrets["GH_TOKEN"]).strip()
CONTENT_REPO = str(st.secrets.get("CONTENT_REPO", "albert7755-ux/bond-islands")).strip()
CONTENT_BRANCH = str(st.secrets.get("CONTENT_BRANCH", "main")).strip()


@st.cache_data(ttl=300, show_spinner=False)
def load_content(path: str) -> str:
    """從私人 repo 讀檔案。快取 5 分鐘：你在 GitHub 改了內容，最多 5 分鐘後生效。"""
    url = f"https://api.github.com/repos/{CONTENT_REPO}/contents/{path}?ref={CONTENT_BRANCH}"
    r = requests.get(url, timeout=20, headers={
        "Authorization": f"Bearer {GH_TOKEN}",
        "Accept": "application/vnd.github.raw",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    if r.status_code != 200:
        raise RuntimeError(f"{r.status_code}")
    r.encoding = "utf-8"
    return r.text


@st.cache_data(ttl=300, show_spinner=False)
def load_posters() -> dict:
    """讀私人 repo 的 posters 資料夾（成交故事島的戰報海報）。
    檔名就是案例代號，例如 posters/case-hl.webp。資料夾不存在就回傳空的。"""
    base = f"https://api.github.com/repos/{CONTENT_REPO}/contents/posters?ref={CONTENT_BRANCH}"
    head = {"Authorization": f"Bearer {GH_TOKEN}", "X-GitHub-Api-Version": "2022-11-28"}
    try:
        r = requests.get(base, timeout=20, headers={**head, "Accept": "application/vnd.github+json"})
        if r.status_code != 200:
            return {}
        out = {}
        mime = {"webp": "image/webp", "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png"}
        for f in r.json():
            name = f.get("name", "")
            stem, _, ext = name.rpartition(".")
            if f.get("type") != "file" or ext.lower() not in mime or f.get("size", 0) > 900_000:
                continue
            b = requests.get(f["url"], timeout=20, headers={**head, "Accept": "application/vnd.github.raw"})
            if b.status_code == 200:
                out[stem] = f"data:{mime[ext.lower()]};base64," + base64.b64encode(b.content).decode()
        return out
    except Exception:
        return {}


def show_load_error(path: str, err: Exception) -> None:
    code = str(err)
    why = {
        "401": "GitHub 通行碼（GH_TOKEN）不對或已過期，請到 GitHub 重新產生一組，貼回 Secrets。",
        "403": "GitHub 通行碼沒有讀取權限，請確認它有勾選這個 repo，而且 Contents 設成 Read-only。",
        "404": f"在 {CONTENT_REPO} 找不到 {path}。請確認檔案有上傳、名稱和資料夾都對。",
    }.get(code, f"讀取內容失敗（{code}），請稍後重新整理。")
    st.error(why)


# 遊戲連結帶的通行碼（由授權碼推算，換授權碼就會一起失效）
TOKEN = hashlib.sha256(f"bond-islands:{PASSWORD}".encode()).hexdigest()[:20]

FULL = """
<style>
header, footer, #MainMenu, [data-testid="stToolbar"], [data-testid="stDecoration"] {display:none!important;}
.block-container {padding:0!important; max-width:100%!important;}
[data-testid="stAppViewContainer"] > .main {padding:0!important;}
iframe {display:block; width:100%; height:100dvh!important; border:0;}
</style>
"""

LOGIN_CSS = """
<style>
.stApp {background:#0e1626;}
.login {max-width:360px; margin:12vh auto 0; text-align:center; color:#e8edf6;}
.login h1 {font-size:30px; margin:0 0 6px; color:#e8edf6;}
.login p {color:#9aa7bd; font-size:14px; margin:0 0 18px;}
</style>
"""

# ---------- 授權 ----------
qp = st.query_params
if qp.get("k") == TOKEN:
    st.session_state.authed = True

if not st.session_state.get("authed"):
    st.markdown(LOGIN_CSS, unsafe_allow_html=True)
    st.markdown('<div class="login"><h1>🏝️ 海外債知識群島</h1><p>僅供內部教育訓練使用，請輸入授權碼</p></div>',
                unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 2, 1])
    with mid:
        with st.form("login", border=False):
            pwd = st.text_input("授權碼", type="password", placeholder="輸入授權碼", label_visibility="collapsed")
            ok = st.form_submit_button("上島", use_container_width=True, type="primary")
        if ok:
            if pwd == PASSWORD:
                st.session_state.authed = True
                st.rerun()
            else:
                st.error("授權碼不對，再試一次。")
    st.stop()

# 這個 app 自己的網址（遊戲連結要用）；Secrets 有填 APP_URL 就用它
host = ""
try:
    host = st.context.headers.get("host", "")
except Exception:
    pass
APP_URL = st.secrets.get("APP_URL", f"https://{host}/" if host else "")

# ---------- 遊樂園島的三款遊戲 ----------
game = qp.get("game")
if game in GAMES:
    html, last_err = None, None
    for path in GAMES[game]:
        try:
            html = load_content(path)
            break
        except Exception as e:
            last_err = e
            if str(e) != "404":
                break
    if html is None:
        show_load_error(GAMES[game][0], last_err)
        st.stop()
    st.markdown(FULL, unsafe_allow_html=True)
    components.html(html, height=860, scrolling=True)
    st.stop()

# ---------- 群島 ----------
try:
    html = load_content("island.html")
except Exception as e:
    show_load_error("island.html", e)
    st.stop()

st.markdown(FULL, unsafe_allow_html=True)
if not html.lstrip().lower().startswith("<!doctype"):
    html = ('<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            '<style>body{margin:0;font:14px system-ui,sans-serif}</style></head><body>' + html + '</body></html>')
cfg = {"url": SB_URL, "key": SB_KEY, "app": APP_URL, "k": TOKEN}
posters = load_posters()
html = html.replace("/*__ISLAND_CONFIG__*/",
                    "window.ISLAND_CFG=" + json.dumps(cfg) + ";window.ISLAND_POSTERS=" + json.dumps(posters) + ";", 1)
components.html(html, height=860, scrolling=False)
