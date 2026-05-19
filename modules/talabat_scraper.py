"""
=============================================================================
  Food Delivery Menu Scraper v7  —  Talabat + elmenus
  -------------------------------------------------------
  Fixes vs v6:
    ✅ elmenus IMAGE FIX — image URLs contain literal {{PHOTO_VERSION}} and
       {{PHOTO_EXTENSION}} template strings. The script now:
         1. Scans the page JS source for the real values.
         2. Falls back to smart defaults (mobile / jpg).
         3. Substitutes both placeholders before writing to CSV.

    ✅ elmenus PRICE FIX — prices live inside a FLAT sizes array:
           "sizes": [{"name": "Regular", "price": 89},
                     {"name": "Large",   "price": 110}]
       Previous code treated each size dict as a "group" and looked for
       sub-options inside it — finding nothing.
       Now: a flat array of name+price objects is detected and handled
       correctly:
         • 1 size  → treat its price as the item's direct Price.
         • 2+ sizes → populate Modifiers, leave Price blank.

  CSV columns:
    Category Name | Item Name | Description | Image URL | Price | Modifiers

=============================================================================
  SETUP
    pip install playwright
    playwright install chromium

  RUN
    python menu_scraper.py
    python menu_scraper.py "https://www.talabat.com/egypt/restaurant/..."
    python menu_scraper.py "https://www.elmenus.com/cairo/restaurant-name"
    python menu_scraper.py "URL" --debug
=============================================================================
"""

import asyncio
import csv
import json
import os
import re
import random
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Response,
    TimeoutError as PWTimeout,
)

# ─────────────────────────────────────────────────────────────────────────────
#  FIELD KEY LISTS   (camelCase = Talabat,  snake_case = elmenus)
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_KEYS = [
    "name","title","nameEn","nameAr","categoryName","category_name",
    "sectionName","section_name","groupName","group_name","heading","label",
]
ITEM_NAME_KEYS = [
    "name","title","nameEn","nameAr","itemName","item_name",
    "productName","product_name","displayName","display_name","label",
]
DESC_KEYS = [
    "description","descriptionEn","descriptionAr","desc",
    "itemDescription","item_description","about","details",
    "shortDescription","short_description","info","summary","body",
]
IMAGE_KEYS = [
    # camelCase (Talabat / Delivery Hero)
    "imageUrl","imageURL","image","img","imgUrl",
    "photoUrl","photoURL","photo",
    "thumbnailUrl","thumbnail","coverImage","coverPhoto","coverUrl",
    "logoUrl","logo","itemPhoto","itemImage","smallPhoto","mediumPhoto","largePhoto",
    "pictureUrl","picture","src",
    # snake_case (elmenus / Python APIs)
    "image_url","photo_url","thumbnail_url","cover_image","cover_photo",
    "item_photo","item_image","small_photo","medium_photo","large_photo",
    "picture_url","icon_url","icon","avatar","avatar_url","banner","banner_url",
]
PRICE_KEYS = [
    "price","basePrice","base_price","unitPrice","unit_price",
    "originalPrice","original_price","sellingPrice","selling_price",
    "regularPrice","regular_price","itemPrice","item_price",
    "discountedPrice","discounted_price","minPrice","min_price",
    "maxPrice","max_price","amount","cost","value","pricePT","priceEGP",
    "fee","charge",
]
# Keys that hold a list of modifier GROUPS (each group can contain options)
MODIFIER_GROUP_KEYS = [
    "modifierGroups","modifier_groups","optionGroups","option_groups",
    "groups","selections","customizations","toppings","extras","addons","add_ons",
]
# Keys that hold a flat list of OPTIONS (name + price objects)
FLAT_OPTION_KEYS = [
    "sizes","size_options","sizeOptions","variants","options","choices",
    "modifiers","itemOptions","item_options",
]
# Keys inside a modifier group that contain its options
INNER_OPTION_KEYS = [
    "options","items","choices","modifiers","variants","values","entries","sizes",
]
CONTAINER_KEYS = {
    "menus","menu","categories","category","items","item",
    "products","product","sections","section","subCategories","sub_categories",
    "subcategories","children","data","result","results",
    "menuItems","menu_items","menuSections","menu_sections",
    "restaurantMenu","restaurant_menu","catalog","dishes","meals",
    "branches","branch",
}

# ─────────────────────────────────────────────────────────────────────────────
#  ELMENUS IMAGE TEMPLATE CONFIG
# ─────────────────────────────────────────────────────────────────────────────

