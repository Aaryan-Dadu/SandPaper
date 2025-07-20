from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

def load_page(url: str) -> str:
    with sync_playwright() as p:
        browsers = [
            ("chromium", p.chromium),
            ("firefox", p.firefox),
            ("webkit", p.webkit)
        ]

        for name, browser_type in browsers:
            try:
                # print(f"Trying with {name}...")
                browser = browser_type.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=60000)
                page.wait_for_load_state("networkidle")
                content = page.content()
                browser.close()
                print(f"Success with {name}!")
                return content
            except Exception as e:
                # print(f"{name} failed: {e}")
                try:
                    browser.close()
                except:
                    pass

        raise RuntimeError("All browser engines failed to load the page.")
