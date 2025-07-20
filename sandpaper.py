from scraper import load_page
from extractor import extract_data
from exporter import export_groups
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

def update_url(url, page):
    parts = list(urlparse(url))
    query = parse_qs(parts[4])
    query["page"] = [str(page)]
    parts[4] = urlencode(query, doseq=True)
    return urlunparse(parts)

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

    # for i in range(intial_page, final_page + 1):
    #     page_url = update_url(url, i) if page_count > 1 else url
    #     html = load_page(page_url)
    #     groups = extract_groups(html, allowed_keys)
    #     if allowed_keys is None:
    #         allowed_keys = set(groups.keys())
    #     for key in allowed_keys:
    #         all_data.setdefault(key, []).extend(groups.get(key, []))

    export_groups(all_data, encoding, filename)
    print("[bold green]✅ Done! Data saved to {filename}.csv[/bold green]")

if __name__ == "__main__":
    scraper()
