#!/usr/bin/env python3
"""
Research Agent — backend (demo build)

Simulates an autonomous research agent's workflow: plan sub-questions,
search the web, read sources, and synthesize a cited report. The step
sequence below is scripted (fixed timings and canned tool results) so the
project can be demonstrated and screenshotted without live API keys.

Swapping SIMULATE = False and wiring real_search()/real_llm_call() in
agent_core() would turn this into a live agent against an LLM + search API
with no change to the frontend or the event protocol.

Stdlib only: http.server for the API/static files, no third-party deps.
"""
import json
import queue
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SIMULATE = True
FRONTEND_DIR = Path(__file__).parent / "frontend"

# ---------------------------------------------------------------------------
# Canned knowledge base: per-topic sub-questions and "search results" so the
# demo reads coherently for any of the sample topics offered in the UI.
# ---------------------------------------------------------------------------
TOPIC_LIBRARY = {
    "quantum computing in drug discovery": {
        "subquestions": [
            "How is quantum computing currently used in molecular simulation?",
            "What pharmaceutical companies are investing in quantum computing R&D?",
            "What are the main technical barriers to quantum advantage in drug discovery?",
        ],
        "sources": [
            ("Quantum Simulation of Molecular Systems", "quantumjournal.example.org/molecular-sim-2025"),
            ("Pfizer and IBM Quantum Partnership Expands", "techbio-news.example.com/pfizer-ibm-quantum"),
            ("Why Quantum Advantage Remains Elusive for Chemistry", "arxiv-digest.example.org/qc-chemistry-barriers"),
            ("Roche Invests $50M in Quantum Drug Discovery Startup", "biopharma-wire.example.com/roche-quantum-invest"),
            ("NISQ-era Algorithms for Protein Folding", "quantumjournal.example.org/nisq-protein-folding"),
        ],
    },
    "impact of remote work on urban real estate": {
        "subquestions": [
            "How has commercial office vacancy changed since the shift to remote work?",
            "Which cities have seen the largest residential price shifts due to remote work migration?",
            "What policy responses are cities adopting to office-to-residential conversion?",
        ],
        "sources": [
            ("Office Vacancy Hits Record Highs in Major US Metros", "realestate-insights.example.com/office-vacancy-2025"),
            ("The Great Reshuffling: Where Remote Workers Moved", "urbanpolicy-review.example.org/reshuffling-report"),
            ("San Francisco Office-to-Residential Conversion Incentives", "citylab-brief.example.com/sf-conversion-2025"),
            ("Suburban Home Prices Outpace Urban Core Post-2023", "housingdata-weekly.example.com/suburban-price-trend"),
            ("Commercial Real Estate Lenders Face Rising Defaults", "finance-brief.example.org/cre-loan-defaults"),
        ],
    },
    "ai agents in enterprise software": {
        "subquestions": [
            "What are the most common enterprise use cases for AI agents today?",
            "What are the main risks organizations cite when deploying autonomous agents?",
            "Which vendors lead the enterprise agent tooling market?",
        ],
        "sources": [
            ("State of Enterprise AI Agents 2026", "enterprise-ai-report.example.com/state-of-agents-2026"),
            ("Why 60% of Agent Pilots Stall Before Production", "cio-digest.example.org/agent-pilots-stall"),
            ("Salesforce, Microsoft, and the Agent Platform Race", "techmarket-watch.example.com/agent-platform-race"),
            ("Governance Frameworks for Autonomous AI Systems", "enterprise-ai-report.example.com/agent-governance"),
            ("Case Study: Agent-Automated Invoice Processing at Scale", "cio-digest.example.org/invoice-automation-case"),
        ],
    },
}

DEFAULT_TOPIC_KEY = "ai agents in enterprise software"


def match_topic(topic: str) -> str:
    t = topic.strip().lower()
    if t in TOPIC_LIBRARY:
        return t
    for key in TOPIC_LIBRARY:
        if key in t or t in key:
            return key
    return DEFAULT_TOPIC_KEY


def make_snippet(title: str) -> str:
    return (
        f"{title} — overview of recent developments, key figures, and analyst "
        f"commentary relevant to the research question, summarizing primary "
        f"findings and their implications for the broader field."
    )


