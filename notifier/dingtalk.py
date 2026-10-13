import requests
import time
import hmac
import hashlib
import base64
import urllib.parse

class DingTalkSender:
    """钉钉机器人通知"""

    def __init__(self, dt_config):
        self.cfg = dt_config
        self.enabled = dt_config.get("enabled", False)

    def _sign(self):
        """钉钉加签"""
        secret = self.cfg.get("secret", "")
        if not secret:
            return ""
        timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        return f"&timestamp={timestamp}&sign={sign}"

    def send(self, notices):
        """发送钉钉通知"""
        if not self.enabled or not notices:
            return False
        try:
            webhook = self.cfg["webhook"] + self._sign()
            content = self._build_markdown(notices)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"校园通知 - {len(notices)}条新通知",
                    "text": content
                }
            }
            resp = requests.post(webhook, json=payload, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") != 0:
                print(f"[ERROR] 钉钉拒绝通知: {result}")
                return False
            print(f"[OK] 钉钉通知已发送: {result}")
            return True
        except Exception as e:
            print(f"[ERROR] 钉钉发送失败: {e}")
            return False

    def _build_markdown(self, notices):
        lines = [f"## 📢 校园通知速递", f"发现 **{len(notices)}** 条新通知\n"]
        for n in notices:
            source = n['source']
            section = n.get('section', '')
            lines.append(
                f"- **【{source}-{section}】** [{n['title']}]({n['url']})  _{n['date']}_"
            )
        return "\n".join(lines)