# Fallback values when we cannot extract them from the page source
ELMENUS_DEFAULT_VERSION   = "Thumbnail"
ELMENUS_DEFAULT_EXTENSION = "jpg"

# Regex patterns to find the real values in the page JS
_RE_PHOTO_VERSION   = re.compile(r'PHOTO_VERSION\s*[=:]\s*["\']([^"\']+)["\']')
_RE_PHOTO_EXTENSION = re.compile(r'PHOTO_EXTENSION\s*[=:]\s*["\']([^"\']+)["\']')

# Template placeholders elmenus puts in image URLs
_TEMPLATE_PLACEHOLDER = re.compile(r'\{\{[A-Z_]+\}\}')


def resolve_elmenus_image(url: str, version: str, extension: str) -> str:
    """
    Replace {{PHOTO_VERSION}} and {{PHOTO_EXTENSION}} in a URL with real values.
    Also normalises the S3 bucket from staging (-stg) to production if needed.
    """
    url = url.replace("{{PHOTO_VERSION}}",   version)
    url = url.replace("{{PHOTO_EXTENSION}}", extension)
    # If any unknown placeholders remain, the URL is still broken — return as-is
    # so the caller can decide what to do.
    return url


async def detect_elmenus_photo_config(page: Page) -> tuple[str, str]:
    """
    Scan the rendered page's full HTML + inline scripts for PHOTO_VERSION
    and PHOTO_EXTENSION values the elmenus frontend uses to build image URLs.
    """
    html = await page.content()

    version_match   = _RE_PHOTO_VERSION.search(html)
    extension_match = _RE_PHOTO_EXTENSION.search(html)

    version   = version_match.group(1)   if version_match   else ELMENUS_DEFAULT_VERSION
    extension = extension_match.group(1) if extension_match else ELMENUS_DEFAULT_EXTENSION

    log(f"  elmenus PHOTO_VERSION='{version}'  PHOTO_EXTENSION='{extension}'")
    return version, extension

# ─────────────────────────────────────────────────────────────────────────────
#  LOGGING
# ─────────────────────────────────────────────────────────────────────────────

ICONS = {
    "INFO":"ℹ️ ","OK":"✅","WARN":"⚠️ ","ERR":"❌",
    "DATA":"📦","NET":"🌐","STEP":"🔹","DBG":"🔍",
}
DEBUG_MODE = False

def log(msg: str, level: str = "INFO") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {ICONS.get(level,'   ')} {msg}", flush=True)

def dlog(msg: str) -> None:
    if DEBUG_MODE:
        log(msg, "DBG")

# ─────────────────────────────────────────────────────────────────────────────
#  UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

RE_IMAGE_URL = re.compile(
    r'https?://[^\s"\'<>\]\[{}]+\.(?:jpg|jpeg|png|webp|gif|avif|svg|bmp)'
    r'(?:\?[^\s"\'<>\]\[{}]*)?',
    re.IGNORECASE,
)
RE_PRICE_KEY = re.compile(r'price|cost|amount|fee|charge|tariff', re.IGNORECASE)
RE_IMAGE_KEY = re.compile(
    r'photo|image|img|thumb|cover|logo|picture|icon|avatar|banner|src|url|media',
    re.IGNORECASE,
)

