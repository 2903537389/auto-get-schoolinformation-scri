"""
校园通知爬虫 + 推送系统
适配成都理工大学（CDUT）教务处 + 机电工程学院
使用持久化 Chrome 用户目录绕过 WAF
"""
import yaml
import os
import sys
import logging
import traceback
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import re
from datetime import datetime, timedelta
from notifier import EmailSender
from notifier.dispatcher import dispatch_notices

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "cdut-chrome-profile")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "crawler.log")

# 同时输出到文件和控制台
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def load_config():
    """加载配置文件，环境变量可覆盖敏感信息"""
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 环境变量覆盖敏感配置（优先级高于 config.yaml）
    channels = config.get("channels", {})
    email_cfg = channels.get("email", {})
    if os.environ.get("EMAIL_SENDER"):
        email_cfg["sender_email"] = os.environ["EMAIL_SENDER"]
    if os.environ.get("EMAIL_PASSWORD"):
        email_cfg["sender_password"] = os.environ["EMAIL_PASSWORD"]
    if os.environ.get("EMAIL_RECIPIENTS"):
        email_cfg["recipients"] = [r.strip() for r in os.environ["EMAIL_RECIPIENTS"].split(",")]

    dt_cfg = channels.get("dingtalk", {})
    if os.environ.get("DINGTALK_WEBHOOK"):
        dt_cfg["webhook"] = os.environ["DINGTALK_WEBHOOK"]
    if os.environ.get("DINGTALK_SECRET"):
        dt_cfg["secret"] = os.environ["DINGTALK_SECRET"]

    fs_cfg = channels.get("feishu", {})
    if os.environ.get("FEISHU_WEBHOOK"):
        fs_cfg["webhook"] = os.environ["FEISHU_WEBHOOK"]

    return config


def scrape_site(context, target):
    """爬取单个网站的所有通知列表页"""
    name = target["name"]
    base_url = target["base_url"]
    homepage = target.get("url", "")  # 首页地址，用于预热
    link_patterns = target.get("link_patterns", [])
    all_notices = []

    # 先访问首页，建立合法会话，绕过 CAS/WAF 首请求检测
    if homepage:
        try:
            logger.info(f"  预热: {homepage}")
            home_page = context.new_page()
            home_page.goto(homepage, wait_until="load", timeout=30000)
            home_page.wait_for_timeout(3000)
            html_len = len(home_page.content())
            home_page.close()
            logger.info(f"  预热完成，首页: {html_len} 字节")
        except Exception as e:
            logger.warning(f"  预热失败（继续爬取）: {e}")

    for lp in target["list_pages"]:
        page_url = lp["url"]
        section = lp.get("section", "")
        try:
            logger.info(f"  爬取: {page_url}")
            page = context.new_page()
            page.goto(page_url, wait_until="load", timeout=30000)
            page.wait_for_timeout(3000)

            html = page.content()
            page.close()

            # WAF / CAS 拦截检测
            if len(html) < 5000:
                logger.warning(f"  [WARN] {page_url} 可能被拦截，响应: {len(html)}字节，内容: {html[:500]}")

            soup = BeautifulSoup(html, "html.parser")

            for a in soup.find_all("a", href=True):
                href = a.get("href", "")
                title = a.get_text(strip=True)

                # 检查是否是通知链接
                if not any(p in href for p in link_patterns):
                    continue
                if not title or len(title) < 4:
                    continue

                # 补全URL
                if href.startswith("../"):
                    full_url = "/".join(base_url.rstrip("/").split("/")[:-1]) + href[2:]
                elif href.startswith("/"):
                    full_url = base_url.rstrip("/") + href
                elif not href.startswith("http"):
                    full_url = base_url.rstrip("/") + "/" + href
                else:
                    full_url = href

                # 提取日期（从父元素 li 中的 span）
                date_str = ""
                parent = a.parent
                if parent:
                    spans = parent.find_all("span")
                    for s in spans:
                        t = s.get_text(strip=True)
                        if re.match(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}", t):
                            date_str = t
                            break

                if not date_str:
                    date_str = "未知"

                all_notices.append({
                    "title": title,
                    "url": full_url,
                    "date": date_str,
                    "source": name,
                    "section": section,
                })

        except Exception as e:
            logger.error(f"  [ERROR] {page_url}: {e}")

    return all_notices


def main():
    logger.info("=" * 50)
    logger.info(f"  校园通知爬虫 {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    logger.info("=" * 50)

    config = load_config()
    lookback = config.get("schedule", {}).get("lookback_days", 1)
    cutoff = datetime.now() - timedelta(days=lookback)

    # 使用持久化 Chrome 用户目录（保持 WAF Cookie）
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            channel="chrome",
            headless=False,  # 需要可见窗口过WAF，任务完成后自动关闭浏览器
            viewport={"width": 1920, "height": 1080},
            args=["--disable-blink-features=AutomationControlled"],
        )

        all_notices = []
        for target in config["targets"]:
            notices = scrape_site(context, target)
            recent = []
            for n in notices:
                if n["date"] != "未知":
                    try:
                        nd = datetime.strptime(n["date"].replace("/", "-"), "%Y-%m-%d")
                        if nd >= cutoff:
                            recent.append(n)
                    except ValueError:
                        pass
                else:
                    recent.append(n)
            logger.info(f"[{target['name']}] {len(notices)}条, 近{lookback}天{len(recent)}条")
            all_notices.extend(recent)

        context.close()

    channels = config.get("channels", {})
    # 本次没有抓到新通知时，也要处理之前未成功送达的通知。
    results = dispatch_notices(all_notices, channels)
    if not results:
        logger.info("无待推送通知。")
        email_cfg = channels.get("email", {})
        if email_cfg.get("enabled"):
            EmailSender(email_cfg).send_no_new()
    elif not all(results.values()):
        logger.warning("有渠道推送失败，待发送记录已保留。")

    logger.info("完成！")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"未捕获异常: {e}")
        logger.error(traceback.format_exc())
