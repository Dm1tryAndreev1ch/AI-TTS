import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from gateway.config import Settings
from gateway.server import AudioSocketServer

logging.basicConfig(level=logging.INFO, format='%(message)s')

@asynccontextmanager
async def lifespan(app: FastAPI):
    server = AudioSocketServer(Settings())
    app.state.audio = server
    await server.start()
    try:
        yield
    finally:
        await server.stop()

app = FastAPI(title='AI-TTS AudioSocket gateway', lifespan=lifespan)

@app.get('/health')
async def health() -> dict:
    return {'status': 'ok', 'active_calls': len(app.state.audio.sessions), 'mode': 'transport-only'}
