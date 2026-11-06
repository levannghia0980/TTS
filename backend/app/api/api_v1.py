from fastapi import APIRouter
from app.api.endpoints import settings, translate, tts, reader_session

api_router = APIRouter()
api_router.include_router(settings.router, prefix="/settings", tags=["Settings"])
api_router.include_router(translate.router, prefix="/translate", tags=["Translate"])
api_router.include_router(tts.router, prefix="/tts", tags=["Text-to-Speech"])
api_router.include_router(reader_session.router, tags=["Reader Session"])
