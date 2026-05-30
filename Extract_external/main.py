import io
import json
import fitz  # PyMuPDF
import requests
from typing import Dict, Any, Optional
import pandas as pd
from bs4 import BeautifulSoup




def main():
    wiki_url = "https://en.wikipedia.org/wiki/List_of_United_States_House_of_Representatives_committees"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    # 1. Fetch the raw page content
    response = requests.get(wiki_url, headers=headers)

    # 1. Parse the page with BeautifulSoup
    soup = BeautifulSoup(response.text, "html.parser")

    # 2. Find the target table (using Wikipedia's standard class name)
    wiki_table = soup.find("table", {"class": "wikitable"})

    extracted_data = []
    # 3. Loop through each row (skip the header row)
    for row in wiki_table.find_all("tr")[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        row_data = []
        for idx in range(0, len(cells)):
            cell = cells[idx]
            if not cell:
                continue

            colspan = int(cell.get("colspan", 1))
            if colspan == 2:
                link = cell.find("a")
                if link:
                    cell_info = {
                        "text": cell.text.strip(),
                        "href": f"https://wikipedia.org{link.get('href', '')}",
                        "title": link.get("title", ""),
                    }
                    row_data.append(cell_info)
            elif idx == 0 and colspan == 6:
                link = cell.find("a")
                if link:
                    cell_info = {
                        "sub_committee": cell.text.strip(),
                        "sub_committee_href": f"https://wikipedia.org{link.get('href', '')}",
                        "sub_committee_title": link.get("title", ""),
                    }
                    row_data.append(cell_info)
            else:
                if idx == len(cells) and colspan == 6:
                    break 
                link = cell.find("a")
                if not link:
                    continue
                cell_info = {
                    "member": cell.text.strip(),
                    "memebr_href": f"https://wikipedia.org{link.get('href', '')}",
                    "title": link.get("title", ""),
                }
                row_data.append(cell_info)
             
        extracted_data.append(row_data)

    # 4. Convert your beautifully unpacked data into a DataFrame
    df = pd.DataFrame(extracted_data)
    print(df)




if __name__ == "__main__":
    main()