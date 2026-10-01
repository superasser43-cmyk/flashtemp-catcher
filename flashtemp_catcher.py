#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlashTemp Catcher  (links + codes, speed-optimized)
---------------------------------------------------
1) Opens https://flashtemp.email and clicks "Generate" exactly once.
2) Locks the generated email and copies it to the clipboard.
3) Read-only mode afterwards: no reload, no goto, no second Generate.
4) Watches the inbox. As soon as a NEW row appears it clicks it and reads the message:
     - verification / activation LINK  -> copies the link
     - numeric CODE (OTP)              -> copies the code
   then prints it and closes everything immediately.

Works with ANY sender (Claude, Facebook, Instagram, Google, X, TikTok, Discord, ...):
detection is based on the wording around a code and on the button text of links,
never on who sent the message.

Speed tricks:
  * images / media / fonts / ads are blocked (much faster page load)
  * every DOM scan is ONE browser round-trip (JS evaluate)
  * codes in the inbox preview/subject are caught BEFORE even opening the message
  * no fixed sleeps, tight polling, browser closes before any notification work

Runs HEADLESS by default: no browser window at all, only this terminal is visible.

Usage:
    python flashtemp_catcher.py            # hidden browser (default)
    python flashtemp_catcher.py --show     # show the browser window (debugging)
    python flashtemp_catcher.py --debug    # extra detection logs
    python flashtemp_catcher.py --no-sound # silent mode

Install:
    pip install playwright pyperclip
    playwright install chromium
    # Linux only: sudo apt install xclip
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from typing import Iterable, Optional
from urllib.parse import urlparse

import pyperclip
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout

# ================================ Settings ================================ #
APP_NAME = "FlashTemp Catcher"
SITE_URL = "https://flashtemp.email"
SITE_DOMAIN = "flashtemp.email"

POLL_INTERVAL_SEC = 0.25           # inbox polling speed (DOM only, no network cost)
GENERATE_WAIT_TIMEOUT_SEC = 25     # max wait for the Generate button
EMAIL_WAIT_TIMEOUT_SEC = 60        # max wait for the email after clicking Generate
MESSAGE_OPEN_WAIT_SEC = 8          # max wait for message content after clicking a row
FALLBACK_GRACE_SEC = 8             # accept a keyword-less link only after this delay
MAX_ROW_RETRIES = 3                # retries for a row whose click failed
INBOX_MAX_WAIT_SEC = 0             # 0 = wait forever
HEADLESS = True                    # True = no browser window at all (terminal only)
DEBUG = False                      # True = print extra detection details

# Play a short single 'ding' when the email is copied and again when the link/code is copied.
PLAY_SOUND = True

# If one message contains BOTH an activation link and a code:
#   False -> copy the link,  True -> copy the code
PREFER_CODE_OVER_LINK = False

# Block images/media/fonts/ads for a much faster load. Set False if the site ever
# misbehaves (e.g. the Generate button is an image-only icon).
BLOCK_HEAVY_RESOURCES = True

# Some sites tie "Refresh" to generating a NEW email, so it is disabled by default.
CLICK_INBOX_REFRESH = False

BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
BLOCKED_URL_PARTS = (
    "googlesyndication", "doubleclick", "google-analytics", "googletagmanager",
    "googletagservices", "adservice", "adsbygoogle", "hotjar", "clarity.ms",
    "facebook.net", "taboola", "outbrain", "popads", "propellerads", "adsterra",
    "scorecardresearch", "amazon-adsystem", "adnxs", "criteo", "onesignal",
)
LAUNCH_ARGS = [
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-default-apps",
    "--disable-component-update",
    "--no-first-run",
    "--mute-audio",
    "--disable-blink-features=AutomationControlled",
]

EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_REGEX = re.compile(r"https?://[^\s\"'<>)\]]+", re.IGNORECASE)
WORD_REGEX = re.compile(r"[A-Za-z\u0600-\u06FF]{3,}")
PLACEHOLDER_REGEX = re.compile(
    r"no (new )?(messages?|e-?mails?|mails?)|inbox is empty|nothing (here|yet)|"
    r"waiting for|checking|loading|empty inbox|no mail",
    re.IGNORECASE,
)
ACTION_ONLY_REGEX = re.compile(
    r"\s*(generate|refresh|delete|copy|new|change|qr code|share|download|inbox|messages?)\s*",
    re.IGNORECASE,
)

# Link scoring works for any service. A link is judged by BOTH its URL and its visible
# button text, because Facebook / LinkedIn / Discord / Amazon ... hide the real target
# behind click-tracking redirects whose URL contains no keyword at all.
LINK_STRONG_WORDS = (
    "verify", "verification", "confirm", "activate", "activation", "validate", "magic",
)
LINK_MEDIUM_WORDS = (
    "reset", "recover", "approve", "challenge", "token", "registration", "register",
    "signup", "sign-up", "sign_up",
)
LINK_WEAK_WORDS = ("auth", "otp", "login", "signin", "sign-in", "log-in", "code=")
STRONG_LINK_SCORE = 4   # a link at/above this beats a code when a message has both

