"""海外債知識群島 — Streamlit 外殼（公開 repo）
這個 repo 只有外殼，島的內容放在私人 repo（Secrets 的 CONTENT_REPO），
執行時用唯讀的 GitHub 通行碼（GH_TOKEN）去讀，所以內容不會公開。

- 先輸入授權碼（和投資機長箱同一組，Secrets 的 PORTAL_PASSWORD）
- 通過後載入 island.html，並把 Supabase 設定注入網頁
- ?game=coupon / stopwatch / forest 會開啟遊樂園島上的三款遊戲
- 私人 repo 的 posters 資料夾放成交故事島的戰報海報（檔名＝案例代號）
- ?admin=1 是固收科上傳頁（要 ADMIN_PASSWORD 和可寫入的 GH_WRITE_TOKEN）：
  上傳「債市每日聚焦」（只留近 60 天）和「發行機構簡介」，存到私人 repo 的 focus／issuers 資料夾
- ?view=focus&d=日期、?view=issuer&id=代號 是放大看的頁面
"""
import base64
import datetime as dt
import hashlib
import io
import json
from zoneinfo import ZoneInfo

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


# ---------- 上傳資料（債市每日聚焦、發行機構簡介） ----------
ISSUERS = [("gs", "高盛集團"), ("socgen", "法國興業銀行"), ("wfc", "富國銀行"), ("db", "德意志銀行"),
           ("brk", "波克夏海瑟威"), ("axp", "美國運通"), ("aapl", "蘋果"), ("meta", "Meta"), ("googl", "Google"),
           ("amzn", "亞馬遜"), ("nvda", "輝達"), ("dis", "迪士尼"), ("sony", "Sony"), ("unh", "聯合健康集團"),
           ("gild", "吉利德科學")]
ISSUER_NAME = dict(ISSUERS)
KEEP_DAYS = 60
TZ = ZoneInfo("Asia/Taipei")