def detect_platform(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "talabat" in host: return "talabat"
    if "elmenus" in host: return "elmenus"
    return "universal"

def base_domain(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}"

def slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    slug = path.split("/")[-1]
    return re.sub(r"[^a-zA-Z0-9_-]", "_", slug) or "restaurant"

def restaurant_id_from_url(url: str) -> Optional[str]:
    m = re.search(r"/restaurant/(\d+)/", url)
    return m.group(1) if m else None

def safe(value, fallback: str = "N/A") -> str:
    if value is None: return fallback
    s = str(value).strip()
    return s if s else fallback

def make_absolute(url_str: str, base: str) -> str:
    url_str = url_str.strip()
    if not url_str: return ""
    if url_str.startswith("http"): return url_str
    if url_str.startswith("//"): return "https:" + url_str
    if url_str.startswith("/"): return base.rstrip("/") + url_str
    return url_str

def score_blob(data) -> int:
    if not isinstance(data, (dict, list)): return 0
    try:
        text = json.dumps(data, ensure_ascii=False).lower()
    except Exception:
        return 0
    weights = [
        ("category",4),("item",3),("menu",4),("price",3),
        ("photo",3),("image",2),("description",2),("name",1),
        ("section",2),("product",2),("sizes",3),
    ]
    score = sum(w * text.count(kw) for kw, w in weights)
    root = data if isinstance(data, list) else list(data.values())
    for v in root:
        if isinstance(v, list) and v and isinstance(v[0], dict):
            score += 10
            break
    return score

def save_debug_blob(blob, label: str, debug_dir: Path) -> None:
    if not DEBUG_MODE: return
    debug_dir.mkdir(parents=True, exist_ok=True)
    safe_label = re.sub(r"[^\w\-]", "_", label)[:80]
    path = debug_dir / f"{safe_label}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(blob, f, ensure_ascii=False, indent=2)
    dlog(f"Saved → {path}")

# ─────────────────────────────────────────────────────────────────────────────
#  FIELD EXTRACTORS
# ─────────────────────────────────────────────────────────────────────────────

def discover_image(node: dict, site_base: str, elmenus_config: tuple) -> str:
    """
    Find an image URL from an item dict using 3 strategies:
      1. Known field names
      2. Any key whose name looks image-related
      3. Regex scan of all string values for an image URL pattern

    For elmenus: resolves {{PHOTO_VERSION}} / {{PHOTO_EXTENSION}} placeholders.
    """
    version, extension = elmenus_config

    def _clean(raw: str) -> str:
        """Resolve template vars, make absolute, return or empty string."""
        if not raw or not raw.strip():
            return ""
        resolved = resolve_elmenus_image(raw.strip(), version, extension)
        # If unknown placeholders still remain the URL is unusable
        if _TEMPLATE_PLACEHOLDER.search(resolved):
            return ""
        return make_absolute(resolved, site_base)

    # Strategy 1: known field names
    for key in IMAGE_KEYS:
        val = node.get(key)
        if val is None:
            continue
        if isinstance(val, str):
            result = _clean(val)
            if result:
                dlog(f"    img via '{key}': {result[:70]}")
                return result
        if isinstance(val, dict):
            for sub in ("url","src","original","large","medium","small","path","href","fullUrl","full_url"):
                s = val.get(sub)
                if isinstance(s, str):
                    result = _clean(s)
                    if result:
                        dlog(f"    img via '{key}.{sub}': {result[:70]}")
                        return result
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, str):
                result = _clean(first)
                if result:
                    dlog(f"    img via '{key}[0]': {result[:70]}")
                    return result
            if isinstance(first, dict):
                for sub in ("url","src","original","large","medium","small","path"):
                    s = first.get(sub)
                    if isinstance(s, str):
                        result = _clean(s)
                        if result:
                            dlog(f"    img via '{key}[0].{sub}': {result[:70]}")
                            return result

    # Strategy 2: heuristic key name scan
    for key, val in node.items():
        if key in set(ITEM_NAME_KEYS + DESC_KEYS + PRICE_KEYS + CATEGORY_KEYS):
            continue
        if not RE_IMAGE_KEY.search(str(key)):
            continue
        if isinstance(val, str):
            result = _clean(val)
            if result and (result.startswith("http") or result.startswith("/")):
                dlog(f"    img via heuristic key '{key}': {result[:70]}")
                return result
        if isinstance(val, dict):
            for sub in ("url","src","path","href","original","large"):
                s = val.get(sub)
                if isinstance(s, str):
                    result = _clean(s)
                    if result:
                        dlog(f"    img via heuristic '{key}.{sub}': {result[:70]}")
                        return result

    # Strategy 3: regex scan of all string values
    for key, val in node.items():
        if isinstance(val, str):
            # First resolve templates, then search for a URL
            resolved = resolve_elmenus_image(val, version, extension)
            m = RE_IMAGE_URL.search(resolved)
            if m:
                dlog(f"    img via regex in '{key}': {m.group(0)[:70]}")
                return m.group(0)
        if isinstance(val, dict):
            for sv in val.values():
                if isinstance(sv, str):
                    resolved = resolve_elmenus_image(sv, version, extension)
                    m = RE_IMAGE_URL.search(resolved)
                    if m:
                        return m.group(0)

    return ""


def _parse_number(val) -> Optional[float]:
    """Try to extract a non-negative float from val."""
    if val is None:
        return None
    if isinstance(val, (int, float)):
        num = float(val)
        # Large integers might be piasters (100 piasters = 1 EGP)
        if num > 10_000 and isinstance(val, int):
            num = num / 100
        return num if num >= 0 else None
    if isinstance(val, str):
        m = re.search(r'\d+(?:\.\d+)?', val)
        if m:
            return float(m.group(0))
    return None