# Visible button / anchor text.
ANCHOR_STRONG_WORDS = (
    "verify", "verification", "confirm", "activate", "validate",
    "reset password", "reset your password", "create account", "create my account",
    "complete registration", "complete sign", "that was me", "this was me", "yes, it",
    "\u062a\u0623\u0643\u064a\u062f", "\u062a\u062d\u0642\u0642", "\u062a\u0641\u0639\u064a\u0644",
)
ANCHOR_MEDIUM_WORDS = ("log in", "login", "sign in", "get started", "finish", "approve")
ANCHOR_BLACKLIST = (
    "unsubscribe", "privacy", "terms", "policy", "help", "support", "contact", "settings",
    "preferences", "notification", "report", "wasn't me", "wasn\u2019t me", "not me",
    "not you", "didn't", "didn\u2019t", "secure your account", "download", "app store",
    "google play", "learn more", "view in browser", "view online",
)

LINK_BLACKLIST = (
    "unsubscribe", "privacy", "terms", "mailto:", "javascript:",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".css", ".ico", "tracking-pixel",
    "optout", "opt-out", "preferences", "notification_settings", "/policies", "/legal",
    "play.google.com", "apps.apple.com", "itunes.apple.com",
)
EMAIL_BLACKLIST_PREFIXES = ("support@", "contact@", "info@", "admin@", "noreply@flashtemp")
EMAIL_BLACKLIST_DOMAINS = ("@example.com",)

MESSAGE_ROW_SELECTORS = (
    "[class*='inbox'] [class*='message']",
    "[class*='inbox'] [class*='mail']",
    "[class*='inbox'] li",
    "[class*='inbox'] tr",
    "[id*='inbox'] li",
    "[id*='inbox'] tr",
    "[id*='inbox'] [class*='item']",
    "[class*='message-item']",
    "[class*='mail-item']",
    "[class*='email-item']",
    "[class*='message'] [class*='subject']",
    "[class*='mail'] [class*='subject']",
    "[role='listitem']",
    "[role='row']",
    "table tbody tr",
    "ul[class*='mail'] li",
    "ul[class*='message'] li",
)
EMAIL_ELEMENT_SELECTORS = (
    "input[type='email']",
    "input[readonly]",
    "input[id*='email' i]",
    "input[class*='email' i]",
    "[id*='email' i]",
    "[class*='email' i]",
    "[id*='address' i]",
    "[class*='address' i]",
    "[data-email]",
)
NON_ROW_TAGS = ["button", "input", "textarea", "select", "svg", "script", "style", "iframe", "img"]

# ------------------------------- Code detection ------------------------------- #
# Works for ANY sender (Claude, Facebook, Instagram, Google, X, TikTok, Discord, ...):
# detection looks at the wording around a number, never at who sent the message.

# Explicit "this is a code" words - the strongest signal.
CODE_WORD_RE = re.compile(
    r"\b(?:codes?|otp|pin|passcode|2fa|mfa)\b|\u0643\u0648\u062f|\u0631\u0645\u0632",
    re.I,
)
# Broader words that usually surround a code in verification / login e-mails.
CODE_CONTEXT_RE = re.compile(
    r"\b(?:codes?|otp|pin|passcode|2fa|mfa|verif\w*|security|confirmation|confirm|"
    r"one[- ]?time|single[- ]?use|login|log[- ]?in|sign[- ]?in|authentication|"
    r"authenticate|authorization|recovery|reset|access|token)\b"
    r"|\u0643\u0648\u062f|\u0631\u0645\u0632|\u062a\u0623\u0643\u064a\u062f|\u062a\u062d\u0642\u0642",
    re.I,
)
STRONG_CTX_RE = re.compile(
    r"otp|passcode|verification|security|confirmation|one[- ]?time|single[- ]?use|login|sign[- ]?in"
    r"|\u0643\u0648\u062f|\u0631\u0645\u0632",
    re.I,
)
# 4-8 digits (or 3+3 like 123-456, or spaced like "1 2 3 4 5 6"), not part of a
# date / phone / decimal / price / id. Prefixed codes such as "FB-12345" or "G-123456"
# are accepted: only a DIGIT in front of the hyphen blocks a match.
DIGIT_CODE_RE = re.compile(
    r"(?<![\d.,/@$#])(?<!\d-)"
    r"(\d{3}[ \-]\d{3}|(?:\d ){3,7}\d|\d{4,8})"
    r"(?![\d,/@]|-\d|\.\d)"
)
ALNUM_CODE_RE = re.compile(r"\b(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{5,8}\b")
# "code is 5k7f2a" (X/Twitter style, mixed letters+digits, any case)
ALNUM_AFTER_CODE_RE = re.compile(
    r"\b(?:codes?|otp|pin|passcode)\b\W{0,3}(?:is|are)?\W{0,6}([A-Za-z0-9]{5,10})\b",
    re.I,
)
STANDALONE_DIGITS_RE = re.compile(r"\d{3}[ \-]\d{3}|\d{4,8}|(?:\d ){3,7}\d")
STANDALONE_PREFIXED_RE = re.compile(r"[A-Za-z]{1,4}-(\d{4,8})")
STANDALONE_ALNUM_UPPER_RE = re.compile(r"(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{5,8}")
STANDALONE_ALNUM_ANY_RE = re.compile(r"(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{5,10}")

_ARABIC_DIGITS = str.maketrans(
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9",
    "01234567890123456789",
)
# zero-width / invisible padding that e-mails (Facebook especially) put inside the text
_INVISIBLE_RE = re.compile(r"[\u00ad\u034f\u180e\u200b-\u200f\u202a-\u202e\u2060\ufeff]")


