import json
import os
import tempfile

HISTORY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "history.json")

def load_history():
    """加载已发送通知历史"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history):
    """保存通知历史"""
    directory = os.path.dirname(os.path.abspath(HISTORY_FILE))
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".history-", suffix=".tmp", delete=False) as f:
            temp_path = f.name
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, HISTORY_FILE)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)

def filter_new_notices(notices):
    """
    过滤出未记录的通知，不修改送达历史
    使用 URL 作为唯一标识
    """
    history = load_history()
    new_notices = []
    seen = set(history)
    for n in notices:
        uid = n["url"]
        if uid not in seen:
            seen.add(uid)
            new_notices.append(n)
    return new_notices


def queue_notices(notices, channels):
    """先保存待发送内容，失败后即使通知移出抓取时间窗口也能重试。"""
    if not channels:
        return
    history = load_history()
    changed = False
    for notice in notices:
        uid = notice["url"]
        if uid not in history:
            history[uid] = {**notice, "deliveries": {channel: False for channel in channels}}
            changed = True
    if changed:
        save_history(history)


def pending_notices(channel):
    history = load_history()
    pending = []
    for uid, entry in history.items():
        # 旧记录没有分渠道状态，沿用已发送语义，升级时不重新推送全部历史。
        if entry.get("deliveries", {}).get(channel) is False:
            notice = {key: value for key, value in entry.items() if key != "deliveries"}
            notice["url"] = uid
            pending.append(notice)
    return pending


def mark_delivered(notices, channel):
    history = load_history()
    for notice in notices:
        history[notice["url"]]["deliveries"][channel] = True
    save_history(history)
