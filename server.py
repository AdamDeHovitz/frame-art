#!/usr/bin/env python3
"""Small local Stillroom server and same-origin relay for museum data/images."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from html import unescape
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen
from tv_transfer import (TVTransferError, pair as pair_tv, status as tv_status,
                         upload as upload_tv, slideshow_status, start_slideshow,
                         stop_slideshow, list_photos, delete_photos)


ROOT = Path(__file__).resolve().parent
API_URL = "https://openaccess-api.clevelandart.org/api/artworks/"
MET_API = "https://collectionapi.metmuseum.org/public/collection/v1"
MET_SEARCH_API = "https://collectionapi.metmuseum.org/public/collection/v1.1/search"
IMAGE_HOST = "openaccess-cdn.clevelandart.org"
MET_IMAGE_HOST = "images.metmuseum.org"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_IMAGE_HOST = "upload.wikimedia.org"
USER_AGENT = "Stillroom/0.1 (local art display app)"

# Flat visual works suitable for a screen. Keep photography out even when a
# museum calls a photographic process a print.
FLAT_TYPES = ("painting", "drawing", "print", "watercolor", "watercolour", "pastel",
              "collage", "illustration", "poster", "woodcut", "lithograph",
              "etching", "engraving", "screenprint", "silkscreen", "monotype",
              "gouache", "tempera", "calligraphy", "illuminated manuscript",
              "miniature", "album leaf")
NON_FLAT = ("photograph", "photography", "photo print", "gelatin silver", "albumen",
            "daguerreotype", "ambrotype", "collotype", "sculpture", "statue", "relief",
            "furniture", "vessel", "textile", "carpet", "garment", "jewelry", "coin")


def is_flat_art(*labels):
    text = " ".join(str(label or "") for label in labels).lower()
    if any(term in text for term in NON_FLAT):
        return False
    return any(term in text for term in FLAT_TYPES)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/tv/status":
            if not self.local_tv_request_allowed():
                self.send_json(403, {"error": "Open Stillroom from its local address to view TV status."})
                return
            self.send_json(200, tv_status())
        elif parsed.path == "/api/tv/photos":
            if not self.local_tv_request_allowed():
                self.send_json(403, {"error": "Open Stillroom from its local address to view TV photos."})
                return
            try:
                page = int(parse_qs(parsed.query).get("page", ["1"])[0])
                self.send_json(200, list_photos(page))
            except ValueError:
                self.send_json(400, {"error": "Choose a valid photo page."})
            except TVTransferError as error:
                self.send_json(error.status, {"error": str(error)})
        elif parsed.path == "/api/tv/slideshow/status":
            if not self.local_tv_request_allowed():
                self.send_json(403, {"error": "Open Stillroom from its local address to view TV status."})
                return
            self.send_json(200, slideshow_status())
        elif parsed.path == "/api/collections":
            self.send_json(200, json.loads((ROOT / "collections.json").read_text()))
        elif parsed.path == "/api/search":
            self.proxy_search(parse_qs(parsed.query))
        elif parsed.path == "/image":
            self.proxy_image(parse_qs(parsed.query))
        elif parsed.path in ("/", "/index.html", "/app.js", "/styles.css"):
            super().do_GET()
        else:
            self.send_error(404, "Not found")

    def send_json(self, status, payload):
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def local_tv_request_allowed(self):
        host = urlparse("http://" + self.headers.get("Host", ""))
        origin_value = self.headers.get("Origin")
        origin = urlparse(origin_value) if origin_value else None
        try:
            host_port = host.port
            origin_port = origin.port if origin else None
        except ValueError:
            return False
        return (host.hostname in ("127.0.0.1", "localhost", "::1")
                and host_port == self.server.server_port
                and self.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")
                and (not origin or (origin.scheme == "http" and origin.hostname == host.hostname
                                    and origin_port == host_port)))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path not in ("/api/tv/pair", "/api/tv/upload",
                        "/api/tv/slideshow/start", "/api/tv/slideshow/stop",
                        "/api/tv/photos/delete"):
            self.send_json(404, {"error": "Not found"})
            return
        # Only the local app may request TV changes. The same check also
        # protects the read-only photo list from cross-site access.
        if not self.local_tv_request_allowed():
            self.send_json(403, {"error": "Open Stillroom from its local address to use TV transfer."})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = -1
        json_request = path != "/api/tv/upload"
        limit = (1024 if path.endswith("/pair") else 16 * 1024) if json_request else 16 * 1024 * 1024
        if length < 1 or length > limit:
            self.send_json(413, {"error": "The request is empty or too large."})
            return
        content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        expected = "application/json" if json_request else "image/jpeg"
        if content_type != expected:
            self.send_json(415, {"error": f"Expected {expected}."})
            return
        body = self.rfile.read(length)
        try:
            if json_request:
                try:
                    data = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    self.send_json(400, {"error": "Invalid request data."})
                    return
                if not isinstance(data, dict):
                    self.send_json(400, {"error": "Invalid request data."})
                    return
                if path.endswith("/pair"):
                    result = pair_tv(data.get("ip"))
                elif path.endswith("/start"):
                    result = start_slideshow(data.get("contentIds"), data.get("intervalMinutes"))
                elif path.endswith("/delete"):
                    result = delete_photos(data.get("contentIds"))
                else:
                    result = stop_slideshow()
            else:
                select = parse_qs(parsed.query).get("select", ["1"])[0] != "0"
                result = upload_tv(body, select=select)
            self.send_json(200, result)
        except TVTransferError as error:
            self.send_json(error.status, {"error": str(error)})

    def proxy_search(self, query):
        term = query.get("q", [""])[0][:120]
        source = query.get("source", ["all"])[0]
        try:
            page = max(1, int(query.get("page", ["1"])[0]))
        except ValueError:
            page = 1
        try:
            if source == "all":
                payload = self.search_all_sources(term, page)
            elif source == "met":
                payload = self.search_met(term, page)
            elif source == "cleveland":
                payload = self.search_cleveland(term, page)
            elif source == "commons":
                payload = self.search_commons(term, page)
            else:
                self.send_error(400, "Unknown collection")
                return
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError) as error:
            self.send_error(502, f"Museum search failed: {error}")

    def search_all_sources(self, term, page):
        searches = {
            "cleveland": self.search_cleveland,
            "met": self.search_met,
            "commons": self.search_commons,
        }
        results = {}
        failures = []
        with ThreadPoolExecutor(max_workers=3) as pool:
            jobs = {pool.submit(search, term, page): name for name, search in searches.items()}
            for job, name in ((job, jobs[job]) for job in jobs):
                try:
                    results[name] = job.result()
                except Exception as error:
                    failures.append(f"{name}: {error}")
        if not results:
            raise OSError("All art collections failed: " + "; ".join(failures))
        items = []
        total = 0
        page_size = 0
        has_more = False
        for name, result in results.items():
            for item in result["data"]:
                if re.search(r"\bkandinsky\b", term, re.IGNORECASE):
                    searchable = f"{item.get('title', '')} {item.get('artistDisplayName', '')}"
                    if not re.search(r"\bkandinsky\b", searchable, re.IGNORECASE):
                        continue
                item["source"] = name
                items.append(item)
            total += result["info"].get("total", 0)
            page_size += result["info"].get("pageSize", 12)
            has_more = has_more or result["info"].get("hasMore", False)
        return {"info": {"total": total, "pageSize": page_size, "hasMore": has_more}, "data": items,
                "warnings": failures}

    def fetch_json(self, url):
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        with urlopen(request, timeout=25) as response:
            return json.loads(response.read())

    def search_cleveland(self, term, page):
        params = urlencode({
            "q": term,
            "cc0": 1,
            "has_image": 1,
            "limit": 12,
            "skip": (page - 1) * 12,
        })
        data = self.fetch_json(f"{API_URL}?{params}")
        works = []
        for item in data.get("data", []):
            if not is_flat_art(item.get("type")):
                continue
            images = item.get("images") or {}
            web = (images.get("web") or {}).get("url")
            print_image = (images.get("print") or {}).get("url")
            if not web or not print_image:
                continue
            artists = [creator.get("description", "") for creator in item.get("creators", []) if creator.get("role") == "artist"]
            works.append({
                "id": f"cma-{item.get('id')}", "title": item.get("title"),
                "artistDisplayName": ", ".join(artists), "objectDate": item.get("creation_date"),
                "objectURL": item.get("url"), "museum": "Cleveland Museum of Art",
                "images": {"web": {"url": web}, "print": {"url": print_image}},
            })
        total = data.get("info", {}).get("total", len(works))
        return {"info": {"total": total, "pageSize": 12,
                          "hasMore": (page - 1) * 12 + len(data.get("data", [])) < total}, "data": works}

    def search_met(self, term, page):
        search_params = {"isPublicDomain": "true", "hasImages": "true",
                         "offset": (page - 1) * 24, "limit": 24}
        if term:
            search_params["q"] = term
        params = urlencode(search_params)
        result = self.fetch_json(f"{MET_SEARCH_API}?{params}")
        ids = result.get("objectIDs") or []
        # This known public-domain Kandinsky gouache is indexed inconsistently
        # by the Met's text search (artist name is recorded as "Vasily").
        if "kandinsky" in term.lower() and 485829 not in ids:
            ids.insert(0, 485829)
        object_urls = [f"{MET_API}/objects/{object_id}" for object_id in ids]
        with ThreadPoolExecutor(max_workers=4) as pool:
            details = list(pool.map(self.fetch_json, object_urls))
        works = []
        for item in details:
            if not item.get("isPublicDomain") or not item.get("primaryImage"):
                continue
            if not is_flat_art(item.get("medium"), item.get("objectName")):
                continue
            small = item.get("primaryImageSmall") or item["primaryImage"]
            works.append({
                "id": f"met-{item.get('objectID')}", "title": item.get("title"),
                "artistDisplayName": item.get("artistDisplayName"), "objectDate": item.get("objectDate"),
                "objectURL": item.get("objectURL"), "museum": "The Met",
                "images": {"web": {"url": small}, "print": {"url": item["primaryImage"]}},
            })
        total = result.get("total", len(works))
        return {"info": {"total": total, "pageSize": 24,
                          "hasMore": page * 24 < total}, "data": works}

    def search_commons(self, term, page):
        params = {
            "action": "query", "format": "json", "formatversion": 2,
            "generator": "search", "gsrnamespace": 6,
            "gsrsearch": term or 'incategory:Paintings OR incategory:Drawings OR incategory:Prints OR incategory:Watercolors OR incategory:Posters OR incategory:Illustrations',
            "gsrlimit": 50,
            "prop": "imageinfo|categories", "iiprop": "url|size|extmetadata|thumburls",
            "iiurlwidth": 1200, "cllimit": "max",
        }
        candidate_page_size = 200
        base_offset = (page - 1) * candidate_page_size
        candidate_items = []
        for batch_offset in range(0, candidate_page_size, 50):
            params["gsroffset"] = base_offset + batch_offset
            data = self.fetch_json(f"{COMMONS_API}?{urlencode(params)}")
            query_data = data.get("query", {})
            candidate_items.extend(query_data.get("pages", []))
        works = []
        for item in candidate_items:
            image_info = (item.get("imageinfo") or [{}])[0]
            metadata = image_info.get("extmetadata") or {}
            title = item.get("title", "").removeprefix("File:")
            categories = [c.get("title", "").removeprefix("Category:") for c in item.get("categories", [])]
            classification = " ".join([title, *categories])
            license_name = unescape(re.sub(r"<[^>]*>", "", metadata.get("LicenseShortName", {}).get("value", ""))).strip()
            if not is_flat_art(classification):
                continue
            if not ("public domain" in license_name.lower() or "cc0" in license_name.lower()):
                continue
            image_url = image_info.get("url")
            thumb_url = image_info.get("thumburl")
            if not thumb_url or "thumbnail_unscaled" in urlparse(thumb_url).query:
                thumb_url = self.commons_thumbnail_url(image_url, 1280)
            else:
                thumb_url = self.normalize_commons_thumbnail(thumb_url)
            if not image_url or not thumb_url:
                continue
            artist = metadata.get("Artist", {}).get("value", "")
            artist = unescape(re.sub(r"<[^>]*>", "", artist)).strip()
            date = metadata.get("DateTimeOriginal", {}).get("value") or metadata.get("Date", {}).get("value", "")
            works.append({
                "id": f"commons-{item.get('pageid')}",
                "title": re.sub(r"\.[^.]+$", "", title),
                "artistDisplayName": artist, "objectDate": date,
                "objectURL": image_info.get("descriptionurl"),
                "museum": f"Wikimedia Commons · {license_name}",
                "images": {"web": {"url": thumb_url}, "print": {"url": image_url}},
            })
        # Commons' searchinfo.totalhits is approximate and can be capped. Treat
        # a full candidate window as evidence that another offset may contain
        # usable works; the client keeps paging until its preview batch fills.
        has_more = len(candidate_items) >= candidate_page_size
        return {"info": {"total": len(works), "pageSize": candidate_page_size,
                          "hasMore": has_more}, "data": works}

    @staticmethod
    def normalize_commons_thumbnail(thumbnail_url):
        parsed = urlparse(thumbnail_url)
        if parsed.hostname == COMMONS_IMAGE_HOST and "/thumb/" in parsed.path:
            parsed = parsed._replace(netloc="thumb.wikimedia.org", query="")
        return urlunparse(parsed)

    @staticmethod
    def commons_thumbnail_url(image_url, width):
        if not image_url:
            return ""
        parsed = urlparse(image_url)
        original_path = unquote(parsed.path)
        if parsed.hostname != COMMONS_IMAGE_HOST or not original_path.startswith("/wikipedia/commons/") or "/thumb/" in original_path:
            return ""
        filename = original_path.rsplit("/", 1)[-1]
        thumb_path = original_path.replace("/wikipedia/commons/", "/wikipedia/commons/thumb/", 1)
        thumb_path = f"{thumb_path}/{width}px-{filename}"
        return urlunparse(parsed._replace(netloc="thumb.wikimedia.org", path=quote(thumb_path, safe="/@-._~()"), query=""))

    def proxy_image(self, query):
        source = query.get("src", [""])[0]
        parsed = urlparse(source)
        allowed_cleveland = parsed.hostname == IMAGE_HOST and parsed.path.lower().endswith(("_web.jpg", "_print.jpg"))
        allowed_met = parsed.hostname == MET_IMAGE_HOST and parsed.path.lower().endswith((".jpg", ".jpeg"))
        allowed_commons = parsed.hostname in {COMMONS_IMAGE_HOST, "thumb.wikimedia.org"} and parsed.path.startswith("/wikipedia/commons/")
        if parsed.scheme != "https" or not (allowed_cleveland or allowed_met or allowed_commons):
            self.send_error(400, "Only approved Cleveland, Met, and Wikimedia Commons image URLs are available through this route")
            return
        request = Request(source, headers={"User-Agent": USER_AGENT, "Accept": "image/*" if allowed_commons else "image/jpeg"})
        try:
            with urlopen(request, timeout=35) as response:
                payload = response.read(30 * 1024 * 1024 + 1)
                content_type = response.headers.get_content_type()
            if not (content_type or "").startswith("image/"):
                self.send_error(415, "The source did not return an image")
                return
            if len(payload) > 30 * 1024 * 1024:
                self.send_error(413, "Image is too large")
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type or "image/jpeg")
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            self.send_error(502, f"Museum image fetch failed: {error}")

    def log_message(self, format, *args):
        print(f"{self.log_date_time_string()} {format % args}")


if __name__ == "__main__":
    # A user can still launch with `python3 server.py`: switch to this
    # project's installed TV environment before accepting requests.
    project_python = ROOT / ".venv" / "bin" / "python"
    if sys.prefix == sys.base_prefix and project_python.is_file():
        os.execv(str(project_python), [str(project_python), str(ROOT / "server.py"), *sys.argv[1:]])
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    print("Stillroom is available at http://127.0.0.1:8000 — press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStillroom server stopped.")
        server.server_close()