def _normalize_line(s: str) -> str:
    """Arabic-Indic digits -> ASCII, drop invisible chars, unify odd spaces."""
    s = s.translate(_ARABIC_DIGITS)
    s = _INVISIBLE_RE.sub("", s)
    s = re.sub(r"[\u00a0\u2007\u2009\u202f\t ]+", " ", s)
    return s.strip()


def _clean_code(raw: str) -> str:
    return re.sub(r"[ \-]", "", raw)


def _is_year(code: str) -> bool:
    return len(code) == 4 and 1990 <= int(code) <= 2100


def _spans(rx: "re.Pattern[str]", text: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in rx.finditer(text)]


def _gap(lo: int, hi: int, spans: list[tuple[int, int]]) -> int:
    """Characters between the number [lo, hi) and the nearest word span."""
    return min((max(s - hi, lo - e, 0) for s, e in spans), default=10**6)


def _code_in_line(text: str) -> Optional[str]:
    """
    Best number in ONE line, judged by how close it sits to code/verification words.
      rank 2: within 60 chars of an explicit word (code/otp/pin/...)   -> 4-8 digits
      rank 1: within 20 chars of a broader word (verification/...)     -> 5-8 digits only
    The closest number to the word wins ("Order 998877: your code is 123456" -> 123456).
    """
    explicit = _spans(CODE_WORD_RE, text)
    context = _spans(CODE_CONTEXT_RE, text)
    best: Optional[tuple[int, int, str]] = None
    for m in DIGIT_CODE_RE.finditer(text):
        code = _clean_code(m.group(1))
        gap = _gap(m.start(), m.end(), explicit)
        if gap <= 60:
            rank = 2
        else:
            gap = _gap(m.start(), m.end(), context)
            if gap > 20 or len(code) < 5:
                continue
            rank = 1
        if best is None or (rank, -gap) > (best[0], best[1]):
            best = (rank, -gap, code)
    return best[2] if best else None


def _alnum_in_line(text: str) -> Optional[str]:
    """Letters+digits codes: 'code is 5k7f2a', or an UPPERCASE token after a strong word."""
    for m in ALNUM_AFTER_CODE_RE.finditer(text):
        tok = m.group(1)
        if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
            return tok
    if STRONG_CTX_RE.search(text):
        cm = CODE_CONTEXT_RE.search(text)
        am = ALNUM_CODE_RE.search(text[cm.end():]) if cm else None
        if am:
            return am.group(0)
    return None


def _standalone_code(
    text: str, allow_alnum: bool, allow_year: bool, any_case: bool = False
) -> Optional[str]:
    """A line that is ONLY a code: '123456', '123 456', '1 2 3 4 5 6', 'FB-12345', 'AB3C7'."""
    t = text.strip(" \t.:*")
    if STANDALONE_DIGITS_RE.fullmatch(t):
        code = _clean_code(t)
        if _is_year(code) and not allow_year:
            return None
        return code
    pm = STANDALONE_PREFIXED_RE.fullmatch(t)
    if pm:
        return pm.group(1)
    if allow_alnum:
        rx = STANDALONE_ALNUM_ANY_RE if any_case else STANDALONE_ALNUM_UPPER_RE
        if rx.fullmatch(t):
            return t
    return None


def extract_code(lines: list[str], loose: bool) -> Optional[str]:
    """
    Finds a verification code in `lines` (text that is NEW since the email was locked).

    strict (loose=False): only lines that mention code/otp/pin/verification/... and carry a
        number close to those words, or a number on one of the next lines.
    loose  (loose=True) : additionally accepts a line that is ONLY a 4-8 digit number
        (used after a message has been opened, when the body is on screen). It is only
        a last resort: any code backed by wording anywhere in the text wins over it.
    """
    pending = 0                 # how many following lines may still hold the code
    pending_explicit = False    # the line before it contained an explicit "code" word
    since_ctx = 99              # lines since the last context line
    run: list[str] = []         # consecutive single-digit lines (one digit per table cell)
    run_ok = False
    loose_hit: Optional[str] = None

    def take_run() -> Optional[str]:
        nonlocal run, run_ok
        found = "".join(run) if (run_ok and 4 <= len(run) <= 8) else None
        run, run_ok = [], False
        return found

    for raw in lines:
        text = _normalize_line(URL_REGEX.sub(" ", raw))  # digits inside URLs are never codes
        if not text:
            continue
        since_ctx += 1

        if len(text) == 1 and text in "0123456789":
            if not run:
                run_ok = since_ctx <= 12
            run.append(text)
            continue
        found = take_run()
        if found:
            return found

        if CODE_CONTEXT_RE.search(text):
            since_ctx = 0
            code = _code_in_line(text) or _alnum_in_line(text)
            if code:
                return code
            pending = 3  # the code may sit on one of the next lines
            pending_explicit = bool(CODE_WORD_RE.search(text))
            continue
        if pending > 0:
            pending -= 1
            sc = _standalone_code(text, allow_alnum=True, allow_year=True, any_case=pending_explicit)
            if sc:
                return sc
            continue
        if loose and loose_hit is None:
            loose_hit = _standalone_code(text, allow_alnum=False, allow_year=False)

    return take_run() or loose_hit