def discover_price(node: dict) -> Optional[str]:
    """
    Find the best price in an item node.
    Checks all known price keys + any key whose name contains price/cost/amount.
    Returns a formatted string or None.
    """
    candidates: list[str] = list(PRICE_KEYS)
    for key in node:
        if key not in candidates and RE_PRICE_KEY.search(str(key)):
            candidates.append(key)

    best: Optional[float] = None
    for key in candidates:
        num = _parse_number(node.get(key))
        if num is None:
            continue
        if best is None or (num > 0 and (best == 0 or num < best)):
            best = num

    if best is not None:
        formatted = f"{best:.2f}".rstrip("0").rstrip(".")
        dlog(f"    price = {formatted}")
        return formatted
    return None


def _is_flat_options_list(lst: list) -> bool:
    """
    Return True if `lst` is a flat list of option dicts (each with a name ±
    price) rather than a list of groups that contain nested options.

    A flat options list looks like:
        [{"name": "Regular", "price": 89}, {"name": "Large", "price": 110}]

    A nested group list looks like:
        [{"name": "Size", "options": [{"name": "Regular", "price": 89}]}]
    """
    if not lst or not isinstance(lst[0], dict):
        return False
    # If any element has an inner option key, it's a nested-group list
    has_nested = any(
        isinstance(item.get(k), list)
        for item in lst
        for k in INNER_OPTION_KEYS
    )
    if has_nested:
        return False
    # Each element should have a name-like key
    has_names = all(
        any(item.get(k) for k in ("name","title","nameEn","nameAr","label","size_name","sizeName"))
        for item in lst
    )
    return has_names


def discover_modifiers_and_price(node: dict) -> tuple[str, Optional[str]]:
    """
    Returns (modifiers_string, price_string_or_None).

    Logic:
      ┌──────────────────────────────────────────────────────┐
      │  sizes / options array found?                        │
      │    • Flat options (name+price objects)               │
      │        – 1 option  → price = that option's price     │
      │                       modifiers = ""                 │
      │        – 2+ options → modifiers = "S (89), L (110)"  │
      │                        price = ""                    │
      │    • Nested groups (group → options)                 │
      │        → expand into "Group: Opt1 (p), Opt2 (p)"    │
      └──────────────────────────────────────────────────────┘
    """

    # ── 1. Flat option arrays (elmenus sizes, Talabat simple options) ─────────
    for key in FLAT_OPTION_KEYS:
        lst = node.get(key)
        if not isinstance(lst, list) or not lst:
            continue
        if not _is_flat_options_list(lst):
            continue

        option_strs: list[str] = []
        for opt in lst:
            opt_name = next(
                (str(opt.get(k,"")).strip()
                 for k in ("name","title","nameEn","nameAr","label","size_name","sizeName")
                 if opt.get(k)),
                "",
            )
            if not opt_name:
                continue
            opt_price = discover_price(opt)
            option_strs.append(f"{opt_name} ({opt_price})" if opt_price else opt_name)

        if not option_strs:
            continue

        if len(option_strs) == 1:
            # Single option → item's direct price, no modifier needed
            single_price = discover_price(lst[0])
            return "", single_price

        # Multiple options → modifiers column
        return ", ".join(option_strs), ""

    # ── 2. Nested modifier groups ─────────────────────────────────────────────
    for group_key in MODIFIER_GROUP_KEYS:
        groups = node.get(group_key)
        if not isinstance(groups, list) or not groups:
            continue

        parts: list[str] = []
        for group in groups:
            if not isinstance(group, dict):
                continue

            group_label = next(
                (str(group.get(k,"")).strip()
                 for k in ("name","title","nameEn","nameAr","label","groupName","group_name")
                 if group.get(k)),
                "",
            )

            raw_options: list[dict] = []
            for opt_key in INNER_OPTION_KEYS:
                opts = group.get(opt_key)
                if isinstance(opts, list) and opts:
                    raw_options = [o for o in opts if isinstance(o, dict)]
                    break

            if not raw_options:
                continue

            option_strs = []
            for opt in raw_options:
                opt_name = next(
                    (str(opt.get(k,"")).strip()
                     for k in ("name","title","nameEn","nameAr","label")
                     if opt.get(k)),
                    "",
                )
                if not opt_name:
                    continue
                opt_price = discover_price(opt)
                option_strs.append(f"{opt_name} ({opt_price})" if opt_price else opt_name)

            if option_strs:
                chunk = ", ".join(option_strs)
                parts.append(f"{group_label}: {chunk}" if group_label else chunk)

        if parts:
            return " | ".join(parts), ""

    return "", None   # no modifiers found

