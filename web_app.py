# -*- coding: utf-8 -*-
"""
Agent Reach - Web UI & API Server
Built with FastAPI to provide public web access on Railway / Docker.
"""

import os
import re
import json
import tempfile
import subprocess
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(title="Agent Reach Web UI", version="1.0.0")

class ExtractRequest(BaseModel):
    url: str

def clean_vtt(vtt_text: str) -> str:
    """Parse VTT subtitles into clean readable transcript."""
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
        line = re.sub(r"<[^>]+>", "", line)
        if line and line not in seen:
            seen.add(line)
            clean_lines.append(line)
            
    return "\n\n".join(clean_lines)

def extract_youtube(url: str) -> Dict[str, Any]:
    """Extract metadata and subtitles using yt-dlp."""
    try:
        # 1. Fetch metadata JSON
        meta_cmd = ["yt-dlp", "--dump-json", "--no-warnings", url]
        meta_res = subprocess.run(meta_cmd, capture_output=True, text=True, timeout=30)
        
        metadata = {}
        if meta_res.returncode == 0 and meta_res.stdout.strip():
            metadata = json.loads(meta_res.stdout)
            
        title = metadata.get("title", "YouTube Video")
        uploader = metadata.get("uploader", "Unknown")
        duration = metadata.get("duration", 0)
        views = metadata.get("view_count", 0)
        thumbnail = metadata.get("thumbnail", "")
        description = metadata.get("description", "")
        
        # 2. Extract subtitles/transcript
        with tempfile.TemporaryDirectory() as tmpdir:
            out_template = os.path.join(tmpdir, "caption_%(id)s")
            sub_cmd = [
                "yt-dlp",
                "--write-sub",
                "--write-auto-sub",
                "--sub-lang", "en,zh-Hans,zh,es",
                "--skip-download",
                "--no-warnings",
                "-o", out_template,
                url
            ]
            subprocess.run(sub_cmd, capture_output=True, text=True, timeout=45)
            
            transcript = ""
            vtt_files = [f for f in os.listdir(tmpdir) if f.endswith(".vtt")]
            if vtt_files:
                target_file = os.path.join(tmpdir, vtt_files[0])
                with open(target_file, "r", encoding="utf-8", errors="ignore") as f:
                    transcript = clean_vtt(f.read())
                    
            if not transcript:
                transcript = f"*No automated English/Chinese transcript was available for this video.*\n\n**Video Description:**\n\n{description[:1500]}"
                
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
    """Extract web article or general URL content via Jina Reader."""
    try:
        from agent_reach.channels.web import WebChannel
        content = WebChannel().read(url)
        
        # Determine title from markdown if available
        title = url
        first_lines = [l.strip() for l in content.splitlines() if l.strip()][:5]
        for l in first_lines:
            if l.startswith("Title:"):
                title = l.replace("Title:", "").strip()
                break
            elif l.startswith("# "):
                title = l.replace("# ", "").strip()
                break
                
        return {
            "platform": "Web (Jina Reader)",
            "title": title,
            "author": "Web Reader",
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

@app.get("/api/doctor")
async def doctor_status():
    """Runs a quick doctor check and returns text."""
    try:
        import sys
        res = subprocess.run([sys.executable, "-m", "agent_reach.cli", "doctor"], capture_output=True, text=True, timeout=20)
        return {"output": res.stdout or res.stderr or "Doctor completed."}
    except Exception as e:
        return {"output": f"Doctor check error: {str(e)}"}

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

        .logo {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-size: 1.25rem;
            font-weight: 800;
            background: var(--accent-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .logo-badge {
            font-size: 0.75rem;
            font-weight: 600;
            padding: 0.2rem 0.6rem;
            border-radius: 9999px;
            background: rgba(59, 130, 246, 0.15);
            color: #60a5fa;
            border: 1px solid rgba(59, 130, 246, 0.3);
            -webkit-text-fill-color: initial;
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

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        footer {
            text-align: center;
            padding: 2rem 1.5rem;
            color: var(--text-muted);
            font-size: 0.85rem;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            margin-top: auto;
        }
    </style>
</head>
<body>
    <header>
        <div class="navbar">
            <div class="logo">
                👁️ Agent Reach <span class="logo-badge">Live Web Hub</span>
            </div>
            <div class="nav-actions">
                <button class="btn-secondary" onclick="openDoctorModal()">🩺 Channel Doctor</button>
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
                <input type="text" id="urlInput" placeholder="Paste any public URL (YouTube video, blog, article, GitHub repo)..." autocomplete="off" />
                <button class="btn-primary" id="extractBtn" onclick="handleExtract()">
                    <span id="btnText">Fetch / Extract</span>
                    <span id="btnSpinner" class="spinner" style="display: none;"></span>
                </button>
            </div>
            <div class="sample-chips">
                <span class="sample-label">Try sample:</span>
                <div class="chip" onclick="setSample('https://www.youtube.com/watch?v=jNQXAC9IVRw')">📺 YouTube Video (Me at the zoo)</div>
                <div class="chip" onclick="setSample('https://example.com')">🌐 Web Article (Example.com)</div>
                <div class="chip" onclick="setSample('https://github.com/Panniantong/agent-reach')">📦 GitHub Repo (agent-reach)</div>
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
                <h3>🩺 Agent Reach Channel Status</h3>
                <button class="close-btn" onclick="closeDoctorModal()">&times;</button>
            </div>
            <div class="modal-body">
                <div class="content-box" id="doctorContent" style="max-height: 400px;">Loading diagnostic...</div>
            </div>
        </div>
    </div>

    <footer>
        Deployed with Docker on Railway &bull; Powered by Panniantong/agent-reach
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
