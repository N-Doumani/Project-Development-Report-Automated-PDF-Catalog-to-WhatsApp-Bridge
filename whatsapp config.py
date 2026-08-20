from playwright.sync_api import sync_playwright

def setup_login():
    with sync_playwright() as p:
        browser = p.chromium.launch_persistent_context(
            user_data_dir="whatsapp_session",
            headless=False  # Visible window only for scanning QR code
        )
        page = browser.new_page()
        page.goto("https://web.whatsapp.com")
        print("📲 Scan the QR code now. Once chats are loaded, press Enter in terminal...")
        input()
        browser.close()

if __name__ == "__main__":
    setup_login()