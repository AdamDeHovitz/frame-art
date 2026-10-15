"""Local-network bridge between Stillroom's browser UI and Samsung Art Mode."""

import asyncio
import base64
import importlib.util
import ipaddress
import json
import os
import re
from pathlib import Path
import socket
from threading import Event, Lock, Thread


ROOT = Path(__file__).resolve().parent
STATE_DIR = ROOT / "work" / "tv"
CONFIG_FILE = STATE_DIR / "connection.json"
LAN_RANGES = tuple(ipaddress.ip_network(cidr) for cidr in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
))
TRANSFER_LOCK = Lock()
SLIDESHOW_CONTROL_LOCK = Lock()
SLIDESHOW_LOCK = Lock()
SLIDESHOW = {"active": False, "contentIds": [], "intervalMinutes": None,
             "currentIndex": 0, "lastError": None, "stopEvent": None}


class TVTransferError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def dependency_available():
    return (importlib.util.find_spec("samsungtvws") is not None
            and importlib.util.find_spec("aiohttp") is not None)


def validate_ip(value):
    try:
        address = ipaddress.ip_address(value)
    except (TypeError, ValueError):
        raise TVTransferError("Enter the TV's local IPv4 address, such as 192.168.1.50.", 400)
    if not isinstance(address, ipaddress.IPv4Address) or not any(address in net for net in LAN_RANGES):
        raise TVTransferError("Use the TV's private home-network IPv4 address.", 400)
    return str(address)


def _ensure_state_dir():
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    STATE_DIR.chmod(0o700)


def _token_file(ip, port):
    _ensure_state_dir()
    path = STATE_DIR / f"token-{ip}-{port}.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    os.close(fd)
    path.chmod(0o600)
    return str(path)


def _read_config():
    try:
        data = json.loads(CONFIG_FILE.read_text())
        ip = validate_ip(data["ip"])
        port = int(data["port"])
        if port not in (8001, 8002):
            return None
        return {"ip": ip, "port": port}
    except (OSError, ValueError, KeyError, TypeError, TVTransferError):
        return None


def status():
    config = _read_config()
    return {"paired": config is not None, "ip": config["ip"] if config else None,
            "port": config["port"] if config else None,
            "available": dependency_available()}


def _require_library():
    try:
        from samsungtvws.async_art import SamsungTVAsyncArt
        return SamsungTVAsyncArt
    except ImportError as error:
        raise TVTransferError(
            "Direct TV transfer needs the optional TV package. Install requirements-tv.txt and restart the server.",
            424,
        ) from error


def _port_for(ip):
    for port in (8002, 8001):
        try:
            with socket.create_connection((ip, port), timeout=2):
                return port
        except OSError:
            pass
    raise TVTransferError(
        "The TV could not be reached. Turn it on and check that it and this computer are on the same network."
    )


async def _pair_async(ip, port, tv_class):
    tv = tv_class(host=ip, port=port, token_file=_token_file(ip, port),
                  timeout=12, name="Stillroom")
    try:
        await tv.start_listening()
        if not await tv.supported():
            raise TVTransferError("This device did not report Frame TV Art Mode support.", 422)
        return True
    finally:
        await tv.close()


def pair(ip):
    ip = validate_ip(ip)
    tv_class = _require_library()
    if not TRANSFER_LOCK.acquire(blocking=False):
        raise TVTransferError("A TV transfer is already in progress. Try again shortly.", 409)
    try:
        port = _port_for(ip)
        try:
            asyncio.run(asyncio.wait_for(_pair_async(ip, port, tv_class), timeout=75))
        except TVTransferError:
            raise
        except Exception as error:
            # If the TV forgot an old authorization, request a fresh token.
            token_path = Path(_token_file(ip, port))
            if token_path.stat().st_size:
                token_path.write_text("")
                try:
                    asyncio.run(asyncio.wait_for(_pair_async(ip, port, tv_class), timeout=75))
                except TVTransferError:
                    raise
                except Exception as retry_error:
                    raise TVTransferError(
                        "Pairing did not complete. Accept Stillroom on the TV, then try again."
                    ) from retry_error
            else:
                raise TVTransferError(
                    "Pairing did not complete. Accept Stillroom on the TV, then try again."
                ) from error
        _ensure_state_dir()
        fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as file:
            json.dump({"ip": ip, "port": port}, file)
        CONFIG_FILE.chmod(0o600)
        return status()
    finally:
        TRANSFER_LOCK.release()


async def _upload_async(ip, port, tv_class, image, select):
    tv = tv_class(host=ip, port=port, token_file=_token_file(ip, port),
                  timeout=12, name="Stillroom")
    try:
        await tv.start_listening()
        content_id = await tv.upload(image, file_type="JPEG", matte="none",
                                     portrait_matte="none", timeout=30)
        if not content_id:
            raise TVTransferError("The TV did not confirm the image upload. Try again while the TV is awake.")
        content_id = content_id.rsplit(".", 1)[0]
        if not select:
            return {"uploaded": True, "contentId": content_id, "displayRequested": False,
                    "message": "Added to My Photos on the TV."}
        try:
            await tv.select_image(content_id, show=True)
        except Exception:
            return {"uploaded": True, "contentId": content_id, "displayRequested": False,
                    "message": "Added to My Photos on the TV, but could not switch to it automatically."}
        return {"uploaded": True, "contentId": content_id, "displayRequested": True,
                "message": "Artwork sent to your Frame TV and requested for display."}
    finally:
        await tv.close()


