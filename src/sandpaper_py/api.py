from dataclasses import asdict
from pathlib import Path
from typing import Dict, List, Optional

from .config import ScrapeConfig
from .core import scrape
from .schema import summarize

try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles
    from fastapi.templating import Jinja2Templates
    from pydantic import BaseModel

    _FASTAPI_AVAILABLE = True

    class ScrapeRequest(BaseModel):
        url: Optional[str] = None
        url_list: List[str] = []
        page_template: Optional[str] = None
        pages: Optional[str] = None
        output: Optional[str] = None
        format: str = "csv"
        encoding: str = "utf-8"
        threshold: int = 10
        extractor: str = "heuristic"
        selectors: Dict[str, str] = {}
        row_selector: Optional[str] = None
        follow_field: Optional[str] = None
        follow_selectors: Dict[str, str] = {}
        follow_concurrency: int = 4
        headless: bool = True
        scroll: bool = True
        rate_per_second: float = 0.0
        retries: int = 2
        concurrency: int = 1
        auto_paginate: bool = False
        deduplicate: bool = False
        write_provenance: bool = False
        obey_robots: bool = False
        async_mode: bool = False

except ImportError:
    _FASTAPI_AVAILABLE = False


def _require_fastapi() -> None:
    if not _FASTAPI_AVAILABLE:
        raise RuntimeError("api/web UI need fastapi: pip install 'sandpaper-py[api]'")


def create_app():
    _require_fastapi()

    import asyncio
    import json
    import queue

    package_root = Path(__file__).parent
    templates = Jinja2Templates(directory=str(package_root / "templates"))

    app = FastAPI(title="SandPaper", version="0.1.0")

    static_dir = package_root / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        return templates.TemplateResponse(request, "index.html")

    @app.post("/api/scrape")
    async def api_scrape(payload: ScrapeRequest):
        cfg = ScrapeConfig(**payload.model_dump())
        try:
            result = await asyncio.to_thread(scrape, cfg)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        stats = summarize(result.table)
        return JSONResponse(
            {
                "rows": result.rows,
                "columns": result.columns,
                "output_path": result.output_path,
                "provenance": asdict(result.provenance),
                "stats": {
                    "rows": stats.rows,
                    "columns": [asdict(c) for c in stats.columns],
                },
                "preview": _preview(result.table.columns, limit=5),
            }
        )

    @app.post("/api/scrape/stream")
    async def api_scrape_stream(payload: ScrapeRequest):
        cfg = ScrapeConfig(**payload.model_dump())
        events: queue.Queue[Optional[dict]] = queue.Queue()

        def progress_cb(index: int, total: int, url: str, status: Optional[str]) -> None:
            events.put(
                {
                    "type": "progress",
                    "index": index,
                    "total": total,
                    "url": url,
                    "status": status or "loading",
                }
            )

        async def drain():
            yield _sse({"type": "start"})
            loop = asyncio.get_event_loop()
            future = loop.run_in_executor(None, lambda: scrape(cfg, on_progress=progress_cb))
            while True:
                if future.done():
                    while not events.empty():
                        yield _sse(events.get_nowait())
                    break
                try:
                    item = await asyncio.wait_for(
                        loop.run_in_executor(None, events.get, True, 0.5),
                        timeout=0.6,
                    )
                except (asyncio.TimeoutError, queue.Empty):
                    yield _sse({"type": "heartbeat"})
                    continue
                if item is None:
                    break
                yield _sse(item)
            try:
                result = await future
            except Exception as exc:
                yield _sse({"type": "error", "message": str(exc)})
                return
            yield _sse(
                {
                    "type": "done",
                    "rows": result.rows,
                    "columns": result.columns,
                    "output_path": result.output_path,
                    "preview": _preview(result.table.columns, limit=5),
                }
            )

        return StreamingResponse(drain(), media_type="text/event-stream")

    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    def _sse(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    return app


def _preview(columns: Dict[str, List[str]], limit: int = 5) -> List[Dict[str, str]]:
    if not columns:
        return []
    keys = list(columns.keys())
    max_len = min(limit, max((len(v) for v in columns.values()), default=0))
    rows = []
    for i in range(max_len):
        rows.append({k: columns[k][i] if i < len(columns[k]) else "" for k in keys})
    return rows


def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise RuntimeError("api needs uvicorn: pip install 'sandpaper-py[api]'") from exc
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