# ---------------------------- Single-round-trip JS ---------------------------- #
EMAIL_SCAN_JS = """
(selectors) => {
  const out = [];
  const re = /[A-Za-z0-9._%+\\-]+@[A-Za-z0-9.\\-]+\\.[A-Za-z]{2,}/g;
  const add = (s) => { if (!s) return; const m = String(s).match(re); if (m) out.push(...m); };
  for (const sel of selectors) {
    let els;
    try { els = document.querySelectorAll(sel); } catch (e) { continue; }
    let i = 0;
    for (const el of els) {
      if (i++ >= 10) break;
      add(el.value);
      if (el.getAttribute) add(el.getAttribute('data-email'));
      add(el.innerText || el.textContent);
    }
  }
  add(document.body ? document.body.innerText : '');
  return out;
}
"""

LINKS_JS = """
() => {
  const anchors = Array.from(document.querySelectorAll('a[href]')).map(a => {
    let t = (a.innerText || a.textContent || '').trim();
    if (!t) {
      const im = a.querySelector('img[alt]');
      t = (im && im.alt) || a.getAttribute('aria-label') || a.title || '';
    }
    return {href: a.href, text: String(t).trim().slice(0, 120)};
  });
  const hrefs = anchors.map(a => a.href);
  const text = document.body ? document.body.innerText : '';
  const srcdocs = Array.from(document.querySelectorAll('iframe[srcdoc]'))
    .map(f => f.getAttribute('srcdoc') || '');
  return {hrefs, anchors, text, srcdocs};
}
"""

MUTATION_OBSERVER_JS = """
() => {
  if (window.__fcObserver) return;
  const tag = (n) => {
    if (n.nodeType !== 1) return;
    n.setAttribute('data-fc-new', '1');
    n.querySelectorAll('*').forEach(c => c.setAttribute('data-fc-new', '1'));
  };
  window.__fcObserver = new MutationObserver(muts => {
    for (const m of muts) m.addedNodes.forEach(tag);
  });
  window.__fcObserver.observe(document.body, {childList: true, subtree: true});
}
"""

FIND_ROWS_JS = """
(args) => {
  const {selectors, site, nonRowTags} = args;
  window.__fcSeq = window.__fcSeq || 0;
  const vis = (el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const idOf = (el) => {
    let v = el.getAttribute('data-fc-id');
    if (!v) { v = String(++window.__fcSeq); el.setAttribute('data-fc-id', v); }
    return v;
  };
  const seen = new Set();
  const rows = [];
  for (const sel of selectors) {
    let els;
    try { els = document.querySelectorAll(sel); } catch (e) { continue; }
    let n = 0;
    for (const el of els) {
      if (n++ >= 30) break;
      if (seen.has(el) || !vis(el)) continue;
      seen.add(el);
      rows.push({id: idOf(el), text: (el.innerText || '').trim()});
    }
  }
  const mut = [];
  let k = 0;
  for (const el of document.querySelectorAll("[data-fc-new='1']")) {
    if (k++ >= 80) break;
    if (!vis(el)) continue;
    if (nonRowTags.includes(el.tagName.toLowerCase())) continue;
    const a = el.closest('a[href]');
    if (a) {
      try {
        const h = new URL(a.href).host.toLowerCase();
        if (h && !h.includes(site)) continue;   // external (ad) link
      } catch (e) {}
    }
    mut.push({id: idOf(el), text: (el.innerText || '').trim()});
  }
  return {rows, mut};
}
"""


