#!/usr/bin/env python3
"""
Minimal FOA ingestion + rule-based semantic tagging pipeline.

Usage:
    python main.py --url "<FOA_URL>" --out_dir ./out
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)


ONTOLOGY: Dict[str, Dict[str, List[str]]] = {
    "research_domains": {
        "biomedical": [
            "alzheimer",
            "dementia",
            "biomedical",
            "clinical",
            "therapeutic",
            "diagnosis",
            "treatment",
            "disease",
            "health",
            "adrd",
        ],
        "public_health": [
            "prevention",
            "care",
            "caregiver",
            "population health",
            "public health",
            "health outcomes",
        ],
        "education_research": [
            "research careers",
            "next generation of researchers",
            "career development",
            "training",
            "workforce",
        ],
        "data_science": [
            "data science",
            "data analytics",
            "machine learning",
            "artificial intelligence",
        ],
    },
    "methods_approaches": {
        "pilot_study": [
            "pilot studies",
            "pilot study",
            "proof of concept",
            "feasibility",
        ],
        "clinical_research": [
            "clinical trial",
            "clinical research",
            "observational",
            "human subjects",
        ],
    },
    "populations": {
        "older_adults": [
            "aging",
            "older adults",
            "older adult",
            "alzheimer",
            "dementia",
        ],
        "patients_and_caregivers": [
            "individuals with",
            "patients",
            "patient",
            "caregivers",
            "caregiver",
        ],
        "early_career_researchers": [
            "next generation of researchers",
            "research careers",
            "early-stage investigator",
            "new investigator",
        ],
    },
    "sponsor_themes": {
        "innovation": [
            "innovative",
            "new",
            "novel",
            "stimulate",
        ],
        "capacity_building": [
            "encourage",
            "research careers",
            "next generation",
            "build upon their existing expertise",
        ],
    },
}


def fetch_html(url: str) -> str:
    response = requests.get(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
        timeout=30,
    )
    response.raise_for_status()
    return response.text


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def extract_between(text: str, start: str, end_candidates: List[str]) -> str:
    start_idx = text.find(start)
    if start_idx == -1:
        return ""

    content = text[start_idx + len(start) :]
    end_positions = [content.find(candidate) for candidate in end_candidates if content.find(candidate) != -1]
    if end_positions:
        content = content[: min(end_positions)]
    return clean_text(content)


def first_match(text: str, patterns: List[str]) -> Optional[str]:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return clean_text(match.group(1))
    return None


def parse_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    value = clean_text(value).rstrip(".")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value

    us_match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if us_match:
        month, day, year = us_match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    month_match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),\s*(\d{4})", value)
    if month_match:
        month_name, day, year = month_match.groups()
        month_map = {
            "january": "01",
            "february": "02",
            "march": "03",
            "april": "04",
            "may": "05",
            "june": "06",
            "july": "07",
            "august": "08",
            "september": "09",
            "october": "10",
            "november": "11",
            "december": "12",
        }
        month_number = month_map.get(month_name.lower())
        if month_number:
            return f"{year}-{month_number}-{day.zfill(2)}"

    return None


def money_to_string(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    return f"${clean_text(raw).replace(' ', '')}"


def clean_award_value(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    value = clean_text(raw)
    return value or None


def generate_foa_id(url: str, title: str, foa_number: Optional[str]) -> str:
    if foa_number:
        safe_number = re.sub(r"[^A-Za-z0-9_-]+", "_", foa_number)
        return f"foa_{safe_number}"
    digest = hashlib.sha256(f"{url}|{title}".encode("utf-8")).hexdigest()[:10]
    host = urlparse(url).netloc.replace(".", "_")
    return f"{host}_{digest}"


def apply_semantic_tags(text: str) -> List[str]:
    haystack = text.lower()
    tags: List[str] = []
    for _, category_tags in ONTOLOGY.items():
        for tag, keywords in category_tags.items():
            if any(keyword in haystack for keyword in keywords):
                tags.append(tag)
    return sorted(set(tags))


def detect_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "simpler.grants.gov" in host or "grants.gov" in host:
        return "grants"
    return "generic"


def parse_grants_eligibility(description_container: Optional[BeautifulSoup]) -> Optional[Dict[str, Any]]:
    if description_container is None:
        return None

    eligibility_heading = description_container.find("h2", string=lambda s: s and clean_text(s) == "Eligibility")
    if not eligibility_heading:
        return None

    sections: Dict[str, Any] = {}
    node = eligibility_heading.find_next_sibling()

    while node:
        if getattr(node, "name", None) == "h2":
            break

        if node.name == "h3":
            section_name = clean_text(node.get_text(" ", strip=True))
            collected_nodes: List[Any] = []
            next_node = node.find_next_sibling()
            while next_node and getattr(next_node, "name", None) not in {"h2", "h3"}:
                collected_nodes.append(next_node)
                next_node = next_node.find_next_sibling()

            subsection_map: Dict[str, Any] = {}
            plain_text_parts: List[str] = []

            for content_node in collected_nodes:
                if content_node.name != "div":
                    text = clean_text(content_node.get_text(" ", strip=True))
                    if text:
                        plain_text_parts.append(text)
                    continue

                subgroup = content_node.find("h4")
                if subgroup:
                    subgroup_name = clean_text(subgroup.get_text(" ", strip=True))
                    items = [
                        clean_text(li.get_text(" ", strip=True))
                        for li in content_node.find_all("li")
                        if clean_text(li.get_text(" ", strip=True))
                    ]
                    if items:
                        subsection_map[subgroup_name] = items if len(items) > 1 else items[0]
                    else:
                        text = clean_text(content_node.get_text(" ", strip=True).replace(subgroup_name, "", 1))
                        subsection_map[subgroup_name] = text or ""
                else:
                    text = clean_text(content_node.get_text(" ", strip=True))
                    if text:
                        plain_text_parts.append(text)

            if subsection_map and plain_text_parts:
                subsection_map["details"] = " ".join(plain_text_parts)
                sections[section_name] = subsection_map
            elif subsection_map:
                sections[section_name] = subsection_map
            elif plain_text_parts:
                joined = " ".join(plain_text_parts)
                sections[section_name] = joined
            else:
                sections[section_name] = ""

            node = next_node
            continue

        node = node.find_next_sibling()

    return sections or None


def parse_grants_award_details(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    result: Dict[str, Optional[str]] = {
        "program_funding": None,
        "award_minimum": None,
        "award_maximum": None,
        "expected_awards": None,
        "foa_number": None,
    }

    award_heading = soup.find("h2", string=lambda s: s and clean_text(s) == "Award")
    if not award_heading:
        return result

    award_container = award_heading.parent
    if not award_container:
        return result

    grid = award_container.find("div", attrs={"data-testid": "grid"})
    if grid:
        for card in grid.find_all("div", class_=lambda c: c and "border" in c):
            paragraphs = card.find_all("p")
            if len(paragraphs) < 2:
                continue
            value = clean_award_value(paragraphs[0].get_text(" ", strip=True))
            label = clean_text(paragraphs[1].get_text(" ", strip=True)).lower()
            if label == "program funding":
                result["program_funding"] = value
            elif label == "award minimum":
                result["award_minimum"] = value
            elif label == "award maximum":
                result["award_maximum"] = value
            elif label == "expected awards":
                result["expected_awards"] = value

    foa_label = award_container.find("p", string=lambda s: s and "Funding opportunity number" in s)
    if foa_label:
        details_block = foa_label.parent
        if details_block:
            value_tag = details_block.find("p", class_=lambda c: c and "line-height-sans-1" in c)
            if value_tag:
                result["foa_number"] = clean_text(value_tag.get_text(" ", strip=True))

    return result


def parse_grants_page(url: str, html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = html_to_text(html)
    description_container = soup.find("div", attrs={"data-testid": "opportunity-description"})
    award_details = parse_grants_award_details(soup)

    title = None
    if soup.title and soup.title.text:
        title_text = clean_text(soup.title.text)
        if " - " in title_text:
            title = title_text.split(" - ", 1)[1]
        else:
            title = title_text

    if not title:
        heading = soup.find(["h1", "h2"])
        if heading:
            title = clean_text(heading.get_text(" ", strip=True))

    agency = first_match(text, [r"Agency:\s*(.+?)\s*Assistance Listings:"])
    if not agency:
        agency = first_match(text, [r"Agency:\s*(.+?)\s*Last Updated:"])

    description = None
    if description_container:
        heading = description_container.find("h2", string=lambda s: s and clean_text(s) == "Description")
        if heading:
            node = heading.find_next_sibling()
            while node and getattr(node, "name", None) != "h2":
                if node.name == "div":
                    text_value = clean_text(node.get_text(" ", strip=True))
                    if text_value and "Jump to all documents" not in text_value:
                        description = text_value
                        break
                node = node.find_next_sibling()
    if not description:
        description = extract_between(text, "Description", ["Eligibility", "Award", "Program Funding", "History"])
        description = description.replace("Jump to all documents", "").strip()

    eligibility = parse_grants_eligibility(description_container)

    foa_number = award_details["foa_number"] or first_match(
        text,
        [
            r"Funding opportunity number\s*:?\s*([A-Z0-9-]{6,})",
            r"\b([A-Z]{1,5}-\d{2}-\d{2,4})\b",
        ],
    )

    open_date = parse_date(
        first_match(
            text,
            [
                r"Posted date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                r"Posted date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})",
                r"Open date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
            ],
        )
    )

    close_date = parse_date(
        first_match(
            text,
            [
                r"Close date\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                r"Closing:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                r"Application due date\(s\)\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                r"Current closing date for applications\s*:?\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})",
                r"Current closing date for applications\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})",
            ],
        )
    )

    award_min = award_details["award_minimum"] or money_to_string(first_match(text, [r"Award Minimum\s*\$?([0-9,]+(?:\.\d+)?)"]))
    award_max = award_details["award_maximum"] or money_to_string(first_match(text, [r"Award Maximum\s*\$?([0-9,]+(?:\.\d+)?)"]))
    award_single = money_to_string(first_match(text, [r"Award\s*\$?([0-9,]+(?:\.\d+)?)"]))

    return {
        "foa_number": foa_number,
        "title": title or "Unknown Title",
        "agency": agency or "Unknown Agency",
        "open_date": open_date,
        "close_date": close_date,
        "eligibility": eligibility,
        "program_description": description or None,
        "program_funding": award_details["program_funding"],
        "award_minimum": award_min,
        "award_maximum": award_max,
        "source_url": url,
    }


def parse_generic_page(url: str, html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.title.text) if soup.title else "Unknown Title"
    return {
        "foa_number": None,
        "title": title,
        "agency": "Unknown Agency",
        "open_date": None,
        "close_date": None,
        "eligibility": None,
        "program_description": None,
        "program_funding": None,
        "award_minimum": None,
        "award_maximum": None,
        "source_url": url,
    }


def build_record(url: str, html: str) -> Dict[str, Any]:
    source = detect_source(url)
    if source == "grants":
        parsed = parse_grants_page(url, html)
    else:
        parsed = parse_generic_page(url, html)

    combined_text = " ".join(
        value
        for value in [
            parsed.get("title"),
            parsed.get("program_description"),
            json.dumps(parsed.get("eligibility"), ensure_ascii=False) if parsed.get("eligibility") else None,
        ]
        if value
    )

    record = {
        "foa_id": generate_foa_id(url, parsed["title"], parsed.get("foa_number")),
        "foa_number": parsed.get("foa_number"),
        "title": parsed["title"],
        "agency": parsed["agency"],
        "open_date": parsed.get("open_date"),
        "close_date": parsed.get("close_date"),
        "eligibility": parsed.get("eligibility"),
        "program_description": parsed.get("program_description"),
        "program_funding": parsed.get("program_funding"),
        "award_minimum": parsed.get("award_minimum"),
        "award_maximum": parsed.get("award_maximum"),
        "source_url": parsed["source_url"],
        "semantic_tags": apply_semantic_tags(combined_text),
        "tagging_method": "rule_based_keyword_matching",
    }
    return record


def write_json(record: Dict[str, Any], output_path: Path) -> None:
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)


def write_csv(record: Dict[str, Any], output_path: Path) -> None:
    flattened = dict(record)
    flattened["semantic_tags"] = "; ".join(record.get("semantic_tags", []))
    flattened["eligibility"] = (
        json.dumps(record["eligibility"], ensure_ascii=False)
        if record.get("eligibility") is not None
        else None
    )
    fieldnames = [
        "foa_id",
        "foa_number",
        "title",
        "agency",
        "open_date",
        "close_date",
        "eligibility",
        "program_description",
        "program_funding",
        "award_minimum",
        "award_maximum",
        "source_url",
        "semantic_tags",
        "tagging_method",
    ]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerow(flattened)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="FOA ingestion and semantic tagging")
    parser.add_argument("--url", required=True, help="Public FOA URL")
    parser.add_argument("--out_dir", required=True, help="Directory for foa.json and foa.csv")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    html = fetch_html(args.url)
    record = build_record(args.url, html)

    write_json(record, out_dir / "foa.json")
    write_csv(record, out_dir / "foa.csv")

    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
