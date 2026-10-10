from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.get("/vulnerable")
def vulnerable():
    return HTMLResponse("<h1>Local demo: missing security headers</h1><p>Intentionally incomplete header configuration.</p>")


@app.get("/hardened")
def hardened():
    return HTMLResponse("<h1>Local demo: security headers configured</h1>", headers={
        "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"})


@app.get("/redirect")
def redirect():
    return RedirectResponse("http://127.0.0.1:8000/health", status_code=302)