# ================================ Helpers ================================ #
def log(msg: str) -> None:
    """Print safely even on consoles that cannot show some characters (Windows CMD)."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def preview(text: str, limit: int = 70) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def copy_to_clipboard(text: str) -> bool:
    try:
        pyperclip.copy(text)
        return True
    except pyperclip.PyperclipException as exc:
        log(f"[!] Could not copy to clipboard: {exc}")
        log("    (On Linux install: sudo apt install xclip  or  xsel)")
        return False


def notify_user(title: str, message: str) -> None:
    """Optional desktop notification (needs: pip install plyer). Silent if unavailable."""
    try:
        from plyer import notification

        notification.notify(title=title, message=message, timeout=8)
    except Exception:
        pass


def _play_sound_blocking() -> None:
    """Plays ONE short 'ding' (Windows / macOS / Linux)."""
    try:
        if sys.platform.startswith("win"):
            import winsound

            winsound.Beep(1319, 90)  # single very short ding
            return

        if sys.platform == "darwin":
            subprocess.run(
                ["afplay", "/System/Library/Sounds/Tink.aiff"],  # short tick/ding
                timeout=3,
                check=False,
            )
            return

        # Linux / others: short system sound, then fall back to the terminal bell
        short_sound = "/usr/share/sounds/freedesktop/stereo/message.oga"
        if shutil.which("paplay") and os.path.exists(short_sound):
            subprocess.run(["paplay", short_sound], timeout=3, check=False)
            return
        if shutil.which("canberra-gtk-play"):
            subprocess.run(["canberra-gtk-play", "-i", "message"], timeout=3, check=False)
            return
    except Exception:
        pass
    try:
        print("\a", end="", flush=True)  # single terminal bell fallback
    except Exception:
        pass


def play_success_sound() -> Optional[threading.Thread]:
    """
    Starts the short ding in a background thread so it never delays anything
    (the browser keeps closing while it plays). Non-daemon, so Python waits for it
    to finish before exiting.
    """
    if not PLAY_SOUND:
        return None
    t = threading.Thread(target=_play_sound_blocking, name="catcher-sound")
    t.start()
    return t


def is_valid_temp_email(candidate: str) -> bool:
    c = candidate.strip().lower()
    if not EMAIL_REGEX.fullmatch(c):
        return False
    if c.startswith(EMAIL_BLACKLIST_PREFIXES):
        return False
    return not any(c.endswith(d) for d in EMAIL_BLACKLIST_DOMAINS)


def all_frames(page: Page) -> Iterable:
    try:
        return list(page.frames)
    except PlaywrightError:
        return [page.main_frame]


def install_resource_blocking(context: BrowserContext) -> None:
    """Abort images/media/fonts and ad/tracker requests to speed everything up."""

    def handler(route):
        try:
            req = route.request
            if req.resource_type in BLOCKED_RESOURCE_TYPES or any(
                p in req.url for p in BLOCKED_URL_PARTS
            ):
                route.abort()
            else:
                route.continue_()
        except PlaywrightError:
            pass

    context.route("**/*", handler)


# ========================== Step 1: Generate button ========================== #
def _generate_candidates(page: Page):
    return (
        lambda: page.get_by_role("button", name=re.compile(r"generate", re.I)),
        lambda: page.get_by_role("link", name=re.compile(r"generate", re.I)),
        lambda: page.locator(
            "button:has-text('Generate'), a:has-text('Generate'), "
            "[role='button']:has-text('Generate')"
        ),
        lambda: page.locator("[id*='generate' i], [class*='generate' i]"),
        lambda: page.get_by_text(re.compile(r"^\s*generate", re.I)),
        lambda: page.get_by_role(
            "button", name=re.compile(r"new (e-?mail|address)|get (e-?mail|address)", re.I)
        ),
    )


def click_generate_once(page: Page, timeout_sec: int) -> tuple[bool, Optional[str]]:
    """
    Clicks Generate exactly once. Returns (clicked, email_shown_right_before_the_click).
    The pre-click email lets us ignore a stale/restored email afterwards.
    """
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        for build in _generate_candidates(page):
            try:
                loc = build().first
                if loc.count() and loc.is_visible() and loc.is_enabled():
                    previous = find_email_once(page)
                    loc.click(timeout=3000)
                    return True, previous
            except PlaywrightError:
                continue
        time.sleep(0.1)
    return False, None


# ========================== Step 2: Read the email ========================== #
def find_emails_all(page: Page) -> list[str]:
    """Read-only, ONE round-trip. All valid emails currently on the page, in priority order."""
    try:
        raw = page.evaluate(EMAIL_SCAN_JS, list(EMAIL_ELEMENT_SELECTORS))
    except PlaywrightError:
        return []
    out, seen = [], set()
    for m in raw or []:
        m = m.strip()
        key = m.lower()
        if key in seen:
            continue
        seen.add(key)
        if is_valid_temp_email(m):
            out.append(m)
    return out


def find_email_once(page: Page) -> Optional[str]:
    emails = find_emails_all(page)
    return emails[0] if emails else None


def wait_for_locked_email(
    page: Page, timeout_sec: int, exclude: Optional[set[str]] = None
) -> str:
    """Waits for an email (not in `exclude`) that stays the same for 2 consecutive reads."""
    exclude = {e.lower() for e in (exclude or set())}
    deadline = time.time() + timeout_sec
    last, streak = None, 0

    while time.time() < deadline:
        email = next((e for e in find_emails_all(page) if e.lower() not in exclude), None)
        if email:
            if email == last:
                streak += 1
            else:
                last, streak = email, 1
            if streak >= 2:
                return email
        else:
            last, streak = None, 0
        time.sleep(0.15)

    raise TimeoutError("The temporary email did not appear after clicking Generate.")


# ========================== Page content scanning ========================== #
LINK_TEXTS: dict[str, str] = {}   # href -> visible button/anchor text (filled while scanning)


def _norm_link(url: str) -> str:
    return url.strip().rstrip(".,;")


def score_link(url: str) -> int:
    """
    -1 = ignore, 0 = neutral link, >0 = looks like an activation link
    (>= STRONG_LINK_SCORE = clearly an activation/verification link).
    Uses the URL words AND the visible button text ("Verify email", "Confirm", ...),
    so click-tracking redirect links (no keyword in the URL) are still recognised.
    """
    u = url.lower()
    if any(b in u for b in LINK_BLACKLIST):
        return -1
    if SITE_DOMAIN in urlparse(u).netloc:
        return -1
    text = LINK_TEXTS.get(_norm_link(url), "").lower()
    anchor_pos = any(k in text for k in ANCHOR_STRONG_WORDS)
    if text and not anchor_pos and any(b in text for b in ANCHOR_BLACKLIST):
        return -1                      # "Unsubscribe", "This wasn't me", "Help", ...
    score = 0
    if any(k in u for k in LINK_STRONG_WORDS):
        score += 4
    if any(k in u for k in LINK_MEDIUM_WORDS):
        score += 2
    if any(k in u for k in LINK_WEAK_WORDS):
        score += 1
    if anchor_pos:
        score += 4
    elif any(k in text for k in ANCHOR_MEDIUM_WORDS):
        score += 2
    if score > 0 and len(u) > 80:
        score += 1
    return score


def collect_content(page: Page) -> tuple[list[str], list[str]]:
    """(links, text_lines) from the page and all its frames - one round-trip per frame."""
    links: list[str] = []
    lines: list[str] = []
    for frame in all_frames(page):
        try:
            data = frame.evaluate(LINKS_JS)
        except PlaywrightError:
            continue
        if not data:
            continue
        text = data.get("text") or ""
        links.extend(data.get("hrefs") or [])
        for a in data.get("anchors") or []:
            href = _norm_link(a.get("href") or "")
            txt = re.sub(r"\s+", " ", a.get("text") or "").strip()
            if href and txt:
                old = LINK_TEXTS.get(href, "")
                if txt.lower() not in old.lower():
                    LINK_TEXTS[href] = (old + " | " + txt)[:300] if old else txt
        links.extend(URL_REGEX.findall(text))
        for doc in data.get("srcdocs") or []:
            links.extend(html.unescape(u) for u in URL_REGEX.findall(doc))  # &amp; -> &
        lines.extend(ln.strip() for ln in text.splitlines() if ln.strip())
    return links, lines


def scan_pages(context: BrowserContext) -> tuple[list[str], list[str]]:
    """Links + text lines from every open tab (a message may open in a new tab/popup)."""
    links: list[str] = []
    lines: list[str] = []
    try:
        pages = list(context.pages)
    except PlaywrightError:
        return links, lines
    for pg in pages:
        try:
            l, t = collect_content(pg)
        except PlaywrightError:
            continue
        links.extend(l)
        lines.extend(t)

    seen, unique = set(), []
    for l in links:
        l = _norm_link(l)
        if l and l not in seen:
            seen.add(l)
            unique.append(l)
    return unique, lines


def pick_activation_link(
    links: list[str], ignore: set[str], fallback: bool = False
) -> Optional[str]:
    """
    Prefers links containing activation keywords. With fallback=True and no keyword
    match, returns the longest neutral external link (activation links are usually long).
    Links that existed on the page before any message arrived are ignored.
    """
    scored = [(score_link(l), l) for l in links if l not in ignore]
    good = [x for x in scored if x[0] > 0]
    if good:
        good.sort(key=lambda x: x[0], reverse=True)
        return good[0][1]
    if fallback:
        neutral = [l for s, l in scored if s == 0]
        if neutral:
            return max(neutral, key=len)
    return None


def decide(link: Optional[str], code: Optional[str]) -> Optional[tuple[str, str]]:
    """Returns ('link', url) or ('code', digits) - or None if nothing found yet."""
    if link and code:
        if PREFER_CODE_OVER_LINK:
            return ("code", code)
        # only a clearly activation-looking link beats a code; a generic link
        # (one loose keyword) must not hijack e-mails whose real payload is a code
        return ("link", link) if score_link(link) >= STRONG_LINK_SCORE else ("code", code)
    if link:
        return ("link", link)
    if code:
        return ("code", code)
    return None


def fresh_lines(lines: list[str], baseline_lines: set[str]) -> list[str]:
    """Only text that was NOT on the page when the email was locked."""
    return [l for l in lines if l not in baseline_lines]


# ========================== Inbox monitoring ========================== #
def acceptable_row_text(sig: str, locked_email: str, opened: set[str]) -> bool:
    """Filters out placeholders ('No messages'), timers, the email display and controls."""
    if not sig or sig in opened:
        return False
    if len(sig) < 6 or len(sig) > 600:
        return False
    if not WORD_REGEX.search(sig):            # pure numbers/timers
        return False
    if len(sig) < 160 and PLACEHOLDER_REGEX.search(sig):
        return False
    if ACTION_ONLY_REGEX.fullmatch(sig):
        return False
    if locked_email.lower() in sig.lower() and len(sig) < 100:
        return False                          # the "your email" display, not a message
    return True


def find_new_rows(page: Page, locked_email: str, opened: set[str]) -> list[tuple[str, object]]:
    """
    Returns candidate (signature, locator) pairs for NEW inbox rows, using ONE JS call.
    1) Union of all known row selectors (a 'No messages' placeholder can't hide the real row).
    2) Fallback: elements added to the DOM after the email was locked.
    Smaller elements first; duplicates (same text) are removed.
    """
    try:
        data = page.evaluate(
            FIND_ROWS_JS,
            {
                "selectors": list(MESSAGE_ROW_SELECTORS),
                "site": SITE_DOMAIN,
                "nonRowTags": NON_ROW_TAGS,
            },
        )
    except PlaywrightError:
        return []
    if not data:
        return []

    def build(items) -> list[tuple[str, object]]:
        result: list[tuple[str, object]] = []
        seen: set[str] = set()
        for item in items or []:
            sig = re.sub(r"\s+", " ", item.get("text") or "").strip()
            if sig in seen or not acceptable_row_text(sig, locked_email, opened):
                continue
            seen.add(sig)
            result.append((sig, page.locator(f"[data-fc-id='{item['id']}']").first))
        return result

    found = build(data.get("rows"))
    if not found:  # DOM-diff fallback
        found = build(data.get("mut"))

    found.sort(key=lambda x: len(x[0]))
    if DEBUG and found:
        log(f"[debug] {len(found)} candidate row(s): " + " | ".join(preview(s, 40) for s, _ in found[:5]))
    return found


def click_row(row) -> None:
    """Clicks the row on its left-middle area (away from delete/action buttons on the right)."""
    try:
        box = row.bounding_box()
        if box and box["width"] > 40:
            row.click(position={"x": box["width"] * 0.25, "y": box["height"] / 2}, timeout=2500)
        else:
            row.click(timeout=2500)
        return
    except PlaywrightError:
        pass
    try:
        row.click(force=True, timeout=2000)
    except PlaywrightError:
        row.evaluate("e => e.click()")


def debug_dump(links: list[str], lines: list[str], baseline_lines: set[str]) -> None:
    """--debug only: show what the scanner saw in a message that produced no result."""
    fresh = fresh_lines(lines, baseline_lines)
    log(f"[debug] message scan: {len(fresh)} new text line(s), {len(links)} link(s)")
    for ln in fresh[:25]:
        log(f"[debug]   | {preview(ln, 110)}")
    for s, l in sorted(((score_link(x), x) for x in links), reverse=True)[:6]:
        log(f"[debug]   link score={s}: {preview(l, 100)}")


def open_and_extract(
    context: BrowserContext,
    row,
    baseline_links: set[str],
    baseline_lines: set[str],
) -> tuple[Optional[tuple[str, str]], Optional[str]]:
    """
    Clicks the row, then scans until a link or a code shows up.
    Returns ((kind, value) | None, fallback_link | None).
    """
    click_row(row)
    fallback: Optional[str] = None
    links: list[str] = []
    lines: list[str] = []
    deadline = time.time() + MESSAGE_OPEN_WAIT_SEC

    while time.time() < deadline:
        links, lines = scan_pages(context)
        result = decide(
            pick_activation_link(links, baseline_links),
            extract_code(fresh_lines(lines, baseline_lines), loose=True),
        )
        if result:
            return result, None
        fb = pick_activation_link(links, baseline_links, fallback=True)
        if fb:
            fallback = fb
        time.sleep(0.1)
    if DEBUG:
        debug_dump(links, lines, baseline_lines)
    return None, fallback


def safe_inbox_refresh(page: Page) -> None:
    if not CLICK_INBOX_REFRESH:
        return
    try:
        btn = page.get_by_role("button", name=re.compile(r"^\s*refresh( inbox)?\s*$", re.I)).first
        if btn.count() and btn.is_visible():
            btn.click(timeout=800)
    except PlaywrightError:
        pass


def watch_inbox(context: BrowserContext, page: Page, locked_email: str) -> tuple[str, str]:
    """
    Read-only polling loop. Clicks new inbox rows only.
    Returns ('link', url) or ('code', digits).
    """
    try:
        page.evaluate(MUTATION_OBSERVER_JS)
    except PlaywrightError as exc:
        log(f"[!] DOM observer unavailable (selectors only): {exc}")

    base_links, base_lines = scan_pages(context)
    baseline_links = set(base_links)      # links present before any message arrives
    baseline_lines = set(base_lines)      # text present before any message arrives
    opened: set[str] = set()
    retries: dict[str, int] = {}
    fallback_link: Optional[str] = None
    fallback_deadline = 0.0
    started = time.time()
    cycle = 0
    warned_mismatch = False
    locked_lower = locked_email.lower()

    while True:
        if INBOX_MAX_WAIT_SEC and (time.time() - started) > INBOX_MAX_WAIT_SEC:
            raise TimeoutError("Timed out waiting for the verification message.")
        cycle += 1

        try:
            safe_inbox_refresh(page)

            # (a) a link/code may already be on screen (e.g. code in the inbox preview/subject)
            links, lines = scan_pages(context)
            result = decide(
                pick_activation_link(links, baseline_links),
                extract_code(fresh_lines(lines, baseline_lines), loose=bool(opened)),
            )
            if result:
                return result

            # (b) a new row appeared -> click it immediately
            candidates = find_new_rows(page, locked_email, opened)
            if candidates:
                sig, row = candidates[0]
                opened.add(sig)
                log(f"[*] New message detected: '{preview(sig)}' - clicking it now...")
                try:
                    result, fb = open_and_extract(context, row, baseline_links, baseline_lines)
                except PlaywrightError as exc:
                    # click failed (row re-rendered?) -> allow a few retries
                    retries[sig] = retries.get(sig, 0) + 1
                    if retries[sig] < MAX_ROW_RETRIES:
                        opened.discard(sig)
                    log(f"[!] Could not open the message (attempt {retries[sig]}): {exc}")
                    result, fb = None, None
                if result:
                    return result
                if fb and not fallback_link:
                    fallback_link = fb
                    fallback_deadline = time.time() + FALLBACK_GRACE_SEC
                log("[-] No link or code found in this message yet, still watching...")
                if len(candidates) > 1:
                    continue  # try the next candidate right away

            # (c) accept a keyword-less link if nothing better showed up
            if fallback_link and time.time() >= fallback_deadline:
                log("[*] No activation keyword/code found; using the best available link.")
                return ("link", fallback_link)

            # (d) passive check: warn (never act) if the locked email vanished from the page
            if cycle % 20 == 0 and not warned_mismatch:
                emails = find_emails_all(page)
                if emails and locked_lower not in {e.lower() for e in emails}:
                    warned_mismatch = True
                    log(f"[!] Warning: the site now shows a different email ({emails[0]}).")
                    log(f"    The locked and copied email is still: {locked_email}")

        except PlaywrightTimeout:
            pass
        except PlaywrightError as exc:
            if "closed" in str(exc).lower():
                raise RuntimeError("The browser was closed manually.") from exc
            log(f"[!] Monitoring error (retrying): {exc}")

        time.sleep(POLL_INTERVAL_SEC)


# ================================ Main ================================ #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="flashtemp_catcher",
        description="Generates a FlashTemp email and catches the verification link/code.",
    )
    p.add_argument("--show", action="store_true",
                   help="show the browser window (default: hidden / headless)")
    p.add_argument("--debug", action="store_true", help="print extra detection details")
    p.add_argument("--no-sound", action="store_true", help="disable the success sound")
    return p.parse_args()


def build_user_agent(browser_version: str) -> str:
    """
    Headless Chromium advertises 'HeadlessChrome' in its User-Agent, which some sites
    treat differently. Present a normal Chrome UA instead (only used in headless mode).
    """
    major = (browser_version or "120").split(".")[0]
    if sys.platform.startswith("win"):
        platform = "Windows NT 10.0; Win64; x64"
    elif sys.platform == "darwin":
        platform = "Macintosh; Intel Mac OS X 10_15_7"
    else:
        platform = "X11; Linux x86_64"
    return (
        f"Mozilla/5.0 ({platform}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{major}.0.0.0 Safari/537.36"
    )


def save_debug_screenshot(page: Optional[Page]) -> None:
    """Headless = nothing to look at, so on failure save a screenshot to help diagnose."""
    if not HEADLESS or page is None:
        return
    path = "flashtemp_catcher_error.png"
    try:
        page.screenshot(path=path, timeout=3000)
        log(f"[i] Screenshot saved: {os.path.abspath(path)}")
    except Exception:
        pass
    log("[i] Tip: run with --show to watch the browser and see what the page is doing.")


def main() -> int:
    global HEADLESS, DEBUG, PLAY_SOUND

    args = parse_args()
    if args.show:
        HEADLESS = False
    if args.debug:
        DEBUG = True
    if args.no_sound:
        PLAY_SOUND = False

    try:
        sys.stdout.reconfigure(errors="replace")  # avoid crashes on legacy consoles
    except Exception:
        pass

    playwright: Optional[Playwright] = None
    browser: Optional[Browser] = None
    context: Optional[BrowserContext] = None
    page: Optional[Page] = None
    exit_code = 0
    notice: Optional[str] = None
    t0 = time.time()

    try:
        log(f"=== {APP_NAME} ===")
        log(f"[*] Mode: {'headless (background, no window)' if HEADLESS else 'visible browser window'}")
        playwright = sync_playwright().start()
        browser = playwright.chromium.launch(headless=HEADLESS, args=LAUNCH_ARGS)

        context_options = {
            "viewport": {"width": 1280, "height": 800},
            "reduced_motion": "reduce",
            "service_workers": "block",
        }
        if HEADLESS:
            context_options["user_agent"] = build_user_agent(browser.version)
        context = browser.new_context(**context_options)

        if BLOCK_HEAVY_RESOURCES:
            install_resource_blocking(context)
        page = context.new_page()

        log(f"[*] Opening site: {SITE_URL}")
        page.goto(SITE_URL, wait_until="domcontentloaded", timeout=45_000)

        log("[*] Looking for the Generate button and clicking it (once only)...")
        clicked, previous = click_generate_once(page, GENERATE_WAIT_TIMEOUT_SEC)
        if clicked:
            log("[+] Generate clicked.")
        else:
            log("[!] Generate button not found; using the email shown on the page, if any.")

        log("[*] Waiting for the email to appear and stabilize...")
        email = wait_for_locked_email(
            page,
            EMAIL_WAIT_TIMEOUT_SEC,
            exclude={previous} if (clicked and previous) else None,
        )

        copied_email = copy_to_clipboard(email)
        if copied_email:
            play_success_sound()  # short ding: email copied
        log(f"\n>>> Email (locked): {email}   [ready in {time.time() - t0:.1f}s]")
        if copied_email:
            log("Email copied! Use it now, the script is waiting for the verification message...\n")
        else:
            log("(Copy it manually) The script is waiting for the verification message...\n")

        # From here on: read-only. No goto / reload / Generate.
        kind, value = watch_inbox(context, page, email)

        copied = copy_to_clipboard(value)
        if copied:
            play_success_sound()  # short ding in the background while the browser closes
        label = "Verification code" if kind == "code" else "Activation link"
        log("\n" + "=" * 60)
        log(f"{label}:\n{value}")
        log("=" * 60)
        if copied:
            log(f"[OK] {label} copied to clipboard - ready to paste (Ctrl+V).   [total {time.time() - t0:.1f}s]")
        notice = f"{label} copied - ready to paste (Ctrl+V)"

    except KeyboardInterrupt:
        log("\n[!] Stopped by the user.")
        exit_code = 130
    except TimeoutError as exc:
        log(f"[!] {exc}")
        save_debug_screenshot(page)
        exit_code = 2
    except PlaywrightTimeout as exc:
        log(f"[!] Playwright timeout: {exc}")
        save_debug_screenshot(page)
        exit_code = 3
    except PlaywrightError as exc:
        log(f"[!] Playwright error: {exc}")
        save_debug_screenshot(page)
        exit_code = 4
    except Exception as exc:  # noqa: BLE001
        log(f"[!] Unexpected error: {type(exc).__name__}: {exc}")
        save_debug_screenshot(page)
        exit_code = 1
    finally:
        # Closing the browser also closes its contexts (faster than closing each one).
        try:
            if browser:
                browser.close()
            elif context:
                context.close()
        except Exception:
            pass
        try:
            if playwright:
                playwright.stop()
        except Exception:
            pass
        log("[*] Browser closed. Exiting.")
        if notice:  # after closing, so the optional notification never delays the shutdown
            notify_user(APP_NAME, notice)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())