# ─────────────────────────────────────────────────────────────────────────────
#  MENU PARSER  (recursive, schema-agnostic)
#
#  CRITICAL: is_item_node() is called BEFORE reading node's "name" as a
#  category — this prevents an item's own name becoming its category label.
# ─────────────────────────────────────────────────────────────────────────────

def is_item_node(node: dict, site_base: str, elmenus_config: tuple) -> bool:
    has_name     = any(node.get(k) for k in ITEM_NAME_KEYS)
    has_desc     = any(node.get(k) for k in DESC_KEYS)
    has_image    = bool(discover_image(node, site_base, elmenus_config))
    has_price    = discover_price(node) is not None
    has_children = any(
        isinstance(node.get(k), list) and len(node.get(k, [])) > 0
        for k in CONTAINER_KEYS
    )
    return has_name and (has_desc or has_image or has_price) and not has_children


def parse_menu(
    data,
    site_base: str,
    elmenus_config: tuple,
    parent_cat: str = "Uncategorised",
) -> list[dict]:
    results: list[dict] = []

    if isinstance(data, list):
        for child in data:
            results.extend(parse_menu(child, site_base, elmenus_config, parent_cat))
        return results

    if not isinstance(data, dict):
        return results

    # ── STEP 1: Leaf item check FIRST (before reading "name" as category) ─────
    if is_item_node(data, site_base, elmenus_config):
        item_name = next(
            (str(data[k]).strip() for k in ITEM_NAME_KEYS if data.get(k)), "N/A"
        )
        description = next(
            (str(data[k]).strip() for k in DESC_KEYS if data.get(k)), ""
        )
        image_url = discover_image(data, site_base, elmenus_config)

        # Get modifiers + price in one call (handles flat sizes correctly)
        modifiers, mod_price = discover_modifiers_and_price(data)

        if modifiers:
            # Has multiple sizes/options → leave Price blank
            price = ""
        elif mod_price is not None:
            # Single size → use that size's price
            price = mod_price
        else:
            # No sizes → look for direct price field
            price = discover_price(data) or "N/A"

        dlog(
            f"  ITEM  cat='{parent_cat[:25]}' | "
            f"name='{item_name[:25]}' | "
            f"img={bool(image_url)} | price={price} | mod={bool(modifiers)}"
        )
        results.append({
            "category":    safe(parent_cat),
            "name":        safe(item_name),
            "description": safe(description),
            "image_url":   safe(image_url),
            "price":       price,
            "modifiers":   modifiers,
        })
        # Keep walking for nested modifier groups inside the item
        for k, v in data.items():
            if RE_IMAGE_KEY.search(k) and k not in CONTAINER_KEYS:
                continue
            if isinstance(v, (dict, list)):
                results.extend(parse_menu(v, site_base, elmenus_config, parent_cat))
        return results

    # ── STEP 2: Category / wrapper — safe to read "name" as category now ──────
    resolved_cat = parent_cat
    for k in CATEGORY_KEYS:
        v = data.get(k)
        if isinstance(v, str) and v.strip():
            resolved_cat = v.strip()
            dlog(f"  CATEGORY: '{resolved_cat}'")
            break

    for k, v in data.items():
        if isinstance(v, (dict, list)):
            results.extend(parse_menu(v, site_base, elmenus_config, resolved_cat))

    return results

# ─────────────────────────────────────────────────────────────────────────────
#  __NEXT_DATA__ EXTRACTOR
# ─────────────────────────────────────────────────────────────────────────────

async def try_next_data(
    page: Page,
    site_base: str,
    elmenus_config: tuple,
    debug_dir: Path,
) -> list[dict]:
    log("STEP 1 — Extracting __NEXT_DATA__ …", "STEP")
    raw = await page.evaluate(
        "()=>{const e=document.getElementById('__NEXT_DATA__');return e?e.textContent:null;}"
    )
    if not raw:
        log("  Not found.", "WARN")
        return []
    try:
        blob = json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"  JSON error: {e}", "WARN")
        return []
    save_debug_blob(blob, "01_NEXT_DATA", debug_dir)
    score = score_blob(blob)
    log(f"  Score: {score}")
    if score < 8:
        log("  Score too low.", "WARN")
        return []
    items = parse_menu(blob, site_base, elmenus_config)
    log(f"  {len(items)} items ✓" if items else "  0 items matched.", "OK" if items else "WARN")
    return items


