#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ニコニコ動画「フォロー中のユーザーの新着動画」フィードAPIを取得し、
RSS 2.0 形式のXMLファイルとして出力するスクリプト。

【事前準備: user_session Cookieの取得方法】
1. ブラウザで https://www.nicovideo.jp にログインする
2. F12などで開発者ツールを開き、「Application」タブ(Chrome)または
   「Storage」タブ(Firefox) → Cookies → nicovideo.jp を選択
3. "user_session" という名前のCookieの値(user_session_xxxxx...という文字列)をコピー
4. 下の USER_SESSION 変数に貼り付け、または環境変数 NICO_USER_SESSION にセットする
   例: export NICO_USER_SESSION="user_session_123456_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"

【注意】
- user_sessionはログイン情報そのものなので、他人に絶対に教えないこと。
- セッションには有効期限があり、ログアウトすると無効になります。
- このAPIはニコニコの内部API(非公式)のため、仕様変更で動かなくなる可能性があります。
- nextCursorを使ったページネーションに対応していますが、カーソルの実際のクエリパラメータ名
  (CURSOR_PARAM_NAME)は未検証です。動かない場合は実際にブラウザの開発者ツールの
  Networkタブで、フォロー中タイムラインをスクロールした際に飛んでいるリクエストのURLを見て、
  パラメータ名を確認・修正してください。
"""

import os
import sys
import json
import html
from datetime import datetime, timezone
import urllib.request
import urllib.error
import urllib.parse

# ====== 設定 ======
USER_SESSION = os.environ.get("NICO_USER_SESSION", "")  # ここに直接書いてもOK
BASE_API_URL = "https://api.feed.nicovideo.jp/v1/activities/followings/video"
OUTPUT_FILE = os.environ.get("NICO_OUTPUT_FILE", "nico_followings.xml")

# ページネーション設定
CURSOR_PARAM_NAME = "untilId"  # APIの実際のパラメータ名が違う場合はここを変更
MAX_PAGES = 5                  # 取得する最大ページ数(無限ループ防止)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; NicoFeedFetcher/1.0)",
    "X-Frontend-Id": "6",
    "Accept": "application/json",
}


def build_url(cursor: str = "") -> str:
    """context=my_timeline は固定。cursorがあれば追加してページ送りする"""
    params = {"context": "my_timeline"}
    if cursor:
        params[CURSOR_PARAM_NAME] = cursor
    return f"{BASE_API_URL}?{urllib.parse.urlencode(params)}"


def fetch_json(url: str, user_session: str) -> dict:
    """指定URLにuser_session Cookie付きでGETし、JSONをdictで返す"""
    req = urllib.request.Request(url, headers=HEADERS)
    if user_session:
        req.add_header("Cookie", f"user_session={user_session}")

    try:
        with urllib.request.urlopen(req, timeout=15) as res:
            charset = res.headers.get_content_charset() or "utf-8"
            body = res.read().decode(charset)
            return json.loads(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[ERROR] HTTP {e.code}: {e.reason}", file=sys.stderr)
        print(body[:1000], file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[ERROR] 接続エラー: {e}", file=sys.stderr)
        sys.exit(1)


def extract_items(data: dict):
    """
    実際のレスポンスは {"activities": [...], "code": "ok", "nextCursor": "..."} の形式。
    各要素は content.type == "video" の投稿アクティビティ。
    """
    activities = data.get("activities", [])
    if not activities:
        print("[WARN] activities が空、または見つかりませんでした。レスポンスを確認してください:", file=sys.stderr)
        print(json.dumps(data, ensure_ascii=False, indent=2)[:3000], file=sys.stderr)

    # 動画投稿(またはチャンネル動画投稿)のアクティビティのみ抽出
    videos = [
        a for a in activities
        if isinstance(a, dict) and a.get("content", {}).get("type") == "video"
    ]
    return videos


def build_rss(items: list) -> str:
    now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")

    rss_items = []
    for activity in items:
        content = activity.get("content", {})
        actor = activity.get("actor", {})

        title = content.get("title", "(無題)")
        content_id = content.get("id", "")
        url = content.get("url", f"https://www.nicovideo.jp/watch/{content_id}" if content_id else "")
        started_at = content.get("startedAt", "")
        duration = content.get("video", {}).get("duration")
        thumbnail = activity.get("thumbnailUrl", "")
        author_name = actor.get("name", "")
        author_url = actor.get("url", "")

        pub_date = ""
        if started_at:
            try:
                dt = datetime.fromisoformat(started_at)
                pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S %z")
            except Exception:
                pub_date = ""

        duration_text = ""
        if isinstance(duration, int):
            m, s = divmod(duration, 60)
            duration_text = f"{m}:{s:02d}"

        desc_parts = []
        if thumbnail:
            desc_parts.append(f'<img src="{html.escape(thumbnail)}"/>')
        if author_name:
            desc_parts.append(f"投稿者: {html.escape(author_name)}")
        if duration_text:
            desc_parts.append(f"再生時間: {duration_text}")
        desc_html = "<br/>".join(desc_parts)

        rss_items.append(f"""    <item>
      <title>{html.escape(str(title))}</title>
      <link>{html.escape(str(url))}</link>
      <guid isPermaLink="false">{html.escape(str(content_id))}</guid>
      <description>{desc_html}</description>
      {f'<author>{html.escape(author_name)}</author>' if author_name else ''}
      {f'<pubDate>{pub_date}</pubDate>' if pub_date else ''}
    </item>""")

    rss = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>ニコニコ動画 - フォロー中の新着動画</title>
    <link>https://www.nicovideo.jp/my/follow</link>
    <description>フォロー中ユーザーの新着動画タイムライン</description>
    <lastBuildDate>{now}</lastBuildDate>
{chr(10).join(rss_items)}
  </channel>
</rss>
"""
    return rss


def main():
    if not USER_SESSION:
        print(
            "[ERROR] user_session が設定されていません。\n"
            "  環境変数 NICO_USER_SESSION にセットするか、\n"
            "  スクリプト内の USER_SESSION 変数に直接記入してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    all_activities = []
    cursor = ""

    for page in range(1, MAX_PAGES + 1):
        url = build_url(cursor)
        print(f"[INFO] ページ{page}を取得中... ({url})")
        data = fetch_json(url, USER_SESSION)

        activities = data.get("activities", [])
        if not activities:
            print("[INFO] activitiesが空になったため終了します。")
            break

        all_activities.extend(activities)

        next_cursor = data.get("nextCursor", "")
        if not next_cursor or next_cursor == cursor:
            print("[INFO] nextCursorが無いため終了します。")
            break
        cursor = next_cursor

    items = extract_items({"activities": all_activities})
    print(f"[INFO] 合計 {len(items)} 件の動画を取得しました。")

    rss_xml = build_rss(items)

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(rss_xml)

    print(f"[INFO] RSSファイルを書き出しました: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
