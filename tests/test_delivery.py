import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from notifier.dispatcher import dispatch_notices
from notifier.dingtalk import DingTalkSender
from notifier.email_sender import EmailSender
from storage import history


NOTICE = {
    "url": "https://example.org/notice/1", "title": "测试通知",
    "date": "2026-01-01", "source": "测试学校", "section": "教务",
}
CHANNELS = {"email": {"enabled": True}, "dingtalk": {"enabled": True}}


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "history.json"
        self.file_patch = patch.object(history, "HISTORY_FILE", str(self.path))
        self.file_patch.start()
        self.addCleanup(self.file_patch.stop)
        self.email = Mock()
        self.dingtalk = Mock()
        for name, sender in (("EmailSender", self.email), ("DingTalkSender", self.dingtalk)):
            factory = patch("notifier.dispatcher." + name, return_value=sender)
            factory.start()
            self.addCleanup(factory.stop)
        self.email.send.return_value = True
        self.dingtalk.send.return_value = True

    def test_filter_does_not_mark_unsent_notices_as_delivered(self):
        self.assertEqual(history.filter_new_notices([NOTICE, NOTICE]), [NOTICE])
        self.assertFalse(self.path.exists())
        self.assertEqual(history.filter_new_notices([NOTICE]), [NOTICE])

    def test_failed_channel_retries_even_when_notice_is_no_longer_scraped(self):
        self.dingtalk.send.return_value = False
        self.assertEqual(dispatch_notices([NOTICE, NOTICE], CHANNELS),
                         {"email": True, "dingtalk": False})
        self.email.send.assert_called_once_with([NOTICE])
        self.assertEqual(history.pending_notices("dingtalk"), [NOTICE])
        self.dingtalk.send.return_value = True
        self.assertEqual(dispatch_notices([], CHANNELS), {"dingtalk": True})
        self.assertEqual(self.email.send.call_count, 1)
        self.assertEqual(self.dingtalk.send.call_count, 2)
        self.assertEqual(dispatch_notices([NOTICE], CHANNELS), {})

    def test_sender_exception_does_not_block_other_channel(self):
        self.email.send.side_effect = RuntimeError("simulated connection failure")
        self.assertEqual(dispatch_notices([NOTICE], CHANNELS),
                         {"email": False, "dingtalk": True})
        self.assertEqual(history.pending_notices("email"), [NOTICE])
        self.assertEqual(history.pending_notices("dingtalk"), [])

    def test_disabled_channel_keeps_pending_notice_until_reenabled(self):
        self.dingtalk.send.return_value = False
        dispatch_notices([NOTICE], CHANNELS)
        self.assertEqual(dispatch_notices([], {"email": {"enabled": True}}), {})
        self.assertEqual(self.dingtalk.send.call_count, 1)
        self.dingtalk.send.return_value = True
        dispatch_notices([], CHANNELS)
        self.assertEqual(self.dingtalk.send.call_count, 2)

    def test_no_enabled_channels_does_not_consume_notice(self):
        dispatch_notices([NOTICE], {})
        self.assertFalse(self.path.exists())
        dispatch_notices([NOTICE], CHANNELS)
        self.email.send.assert_called_once_with([NOTICE])

    def test_legacy_history_is_preserved_without_mass_resend(self):
        old = {key: value for key, value in NOTICE.items() if key != "url"}
        history.save_history({NOTICE["url"]: old})
        self.assertEqual(dispatch_notices([NOTICE], CHANNELS), {})
        self.email.send.assert_not_called()
        self.dingtalk.send.assert_not_called()
        self.assertEqual(history.load_history()[NOTICE["url"]], old)

    def test_failed_atomic_save_preserves_existing_history(self):
        history.save_history({"old": {"title": "已保存"}})
        with patch.object(history.os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                history.save_history({"new": {}})
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")),
                         {"old": {"title": "已保存"}})
        self.assertEqual(list(self.path.parent.glob(".history-*.tmp")), [])

    def test_pending_work_runs_from_main_when_scrape_returns_nothing(self):
        # 只替换外部边界，走真实 main → dispatcher → history，不打开浏览器或发消息。
        with patch("logging.FileHandler", return_value=logging.NullHandler()):
            import main
        history.queue_notices([NOTICE], CHANNELS)
        with patch.object(main, "load_config", return_value={"targets": [], "channels": CHANNELS}), \
                patch.object(main, "sync_playwright"), patch.object(main, "EmailSender") as email:
            main.main()
        self.email.send.assert_called_once_with([NOTICE])
        self.dingtalk.send.assert_called_once_with([NOTICE])
        email.assert_not_called()


class DingTalkResponseTests(unittest.TestCase):
    def test_only_http_and_business_success_counts_as_delivered(self):
        for error, payload, expected in (
            (None, {"errcode": 0}, True),
            (None, {"errcode": 310000, "errmsg": "invalid signature"}, False),
            (None, {}, False),
            (RuntimeError("HTTP 500"), {"errcode": 0}, False),
        ):
            with self.subTest(payload=payload, error=error):
                response = Mock()
                response.raise_for_status.side_effect = error
                response.json.return_value = payload
                sender = DingTalkSender({"enabled": True, "webhook": "https://example.invalid"})
                with patch("notifier.dingtalk.requests.post", return_value=response):
                    self.assertEqual(sender.send([NOTICE]), expected)


class EmailResponseTests(unittest.TestCase):
    def test_failure_or_partial_refusal_does_not_count_as_delivery(self):
        config = {
            "enabled": True, "smtp_server": "example.invalid", "smtp_port": 465,
            "sender_email": "sender@example.invalid", "sender_password": "test-only",
            "recipients": ["recipient@example.invalid"],
        }
        for refused, error, expected in (
            ({}, None, True),
            ({"recipient@example.invalid": (550, b"refused")}, None, False),
            ({}, OSError("connection failed"), False),
        ):
            with self.subTest(refused=refused, error=error):
                smtp = Mock()
                smtp.send_message.return_value = refused
                smtp.send_message.side_effect = error
                with patch("notifier.email_sender.smtplib.SMTP_SSL", return_value=smtp):
                    self.assertEqual(EmailSender(config).send([NOTICE]), expected)


if __name__ == "__main__":
    unittest.main()