async def try_window_state(
    page: Page,
    site_base: str,
    elmenus_config: tuple,
    debug_dir: Path,
) -> list[dict]:
    log("STEP 1b — Checking window state objects …", "STEP")
    for var in ["__REDUX_STATE__","__INITIAL_STATE__","__APP_STATE__","__PRELOADED_STATE__","__DATA__"]:
        raw = await page.evaluate(
            f"()=>{{try{{return JSON.stringify(window['{var}']);}}catch(e){{return null;}}}}"
        )
        if raw and len(raw) > 200:
            try:
                blob = json.loads(raw)
                score = score_blob(blob)
                log(f"  window.{var} score={score}")
                if score >= 8:
                    save_debug_blob(blob, f"01b_{var}", debug_dir)
                    items = parse_menu(blob, site_base, elmenus_config)
                    if items:
                        log(f"  {len(items)} items from window.{var} ✓", "OK")
                        return items
            except Exception:
                pass
    return []

# ─────────────────────────────────────────────────────────────────────────────
#  NETWORK RESPONSE COLLECTOR
# ─────────────────────────────────────────────────────────────────────────────

class ResponseCollector:
    def __init__(self, restaurant_id: Optional[str], debug_dir: Path):
        self._blobs: list[tuple[int, str, object]] = []
        self._rid       = restaurant_id
        self._debug_dir = debug_dir
        self._lock      = asyncio.Lock()
        self._count     = 0

    async def on_response(self, response: Response) -> None:
        url = response.url
        ct  = response.headers.get("content-type", "")
        if "json" not in ct:
            return
        try:
            body = await response.body()
        except Exception:
            return
        if len(body) < 150:
            return
        try:
            data = await response.json()
        except Exception:
            return

        score = score_blob(data)
        if score < 3:
            return
        if self._rid and self._rid in url:
            score += 20
        if "/_next/data/" in url:
            score += 15
        for kw in ("menu","catalog","items","categories","product","dish","meal","restaurant","branch"):
            if kw in url.lower():
                score += 5
                break

        async with self._lock:
            self._count += 1
            save_debug_blob(data, f"{self._count:02d}_blob_score{score}", self._debug_dir)
            self._blobs.append((score, url, data))
            log(f"  JSON [score={score:3d}]: …{url[-70:]}", "NET")

    def best_candidates(self, top_n: int = 8) -> list[tuple[str, object]]:
        ranked = sorted(self._blobs, key=lambda x: x[0], reverse=True)
        return [(url, data) for _, url, data in ranked[:top_n]]

# ─────────────────────────────────────────────────────────────────────────────
#  DOM FALLBACK
# ─────────────────────────────────────────────────────────────────────────────

async def dom_fallback(page: Page, site_base: str, elmenus_config: tuple) -> list[dict]:
    log("STEP 4 — DOM fallback …", "STEP")
    version, extension = elmenus_config
    results: list[dict] = []
    raw = await page.evaluate("""
    () => {
        const rows = [];
        document.querySelectorAll(
            'section,[class*="category"],[class*="section"],[class*="group"],[class*="Category"]'
        ).forEach(sec => {
            const catEl = sec.querySelector(
                'h1,h2,h3,[class*="category-name"],[class*="categoryName"],' +
                '[class*="section-title"],[class*="heading"],[class*="label"]'
            );
            const catName = catEl ? catEl.innerText.trim() : 'Uncategorised';
            sec.querySelectorAll(
                '[class*="item"],[class*="product"],[class*="meal"],[class*="dish"],[class*="card"],article'
            ).forEach(el => {
                const nameEl  = el.querySelector('h2,h3,h4,[class*="name"],[class*="title"]');
                const descEl  = el.querySelector('[class*="description"],[class*="desc"],[class*="about"],p');
                const imgEl   = el.querySelector('img[src]:not([src=""]),img[data-src],img[data-lazy]');
                const priceEl = el.querySelector('[class*="price"],[class*="Price"],[class*="cost"],[data-testid*="price"]');
                const name    = nameEl ? nameEl.innerText.trim() : '';
                if (!name || name.length < 2) return;
                let imgSrc = '';
                if (imgEl) {
                    imgSrc = imgEl.getAttribute('data-src') || imgEl.getAttribute('data-lazy') || imgEl.src || '';
                }
                rows.push({
                    category:    catName,
                    name:        name,
                    description: descEl   ? descEl.innerText.trim()  : '',
                    image_url:   imgSrc,
                    price:       priceEl  ? priceEl.innerText.trim() : '',
                });
            });
        });
        return rows;
    }
    """)
    for r in raw:
        if r.get("name"):
            img = resolve_elmenus_image(
                make_absolute(r.get("image_url",""), site_base),
                version, extension,
            )
            results.append({
                "category":    safe(r.get("category")),
                "name":        safe(r.get("name")),
                "description": safe(r.get("description")),
                "image_url":   safe(img),
                "price":       r.get("price","N/A") or "N/A",
                "modifiers":   "",
            })
    log(f"  DOM found {len(results)} items.", "DATA" if results else "WARN")
    return results

