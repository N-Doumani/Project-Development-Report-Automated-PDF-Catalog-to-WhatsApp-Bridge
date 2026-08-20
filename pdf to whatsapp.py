import os
import glob
import time
import subprocess
import json
import pymupdf
from google import genai
from playwright.sync_api import sync_playwright

# ==========================================
# Configuration
# ==========================================
# Put Your API Key here
client = genai.Client(api_key="Put your API Key here")
MODEL_ID = 'gemini-3.6-flash'

# Put your PDF path
PDF_DIRECTORY = r"PDF path "
OUTPUT_IMG_DIR = os.path.join(PDF_DIRECTORY, "extracted_catalog_images")

def calculate_selling_price(cost_price: float) -> float:
    if cost_price <= 10.0:
        return cost_price + 1.50
    elif cost_price <= 29.0:
        return cost_price + 3.00
    elif cost_price <= 50.0:
        return cost_price + 4.00
    else:
        return cost_price + 5.00

def extract_product_ai(blocks, img_bbox):
    if not img_bbox:
        return 0.0, "Unknown"
        
    img_y_mid = (img_bbox[1] + img_bbox[3]) / 2
    row_texts = []
    
    for b in blocks:
        b_y_mid = (b[1] + b[3]) / 2
        if abs(b_y_mid - img_y_mid) < 40:
            text = b[4].strip()
            if text:
                row_texts.append(text)
                
    if not row_texts:
        return 0.0, "Unknown"
        
    messy_string = " | ".join(row_texts)
    
    prompt = f"""
    You are a smart assistant for a computer store. Extract the real product name and the price in USD from this messy text extracted from a PDF table.
    - Write the brand and model accurately and concisely.
    - Ignore long technical specifications, words like 'In stock', phone numbers, and dates.
    - Return the result EXCLUSIVELY in JSON format like this: {{"name": "...", "price": 00.00}}
    - If the text is just an ad, logo, or does not contain a real product, return: {{"name": "Unknown", "price": 0.0}}
    
    Text: {messy_string}
    """
    
    try:
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=prompt
        )
        
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(clean_json)
        
        price = float(data.get("price", 0.0))
        name = str(data.get("name", "Unknown"))
        return price, name
        
    except Exception as e:
        print(f"  [!] AI Parsing Error: {e}")
        return 0.0, "Unknown"

def copy_image_to_clipboard(image_path):
    escaped_path = image_path.replace("'", "''")
    ps_command = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        f"[System.Windows.Forms.Clipboard]::SetImage([System.Drawing.Image]::FromFile('{escaped_path}'));"
    )
    subprocess.run(["powershell", "-command", ps_command], capture_output=True)

def send_image_to_group(page, image_path, product_name, price_text):
    abs_path = os.path.abspath(image_path)
    
    print("  [i] Copying image to clipboard...")
    copy_image_to_clipboard(abs_path)
    time.sleep(1.5) 
    
    try:
        chat_box = page.locator('footer div[contenteditable="true"], footer div[role="textbox"]').last
        chat_box.click(timeout=5000)
        time.sleep(0.5)
        
        page.keyboard.press("Control+v")
        time.sleep(2.5) 
        page.keyboard.press("Enter") 
        time.sleep(2) 
        
        page.keyboard.type(product_name)
        time.sleep(0.5)
        page.keyboard.press("Enter")
        time.sleep(1)
        
        page.keyboard.type(price_text)
        time.sleep(0.5)
        page.keyboard.press("Enter")
        
    except Exception as e:
        print(f"  [!] Paste/Send Error: {e}")
        return

    time.sleep(4)

def process_single_pdf(page, pdf_path):
    doc = pymupdf.open(pdf_path)
    base_name = os.path.splitext(os.path.basename(pdf_path))[0]
    pdf_out_dir = os.path.join(OUTPUT_IMG_DIR, base_name)
    os.makedirs(pdf_out_dir, exist_ok=True)

    print(f"\n[i] Processing: {base_name} ({len(doc)} pages)")
    total_sent = 0

    for page_num in range(len(doc)):
        p = doc[page_num]
        image_list = p.get_images(full=True)
        text_blocks = p.get_text("blocks")

        for img_index, img_info in enumerate(image_list):
            xref = img_info[0]
            width = img_info[2]
            height = img_info[3]
            
            if width < 150 or height < 150:
                continue

            base_image = doc.extract_image(xref)
            if len(base_image["image"]) < 10000:
                continue

            img_rects = p.get_image_rects(xref)
            img_bbox = img_rects[0] if img_rects else None

            first_cost, extracted_name = extract_product_ai(text_blocks, img_bbox)
            
            if extracted_name == "Unknown" or extracted_name == "Unknown Product":
                print(f"  [i] Skipped: Image {img_index+1} (Not a valid product).")
                continue

            img_filename = os.path.join(pdf_out_dir, f"p{page_num+1}_img{img_index+1}.{base_image['ext']}")
            with open(img_filename, "wb") as f:
                f.write(base_image["image"])

            selling_price = calculate_selling_price(first_cost)
            product_name_msg = f"🔥 {extracted_name}"
            price_msg = f"💵 Price: ${selling_price:,.2f}"

            print(f"  [+] Extracted | Name: {extracted_name} | Sell Price: ${selling_price:.2f}")
            try:
                send_image_to_group(page, img_filename, product_name_msg, price_msg)
                total_sent += 1
            except Exception as e:
                print(f"  [!] Error sending {img_filename}: {e}")

    print(f"[+] Completed {base_name}: Sent {total_sent} items.")

def main():
    pdf_files = glob.glob(os.path.join(PDF_DIRECTORY, "*.pdf"))
    if not pdf_files:
        print(f"[!] No PDF files found in {PDF_DIRECTORY}")
        return

    with sync_playwright() as p:
        print("[i] Launching browser session...")
        browser = p.chromium.launch_persistent_context(
            user_data_dir="whatsapp_session",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"]
        )
        page = browser.new_page()

        print("[i] Loading WhatsApp Web...")
        page.goto("https://web.whatsapp.com", wait_until="domcontentloaded", timeout=60000)
        
        print("[i] Waiting for WhatsApp to sync and load chats...")
        page.wait_for_selector('#side', timeout=90000)
        print("[+] WhatsApp Web session active.")

        time.sleep(2)
        search_box = page.locator('#side div[contenteditable="true"], #side p.selectable-text, #side input[type="text"]').first
        search_box.click()
        time.sleep(1)
        
        page.keyboard.type("KOMPEC")
        time.sleep(2)
        page.keyboard.press("Enter")
        time.sleep(3)

        for index, pdf_path in enumerate(pdf_files, start=1):
            print("\n" + "=" * 60)
            print(f"[{index}/{len(pdf_files)}] Current PDF: {os.path.basename(pdf_path)}")
            print("=" * 60)

            process_single_pdf(page, pdf_path)

            if index < len(pdf_files):
                choice = input(f"\n[?] Finished PDF {index}/{len(pdf_files)}. Proceed to next PDF? (y/n): ").strip().lower()
                if choice not in ['y', 'yes']:
                    print("[!] Paused by user.")
                    break

        print("\n[+] All tasks finished! Closing browser in 5 seconds...")
        time.sleep(5)
        browser.close()

if __name__ == "__main__":
    main()