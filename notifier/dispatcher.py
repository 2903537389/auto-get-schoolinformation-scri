import logging

from .email_sender import EmailSender
from .dingtalk import DingTalkSender
from storage import queue_notices, pending_notices, mark_delivered

logger = logging.getLogger(__name__)


def dispatch_notices(notices, channels):
    """按渠道发送新通知和待重试通知，返回各渠道的发送结果。"""
    senders = {
        name: factory(channels[name])
        for name, factory in (("email", EmailSender), ("dingtalk", DingTalkSender))
        if channels.get(name, {}).get("enabled")
    }
    if not senders:
        logger.warning("未启用邮件或钉钉渠道，本次不记录送达状态。")
        return {}

    queue_notices(notices, senders)
    results = {}
    for channel, sender in senders.items():
        pending = pending_notices(channel)
        if not pending:
            continue
        try:
            succeeded = bool(sender.send(pending))
        except Exception:
            logger.exception("%s 推送异常，保留待发送记录", channel)
            succeeded = False
        results[channel] = succeeded
        if succeeded:
            # 每个渠道成功后立即保存，另一个渠道失败不会让这里重复发送。
            mark_delivered(pending, channel)
        else:
            logger.warning("%s 推送失败，%d 条通知将在下次运行重试", channel, len(pending))
    return results