# ---------------------------------------------------------------------------
# Scripted agent run. Emits events onto a queue consumed by the SSE stream.
# ---------------------------------------------------------------------------
def agent_core(topic: str, emit):
    key = match_topic(topic)
    data = TOPIC_LIBRARY[key]
    subquestions = data["subquestions"]
    all_sources = data["sources"]

    emit("plan", {"message": f"Starting research on: \"{topic}\"", "topic": topic})
    time.sleep(0.6)
    emit("thought", {
        "step": 1,
        "message": "Breaking this topic into focused sub-questions before searching.",
    })
    time.sleep(0.8)
    emit("plan", {"message": "Sub-questions identified", "subquestions": subquestions})
    time.sleep(0.5)

    collected_sources = []
    step = 2
    src_cursor = 0

    for sq in subquestions:
        emit("thought", {"step": step, "message": f"Researching: {sq}"})
        time.sleep(0.5)

        n_results = random.randint(1, 2)
        batch = all_sources[src_cursor: src_cursor + n_results] or all_sources[:1]
        src_cursor += n_results

        emit("tool_call", {"step": step, "tool": "web_search", "args": {"query": sq}})
        time.sleep(0.9)

        results = []
        for title, url in batch:
            if not any(s["url"] == url for s in collected_sources):
                collected_sources.append({"url": url, "title": title})
            citation = next(i + 1 for i, s in enumerate(collected_sources) if s["url"] == url)
            results.append({
                "title": title,
                "url": url,
                "snippet": make_snippet(title),
                "citation": citation,
            })

        emit("tool_result", {
            "step": step,
            "tool": "web_search",
            "result": {"query": sq, "results": results},
        })
        time.sleep(0.4)
        step += 1

    emit("thought", {
        "step": step,
        "message": "Gathered enough sources across all sub-questions. Reading top result in more detail before writing the report.",
    })
    time.sleep(0.6)

    deep_title, deep_url = collected_sources[0]["title"], collected_sources[0]["url"]
    emit("tool_call", {"step": step, "tool": "fetch_page", "args": {"url": deep_url}})
    time.sleep(1.0)
    emit("tool_result", {
        "step": step,
        "tool": "fetch_page",
        "result": {"url": deep_url, "content": make_snippet(deep_title) + " " + make_snippet(deep_title)},
    })
    step += 1
    time.sleep(0.5)

    emit("thought", {"step": step, "message": "Synthesizing findings into a final cited report."})
    time.sleep(1.0)

    report = build_report(topic, subquestions, collected_sources)
    emit("report", {"content": report, "sources": collected_sources})
    time.sleep(0.3)
    emit("done", {"sources": collected_sources, "steps_used": step})


def build_report(topic: str, subquestions: list[str], sources: list[dict]) -> str:
    lines = [f"# Research Report: {topic.title()}", ""]
    lines.append(
        f"This report synthesizes findings across {len(subquestions)} research "
        f"questions, drawing on {len(sources)} sources gathered during the agent's "
        f"search phase."
    )
    lines.append("")
    for i, sq in enumerate(subquestions, 1):
        cites = [c for c in range(1, len(sources) + 1)][: min(2, len(sources))]
        cite_str = " ".join(f"[{c}]" for c in cites)
        lines.append(f"## {i}. {sq}")
        lines.append(
            f"Current evidence indicates meaningful, measurable movement on this "
            f"question {cite_str}. Multiple independent sources point to "
            f"accelerating activity, though the picture remains uneven across "
            f"different organizations and regions, and longer-term outcomes are "
            f"still unresolved."
        )
        lines.append("")
    lines.append("## Summary")
    lines.append(
        "Taken together, the sources suggest this is an active, fast-moving area "
        "with real investment and deployment, but also real friction — technical, "
        "organizational, or regulatory — that will determine how quickly it "
        "matures."
    )
    lines.append("")
    lines.append("## Sources")
    for i, s in enumerate(sources, 1):
        lines.append(f"[{i}] {s['title']} — {s['url']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTTP server: serves the static frontend and an SSE endpoint at /api/run
# ---------------------------------------------------------------------------
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/run":
            self.handle_run(parse_qs(parsed.query))
            return

        if parsed.path == "/api/topics":
            self.send_json({"topics": list(TOPIC_LIBRARY.keys())})
            return

        self.serve_static(parsed.path)

    def serve_static(self, path: str):
        if path == "/":
            path = "/index.html"
        file_path = (FRONTEND_DIR / path.lstrip("/")).resolve()

        if FRONTEND_DIR.resolve() not in file_path.parents and file_path != FRONTEND_DIR.resolve():
            self.send_error(403)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404)
            return

        ctype = CONTENT_TYPES.get(file_path.suffix, "application/octet-stream")
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_run(self, query):
        topic = (query.get("topic", ["AI agents in enterprise software"])[0]).strip() or "AI agents in enterprise software"

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        q: "queue.Queue[tuple[str, dict] | None]" = queue.Queue()

        def emit(event_type, data):
            q.put((event_type, data))

        def worker():
            try:
                agent_core(topic, emit)
            except Exception as e:
                q.put(("error", {"message": str(e)}))
            finally:
                q.put(None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        try:
            while True:
                item = q.get()
                if item is None:
                    self.wfile.write(b"event: close\ndata: {}\n\n")
                    self.wfile.flush()
                    break
                event_type, data = item
                payload = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                self.wfile.write(payload.encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    port = 8000
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"Research Agent demo server running at http://localhost:{port}")
    print("(Demo mode: agent steps are scripted — no live API keys required)")
    server.serve_forever()


if __name__ == "__main__":
    main()
