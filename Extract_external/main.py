# PyMuPDF
import profile

import requests
from typing import Dict, Any, Optional, List
import pandas as pd
from bs4 import BeautifulSoup
import re

STATE_ABBREVIATIONS = {
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
    "Guam": "GU",
    "District of Columbia": "DC",
    "Puerto Rico": "PR",
    "Guam": "GU",
    "American Samoa": "AS",
    "U.S. Virgin Islands": "VI",
    "Northern Mariana Islands": "MP",
}


class ExtractWikiContent:
    """ Class extracts house of rep from wiki page using bs4 """
        
    def __init__(self):
        self.wiki_url = "https://en.wikipedia.org/wiki/List_of_United_States_House_of_Representatives_committees"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    
    def get_headers(self) -> Dict[str, str]:
        return self.headers

    def get_wiki_url(self) -> str:
        return self.wiki_url

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
                        "href": f"https:{link.get('href', '')}",
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
            link = committee.get("href")
            if link is None or link == "":
                continue
            response = self.fetch_content(link, self.headers)
            soup = self._soup(response.text)

            if not self.valid_committee(soup, "119"):
                continue
            
            profile = self.extract_full_committee_profile(soup)
            

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
                        state = re.sub(r'\s*\(.*$', '', parts[1]).strip()
                        state = re.sub(r'\s+', ' ', state)
                        map_type = 'Majority' if idx == 0 else 'Minority'
                        ex_data[map_type].append((name, state))
                        
            committees[i].append(ex_data)
            committees[i].append({"profile": profile})
        return committees




    def valid_committee(self, soup, congress_number="119") -> bool:
        expected = f"{congress_number}th Congress"

        for h2 in soup.find_all("h2"):
            text = h2.get_text(" ", strip=True)
            if expected in text:
                return True

        for h3 in soup.find_all("h3"):
            text = h3.get_text(" ", strip=True)
            if expected in text:
                return True

        return False

    def get_abbriv(self, state: str) ->str:
        return STATE_ABBREVIATIONS[state]
    
    
    def extract_full_committee_profile(self, soup) -> dict:
        return {
            "role":         self._extract_role(soup),
            "jurisdiction": self._extract_jurisdiction_text(soup),
            "rules":        self._extract_rules(soup),
            "subcommittees": self._extract_subcommittees(soup)
        }


    def _extract_subcommittees(self, soup) -> list[dict]:
        """
        Extracts current subcommittees and their chair/ranking member
        from the subcommittees section table.
        """
        subcommittees = []

        # Find the subcommittees heading
        heading = soup.find("h2", {"id": "Subcommittees"}) or \
                soup.find("span", {"id": "Subcommittees"})

        if not heading:
            return subcommittees

        start = (
            heading.parent
            if heading.parent.name == "div" and "mw-heading" in heading.parent.get("class", [])
            else heading
        )

        for sibling in start.find_next_siblings():
            if sibling.name in ["h2", "h3"]:
                break
            if sibling.name == "div" and "mw-heading" in sibling.get("class", []):
                break

            table = sibling.find("table") if sibling.name != "table" else sibling
            if not table:
                continue

            rows = table.find_all("tr")
            if not rows:
                continue

            # Extract headers to map column positions
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                entry = {}
                for idx, cell in enumerate(cells):
                    if idx < len(headers):
                        entry[headers[idx]] = cell.get_text(" ", strip=True)

                if entry:
                    subcommittees.append(entry)

            # Only grab the first table in this section (current congress)
            break

        return subcommittees
    
    def _extract_role(self, soup) -> str:
        """
        Extracts governance-relevant sentences from body paragraphs.
        Two strategies:
        1. Dedicated section heading (e.g. 'Role', 'Overview')
        2. Fallback — scan ALL lead paragraphs for governance sentences
        """
        content_div = soup.find("div", {"class": "mw-parser-output"})
        if not content_div:
            return ""

        # Patterns that signal a sentence describes what the committee DOES
        ROLE_KEYWORDS = re.compile(
            r'\b(jurisdiction|oversight|authority|responsible|responsibility|'
            r'policy|regulate|govern|review|approve|recommend|supervise|'
            r'authorize|drafting|preparation|enforce|investigate|subpoena|'
            r'hearings|legislation|appropriat|budget|spending|revenue|'
            r'monitor|consider|amend|table|markup)\b',
            re.I
        )

        # Patterns that signal a purely historical/biographical sentence to skip
        SKIP_PATTERNS = re.compile(
            r'\b(was (created|formed|established|made)|'
            r'in \d{4}|originally consisted|went on to serve|'
            r'high-profile|gone on to|born|died|re-elected)\b',
            re.I
        )

        role_sentences = []

        for tag in content_div.children:
            if not hasattr(tag, "name"):
                continue
            # Stop at the first section heading
            if tag.name in ["h2", "h3"]:
                break
            if tag.name == "div" and "mw-heading" in tag.get("class", []):
                break
            if tag.name != "p":
                continue

            text = tag.get_text(" ", strip=True)
            if not text:
                continue

            for sentence in re.split(r'(?<=[.!?])\s+', text):
                sentence = sentence.strip()
                if not sentence or len(sentence) < 20:
                    continue
                if SKIP_PATTERNS.search(sentence):
                    continue
                if ROLE_KEYWORDS.search(sentence):
                    role_sentences.append(sentence)

        return " ".join(role_sentences)

    def _extract_jurisdiction_text(self, soup) -> str:
        """
        Two strategies:
        1. Dedicated Jurisdiction section heading — full bullet list + prose
        2. Fallback — infobox jurisdiction row when no section exists
            (e.g. House Budget Committee only has infobox jurisdiction)
        """
        parts = []

        # ── Strategy 1: dedicated section ────────────────────────────────────
        heading_tag = (
            soup.find("h2", {"id": "Jurisdiction"}) or
            soup.find("span", {"id": "Jurisdiction"})
        )

        if heading_tag:
            start_node = (
                heading_tag.parent
                if heading_tag.parent.name == "div"
                and "mw-heading" in heading_tag.parent.get("class", [])
                else heading_tag
            )
            for sibling in start_node.find_next_siblings():
                if sibling.name in ["h2", "h3"]:
                    break
                if sibling.name == "div" and "mw-heading" in sibling.get("class", []):
                    break
                if sibling.name == "p":
                    text = sibling.get_text(" ", strip=True)
                    if text:
                        parts.append(text)
                for li in sibling.find_all("li"):
                    text = li.get_text(" ", strip=True)
                    if text:
                        parts.append(text)

            if parts:
                return " ".join(parts)

        # ── Strategy 2: fallback to infobox jurisdiction row ─────────────────
        infobox = soup.find("table", {"class": "infobox"})
        if infobox:
            for row in infobox.find_all("tr"):
                header = row.find("th")
                if header and "Jurisdiction" in header.get_text():
                    td = row.find("td")
                    if td:
                        text = td.get_text(" ", strip=True)
                        if text:
                            parts.append(text)

        return " ".join(parts)

    def _extract_rules(self, soup) -> str:
        """
        Two strategies:
        1. Dedicated Rules section heading
        2. Fallback — detect procedural sentences embedded in body paragraphs
            (e.g. Budget Committee embeds quorum/procedure rules in body)
        """
        parts = []

        RULES_KEYWORDS = re.compile(
            r'\b(quorum|markup|point of order|majority vote|seniority|'
            r'term.limit|rotate off|waived|motion|amendment|gavel|'
            r'question witnesses|called to order|permitted to conduct|'
            r'may only consider|rank.and.file|clause|rule [IVXLC]+)\b',
            re.I
        )

        # ── Strategy 1: dedicated section ────────────────────────────────────
        heading_tag = None
        for heading_id in ["Rules", "Committee_rules", "Committee_Rules"]:
            heading_tag = (
                soup.find("h2", {"id": heading_id}) or
                soup.find("h3", {"id": heading_id}) or
                soup.find("span", {"id": heading_id})
            )
            if heading_tag:
                break

        if heading_tag:
            start_node = (
                heading_tag.parent
                if heading_tag.parent.name == "div"
                and "mw-heading" in heading_tag.parent.get("class", [])
                else heading_tag
            )
            for sibling in start_node.find_next_siblings():
                if sibling.name in ["h2", "h3"]:
                    break
                if sibling.name == "div" and "mw-heading" in sibling.get("class", []):
                    break
                if sibling.name == "p":
                    text = sibling.get_text(" ", strip=True)
                    if text:
                        parts.append(text)
                for li in sibling.find_all("li"):
                    text = li.get_text(" ", strip=True)
                    if text:
                        parts.append(text)

            if parts:
                return " ".join(parts)

        # ── Strategy 2: scan body paragraphs for procedural sentences ─────────
        content_div = soup.find("div", {"class": "mw-parser-output"})
        if content_div:
            for tag in content_div.find_all("p"):
                text = tag.get_text(" ", strip=True)
                if not text:
                    continue
                for sentence in re.split(r'(?<=[.!?])\s+', text):
                    sentence = sentence.strip()
                    if RULES_KEYWORDS.search(sentence):
                        parts.append(sentence)

        return " ".join(parts)

if __name__ == "__main__":
    extractor = ExtractWikiContent()
    committees = extractor.fetch_all_members()
    cnt = 0
    cnt_members = 0
    print(f"Committee: {committees[5]}")



