import logging
import pathlib

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.routers import pdf, webhook

logging.basicConfig(level=logging.DEBUG)

app = FastAPI(
    title="Evolution API Webhook",
    description="Webhook handler para Evolution API + WhatsApp Cloud API",
    version="0.3.0",
)

app.include_router(webhook.router, prefix="/webhook", tags=["webhook"])
app.include_router(pdf.router)

_STATIC = pathlib.Path(__file__).parent.parent / "static"


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    return (_STATIC / "index.html").read_text(encoding="utf-8")


@app.get("/health")
async def health_check():
    return {"status": "ok"}


@app.get("/qr/{instance}", response_class=HTMLResponse, tags=["qrcode"])
async def show_qr(instance: str):
    """Exibe o QR Code da instância para escanear com o WhatsApp."""
    from app.services.message_handler import qr_store
    base64_img = qr_store.get(instance)
    if not base64_img:
        return HTMLResponse(content="""
            <html><body style="font-family:sans-serif;text-align:center;padding:40px">
              <h2>QR Code não disponível</h2>
              <p>Aguarde alguns segundos e recarregue.<br>
              A instância deve estar no estado <b>connecting</b>.</p>
              <script>setTimeout(()=>location.reload(),4000)</script>
            </body></html>""", status_code=202)
    return HTMLResponse(content=f"""
        <html><body style="font-family:sans-serif;text-align:center;padding:40px">
          <h2>Escaneie com o WhatsApp — <b>{instance}</b></h2>
          <img src="{base64_img}" style="width:300px;height:300px;border:2px solid #ccc;border-radius:8px"/>
          <p>A página recarrega a cada 20 segundos.</p>
          <script>setTimeout(()=>location.reload(),20000)</script>
        </body></html>""")
