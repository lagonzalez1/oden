"""
Parses the 119th Congress House of Representatives committee structure
from Wikipedia — committees, subcommittees, leadership, rank-and-file
members, and governance content (role/jurisdiction/rules) for each.
"""
import hashlib
import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


STATE_ABBREVIATIONS = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "Guam": "GU", "District of Columbia": "DC",
    "Puerto Rico": "PR", "American Samoa": "AS", "U.S. Virgin Islands": "VI",
    "Northern Mariana Islands": "MP",
}


# ── Data Model ──────────────────────────────────────────────────────────────

@dataclass
class Member:
    name: str
    state: str
    party: Optional[str] = None       # "Majority" | "Minority" (rank-and-file)
    role: Optional[str] = None        # "Chair" | "Ranking Member" | None


@dataclass
class Subcommittee:
    name: str
    url: Optional[str] = None                 # link to subcommittee's own Wikipedia page, if present
    chair: Optional[str] = None
    chair_state_party: Optional[str] = None   # e.g. "R-SD"
    ranking_member: Optional[str] = None
    ranking_member_state_party: Optional[str] = None
    members: List[Member] = field(default_factory=list)


@dataclass
class CommitteeProfile:
    """Governance-dense content — optimized for semantic similarity matching."""
    role: str = ""
    jurisdiction: str = ""
    rules: str = ""


@dataclass
class Committee:
    name: str
    url: str
    chair: Optional[str] = None
    chair_state_party: Optional[str] = None
    ranking_member: Optional[str] = None
    ranking_member_state_party: Optional[str] = None
    congress_number: str = "119"
    profile: CommitteeProfile = field(default_factory=CommitteeProfile)
    members: List[Member] = field(default_factory=list)
    subcommittees: List[Subcommittee] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "url": self.url,
            "chair": self.chair,
            "chair_state_party": self.chair_state_party,
            "ranking_member": self.ranking_member,
            "ranking_member_state_party": self.ranking_member_state_party,
            "congress_number": self.congress_number,
            "profile": {
                "role": self.profile.role,
                "jurisdiction": self.profile.jurisdiction,
                "rules": self.profile.rules,
            },
            "members": [
                {"name": m.name, "state": m.state, "party": m.party, "role": m.role}
                for m in self.members
            ],
            "subcommittees": [
                {
                    "name": sc.name,
                    "url": sc.url,
                    "chair": sc.chair,
                    "chair_state_party": sc.chair_state_party,
                    "ranking_member": sc.ranking_member,
                    "ranking_member_state_party": sc.ranking_member_state_party,
                    "members": [
                        {"name": m.name, "state": m.state, "party": m.party, "role": m.role}
                        for m in sc.members
                    ],
                }
                for sc in self.subcommittees
            ],
        }


# ── Parser ──────────────────────────────────────────────────────────────────

