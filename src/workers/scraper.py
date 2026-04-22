from bs4 import BeautifulSoup
import requests
import re


DEFAULT_BASE_URL = "https://www.myinstants.com"
DEFAULT_REGION = "us"


def normalize_base_url(base_url: str) -> str:
    cleaned = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
    if not cleaned:
        cleaned = DEFAULT_BASE_URL
    if not re.match(r"^https?://", cleaned, re.IGNORECASE):
        cleaned = f"https://{cleaned}"
    return cleaned


def normalize_region(region: str) -> str:
    cleaned = (region or DEFAULT_REGION).strip().strip("/")
    return cleaned or DEFAULT_REGION


def searchq(query: str, base_url: str = DEFAULT_BASE_URL):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0",
    }
    query = query.replace(" ", "+")
    base_url = normalize_base_url(base_url)
    url = f"{base_url}/en/search/?name={query}"
    response = requests.get(url=url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    url_list = []
    for index, button in enumerate(soup.find_all(class_="small-button")):
        onclick = button["onclick"]
        button["title"] = re.findall(
            f"{re.escape('Play')}(.*){re.escape('sound')}", button["title"]
        )[0]
        parts = onclick.split("'")
        url_list.append({"url": f"{base_url}{parts[1]}", "title": str(button["title"])})
        if index >= 9:
            break
    return url_list


def getPage(page: str, region: str = DEFAULT_REGION, base_url: str = DEFAULT_BASE_URL):
    headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET",
        "Access-Control-Allow-Headers": "Content-Type",
        "Access-Control-Max-Age": "3600",
        "User-Agent": "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:52.0) Gecko/20100101 Firefox/52.0",
    }
    base_url = normalize_base_url(base_url)
    region = normalize_region(region)

    if int(page) == 1:
        url = f"{base_url}/en/index/{region}/?page={page}"
    else:
        url = f"{base_url}/en/trending/{region}/?page={page}"

    response = requests.get(url=url, headers=headers, timeout=30)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    url_list = []
    for button in soup.find_all(class_="small-button"):
        onclick = button["onclick"]
        button["title"] = re.findall(
            f"{re.escape('Play')}(.*){re.escape('sound')}", button["title"]
        )[0]
        button["title"] = button["title"].strip()
        parts = onclick.split("'")
        url_list.append({"url": f"{base_url}{parts[1]}", "title": str(button["title"])})
    return url_list
