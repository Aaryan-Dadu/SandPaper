from rich import print
import questionary
from sandpaper import scraper
import tldextract

def get_site_name(url: str) -> str:
    extracted = tldextract.extract(url)
    return extracted.domain

def sandpaper():
    print(r"""[bold red]
   _____                 _ _____                      
  / ____|               | |  __ \                     
 | (___   __ _ _ __   __| | |__) |_ _ _ __   ___ _ __ 
  \___ \ / _` | '_ \ / _` |  ___/ _` | '_ \ / _ \ '__|
  ____) | (_| | | | | (_| | |  | (_| | |_) |  __/ |   
 |_____/ \__,_|_| |_|\__,_|_|   \__,_| .__/ \___|_|   
                                     | |              
                                     |_|               
    [/bold red]""")
    print("[bold green]🪵  Welcome to the SandPaper Web Page Data Extractor[/bold green]\n")

    mode = questionary.select(
        "Choose mode:",
        choices=["Single Web Page", "Multiple Web Pages"]
    ).ask()

    if mode == "Multiple Web Pages":
        print("\n[bold cyan]URL formats:[/bold cyan]")
        print("[yellow]1.[/yellow] Path Variable: [italic]https://example.com/products/{page}[/italic]")
        print("[yellow]2.[/yellow] Request Param: [italic]https://example.com/products?page={page}[/italic]")
        print("[yellow]3.[/yellow] Query Param: [italic]https://example.com/search?q=books&page={page}[/italic]")
        print("[yellow]4.[/yellow] Custom List: Provide your own list of URLs\n")
        url_format = questionary.select(
            "Choose URL format:",
            choices=[r"Path Variable",
                     r"Request Param",
                     r"Query Param",
                     r"Custom List"]
        ).ask()

    base_url = questionary.text(
        "Enter the base URL (use {page} for page number if applicable):"
    ).ask()

    headers = questionary.select(
        "Choose request header setup:",
        choices=["Default", "Custom"]
    ).ask()

    if headers == "Custom":
        custom_header = questionary.text("Enter headers as JSON string (e.g., {\"User-Agent\": \"Mozilla\"}):").ask()
        try:
            import json
            headers = json.loads(custom_header)
        except Exception as e:
            print("Invalid header format. Using default.")
            headers = "Default"

    encoding = questionary.select(
        "Choose encoding:",
        choices=["utf-8", "custom"],
        default="utf-8"
    ).ask()

    if encoding == "custom":
        encoding = questionary.text("Enter custom encoding (e.g., utf-8-sig, ISO-8859-1):").ask()
    threshold = questionary.text(
        "Enter filter threshold (minimum number of elements per column to keep):",
        default="10"
    ).ask()

    threshold = int(threshold)

    filename = questionary.text(
        "Enter output filename:",
        default=get_site_name(base_url) + ".csv"
    ).ask()

    custom_list = []

    if mode == "Multiple Web Pages":
        if url_format != "Custom List":
            intial_page = int(questionary.text("Initial Page Number:", default="1").ask())
            final_page = int(questionary.text("Final Page Number:", default="10").ask())
            confirm = questionary.confirm(f"Ready to scrape {intial_page} to {final_page} from {base_url}?").ask()
        else:
            urls = questionary.text("Enter comma-separated list of URLs:").ask()
            custom_list = [u.strip() for u in urls.split(",") if u.strip()]
            confirm = questionary.confirm(f"Ready to scrape {len(custom_list)} custom URLs?").ask()
    else:
        intial_page = 1
        final_page = 1
        confirm = questionary.confirm(f"Ready to scrape {base_url}?").ask()
    if not confirm:
        print("\n[bold red]❌ Aborted by user[/bold red]")
        return
    else:
        print("\n[bold magenta]⏳ Starting the scraping process...[/bold magenta]\n")

    result = scraper(
        mode=mode,
        filename=filename,
        base_url=base_url,
        headers=headers,
        encoding=encoding,
        filter_threshold=threshold,
        intial_page=intial_page,
        final_page=final_page,
        url_list=custom_list
    )
    if result is True:
        print(f"[bold green]✅ Data successfully saved to {filename}[/bold green]")
    else:
        print("[bold red]❌ An error occurred during scraping[/bold red]")

if __name__ == "__main__":
    sandpaper()
