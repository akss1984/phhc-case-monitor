#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

CASE_NUMBER = os.getenv("CASE_NUMBER", "CWP-1770-2026")
STATE_FILE = Path(os.getenv("STATE_FILE", "state.json"))
USER_AGENT = "Mozilla/5.0"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"case_number": CASE_NUMBER, "last_detected": None}
    return {"case_number": CASE_NUMBER, "last_detected": None}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def build_candidate_urls(case_number: str) -> list[str]:
    base_urls = [
        f"https://new.phhc.gov.in/case-status?case_no={case_number}",
        f"https://new.phhc.gov.in/case_status?case_no={case_number}",
        f"https://new.phhc.gov.in/case-status/{case_number}",
        f"https://phhc.gov.in/case-status?case_no={case_number}",
        f"https://phhc.gov.in/case_status?case_no={case_number}",
        f"https://highcourtchd.gov.in/?mod=case_status",
    ]
    return list(dict.fromkeys(base_urls))


def fetch_page(url: str):
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": USER_AGENT})
        response.raise_for_status()
        return response.text, response.url
    except requests.RequestException as exc:
        print(f"Failed to fetch {url}: {exc}", file=sys.stderr)
        return None, url


def extract_pdf_links(html: str, page_url: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []

    for tag in soup.find_all(["a", "link", "iframe", "embed"]):
        href = tag.get("href") or tag.get("src")
        if not href:
            continue
        absolute_url = urljoin(page_url, href)
        if not absolute_url.lower().endswith(".pdf"):
            continue
        text = " ".join(tag.stripped_strings).strip() or Path(absolute_url).name
        results.append((text, absolute_url))

    return results


def is_judgment_candidate(text: str, href: str) -> bool:
    lowered = f"{text} {href}".lower()
    if "interim" in lowered:
        return False
    if ".pdf" not in lowered:
        return False
    keywords = [
        "judgment",
        "judgement",
        "final order",
        "final judgement",
        "final judgment",
        "final order pdf",
        "judgment pdf",
    ]
    return any(keyword in lowered for keyword in keywords)


def find_new_judgment(case_number: str, state: dict) -> dict | None:
    last_detected = state.get("last_detected") or {}
    last_signature = last_detected.get("signature")

    for url in build_candidate_urls(case_number):
        html, page_url = fetch_page(url)
        if not html:
            continue

        for text, href in extract_pdf_links(html, page_url):
            if not is_judgment_candidate(text, href):
                continue

            signature = f"{text}|{href}"
            if signature == last_signature:
                return None

            return {
                "title": text or Path(href).name,
                "url": href,
                "page_url": page_url,
                "signature": signature,
                "detected_at": datetime.now(timezone.utc).isoformat(),
            }

    return None


def main() -> None:
    state = load_state()
    state["case_number"] = CASE_NUMBER

    detection = find_new_judgment(CASE_NUMBER, state)
    if detection is None:
        print("No new judgment found")
        return

    state["last_detected"] = detection
    save_state(state)
    print(f"New judgment found: {detection['title']} -> {detection['url']}")


if __name__ == "__main__":
    main()
