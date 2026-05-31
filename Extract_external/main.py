# PyMuPDF
import requests
from typing import Dict, Any, Optional, List
import pandas as pd
from bs4 import BeautifulSoup
import re

STATE_ABBREVIATIONS = {
    "U.S. Virgin Islands": "VI",
    "Alabama": "AL",
    "Alaska": "AK",
    "Arizona": "AZ",
    "Arkansas": "AR",
    "California": "CA",
    "Colorado": "CO",
    "Connecticut": "CT",
    "Delaware": "DE",
    "Florida": "FL",
    "Georgia": "GA",
    "Hawaii": "HI",
    "Idaho": "ID",
    "Illinois": "IL",
    "Indiana": "IN",
    "Iowa": "IA",
    "Kansas": "KS",
    "Kentucky": "KY",
    "Louisiana": "LA",
    "Maine": "ME",
    "Maryland": "MD",
    "Massachusetts": "MA",
    "Michigan": "MI",
    "Minnesota": "MN",
    "Mississippi": "MS",
    "Missouri": "MO",
    "Montana": "MT",
    "Nebraska": "NE",
    "Nevada": "NV",
    "New Hampshire": "NH",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New York": "NY",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "Ohio": "OH",
    "Oklahoma": "OK",
    "Oregon": "OR",
    "Pennsylvania": "PA",
    "Rhode Island": "RI",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "Tennessee": "TN",
    "Texas": "TX",
    "Utah": "UT",
    "Vermont": "VT",
    "Virginia": "VA",
    "Washington": "WA",
    "West Virginia": "WV",
    "Wisconsin": "WI",
    "Wyoming": "WY",
}


class ExtractWikiContent:
        
    def __init__(self):
        self.wiki_url = "https://en.wikipedia.org/wiki/List_of_United_States_House_of_Representatives_committees"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    
    def _soup(self, text: str, parser_type: Optional[str] = "html.parser"):
        return BeautifulSoup(text, parser_type)

    def fetch_content(self, url: str, headers: dict) -> str:
        response = requests.get(url, headers=headers)
        return response

    def fetch_all_committees(self)->List[Any]:
        response = self.fetch_content(self.wiki_url, self.headers)
        if not response:
            return None
        soup = self._soup(response.text)
        wiki_table = soup.find("table", {"class": "wikitable"})
        extracted_data = []
        for row in wiki_table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue
            row_data = [None] * 3
            pos = 0
            for idx in range(0, len(cells)):
                cell = cells[idx]
                if not cell:
                    continue
                
                link = cell.find("a")
                if link:
                    cell_info = {
                        "text": cell.text.strip(),
                        "href": f"https://en.wikipedia.org{link.get('href', '')}",
                        "title": link.get("title", ""),
                    }
                    if pos < 3:
                        row_data[pos] = cell_info
                    pos += 1
                
            extracted_data.append(row_data)
        return extracted_data

    def fetch_all_members(self)->List[Any]:
        committees = self.fetch_all_committees()
        if not committees:
            return None
        
        for i in range(0, len(committees)):
            row = committees[i]
            if not row[0]:
                continue
            committee = dict(row[0])
            response = self.fetch_content(committee.get("href"), self.headers)
            soup = self._soup(response.text)
            wiki_table = soup.find("table", {"class": "wikitable"})            
            for r in wiki_table.find_all("tr")[1:]:
                cells = r.find_all(['td', 'th'])
                if not cells:
                    continue
                ex_data = {'Majority': [], "Minority": []}
                for idx in range(0, len(cells)):
                    cell = cells[idx]
                    if not cell:
                        continue
                    for li in cell.find_all("li"):
                        text = li.get_text(" ", strip=True)
                        parts = [p.strip() for p in text.split(",")]
                        if len(parts) == 1:
                            continue
                        name = parts[0]
                        ## KeyError: 'California (until January 6'
                        parts_state = parts[1].split(",")
                        state = parts_state[0]
                        map_type = 'Majority' if idx == 0 else 'Minority'
                        ex_data[map_type].append((name, state))
                        
            committees[i].append(ex_data)
        return committees

    def get_abbriv(self, state: str) ->str:
        return STATE_ABBREVIATIONS[state]