def upload(image, select=True):
    config = _read_config()
    if not config:
        raise TVTransferError("Pair your Frame TV before sending artwork.", 409)
    if not image.startswith(b"\xff\xd8\xff") or not image.endswith(b"\xff\xd9"):
        raise TVTransferError("The exported artwork must be a complete JPEG image.", 415)
    tv_class = _require_library()
    if not TRANSFER_LOCK.acquire(blocking=False):
        raise TVTransferError("A TV transfer is already in progress. Try again shortly.", 409)
    try:
        try:
            with socket.create_connection((config["ip"], config["port"]), timeout=3):
                pass
        except OSError as error:
            raise TVTransferError("The paired TV is offline. Turn it on and try again.") from error
        try:
            return asyncio.run(asyncio.wait_for(
                _upload_async(config["ip"], config["port"], tv_class, image, select), timeout=90
            ))
        except TVTransferError:
            raise
        except (TimeoutError, OSError, AssertionError, ValueError) as error:
            raise TVTransferError(
                "The TV did not finish receiving the image. Check that it is awake, then try again."
            ) from error
        except Exception as error:
            raise TVTransferError(
                "Art Mode transfer failed. Re-pair the TV if its connection permission changed."
            ) from error
    finally:
        TRANSFER_LOCK.release()


async def _photos_async(ip, port, tv_class, page, page_size):
    tv = tv_class(host=ip, port=port, token_file=_token_file(ip, port),
                  timeout=12, name="Stillroom")
    try:
        await tv.start_listening()
        records = await tv.available(category="MY-C0002", timeout=12)
        records = [item for item in records if item.get("category_id") == "MY-C0002"
                   and isinstance(item.get("content_id"), str)]
        total = len(records)
        start = (page - 1) * page_size
        page_records = records[start:start + page_size]
        try:
            current = await tv.get_current()
            current_id = str(current.get("content_id", "")).rsplit(".", 1)[0]
        except Exception:
            current_id = ""
        thumbnails = {}
        if page_records:
            try:
                thumbnails = await tv.get_thumbnail_list(
                    [item["content_id"] for item in page_records])
            except Exception:
                # The list is still useful when a firmware version cannot
                # return thumbnails for one or more of its photos.
                pass
        images = {}
        for filename, data in thumbnails.items():
            image_id, _, extension = filename.rpartition(".")
            mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg",
                    "png": "image/png", "webp": "image/webp"}.get(extension.lower())
            if mime and len(data) <= 1024 * 1024:
                images[image_id] = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
        return {"items": [{"id": item["content_id"], "width": item.get("width"),
                           "height": item.get("height"), "date": item.get("image_date"),
                           "current": item["content_id"] == current_id,
                           "thumbnail": images.get(item["content_id"])}
                          for item in page_records],
                "page": page, "pageSize": page_size, "total": total,
                "hasMore": start + page_size < total}
    finally:
        await tv.close()


def list_photos(page=1):
    config = _read_config()
    if not config:
        raise TVTransferError("Pair your Frame TV to see its My Photos library.", 409)
    if type(page) is not int or not 1 <= page <= 10000:
        raise TVTransferError("Choose a valid photo page.", 400)
    tv_class = _require_library()
    if not TRANSFER_LOCK.acquire(blocking=False):
        raise TVTransferError("The TV is busy. Try refreshing the photos shortly.", 409)
    try:
        try:
            return asyncio.run(asyncio.wait_for(
                _photos_async(config["ip"], config["port"], tv_class, page, 24), timeout=75))
        except Exception as error:
            raise TVTransferError("Could not read My Photos from the TV. Make sure it is awake and try again.") from error
    finally:
        TRANSFER_LOCK.release()


async def _delete_photos_async(ip, port, tv_class, content_ids):
    tv = tv_class(host=ip, port=port, token_file=_token_file(ip, port),
                  timeout=12, name="Stillroom")
    try:
        await tv.start_listening()
        records = await tv.available(category="MY-C0002", timeout=12)
        owned_ids = {item.get("content_id") for item in records
                     if item.get("category_id") == "MY-C0002"}
        if not set(content_ids) <= owned_ids:
            raise TVTransferError("The selected photos are no longer all in My Photos. Refresh the list.", 409)
        await tv.delete_list(content_ids)
        remaining = set(content_ids)
        for _ in range(3):
            await asyncio.sleep(0.7)
            records = await tv.available(category="MY-C0002", timeout=12)
            remaining = {item.get("content_id") for item in records
                         if item.get("category_id") == "MY-C0002"} & set(content_ids)
            if not remaining:
                break
        return {"deletedIds": [item for item in content_ids if item not in remaining],
                "notDeletedIds": [item for item in content_ids if item in remaining]}
    finally:
        await tv.close()


