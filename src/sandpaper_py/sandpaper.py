from scraper import load_page
from extractor import extract_data
from exporter import export_groups
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

def update_url(url, page):
    new_url = url.replace("{page}", str(page))
    return new_url
def scraper(mode,
        filename,
        base_url,
        headers,
        encoding,
        filter_threshold,
        intial_page,
        final_page,
        url_list):
    
    all_data = {}
    if mode == "Single Web Page":
        page = load_page(base_url)
        all_data = extract_data(page)
    else:
        for i in range(intial_page, final_page + 1):
            current_url = update_url(base_url, i)
            print(f"Scraping page {i}: {current_url}")
            page = load_page(current_url)
            current_data = extract_data(page)
            for key in list(current_data.keys()):
                for value in current_data[key]:
                    if key not in all_data:
                        all_data[key] = [value]
                    else:
                        all_data[key].append(value)
    export_groups(all_data, encoding, filename)
    return True

if __name__ == "__main__":
    scraper()
