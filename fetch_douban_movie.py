# movie_sync.py
import requests
from bs4 import BeautifulSoup
from notion_client import Client
import re
import os
import sys
from datetime import datetime

# === 配置 ===
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

notion = Client(auth=NOTION_TOKEN)
headers = {"User-Agent": "Mozilla/5.0"}

def split_multi(text):
    if not text:
        return []
    return [t.strip() for t in re.split(r"[/、,，;；]", text) if t.strip()]

def fetch_douban_movie(url):
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")

    title = soup.find("span", property="v:itemreviewed").text.strip()
    rating_tag = soup.find("strong", class_="ll rating_num")
    rating = float(rating_tag.text.strip()) if rating_tag and rating_tag.text.strip() else None
    summary_tag = soup.find("span", property="v:summary")
    summary = summary_tag.get_text("\n", strip=True) if summary_tag else ""
    cover = soup.find("img", rel="v:image")["src"]

    def extract_info(label):
        tag = soup.find(text=re.compile(f"^{label}"))
        if tag and tag.parent:
            next_node = tag.parent.next_sibling
            if isinstance(next_node, str):
                return next_node.strip()
            else:
                return next_node.get_text(strip=True) if next_node else ""
        return ""

    def extract_multiple(label):
        tag = soup.find(text=re.compile(f"^{label}"))
        if tag:
            attrs_span = tag.parent.find_next_siblings("span", class_="attrs")
            if attrs_span:
                return [a.text.strip() for a in attrs_span[0].find_all("a")]
        return []

    release_dates = soup.find_all("span", property="v:initialReleaseDate")
    release_date = ""
    for tag in release_dates:
        text = tag.text.strip()
        if re.search(r"\d{4}", text):
            release_date = text
            break

    movie = {
        "title": title,
        "rating": rating,
        "summary": summary,
        "cover": cover,
        "url": url,
        "directors": extract_multiple("导演"),
        "writers": extract_multiple("编剧"),
        "actors": extract_multiple("主演"),
        "genre": [g.text for g in soup.find_all("span", property="v:genre")],
        "release_date": release_date,
        "duration": soup.find("span", property="v:runtime").text if soup.find("span", property="v:runtime") else "",
        "region": extract_info("制片国家/地区:"),
        "language": extract_info("语言:")
    }

    return movie

def notion_props(movie):
    def multi_select(items):
        return {"multi_select": [{"name": i} for i in items if i]}

    def rich(text):
        return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}

    def date(val):
        for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
            try:
                dt = datetime.strptime(val[:10], fmt)
                return {"date": {"start": dt.strftime("%Y-%m-%d")}}
            except:
                continue
        return {"date": None}

    return {
        "片名": {"title": [{"text": {"content": movie["title"]}}]},
        "导演": multi_select(movie["directors"]),
        "编剧": multi_select(movie["writers"]),
        "主演": multi_select(movie["actors"]),
        "类型": multi_select(movie["genre"]),
        "国家": multi_select(split_multi(movie["region"])),
        "语言": multi_select(split_multi(movie["language"])),
        "上映日期": date(movie["release_date"]),
        "片长": rich(movie["duration"]),
        "豆瓣评分": {"number": movie["rating"]} if movie["rating"] else {"number": None},
        "简介": rich(movie["summary"][:200]),
        "豆瓣链接": {"url": movie["url"]},
        "封面": {
            "files": [{"type": "external", "name": "cover", "external": {"url": movie["cover"]}}]
        },
    }

def find_page_by_url(url):
    response = notion.databases.query(
        database_id=DATABASE_ID,
        filter={
            "property": "豆瓣链接",
            "url": {"equals": url}
        }
    )
    results = response.get("results", [])
    return results[0]["id"] if results else None

def sync_to_notion(movie):
    print(f"同步电影：{movie['title']} - {movie['url']}")
    page_id = find_page_by_url(movie["url"])
    props = notion_props(movie)
    cover = {"external": {"url": movie["cover"]}}
    icon = {"type": "external", "external": {"url": movie["cover"]}}
    if page_id:
        notion.pages.update(page_id=page_id, properties=props, cover=cover, icon=icon)
        print(f"✅ 已更新《{movie['title']}》")
    else:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties=props,
            cover=cover,
            icon=icon
        )
        print(f"✅ 已添加《{movie['title']}》")
def split_urls(line):
    # 用逗号分割，去除空白
    return [u.strip() for u in line.split(",") if u.strip()]
if __name__ == "__main__":
    url_file = sys.argv[1] if len(sys.argv) > 1 else "urls.txt"
    with open(url_file, "r", encoding="utf-8") as f:
        content = f.read()

    urls = split_urls(content)

    for url in urls:
        if not url.startswith("https://movie.douban.com/subject/"):
            print(f"⚠️ 跳过非法链接: {url}")
            continue
        try:
            movie = fetch_douban_movie(url)
            sync_to_notion(movie)
        except Exception as e:
            print(f"❌ 处理 {url} 出错: {e}")