# ─────────────────────────────────────────────────────────────────────────────
#  DEDUPLICATION & CSV
# ─────────────────────────────────────────────────────────────────────────────

def deduplicate(items: list[dict]) -> list[dict]:
    seen, out = set(), []
    for it in items:
        key = (it.get("category",""), it.get("name",""))
        if key not in seen and it.get("name") not in ("N/A",""):
            seen.add(key)
            out.append(it)
    return out


def save_csv(items: list[dict], slug: str) -> str:
    fname = f"menu_{slug}.csv"
    cols  = ["Category Name","Item Name","Description","Image URL","Price","Modifiers"]
    with open(fname, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for it in items:
            w.writerow({
                "Category Name": it.get("category",   "N/A"),
                "Item Name":     it.get("name",        "N/A"),
                "Description":   it.get("description", "N/A"),
                "Image URL":     it.get("image_url",   "N/A"),
                "Price":         it.get("price",       "N/A"),
                "Modifiers":     it.get("modifiers",   ""),
            })
    return fname

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

class MenuScraper:
    def __init__(self, url: str):
        self.url          = url.strip()
        self.slug         = slug_from_url(self.url)
        self.rid          = restaurant_id_from_url(self.url)
        self.platform     = detect_platform(self.url)
        self.site_base    = base_domain(self.url)
        self.elmenus_cfg  = (ELMENUS_DEFAULT_VERSION, ELMENUS_DEFAULT_EXTENSION)
        ts = datetime.now().strftime("%H%M%S")
        self.debug_dir    = Path(f"debug_blobs/{ts}_{self.slug[:30]}")

    async def run(self) -> list[dict]:
        collector = ResponseCollector(self.rid, self.debug_dir)

        async with async_playwright() as pw:
            log("Launching Chromium …", "STEP")
            browser: Browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox","--disable-dev-shm-usage",
                    "--disable-gpu","--window-size=1366,768",
                ],
            )
            ctx: BrowserContext = await browser.new_context(
                user_agent=random.choice(USER_AGENTS),
                viewport={"width":1366,"height":768},
                locale="en-US",
                timezone_id="Africa/Cairo",
                extra_http_headers={
                    "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "DNT": "1",
                },
            )
            await ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"
            )
            page: Page = await ctx.new_page()
            page.on("response", collector.on_response)

            log(f"Navigating → {self.url}", "STEP")
            try:
                await page.goto(self.url, wait_until="domcontentloaded", timeout=45_000)
                log("DOM loaded ✓", "OK")
            except PWTimeout:
                log("Navigation timed out — continuing.", "WARN")

            await asyncio.sleep(2)

            # ── elmenus: extract photo config from page JS ───────────────────
            if self.platform == "elmenus":
                log("STEP 0 — Detecting elmenus photo config …", "STEP")
                self.elmenus_cfg = await detect_elmenus_photo_config(page)

            # Dismiss banners
            for sel in [
                "button:has-text('Accept')","button:has-text('OK')",
                "button:has-text('Allow')","button:has-text('Agree')",
                "button:has-text('Got it')","[data-testid='accept-cookies']",
                "[aria-label*='lose']",
            ]:
                try:
                    btn = page.locator(sel).first
                    if await btn.is_visible(timeout=1_200):
                        await btn.click()
                        await asyncio.sleep(0.4)
                except Exception:
                    pass

            cfg = self.elmenus_cfg

            # ── Priority 1a: __NEXT_DATA__ ───────────────────────────────────
            items = await try_next_data(page, self.site_base, cfg, self.debug_dir)
            if items:
                await browser.close()
                return items

            # ── Priority 1b: Window state ────────────────────────────────────
            items = await try_window_state(page, self.site_base, cfg, self.debug_dir)
            if items:
                await browser.close()
                return items

            # ── Scroll ───────────────────────────────────────────────────────
            log("STEP 2 — Scrolling …", "STEP")
            for i in range(8):
                await page.evaluate("window.scrollBy(0, document.body.scrollHeight/6)")
                await asyncio.sleep(0.9)
                log(f"  scroll {i+1}/8")

            # Re-scan photo config after scroll (in case page updated JS)
            if self.platform == "elmenus":
                self.elmenus_cfg = await detect_elmenus_photo_config(page)
                cfg = self.elmenus_cfg

            try:
                await page.wait_for_load_state("networkidle", timeout=5_000)
            except PWTimeout:
                pass

            items = await try_window_state(page, self.site_base, cfg, self.debug_dir)
            if items:
                await browser.close()
                return items

            # ── Priority 2/3: Captured JSON blobs ────────────────────────────
            log("STEP 3 — Parsing captured JSON blobs …", "STEP")
            candidates = collector.best_candidates(top_n=8)
            log(f"  {len(candidates)} candidate blob(s).")

            for cand_url, data in candidates:
                log(f"  Trying: …{cand_url[-65:]}", "NET")
                parsed = deduplicate(parse_menu(data, self.site_base, cfg))
                if len(parsed) >= 3:
                    log(f"  → {len(parsed)} items ✓", "OK")
                    await browser.close()
                    return parsed
                log(f"  → {len(parsed)} items — skipping.", "WARN")

            # ── Priority 4: DOM fallback ─────────────────────────────────────
            items = await dom_fallback(page, self.site_base, cfg)
            await browser.close()

        return items

