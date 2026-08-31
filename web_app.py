# -*- coding: utf-8 -*-
"""
Agent Reach - Web UI & API Server
Built with FastAPI to provide public web access on Railway / Docker.
"""

import os
import sys
import re
import json
import tempfile
import subprocess
import shutil
from typing import Optional, Dict, Any

# Ensure .venv/Scripts is in PATH for any subprocess calls (yt-dlp, ffmpeg, etc.)
scripts_dir = os.path.dirname(sys.executable)
if scripts_dir not in os.environ.get("PATH", ""):
    os.environ["PATH"] = scripts_dir + os.pathsep + os.environ.get("PATH", "")

# Ensure streams exist when running without console window (pythonw / Windows Service)
log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.log")
if sys.stdout is None:
    sys.stdout = open(log_file_path, "a", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = open(log_file_path, "a", encoding="utf-8", buffering=1)

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

def get_ytdlp_cmd() -> list:
    """Resolve the yt-dlp executable path reliably across Windows/Linux/Venv."""
    s_dir = os.path.dirname(sys.executable)
    for name in ["yt-dlp.exe", "yt-dlp"]:
        candidate = os.path.join(s_dir, name)
        if os.path.isfile(candidate):
            return [candidate]
    which = shutil.which("yt-dlp")
    if which:
        return [which]
    return [sys.executable, "-m", "yt_dlp"]

app = FastAPI(title="Agent Reach Web UI", version="1.0.0")

class ExtractRequest(BaseModel):
    url: str

def is_predominantly_cjk(text: str) -> bool:
    """Check if a line contains predominantly Chinese/Japanese/Korean ideographs."""
    if not text:
        return False
    cjk_count = sum(1 for ch in text if ('\u4e00' <= ch <= '\u9fff') or ('\u3400' <= ch <= '\u4dbf') or ('\u3040' <= ch <= '\u30ff'))
    cleaned_len = len(re.sub(r"\s+", "", text))
    return cleaned_len > 0 and (cjk_count / cleaned_len) > 0.35

def clean_vtt(vtt_text: str) -> str:
    """Parse VTT subtitles into clean readable English transcript."""
    lines = vtt_text.splitlines()
    clean_lines = []
    seen = set()
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        if "-->" in line:
            continue
        # Remove simple HTML-like tags from captions (e.g., <c>, </c>)
        line = re.sub(r"<[^>]+>", "", line).strip()
        # Filter out foreign/Chinese lines from dual-language auto-captions
        if is_predominantly_cjk(line):
            continue
        if line and line not in seen:
            seen.add(line)
            clean_lines.append(line)
            
    return "\n\n".join(clean_lines)

def extract_youtube(url: str) -> Dict[str, Any]:
    """Extract metadata and subtitles using yt-dlp with strict English preferences."""
    try:
        ytdlp_base = get_ytdlp_cmd()
        # 1. Fetch metadata JSON with English locale headers
        meta_cmd = ytdlp_base + [
            "--dump-json",
            "--no-warnings",
            "--add-header", "Accept-Language: en-US,en;q=0.9",
            "--extractor-args", "youtube:player_client=android,web;lang=en",
            url
        ]
        meta_res = subprocess.run(meta_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=35)
        
        metadata = {}
        if meta_res.returncode == 0 and meta_res.stdout.strip():
            metadata = json.loads(meta_res.stdout)
            
        title = metadata.get("title", "YouTube Video")
        uploader = metadata.get("uploader", "Unknown Creator")
        duration = metadata.get("duration", 0)
        views = metadata.get("view_count", 0)
        thumbnail = metadata.get("thumbnail", "")
        description = metadata.get("description", "")
        
        # 2. Extract subtitles/transcript prioritizing English
        with tempfile.TemporaryDirectory() as tmpdir:
            out_template = os.path.join(tmpdir, "caption_%(id)s")
            sub_cmd = ytdlp_base + [
                "--write-sub",
                "--write-auto-sub",
                "--sub-lang", "en,en-US,en-GB,en.*",
                "--add-header", "Accept-Language: en-US,en;q=0.9",
                "--extractor-args", "youtube:player_client=android,web;lang=en",
                "--skip-download",
                "--no-warnings",
                "-o", out_template,
                url
            ]
            subprocess.run(sub_cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
            
            transcript = ""
            vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
            if vtt_files:
                # Prefer explicitly English subtitles (.en.vtt, .en-US.vtt)
                en_vtts = [f for f in vtt_files if ".en" in f.lower()]
                target_file = os.path.join(tmpdir, en_vtts[0] if en_vtts else vtt_files[0])
                with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                    transcript = clean_vtt(f.read())
                    
            if not transcript:
                # Clean description lines from any foreign boilerplate
                clean_desc_lines = [l for l in description.splitlines() if not is_predominantly_cjk(l)]
                clean_desc = "\n".join(clean_desc_lines[:30]).strip()
                transcript = f"*No automated English transcript was available for this video.*\n\n**Video Description:**\n\n{clean_desc[:1500] if clean_desc else 'No description available.'}"
                
            return {
                "platform": "YouTube",
                "title": title,
                "author": uploader,
                "metadata": {
                    "duration_seconds": duration,
                    "views": views,
                    "thumbnail": thumbnail,
                    "channel_url": metadata.get("channel_url", "")
                },
                "content": transcript
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"YouTube extraction failed: {str(e)}")

def extract_general_web(url: str) -> Dict[str, Any]:
    """Extract web article, SPA, or general URL content in clean English."""
    try:
        import requests
        from bs4 import BeautifulSoup
        from agent_reach.utils.url import normalize_public_http_url
        
        clean_target_url = normalize_public_http_url(url)
        content = ""
        title = url
        author = "Web Reader"
        platform = "Web (Jina Reader)"
        
        # 1. Attempt Jina Reader first
        jina_url = f"https://r.jina.ai/{clean_target_url}"
        jina_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "text/plain",
            "Accept-Language": "en-US,en;q=0.9"
        }
        
        try:
            resp = requests.get(jina_url, headers=jina_headers, timeout=20)
            if resp.status_code == 200 and resp.text.strip():
                candidate = resp.text.strip()
                # Check for upstream server error messages like 'Only HTML requests are supported'
                invalid_markers = [
                    '"error":',
                    "Only HTML requests are supported",
                    "403 Forbidden",
                    "502 Bad Gateway",
                    "Cloudflare Ray ID"
                ]
                if not any(m in candidate for m in invalid_markers) and len(candidate) > 100:
                    content = candidate
        except Exception:
            content = ""
            
        # 2. Fallback to Direct HTML Fetch with BeautifulSoup (Handles SPAs, Lovable, React, Next.js, Vite)
        if not content:
            platform = "Web (Direct HTML Engine)"
            browser_headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Sec-Ch-Ua": '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Upgrade-Insecure-Requests": "1"
            }
            direct_resp = requests.get(clean_target_url, headers=browser_headers, timeout=20)
            if direct_resp.status_code == 200 and direct_resp.text.strip():
                soup = BeautifulSoup(direct_resp.text, "html.parser")
                
                # Extract page title
                if soup.title and soup.title.string:
                    title = soup.title.string.strip()
                    
                # Extract meta description
                meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
                desc_text = meta_desc.get("content", "").strip() if meta_desc else ""
                
                # Extract OpenGraph site name or author
                og_site = soup.find("meta", attrs={"property": "og:site_name"})
                if og_site and og_site.get("content"):
                    author = og_site.get("content").strip()
                    
                # Decompose non-content tags
                for tag in soup(["script", "style", "noscript", "svg", "header", "footer"]):
                    tag.decompose()
                    
                # Extract clean readable text
                body_text = soup.get_text(separator="\n")
                clean_lines = [l.strip() for l in body_text.splitlines() if l.strip() and not is_predominantly_cjk(l)]
                
                formatted_blocks = []
                if title:
                    formatted_blocks.append(f"# {title}")
                if desc_text:
                    formatted_blocks.append(f"> {desc_text}")
                formatted_blocks.append("\n\n".join(clean_lines))
                
                content = "\n\n".join(formatted_blocks).strip()
            else:
                content = f"Unable to fetch web page content (HTTP {direct_resp.status_code})."
        
        # Filter out any foreign boilerplate lines if present
        clean_lines = [l for l in content.splitlines() if not is_predominantly_cjk(l)]
        content = "\n".join(clean_lines)
        
        # Determine title from markdown if available
        if title == url:
            first_lines = [l.strip() for l in content.splitlines() if l.strip()][:5]
            for l in first_lines:
                if l.startswith("Title:"):
                    title = l.replace("Title:", "").strip()
                    break
                elif l.startswith("# "):
                    title = l.replace("# ", "").strip()
                    break
                
        return {
            "platform": platform,
            "title": title,
            "author": author,
            "metadata": {
                "url": url,
                "bytes": len(content.encode("utf-8"))
            },
            "content": content
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Web extraction failed: {str(e)}")

@app.post("/api/extract")
async def extract_url(req: ExtractRequest):
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
        
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    if "youtube.com" in url or "youtu.be" in url:
        return extract_youtube(url)
    else:
        return extract_general_web(url)

CHANNELS_EN = {
    "web": ("Webpage Reader", "Extracts clean readable text from any public webpage via Jina Reader"),
    "youtube": ("YouTube Videos & Captions", "Extracts video details, description, and English subtitles via yt-dlp"),
    "github": ("GitHub Repositories", "Reads code, READMEs, issues, and metadata via GitHub CLI"),
    "rss": ("RSS & Atom Feeds", "Parses blog, news, and podcast XML/Atom feeds"),
    "search": ("Semantic Web Search", "AI-powered semantic search via Exa"),
    "twitter": ("Twitter / X Posts", "Fetches tweets and public discussion threads"),
    "reddit": ("Reddit Posts & Comments", "Fetches subreddit threads and discussions"),
    "v2ex": ("V2EX Discussions", "Reads developer forum topics via public API"),
    "facebook": ("Facebook Content", "Reads public social group posts"),
    "instagram": ("Instagram Posts", "Reads public media feeds"),
    "linkedin": ("LinkedIn Network", "Reads professional profiles and posts"),
    "podcast": ("Podcast Transcripts", "Transcribes audio podcast feeds"),
    "bilibili": ("Bilibili Media", "Reads video data and captions via public API"),
    "xiaohongshu": ("Xiaohongshu Notes", "Reads lifestyle and note cards"),
    "xueqiu": ("Financial Feeds", "Reads stock market analysis and community feeds"),
}

@app.get("/api/doctor")
async def doctor_status():
    """Runs a quick doctor check and returns a clean English diagnostics report."""
    try:
        from agent_reach.config import Config
        from agent_reach.doctor import check_all
        
        raw_results = check_all(Config())
        lines = [
            "============================================================",
            "             AGENT REACH - SYSTEM DIAGNOSTICS               ",
            "============================================================",
            "Legend: [OK] Ready to Use  [!] Needs Auth/Config  [X] Optional",
            ""
        ]
        
        ready_count = 0
        for key, (title, desc) in CHANNELS_EN.items():
            ch = raw_results.get(key, {})
            status = ch.get("status", "off")
            
            if status == "ok":
                ready_count += 1
                lines.append(f"  [OK] {title:<28} - Ready ({desc})")
            elif status == "warn":
                lines.append(f"  [!]  {title:<28} - Installed (Auth / API key recommended)")
            else:
                lines.append(f"  [X]  {title:<28} - Optional channel (Not configured)")
                
        lines.append("")
        lines.append(f"Status Summary: {ready_count}/{len(CHANNELS_EN)} channels actively ready.")
        lines.append("Environment: Python 3.11 with FastAPI + yt-dlp + Jina Reader.")
        lines.append("============================================================")
        return {"output": "\n".join(lines)}
    except Exception as e:
        return {"output": f"Diagnostic check error: {str(e)}"}

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "agent-reach-web"}

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    return HTML_CONTENT

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agent Reach — Web Capability Hub</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-base: #0a0d14;
            --bg-surface: #121722;
            --bg-card: #182030;
            --border: #263248;
            --accent: #3b82f6;
            --accent-gradient: linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
            --accent-hover: #2563eb;
            --text-primary: #f1f5f9;
            --text-secondary: #94a3b8;
            --text-muted: #64748b;
            --success: #10b981;
            --font-main: 'Plus Jakarta Sans', system-ui, -apple-system, sans-serif;
            --font-mono: 'JetBrains Mono', monospace;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-base);
            color: var(--text-primary);
            font-family: var(--font-main);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
            line-height: 1.6;
        }

        header {
            border-bottom: 1px solid var(--border);
            background: rgba(18, 23, 34, 0.8);
            backdrop-filter: blur(12px);
            position: sticky;
            top: 0;
            z-index: 100;
        }

        .navbar {
            max-width: 1100px;
            margin: 0 auto;
            padding: 1rem 1.5rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .logo-row {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .logo {
            display: flex;
            align-items: center;
            font-size: 1.25rem;
            font-weight: 800;
        }

        .logo-title {
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            white-space: nowrap;
        }

        .logo-badge {
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.2rem 0.6rem;
            border-radius: 9999px;
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.3);
            white-space: nowrap;
            display: inline-block;
        }

        .nav-actions {
            display: flex;
            align-items: center;
            gap: 1rem;
        }

        .btn-secondary {
            background: var(--bg-card);
            color: var(--text-primary);
            border: 1px solid var(--border);
            padding: 0.5rem 1rem;
            border-radius: 8px;
            font-size: 0.875rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
        }

        .btn-secondary:hover {
            border-color: #3b82f6;
            background: #1e293b;
        }

        main {
            flex: 1;
            max-width: 1100px;
            margin: 0 auto;
            padding: 2.5rem 1.5rem;
            width: 100%;
        }

        .hero {
            text-align: center;
            margin-bottom: 2.5rem;
        }

        .hero h1 {
            font-size: 2.5rem;
            font-weight: 800;
            letter-spacing: -0.025em;
            margin-bottom: 0.75rem;
        }

        .hero p {
            color: var(--text-secondary);
            font-size: 1.125rem;
            max-width: 650px;
            margin: 0 auto;
        }

        .search-container {
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 1.75rem;
            box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.5);
            margin-bottom: 2rem;
        }

        .input-group {
            display: flex;
            gap: 0.75rem;
        }

        input[type="text"] {
            flex: 1;
            background: var(--bg-card);
            border: 1px solid var(--border);
            color: var(--text-primary);
            padding: 1rem 1.25rem;
            border-radius: 10px;
            font-size: 1rem;
            font-family: inherit;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        input[type="text"]:focus {
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
        }

        .btn-primary {
            background: var(--accent-gradient);
            color: white;
            border: none;
            padding: 1rem 1.75rem;
            border-radius: 10px;
            font-size: 1rem;
            font-weight: 700;
            cursor: pointer;
            transition: opacity 0.2s, transform 0.1s;
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            white-space: nowrap;
        }

        .btn-primary:hover {
            opacity: 0.92;
        }

        .btn-primary:active {
            transform: scale(0.98);
        }

        .sample-chips {
            margin-top: 1rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
            flex-wrap: wrap;
        }

        .sample-label {
            font-size: 0.8rem;
            color: var(--text-muted);
            font-weight: 600;
        }

        .chip {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border);
            border-radius: 999px;
            padding: 0.25rem 0.75rem;
            font-size: 0.775rem;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s;
        }

        .chip:hover {
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border-color: rgba(59, 130, 246, 0.4);
        }

        .result-panel {
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            overflow: hidden;
            display: none;
        }

        .result-header {
            padding: 1.25rem 1.5rem;
            background: var(--bg-card);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }

        .result-info h3 {
            font-size: 1.15rem;
            font-weight: 700;
            color: var(--text-primary);
            margin-bottom: 0.25rem;
        }

        .result-meta {
            display: flex;
            align-items: center;
            gap: 1rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        .tag {
            background: rgba(16, 185, 129, 0.15);
            color: #34d399;
            padding: 0.2rem 0.5rem;
            border-radius: 6px;
            font-weight: 600;
            font-size: 0.75rem;
        }

        .result-body {
            padding: 1.5rem;
        }

        .content-box {
            background: var(--bg-base);
            border: 1px solid var(--border);
            border-radius: 10px;
            padding: 1.25rem;
            font-family: var(--font-mono);
            font-size: 0.9rem;
            color: #cbd5e1;
            white-space: pre-wrap;
            word-break: break-word;
            max-height: 550px;
            overflow-y: auto;
            line-height: 1.7;
        }

        .modal {
            display: none;
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.75);
            backdrop-filter: blur(8px);
            z-index: 1000;
            align-items: center;
            justify-content: center;
            padding: 1.5rem;
        }

        .modal-card {
            background: var(--bg-surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            max-width: 650px;
            width: 100%;
            overflow: hidden;
            box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
        }

        .modal-header {
            padding: 1.25rem 1.5rem;
            background: var(--bg-card);
            border-bottom: 1px solid var(--border);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-body {
            padding: 1.5rem;
        }

        .close-btn {
            background: none;
            border: none;
            color: var(--text-secondary);
            font-size: 1.5rem;
            cursor: pointer;
        }

        .spinner {
            border: 3px solid rgba(255, 255, 255, 0.2);
            border-top-color: white;
            border-radius: 50%;
            width: 1.25rem;
            height: 1.25rem;
            animation: spin 0.8s linear infinite;
            display: inline-block;
        }

        footer {
            text-align: center;
            padding: 2rem 1.5rem;
            color: var(--text-muted);
            font-size: 0.85rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            margin-top: auto;
        }

        /* Mobile Responsive Media Queries */
        @media (max-width: 768px) {
            .navbar {
                flex-direction: column;
                align-items: stretch;
                gap: 0.85rem;
                padding: 0.85rem 1rem;
            }

            .logo-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                width: 100%;
            }

            .logo {
                font-size: 1.15rem;
                gap: 0.5rem;
            }

            .logo-badge {
                font-size: 0.7rem;
                padding: 0.15rem 0.5rem;
            }

            .nav-actions {
                width: 100%;
            }

            .nav-actions .btn-secondary {
                width: 100%;
                justify-content: center;
                padding: 0.65rem 1rem;
                font-size: 0.85rem;
            }

            main {
                padding: 1.25rem 1rem;
            }

            .hero {
                margin-bottom: 1.5rem;
            }

            .hero h1 {
                font-size: 1.65rem;
                line-height: 1.25;
                margin-bottom: 0.5rem;
            }

            .hero p {
                font-size: 0.95rem;
                line-height: 1.5;
            }

            .search-container {
                padding: 1.25rem 1rem;
                border-radius: 14px;
                margin-bottom: 1.5rem;
            }

            .input-group {
                flex-direction: column;
                gap: 0.75rem;
                width: 100%;
            }

            input[type="text"] {
                width: 100%;
                padding: 0.85rem 1rem;
                font-size: 0.95rem;
                border-radius: 8px;
            }

            .btn-primary {
                width: 100%;
                justify-content: center;
                padding: 0.85rem 1.25rem;
                font-size: 0.95rem;
                border-radius: 8px;
            }

            .sample-chips {
                flex-direction: column;
                align-items: stretch;
                gap: 0.45rem;
                margin-top: 1rem;
            }

            .sample-label {
                font-size: 0.75rem;
                margin-bottom: 0.15rem;
            }

            .chip {
                padding: 0.45rem 0.75rem;
                font-size: 0.8rem;
                text-align: center;
            }

            .result-header {
                flex-direction: column;
                align-items: stretch;
                gap: 0.75rem;
                padding: 1rem;
            }

            .result-header .btn-secondary {
                width: 100%;
                justify-content: center;
            }

            .result-body {
                padding: 1rem;
            }

            .content-box {
                padding: 0.85rem;
                font-size: 0.825rem;
                max-height: 420px;
            }

            .modal {
                padding: 1rem;
            }

            .modal-card {
                border-radius: 12px;
            }

            .modal-header {
                padding: 1rem;
            }

            .modal-body {
                padding: 1rem;
            }

            footer {
                padding: 1.5rem 1rem;
                font-size: 0.775rem;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="navbar">
            <div class="logo-row">
                <div class="logo">
                    <span class="logo-title">👁️ Agent Reach</span>
                </div>
                <span class="logo-badge">Live Web Hub</span>
            </div>
            <div class="nav-actions">
                <button class="btn-secondary" onclick="openDoctorModal()">🩺 System Diagnostics</button>
            </div>
        </div>
    </header>

    <main>
        <div class="hero">
            <h1>Web & Video Content Extractor</h1>
            <p>Direct live capability bridge powered by Agent Reach, yt-dlp, and Jina Reader.</p>
        </div>

        <div class="search-container">
            <div class="input-group">
                <input type="text" id="urlInput" placeholder="Paste any public URL (YouTube video, article, blog, webpage)..." autocomplete="off" />
                <button class="btn-primary" id="extractBtn" onclick="handleExtract()">
                    <span id="btnText">Fetch Content</span>
                    <span id="btnSpinner" class="spinner" style="display: none;"></span>
                </button>
            </div>
            <div class="sample-chips">
                <span class="sample-label">Quick Samples:</span>
                <div class="chip" onclick="setSample('https://www.youtube.com/watch?v=jNQXAC9IVRw')">📺 YouTube Video (Me at the zoo)</div>
                <div class="chip" onclick="setSample('https://example.com')">🌐 Web Article (Example.com)</div>
                <div class="chip" onclick="setSample('https://fastapi.tiangolo.com')">⚡ Documentation (FastAPI)</div>
            </div>
        </div>

        <div class="result-panel" id="resultPanel">
            <div class="result-header">
                <div class="result-info">
                    <h3 id="resTitle">Extraction Result</h3>
                    <div class="result-meta">
                        <span class="tag" id="resPlatform">Platform</span>
                        <span id="resAuthor">Author</span>
                    </div>
                </div>
                <button class="btn-secondary" onclick="copyContent()">📋 Copy Clean Text</button>
            </div>
            <div class="result-body">
                <div class="content-box" id="resContent"></div>
            </div>
        </div>
    </main>

    <!-- Doctor Diagnostic Modal -->
    <div class="modal" id="doctorModal">
        <div class="modal-card">
            <div class="modal-header">
                <h3>🩺 System Diagnostics & Channel Health</h3>
                <button class="close-btn" onclick="closeDoctorModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="content-box" id="doctorContent" style="max-height: 400px;">Loading diagnostics...</div>
            </div>
        </div>
    </div>

    <footer>
        Agent Reach &bull; Universal Web & Video Content Extractor &bull; English Edition
    </footer>

    <script>
        function setSample(url) {
            document.getElementById('urlInput').value = url;
            handleExtract();
        }

        async function handleExtract() {
            const urlInput = document.getElementById('urlInput');
            const url = urlInput.value.trim();
            if (!url) return;

            const btn = document.getElementById('extractBtn');
            const btnText = document.getElementById('btnText');
            const btnSpinner = document.getElementById('btnSpinner');
            const panel = document.getElementById('resultPanel');

            btn.disabled = true;
            btnText.textContent = 'Extracting...';
            btnSpinner.style.display = 'inline-block';

            try {
                const resp = await fetch('/api/extract', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url })
                });

                if (!resp.ok) {
                    const err = await resp.json();
                    throw new Error(err.detail || 'Extraction failed');
                }

                const data = await resp.json();
                document.getElementById('resTitle').textContent = data.title;
                document.getElementById('resPlatform').textContent = data.platform;
                document.getElementById('resAuthor').textContent = data.author;
                document.getElementById('resContent').textContent = data.content;
                panel.style.display = 'block';
                panel.scrollIntoView({ behavior: 'smooth' });
            } catch (err) {
                alert('Error: ' + err.message);
            } finally {
                btn.disabled = false;
                btnText.textContent = 'Fetch / Extract';
                btnSpinner.style.display = 'none';
            }
        }

        function copyContent() {
            const text = document.getElementById('resContent').textContent;
            navigator.clipboard.writeText(text).then(() => {
                alert('Copied to clipboard!');
            });
        }

        async function openDoctorModal() {
            const modal = document.getElementById('doctorModal');
            const docBox = document.getElementById('doctorContent');
            modal.style.display = 'flex';
            docBox.textContent = 'Running agent-reach doctor check...';

            try {
                const resp = await fetch('/api/doctor');
                const data = await resp.json();
                docBox.textContent = data.output || 'No output received';
            } catch (err) {
                docBox.textContent = 'Failed to execute doctor: ' + err.message;
            }
        }

        function closeDoctorModal() {
            document.getElementById('doctorModal').style.display = 'none';
        }

        window.onclick = function(e) {
            const modal = document.getElementById('doctorModal');
            if (e.target === modal) closeDoctorModal();
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")

