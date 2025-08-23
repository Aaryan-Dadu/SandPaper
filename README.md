# SandPaper-py

**SandPaper** - SandPaper is a command-line tool for web scraping that extracts structured data from web pages and exports it to CSV. It provides an interactive CLI with options for single-page and multi-page scraping, including pagination support through path variables, query parameters, or custom URL lists. The tool uses Playwright for browser automation with features like automatic scrolling, custom headers, and encoding options, making it useful for collecting data from dynamic websites and turning it into organized datasets.

## Features

- **Interactive CLI Interface**: Interactive terminal interface
- **Single & Multi-Page Scraping**: Extract data from individual page or multiple pages with pagination support
- **Flexible URL Formats**: Support for path variables, query parameters, and custom URL lists
- **Browser Automation**: Uses Playwright for JavaScript-rendered content scraping
- **Automatic Scrolling**: Handles infinite scroll and dynamic content loading
- **Custom Headers**: Configure request headers for different websites
- **Encoding Support**: Handle various character encodings (UTF-8, ISO-8859-1, etc.)
- **Data Filtering**: Filter data based on minimum element thresholds
- **CSV Export**: Clean, organized data export with customizable filenames

## Installation

### From PyPI (Recommended)

```bash
pip install sandpaper-py
```

### From Source

```bash
git clone https://github.com/Aaryan-Dadu/SandPaper
cd sandpaper
pip install -e .
```

## Quick Start

### Command Line Usage

After installation, launch the interactive CLI:

```bash
sandpaper
```

This will start an interactive session that guides you through the scraping process.

### Programmatic Usage

```python
from sandpaper_py import scraper

# Single page scraping
result = scraper(
    mode="Single Web Page",
    filename="output.csv",
    base_url="https://example.com",
    headers="Default",
    encoding="utf-8",
    filter_threshold=10,
    intial_page=1,
    final_page=1,
    url_list=[]
)
```

## Usage Examples

### 1. Single Page Scraping

```bash
sandpaper
# Choose: Single Web Page
# Enter URL: https://quotes.toscrape.com
# Output: quotes.csv
```

### 2. Multi-Page Scraping with Path Variables

```bash
sandpaper
# Choose: Multiple Web Pages
# URL Format: Path Variable
# Base URL: https://quotes.toscrape.com/page/{page}/
# Pages: 1 to 5
# Output: quotes_pages.csv
```

### 3. Multi-Page Scraping with Query Parameters

```bash
sandpaper
# Choose: Multiple Web Pages
# URL Format: Query Param
# Base URL: https://example.com/search?q=books&page={page}
# Pages: 1 to 10
# Output: search_results.csv
```

### 4. Custom URL List

```bash
sandpaper
# Choose: Multiple Web Pages
# URL Format: Custom List
# URLs: https://site1.com,https://site2.com,https://site3.com
# Output: custom_sites.csv
```

## Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| **Mode** | Single page or multiple page scraping | - |
| **URL Format** | Path variable, query param, or custom list | - |
| **Headers** | Default or custom JSON headers | Default |
| **Encoding** | Character encoding for the page | utf-8 |
| **Filter Threshold** | Minimum elements per column to keep | 10 |
| **Output Filename** | Custom CSV filename | `{domain}.csv` |

## URL Format Examples

### Path Variable
```
https://example.com/products/{page}
https://blog.example.com/posts/{page}
```

### Query Parameter
```
https://example.com/search?q=books&page={page}
https://shop.example.com/category/electronics?page={page}&sort=price
```

### Custom URL List
```
https://example.com/page1,https://example.com/page2,https://example.com/page3
```

## Project Structure

```
SandPaper/
├── src/
│   └── sandpaper-py/
│       ├── __init__.py
│       ├── menu.py          # Interactive CLI interface
│       ├── sandpaper.py     # Main scraping logic
│       ├── scraper.py       # Web scraping utilities
│       ├── extractor.py     # Data extraction
│       └── exporter.py      # CSV export functionality
├── tests/                   # Tests
├── pyproject.toml           # Package configuration
├── README.md                # Readme
└── LICENSE                  # License
```

## Dependencies

- **playwright** - Browser automation and JavaScript rendering
- **rich** - Beautiful terminal output and formatting
- **questionary** - Interactive CLI prompts
- **pandas** - Data manipulation and CSV export
- **tldextract** - URL domain extraction
- **requests** - HTTP requests
- **beautifulsoup4** - HTML parsing

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-feature`)
3. Commit your changes (`git commit -m 'Add new feature'`)
4. Push to the branch (`git push origin feature/new-feature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Version History

### v0.0.1 (Current)
- Initial release
- Single and multi-page scraping
- Interactive CLI interface
- CSV export functionality
- Browser automation with Playwright

---