def gh_raw(path: str):
    """讀私人 repo 的檔案（bytes）；沒有就回傳 None。"""
    url = f"https://api.github.com/repos/{CONTENT_REPO}/contents/{path}?ref={CONTENT_BRANCH}"
    r = requests.get(url, timeout=20, headers={"Authorization": f"Bearer {GH_TOKEN}",
                                               "Accept": "application/vnd.github.raw",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    return r.content if r.status_code == 200 else None


@st.cache_data(ttl=300, show_spinner=False)
def load_index(kind: str):
    """focus/index.json 是清單（新的在前）；issuers/index.json 是 {代號: {...}}。"""
    b = gh_raw(f"{kind}/index.json")
    try:
        return json.loads(b.decode("utf-8")) if b else ([] if kind == "focus" else {})
    except Exception:
        return [] if kind == "focus" else {}


@st.cache_data(ttl=300, show_spinner=False)
def load_image(path: str) -> str:
    b = gh_raw(path)
    return ("data:image/webp;base64," + base64.b64encode(b).decode()) if b else ""


@st.cache_data(ttl=300, show_spinner=False)
def load_json(path: str, default):
    b = gh_raw(path)
    try:
        return json.loads(b.decode("utf-8")) if b else default
    except Exception:
        return default


def top10_payload():
    """熱銷前十大：top10.json 是你在上傳頁填的代碼；quotes/latest.json 是龍蝦上傳報價檔時同步過來的全部報價。"""
    cfg = load_json("top10.json", {})
    items = cfg.get("items") or []
    if not items:
        return None
    q = load_json("quotes/latest.json", {})
    by = {str(b.get("code", "")).strip().upper(): b for b in q.get("bonds", [])}
    out = []
    for it in items:
        code = str(it.get("code", "")).strip().upper()
        if code:
            out.append({"code": code, "ltv": it.get("ltv", ""), "q": by.get(code)})
    return {"date": q.get("date", ""), "title": cfg.get("title", "熱銷前十大"), "items": out}


def recent_focus():
    cut = (dt.datetime.now(TZ).date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    return [x for x in load_index("focus") if x.get("d", "") >= cut]


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

# ---------- 放大看：債市每日聚焦／發行機構簡介 ----------
view = qp.get("view")
if view in ("focus", "issuer"):
    st.markdown("<style>header,footer,#MainMenu{display:none!important}.block-container{max-width:900px;padding-top:1rem}</style>",
                unsafe_allow_html=True)
    if view == "focus":
        d = qp.get("d", "")
        item = next((x for x in load_index("focus") if x.get("d") == d), None)
        title = f"債市每日聚焦｜{d}" + (f"｜{item.get('title')}" if item and item.get("title") else "")
    else:
        iid = qp.get("id", "")
        item = load_index("issuers").get(iid)
        title = f"{ISSUER_NAME.get(iid, iid)}｜發行機構簡介"
    st.subheader(title)
    if not item:
        st.info("找不到這份資料，可能已經超過保留期間或被刪除了。")
        st.stop()
    if item.get("text"):
        st.write(item["text"])
    for path in item.get("pages", []):
        src = load_image(path)
        if src:
            st.image(src, use_container_width=True)
    st.caption("僅供內部教育訓練使用，請勿外流。")
    st.stop()

# ---------- 固收科上傳頁（?admin=1） ----------
if qp.get("admin") == "1":
    ADMIN_PW = str(st.secrets.get("ADMIN_PASSWORD", "")).strip()
    WRITE_TOKEN = str(st.secrets.get("GH_WRITE_TOKEN", "")).strip()
    st.markdown("<style>header,footer,#MainMenu{display:none!important}.block-container{max-width:900px;padding-top:1rem}</style>",
                unsafe_allow_html=True)
    st.title("🏝️ 群島上傳頁")
    if not ADMIN_PW or not WRITE_TOKEN:
        st.error("Secrets 還少了 " + "、".join([n for n, v in (("ADMIN_PASSWORD", ADMIN_PW), ("GH_WRITE_TOKEN", WRITE_TOKEN)) if not v])
                 + "。ADMIN_PASSWORD 是這個上傳頁的密碼；GH_WRITE_TOKEN 是可以寫入 bond-islands 的 GitHub 通行碼。")
        st.stop()
    if not st.session_state.get("admin_ok"):
        with st.form("adm", border=False):
            apw = st.text_input("上傳頁密碼", type="password")
            if st.form_submit_button("進入", type="primary"):
                if apw == ADMIN_PW:
                    st.session_state.admin_ok = True
                    st.rerun()
                st.error("密碼不對。")
        st.stop()

    WH = {"Authorization": f"Bearer {WRITE_TOKEN}", "Accept": "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28"}

    def gh_sha(path):
        r = requests.get(f"https://api.github.com/repos/{CONTENT_REPO}/contents/{path}?ref={CONTENT_BRANCH}",
                         headers=WH, timeout=20)
        return r.json().get("sha") if r.status_code == 200 else None

    def gh_put(path, data: bytes, msg):
        body = {"message": msg, "content": base64.b64encode(data).decode(), "branch": CONTENT_BRANCH}
        sha = gh_sha(path)
        if sha:
            body["sha"] = sha
        r = requests.put(f"https://api.github.com/repos/{CONTENT_REPO}/contents/{path}", headers=WH,
                         json=body, timeout=60)
        if r.status_code not in (200, 201):
            raise RuntimeError(f"寫入 {path} 失敗（{r.status_code}）：{r.text[:200]}")

    def gh_del(path, msg):
        sha = gh_sha(path)
        if sha:
            requests.delete(f"https://api.github.com/repos/{CONTENT_REPO}/contents/{path}", headers=WH,
                            json={"message": msg, "sha": sha, "branch": CONTENT_BRANCH}, timeout=30)

    def to_pages(files):
        """PDF 每頁轉成圖片；圖片直接壓縮。全部轉成 webp。"""
        from PIL import Image
        import pymupdf
        imgs = []
        for f in files:
            data = f.getvalue()
            if f.name.lower().endswith(".pdf"):
                doc = pymupdf.open(stream=data, filetype="pdf")
                for page in list(doc)[:10]:
                    pix = page.get_pixmap(dpi=120)
                    imgs.append(Image.frombytes("RGB", [pix.width, pix.height], pix.samples))
            else:
                imgs.append(Image.open(io.BytesIO(data)).convert("RGB"))
        out = []
        for im in imgs:
            if im.width > 1100:
                im = im.resize((1100, round(im.height * 1100 / im.width)))
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=72)
            out.append(buf.getvalue())
        return out

    def save_json(path, obj, msg):
        gh_put(path, json.dumps(obj, ensure_ascii=False, indent=1).encode("utf-8"), msg)

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📰 債市每日聚焦", "🏢 發行機構簡介", "🔥 熱銷前十大", "📣 全島廣播", "📊 統計"])
    SB_SERVICE = str(st.secrets.get("SUPABASE_SERVICE_KEY", "")).strip()
    SBH = {"apikey": SB_SERVICE, "Authorization": f"Bearer {SB_SERVICE}", "Content-Type": "application/json"}

    def need_service():
        st.warning("Secrets 還少了 SUPABASE_SERVICE_KEY（Supabase → Project Settings → API Keys 裡的 service_role／secret key）。"
                   "它只放在 Streamlit 這邊，不會傳到理專的瀏覽器。")

    def sb_get(path):
        r = requests.get(f"{SB_URL}/rest/v1/{path}", headers=SBH, timeout=20)
        if r.status_code != 200:
            raise RuntimeError(f"{r.status_code} {r.text[:160]}")
        return r.json()
    with tab1:
        st.caption(f"可以傳 PDF 或圖片（可多張），也可以只打文字。同一天再傳一次會覆蓋。島上只留近 {KEEP_DAYS} 天，超過的會自動刪掉。")
        with st.form("focus", clear_on_submit=True):
            day = st.date_input("日期", value=dt.datetime.now(TZ).date())
            ttl = st.text_input("標題（可不填）")
            txt = st.text_area("文字重點（可不填）", height=120)
            ups = st.file_uploader("檔案", type=["pdf", "png", "jpg", "jpeg", "webp"], accept_multiple_files=True)
            go = st.form_submit_button("上傳", type="primary")
        if go:
            if not ups and not txt.strip():
                st.warning("檔案和文字至少要有一個。")
            else:
                with st.spinner("上傳中…"):
                    d = day.isoformat()
                    idx = load_index("focus")
                    load_index.clear()
                    idx = [x for x in load_index("focus")]
                    old = next((x for x in idx if x.get("d") == d), None)
                    for pth in (old or {}).get("pages", []):
                        gh_del(pth, f"每日聚焦 {d}：覆蓋舊檔")
                    pages = []
                    for n, b in enumerate(to_pages(ups or []), 1):
                        pth = f"focus/{d}/p{n}.webp"
                        gh_put(pth, b, f"每日聚焦 {d} 第 {n} 頁")
                        pages.append(pth)
                    idx = [x for x in idx if x.get("d") != d] + [{"d": d, "title": ttl.strip(), "text": txt.strip(), "pages": pages}]
                    cut = (dt.datetime.now(TZ).date() - dt.timedelta(days=KEEP_DAYS)).isoformat()
                    for x in [x for x in idx if x.get("d", "") < cut]:
                        for pth in x.get("pages", []):
                            gh_del(pth, f"每日聚焦 {x['d']} 超過 {KEEP_DAYS} 天，自動刪除")
                    idx = sorted([x for x in idx if x.get("d", "") >= cut], key=lambda x: x["d"], reverse=True)
                    save_json("focus/index.json", idx, f"每日聚焦清單更新（{d}）")
                    load_index.clear()
                st.success(f"{d} 上傳完成，約 5 分鐘內島上就會更新。")
        st.divider()
        st.markdown("**目前島上的每日聚焦**")
        for x in load_index("focus"):
            c1, c2 = st.columns([5, 1])
            c1.write(f"{x['d']}　{x.get('title', '')}　（{len(x.get('pages', []))} 頁）")
            if c2.button("刪除", key="delf" + x["d"]):
                for pth in x.get("pages", []):
                    gh_del(pth, f"刪除每日聚焦 {x['d']}")
                save_json("focus/index.json", [y for y in load_index("focus") if y["d"] != x["d"]], f"刪除每日聚焦 {x['d']}")
                load_index.clear()
                st.rerun()
    with tab2:
        st.caption("選一家發行機構，傳 PDF 或圖片，或打一段文字簡介。再傳一次會覆蓋舊的。")
        with st.form("issuer", clear_on_submit=True):
            iid = st.selectbox("發行機構", [i for i, _ in ISSUERS], format_func=lambda i: ISSUER_NAME[i])
            txt2 = st.text_area("文字簡介（可不填）", height=120)
            ups2 = st.file_uploader("檔案", type=["pdf", "png", "jpg", "jpeg", "webp"], accept_multiple_files=True, key="iu")
            go2 = st.form_submit_button("上傳", type="primary")
        if go2:
            if not ups2 and not txt2.strip():
                st.warning("檔案和文字至少要有一個。")
            else:
                with st.spinner("上傳中…"):
                    load_index.clear()
                    idx = dict(load_index("issuers"))
                    for pth in idx.get(iid, {}).get("pages", []):
                        gh_del(pth, f"{ISSUER_NAME[iid]} 簡介：覆蓋舊檔")
                    pages = []
                    for n, b in enumerate(to_pages(ups2 or []), 1):
                        pth = f"issuers/{iid}/p{n}.webp"
                        gh_put(pth, b, f"{ISSUER_NAME[iid]} 簡介第 {n} 頁")
                        pages.append(pth)
                    idx[iid] = {"text": txt2.strip(), "pages": pages, "updated": dt.datetime.now(TZ).date().isoformat()}
                    save_json("issuers/index.json", idx, f"{ISSUER_NAME[iid]} 簡介更新")
                    load_index.clear()
                st.success(f"{ISSUER_NAME[iid]} 簡介上傳完成，約 5 分鐘內島上就會更新。")
        st.divider()
        st.markdown("**已有簡介的發行機構**")
        idx = load_index("issuers")
        for i, n in ISSUERS:
            if i in idx:
                c1, c2 = st.columns([5, 1])
                c1.write(f"{n}　（{len(idx[i].get('pages', []))} 頁，{idx[i].get('updated', '')} 更新）")
                if c2.button("刪除", key="deli" + i):
                    for pth in idx[i].get("pages", []):
                        gh_del(pth, f"刪除 {n} 簡介")
                    save_json("issuers/index.json", {k: v for k, v in idx.items() if k != i}, f"刪除 {n} 簡介")
                    load_index.clear()
                    st.rerun()
    with tab3:
        st.caption("依排名填產品代碼（WMBB 開頭），價格、YTM、評等等等會自動從每天上傳的報價檔帶入。"
                   "LTV 報價檔沒有，要自己填（例如 0.75），不填就顯示「－」。")
        load_json.clear()
        cur = load_json("top10.json", {})
        cur_items = (cur.get("items") or []) + [{}] * 10
        q = load_json("quotes/latest.json", {})
        by = {str(b.get("code", "")).strip().upper(): b for b in q.get("bonds", [])}
        st.info(f"目前報價日期：{q.get('date') or '還沒有同步過'}（共 {len(by)} 檔）")
        with st.form("top10"):
            ttl3 = st.text_input("標題", value=cur.get("title", "熱銷前十大"))
            rows = []
            for k in range(10):
                c1, c2, c3 = st.columns([3, 1, 4])
                code = c1.text_input(f"第 {k + 1} 名代碼", value=cur_items[k].get("code", ""), key=f"tc{k}")
                ltv = c2.text_input("LTV", value=str(cur_items[k].get("ltv", "")), key=f"tl{k}")
                hit = by.get(code.strip().upper()) if code.strip() else None
                c3.markdown(f"<div style='padding-top:30px;font-size:13px'>{'✅ ' + hit['name'] if hit else ('⚠️ 報價檔找不到' if code.strip() else '')}</div>",
                            unsafe_allow_html=True)
                rows.append((code.strip().upper(), ltv.strip()))
            go3 = st.form_submit_button("儲存", type="primary")
        if go3:
            items = [{"code": c, "ltv": l} for c, l in rows if c]
            save_json("top10.json", {"title": ttl3.strip() or "熱銷前十大", "items": items},
                      f"熱銷前十大更新（{len(items)} 檔）")
            load_json.clear()
            st.success(f"已儲存 {len(items)} 檔，約 5 分鐘內島上就會更新。")
    with tab4:
        st.caption("送出後，島上所有人 1 分鐘內會在畫面上方看到金色橫幅「📣 固收科：…」，聊天視窗也會出現。"
                   "到了設定的時間會自動消失。只有固收科能從這裡發，理專的附近聊天不受影響。")
        if not SB_SERVICE:
            need_service()
        else:
            now = dt.datetime.now(TZ)
            with st.form("ann", clear_on_submit=True):
                msg = st.text_area("廣播內容（最多 200 字，勿含客戶資料）", max_chars=200, height=100)
                c1, c2 = st.columns(2)
                ud = c1.date_input("顯示到（日期）", value=now.date())
                ut = c2.time_input("顯示到（時間）", value=dt.time(18, 0))
                go4 = st.form_submit_button("送出廣播", type="primary")
            if go4:
                until = dt.datetime.combine(ud, ut, tzinfo=TZ)
                if not msg.strip():
                    st.warning("請輸入廣播內容。")
                elif until <= now:
                    st.warning("顯示到的時間要晚於現在。")
                else:
                    r = requests.post(f"{SB_URL}/rest/v1/island_announce", headers=SBH, timeout=20,
                                      json={"msg": msg.strip(), "until": until.isoformat()})
                    if r.status_code in (200, 201, 204):
                        st.success(f"已廣播，顯示到 {until:%m/%d %H:%M}。")
                    else:
                        st.error(f"送出失敗（{r.status_code}）：{r.text[:200]}。如果是第一次用，請先在 Supabase 執行設定 SQL。")
            st.divider()
            st.markdown("**目前還在顯示的廣播**")
            try:
                rows = sb_get("island_announce?select=id,msg,until,created_at&until=gt." + now.isoformat().replace("+", "%2B")
                              + "&order=created_at.desc")
                if not rows:
                    st.caption("沒有。")
                for a in rows:
                    u = dt.datetime.fromisoformat(a["until"]).astimezone(TZ)
                    c1, c2 = st.columns([5, 1])
                    c1.write(f"{a['msg']}　（到 {u:%m/%d %H:%M}）")
                    if c2.button("撤下", key=f"ann{a['id']}"):
                        requests.patch(f"{SB_URL}/rest/v1/island_announce?id=eq.{a['id']}", headers=SBH, timeout=20,
                                       json={"until": now.isoformat()})
                        st.rerun()
            except Exception as e:
                st.error(f"讀不到廣播（{e}）。如果是第一次用，請先在 Supabase 執行設定 SQL。")
    with tab5:
        st.caption("匿名統計：只記這台裝置的隨機代號，不記名字。同一個人用手機和電腦會算兩台裝置。")
        if not SB_SERVICE:
            need_service()
        else:
            try:
                daily = sb_get("stats_daily?select=*&limit=60")
                top = sb_get("stats_top?select=*&limit=30")
                if daily:
                    last7 = daily[:7]
                    c1, c2, c3 = st.columns(3)
                    c1.metric("今天上島人次", daily[0]["上島人次"] if daily[0]["日期"] == dt.datetime.now(TZ).date().isoformat() else 0)
                    c2.metric("近 7 天上島人次", sum(x["上島人次"] for x in last7))
                    c3.metric("近 7 天點開內容", sum(x["點開內容次數"] for x in last7))
                    st.markdown("**每天**")
                    st.bar_chart({x["日期"]: x["上島人次"] for x in reversed(daily)})
                    st.dataframe(daily, use_container_width=True, hide_index=True)
                else:
                    st.info("還沒有資料。有人上島後就會出現。")
                st.markdown("**最熱門的內容（累計）**")
                if top:
                    st.dataframe(top, use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"讀不到統計（{e}）。如果是第一次用，請先在 Supabase 執行設定 SQL。")
    st.stop()

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
days = recent_focus()
focus = {"days": [{"d": x["d"], "title": x.get("title", "")} for x in days], "latest": None}
if days:
    L = days[0]
    focus["latest"] = {"d": L["d"], "title": L.get("title", ""), "text": L.get("text", ""),
                       "imgs": [u for u in (load_image(p) for p in L.get("pages", [])[:4]) if u]}
top10 = top10_payload()
issuers = {k: {"text": v.get("text", ""), "pages": v.get("pages", [])} for k, v in load_index("issuers").items()}
def js(o):
    return json.dumps(o, ensure_ascii=False).replace("</", "<\\/")


html = html.replace("/*__ISLAND_CONFIG__*/",
                    "window.ISLAND_CFG=" + json.dumps(cfg) + ";window.ISLAND_POSTERS=" + json.dumps(posters)
                    + ";window.ISLAND_FOCUS=" + js(focus)
                    + ";window.ISLAND_ISSUERS=" + js(issuers)
                    + ";window.ISLAND_TOP10=" + js(top10) + ";", 1)
components.html(html, height=860, scrolling=False)
