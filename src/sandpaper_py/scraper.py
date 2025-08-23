from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time

def load_page(url: str, scroll_pause: float = 1) -> str:
    with sync_playwright() as p:
        browsers = [
            ("chromium", p.chromium),
            ("firefox", p.firefox),
            ("webkit", p.webkit)
        ]

        for name, browser_type in browsers:
            try:
                browser = browser_type.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=60000)
                page.wait_for_load_state("networkidle")
                
                # Get initial height

                while True:
                    previous_height = page.evaluate("() => document.body.scrollHeight")
                    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
                    time.sleep(scroll_pause)
                    new_height = page.evaluate("() => document.body.scrollHeight")
                    if new_height == previous_height:
                        break
                    previous_height = new_height

                content = page.content()
                browser.close()
                return content

            except Exception as e:
                try:
                    browser.close()
                except:
                    pass

        raise RuntimeError("All browser engines failed to load the page.")