class HouseCommitteeParser:
    """
    Parses the full 119th Congress House committee structure from Wikipedia.

    Usage:
        parser = HouseCommitteeParser()
        committees = parser.parse_all()
        for c in committees:
            print(c.name, len(c.members), len(c.subcommittees))
    """

    LISTING_URL = (
        "https://en.wikipedia.org/wiki/"
        "List_of_United_States_House_of_Representatives_committees"
    )

    def __init__(self, congress_number: str = "119", request_delay: float = 0.5):
        self.congress_number = congress_number
        self.request_delay = request_delay  # polite delay between page fetches
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }

    # ── HTTP / parsing helpers ────────────────────────────────────────────

    def _fetch(self, url: str) -> BeautifulSoup:
        response = requests.get(url, headers=self.headers, timeout=15)
        response.raise_for_status()
        time.sleep(self.request_delay)
        return BeautifulSoup(response.text, "html.parser")

    def _abbrev(self, state: str) -> str:
        return STATE_ABBREVIATIONS.get(state.strip(), state.strip())

    @staticmethod
    def _split_name_party(text: str) -> tuple[str, Optional[str]]:
        """'Glenn Thompson (R-PA)' -> ('Glenn Thompson', 'R-PA')"""
        match = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", text.strip())
        if match:
            return match.group(1).strip(), match.group(2).strip()
        return text.strip(), None

    # ── Step 1: Parse the listing page ─────────────────────────────────────

    def _parse_listing_page(self) -> List[Dict[str, Any]]:
        """
        Parses the main committee listing table.
        Returns raw rows: committee name/link + chair/ranking member +
        any inline subcommittee rows that follow it (until the next
        top-level committee row).
        """
        soup = self._fetch(self.LISTING_URL)
        tables = soup.find_all("table", {"class": "wikitable"})

        raw_committees = []
        current = None

        for table in tables:
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if not cells:
                    continue

                # Top-level committee rows have a <b> or a link with a title
                # attribute matching "United States House Committee on..."
                first_cell = cells[0]
                link = first_cell.find("a")

                is_top_level = (
                    link is not None
                    and link.get("title", "").startswith("United States House Committee")
                )

                if is_top_level:
                    if current:
                        raw_committees.append(current)

                    name = link.get_text(strip=True)
                    href = link.get("href", "")
                    url = f"https:{href}" if href.startswith("/") else href

                    current = {
                        "name": name,
                        "url": url,
                        "subcommittee_rows": [],
                    }
                elif current is not None:
                    # Subcommittee row — belongs to the current committee
                    current["subcommittee_rows"].append(cells)

            if current:
                raw_committees.append(current)
                current = None

        return raw_committees

    # ── Step 2: Parse subcommittee rows from the listing page ──────────────

    def _parse_subcommittee_rows(self, rows: List[Any]) -> List[Subcommittee]:
        """
        Subcommittee rows on the listing page follow two shapes:
          - Bare text rows: "Name; Chair (R-ST); Ranking (D-ST)"
          - Table rows: | Name | Chair (R-ST) | Ranking (D-ST) |
        """
        subcommittees = []

        for cells in rows:
            texts = [c.get_text(" ", strip=True) for c in cells]
            texts = [t for t in texts if t]
            if len(texts) < 3:
                continue

            sub_name = texts[0]
            chair_raw = texts[1]
            ranking_raw = texts[2]

            # Subcommittee name cell often links to its own Wikipedia page
            sub_url = None
            first_cell_link = cells[0].find("a") if cells else None
            if first_cell_link:
                href = first_cell_link.get("href", "")
                if href.startswith("/"):
                    sub_url = f"https:{href}"
                elif href.startswith("http"):
                    sub_url = href

            chair_name, chair_sp = self._split_name_party(chair_raw)
            ranking_name, ranking_sp = self._split_name_party(ranking_raw)

            subcommittees.append(
                Subcommittee(
                    name=sub_name,
                    url=sub_url,
                    chair=chair_name,
                    chair_state_party=chair_sp,
                    ranking_member=ranking_name,
                    ranking_member_state_party=ranking_sp,
                )
            )

        return subcommittees

    # ── Step 3: Committee page — profile + members ──────────────────────────

    def valid_committee(self, soup: BeautifulSoup) -> bool:
        expected = f"{self.congress_number}th Congress"
        for heading in soup.find_all(["h2", "h3"]):
            if expected in heading.get_text(" ", strip=True):
                return True
        return False

    def _extract_profile(self, soup: BeautifulSoup) -> CommitteeProfile:
        return CommitteeProfile(
            role=self._extract_role(soup),
            jurisdiction=self._extract_jurisdiction_text(soup),
            rules=self._extract_rules(soup),
        )

    def _extract_role(self, soup: BeautifulSoup) -> str:
        content_div = soup.find("div", {"class": "mw-parser-output"})
        if not content_div:
            return ""

        role_keywords = re.compile(
            r"\b(jurisdiction|oversight|authority|responsible|responsibility|"
            r"policy|regulate|govern|review|approve|recommend|supervise|"
            r"authorize|drafting|preparation|enforce|investigate|subpoena|"
            r"hearings|legislation|appropriat|budget|spending|revenue|"
            r"monitor|consider|amend|table|markup)\b",
            re.I,
        )
        skip_patterns = re.compile(
            r"\b(was (created|formed|established|made)|in \d{4}|"
            r"originally consisted|went on to serve|high-profile|"
            r"gone on to|born|died|re-elected)\b",
            re.I,
        )

        role_sentences = []
        for tag in content_div.children:
            if not hasattr(tag, "name"):
                continue
            if tag.name in ["h2", "h3"]:
                break
            if tag.name == "div" and "mw-heading" in tag.get("class", []):
                break
            if tag.name != "p":
                continue

            text = tag.get_text(" ", strip=True)
            if not text:
                continue

            for sentence in re.split(r"(?<=[.!?])\s+", text):
                sentence = sentence.strip()
                if not sentence or len(sentence) < 20:
                    continue
                if skip_patterns.search(sentence):
                    continue
                if role_keywords.search(sentence):
                    role_sentences.append(sentence)

        return " ".join(role_sentences)

    def _extract_jurisdiction_text(self, soup: BeautifulSoup) -> str:
        parts: List[str] = []

        heading_tag = (
            soup.find("h2", {"id": "Jurisdiction"})
            or soup.find("span", {"id": "Jurisdiction"})
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

        # Fallback: infobox jurisdiction row
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

    def _extract_rules(self, soup: BeautifulSoup) -> str:
        parts: List[str] = []

        rules_keywords = re.compile(
            r"\b(quorum|markup|point of order|majority vote|seniority|"
            r"term.limit|rotate off|waived|motion|amendment|gavel|"
            r"question witnesses|called to order|permitted to conduct|"
            r"may only consider|rank.and.file|clause|rule [IVXLC]+)\b",
            re.I,
        )

        heading_tag = None
        for heading_id in ["Rules", "Committee_rules", "Committee_Rules"]:
            heading_tag = (
                soup.find("h2", {"id": heading_id})
                or soup.find("h3", {"id": heading_id})
                or soup.find("span", {"id": heading_id})
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

        # Fallback: scan all body paragraphs for procedural sentences
        content_div = soup.find("div", {"class": "mw-parser-output"})
        if content_div:
            for tag in content_div.find_all("p"):
                text = tag.get_text(" ", strip=True)
                if not text:
                    continue
                for sentence in re.split(r"(?<=[.!?])\s+", text):
                    sentence = sentence.strip()
                    if rules_keywords.search(sentence):
                        parts.append(sentence)

        return " ".join(parts)

    def _parse_members_wikitable(self, wiki_table) -> List[Member]:
        """
        Shared row-parsing logic for a Majority/Minority members wikitable.
        Column 0 = Majority, Column 1+ = Minority (Wikipedia convention).
        """
        members: List[Member] = []
        if not wiki_table:
            return members

        for row in wiki_table.find_all("tr")[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            for idx, cell in enumerate(cells):
                party = "Majority" if idx == 0 else "Minority"
                for li in cell.find_all("li"):
                    text = li.get_text(" ", strip=True)
                    parts = [p.strip() for p in text.split(",")]
                    if len(parts) == 1:
                        continue

                    name = parts[0]
                    role = None
                    # e.g. "Angie Craig, Minnesota, Ranking Member"
                    state_and_role = parts[1]
                    role_match = re.search(
                        r"\b(Chair|Ranking Member|Vice Chair)\b", state_and_role, re.I
                    )
                    if role_match:
                        role = role_match.group(1)

                    state = re.sub(r"\s*\(.*$", "", state_and_role).strip()
                    state = re.sub(r"\b(Chair|Ranking Member|Vice Chair)\b", "", state, flags=re.I)
                    state = re.sub(r"\s+", " ", state).strip().rstrip(",").strip()

                    members.append(Member(name=name, state=state, party=party, role=role))

        return members

    def _extract_members_table(self, soup: BeautifulSoup) -> List[Member]:
        """
        Parses the primary Majority/Minority members wikitable
        found on each committee's own page (first wikitable on the page).
        """
        wiki_table = soup.find("table", {"class": "wikitable"})
        return self._parse_members_wikitable(wiki_table)

    def _find_heading_by_id_pattern(self, soup: BeautifulSoup, pattern: re.Pattern):
        """
        Finds a heading tag whose id matches the given compiled regex pattern.
        Checks both <h2 id="..."> and <span id="..."> (older markup) forms,
        across h2/h3/h4 levels.
        """
        for tag in soup.find_all(["h2", "h3", "h4", "span"]):
            tag_id = tag.get("id", "")
            if tag_id and pattern.search(tag_id):
                return tag
        return None

    def _extract_subcommittee_members(self, soup: BeautifulSoup) -> List[Member]:
        """
        Parses the members table from a subcommittee's own Wikipedia page.
        Targets the heading id shaped like "Members,_119th_Congress"
        (Wikipedia replaces spaces with underscores, keeps the comma).
        Falls back to the first wikitable on the page if the heading
        isn't found under the expected id.
        """
        heading_pattern = re.compile(
            rf"Members,?_{self.congress_number}(st|nd|rd|th)?_Congress", re.I
        )
        heading_tag = self._find_heading_by_id_pattern(soup, heading_pattern)

        if not heading_tag:
            # Fallback — generic "Members" heading regardless of congress number
            heading_tag = self._find_heading_by_id_pattern(soup, re.compile(r"^Members", re.I))

        if not heading_tag:
            # Last resort — first wikitable on the page
            return self._extract_members_table(soup)

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

            table = sibling if sibling.name == "table" else sibling.find("table")
            if table and "wikitable" in table.get("class", []):
                return self._parse_members_wikitable(table)

        return []

    # ── Orchestration ────────────────────────────────────────────────────

    def parse_all(self) -> List[Committee]:
        """Parses every committee, its profile, members, and subcommittees."""
        raw_committees = self._parse_listing_page()
        committees: List[Committee] = []

        for raw in raw_committees:
            name = raw["name"]
            url = raw["url"]
            logger.info(f"[Parsing] {name}")

            committee = Committee(name=name, url=url, congress_number=self.congress_number)
            committee.subcommittees = self._parse_subcommittee_rows(raw["subcommittee_rows"])

            if not url:
                committees.append(committee)
                continue

            try:
                soup = self._fetch(url)
            except requests.RequestException as e:
                logger.error(f"[Fetch failed] {name}: {e}")
                committees.append(committee)
                continue

            if not self.valid_committee(soup):
                logger.warning(f"[Skip — no {self.congress_number}th Congress section] {name}")
                committees.append(committee)
                continue

            committee.profile = self._extract_profile(soup)
            committee.members = self._extract_members_table(soup)

            # ── Subcommittee members — each subcommittee may have its own page ──
            for sub in committee.subcommittees:
                if not sub.url:
                    continue
                try:
                    sub_soup = self._fetch(sub.url)
                except requests.RequestException as e:
                    logger.error(f"[Subcommittee fetch failed] {sub.name}: {e}")
                    continue

                sub.members = self._extract_subcommittee_members(sub_soup)
                logger.info(f"  [Subcommittee] {sub.name}: {len(sub.members)} members")

            committees.append(committee)

        return committees
    

    def generate_md5_hash(self, text: str, length: int = 10) -> str:
        """Generate a truncated MD5 hash from input text.
        
        Args:
            text: The string to hash.
            length: Number of characters to return from the hex digest (default 10).
        
        Returns:
            A hex string of the given length.
        """
        full_hash = hashlib.md5(text.encode("utf-8")).hexdigest()
        return full_hash[:length]


if __name__ == "__main__":
    parser = HouseCommitteeParser(congress_number="119")
    committees = parser.parse_all()

    total_members = sum(len(c.members) for c in committees)
    total_subcommittees = sum(len(c.subcommittees) for c in committees)

    print(f"Total Committees: {len(committees)}")
    print(f"Total Subcommittees: {total_subcommittees}")
    print(f"Total Rank-and-File Members: {total_members}")

    # Example: inspect one committee
    agriculture = next((c for c in committees if c.name == "Agriculture"), None)
    if agriculture:
        import json
        print(json.dumps(agriculture.to_dict(), indent=2)[:15000])