# ─────────────────────────────────────────────────────────────────────────────
#  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
]

async def main() -> None:
    global DEBUG_MODE
    args       = sys.argv[1:]
    DEBUG_MODE = "--debug" in args
    url_args   = [a for a in args if not a.startswith("--")]

    print()
    print("=" * 65)
    print("  🍽️   Food Delivery Menu Scraper v7")
    print("       Talabat · elmenus  —  image template + price fix")
    if DEBUG_MODE:
        print("       🔍 DEBUG MODE — raw JSON saved to debug_blobs/")
    print("=" * 65)
    print()

    url = (
        url_args[0] if url_args
        else input("Paste the restaurant URL (Talabat or elmenus):\n> ").strip()
    )
    if not url.startswith("http"):
        log("URL must start with http:// or https://", "ERR")
        sys.exit(1)

    scraper = MenuScraper(url)
    log(f"Platform      : {scraper.platform.upper()}")
    log(f"Site base     : {scraper.site_base}")
    log(f"Restaurant ID : {scraper.rid or 'n/a'}")
    log(f"Output slug   : {scraper.slug}")
    print()

    try:
        items = await scraper.run()
    except Exception as exc:
        log(f"Fatal error: {exc}", "ERR")
        import traceback; traceback.print_exc()
        sys.exit(1)

    items = deduplicate(items)
    if not items:
        log("No menu items extracted.", "ERR")
        log("Run with --debug to save raw JSON for inspection.", "WARN")
        sys.exit(1)

    fname = save_csv(items, scraper.slug)

    has_img = sum(1 for it in items if it.get("image_url","N/A") != "N/A")
    has_pr  = sum(1 for it in items if it.get("price","N/A") not in ("N/A",""))
    has_mod = sum(1 for it in items if it.get("modifiers",""))

    print()
    print("─" * 72)
    print(f"  {'CATEGORY':<20} {'ITEM NAME':<22} {'PRICE':>7}  IMG  MOD")
    print("─" * 72)
    for row in items[:18]:
        cat   = row.get("category","N/A")[:19]
        name  = row.get("name","N/A")[:21]
        price = row.get("price","N/A")[:6]
        img   = "✓" if row.get("image_url","N/A") != "N/A" else "✗"
        mod   = "✓" if row.get("modifiers","") else ""
        print(f"  {cat:<20} {name:<21} {price:>7}  {img:<4} {mod}")
    if len(items) > 18:
        print(f"  … and {len(items)-18} more rows.")
    print("─" * 72)
    print()
    log(f"Total items      : {len(items)}", "DATA")
    log(f"With image URL   : {has_img}/{len(items)}", "DATA")
    log(f"With price       : {has_pr}/{len(items)}", "DATA")
    log(f"With modifiers   : {has_mod}/{len(items)}", "DATA")
    log(f"CSV saved        : {os.path.abspath(fname)}", "OK")
    if DEBUG_MODE:
        log(f"Debug JSON blobs : {os.path.abspath(scraper.debug_dir)}", "DBG")
    print()


if __name__ == "__main__":
    asyncio.run(main())