def delete_photos(content_ids):
    if (not isinstance(content_ids, list) or not 1 <= len(content_ids) <= 100
            or len(set(item for item in content_ids if isinstance(item, str))) != len(content_ids)
            or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item)
                   for item in content_ids)):
        raise TVTransferError("Select 1–100 distinct photos from My Photos.", 400)
    config = _read_config()
    if not config:
        raise TVTransferError("Pair your Frame TV before deleting photos.", 409)
    tv_class = _require_library()
    if not TRANSFER_LOCK.acquire(blocking=False):
        raise TVTransferError("The TV is busy. Try again shortly.", 409)
    try:
        try:
            result = asyncio.run(asyncio.wait_for(
                _delete_photos_async(config["ip"], config["port"], tv_class, content_ids),
                timeout=90))
        except TVTransferError:
            raise
        except Exception as error:
            raise TVTransferError("The TV could not finish deleting those photos. Refresh the list and try again.") from error
        with SLIDESHOW_LOCK:
            affects_slideshow = bool(set(result["deletedIds"]) & set(SLIDESHOW["contentIds"]))
        if affects_slideshow:
            stop_slideshow()
        result["slideshowStopped"] = affects_slideshow
        return result
    finally:
        TRANSFER_LOCK.release()


async def _select_async(ip, port, tv_class, content_id):
    tv = tv_class(host=ip, port=port, token_file=_token_file(ip, port),
                  timeout=12, name="Stillroom")
    try:
        await tv.start_listening()
        await tv.select_image(content_id, show=True)
    finally:
        await tv.close()


def _select_image(content_id):
    config = _read_config()
    if not config:
        raise TVTransferError("Pair your Frame TV before starting a slideshow.", 409)
    tv_class = _require_library()
    if not TRANSFER_LOCK.acquire(blocking=False):
        raise TVTransferError("A TV transfer is already in progress. Try again shortly.", 409)
    try:
        try:
            asyncio.run(asyncio.wait_for(
                _select_async(config["ip"], config["port"], tv_class, content_id), timeout=45
            ))
        except Exception as error:
            raise TVTransferError("The TV could not display the next slideshow image. Check that it is awake.") from error
    finally:
        TRANSFER_LOCK.release()


def slideshow_status():
    with SLIDESHOW_LOCK:
        return {key: SLIDESHOW[key] for key in
                ("active", "intervalMinutes", "currentIndex", "lastError")} | {
                    "count": len(SLIDESHOW["contentIds"])}


def _rotation_loop(content_ids, interval_minutes, stop_event):
    index = 0
    while not stop_event.wait(interval_minutes * 60):
        index = (index + 1) % len(content_ids)
        if stop_event.is_set():
            return
        try:
            _select_image(content_ids[index])
            error = None
        except TVTransferError as exc:
            error = str(exc)
        with SLIDESHOW_LOCK:
            if SLIDESHOW["stopEvent"] is stop_event and not stop_event.is_set():
                SLIDESHOW["lastError"] = error
                if error is None:
                    SLIDESHOW["currentIndex"] = index


def start_slideshow(content_ids, interval_minutes):
    if (not isinstance(content_ids, list) or not 2 <= len(content_ids) <= 40
            or any(not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", item)
                   for item in content_ids)):
        raise TVTransferError("A slideshow needs 2–40 uploaded artworks.", 400)
    if type(interval_minutes) is not int or interval_minutes not in (1, 5, 15, 30, 60):
        raise TVTransferError("Choose a supported slideshow interval.", 400)
    with SLIDESHOW_CONTROL_LOCK:
        with SLIDESHOW_LOCK:
            if SLIDESHOW["stopEvent"]:
                SLIDESHOW["stopEvent"].set()
            SLIDESHOW.update(active=False, contentIds=[], intervalMinutes=None,
                             currentIndex=0, lastError=None, stopEvent=None)
        _select_image(content_ids[0])
        stop_event = Event()
        with SLIDESHOW_LOCK:
            SLIDESHOW.update(active=True, contentIds=content_ids[:],
                             intervalMinutes=interval_minutes, currentIndex=0,
                             lastError=None, stopEvent=stop_event)
        Thread(target=_rotation_loop, args=(content_ids[:], interval_minutes, stop_event),
               daemon=True, name="stillroom-slideshow").start()
    return slideshow_status()


def stop_slideshow():
    with SLIDESHOW_CONTROL_LOCK:
        with SLIDESHOW_LOCK:
            if SLIDESHOW["stopEvent"]:
                SLIDESHOW["stopEvent"].set()
            SLIDESHOW.update(active=False, contentIds=[], intervalMinutes=None,
                             currentIndex=0, lastError=None, stopEvent=None)
    return slideshow_status()
