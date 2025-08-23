from bs4 import BeautifulSoup

def extract_data(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    body = soup.find("body")
    data = {}

    # Traverse all direct and nested children of <body>
    for tag in body.find_all(recursive=True):
        # Skip non-tags (like NavigableStrings or comments)
        if not hasattr(tag, 'name'):
            continue
        if ((len(tag.contents) != 1) or 
            tag.name == 'script' or 
            tag.name == 'style' or 
            tag.name == 'header' or
            tag.name == 'footer'):
            continue
        tag_name = tag.name
        class_name = "-".join(tag.get("class", [])) or "no-class"
        key = f"{tag_name}-{class_name}"

        # Extract visible text inside the tag (strip whitespace)
        text = tag.get_text(strip=True)

        if text:
            # Append or create the entry
            if key not in data:
                data[key] = [text]
            else:
                data[key].append(text)
    for key in list(data.keys()):
        uniqueData = set(data[key])
        if len(data[key]) <= 10:
            del data[key]  # Remove keys with only one entry
        elif len(uniqueData) == 1:
            del data[key]  # Remove keys with only one unique entry
    return data

