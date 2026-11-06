from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.api.api_v1 import api_router
from app.services.page_cache_manager import page_cache_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Khởi động: làm sạch thư mục cache tạm
    page_cache_manager.clear_all()
    yield
    # Tắt server: giải phóng 100% cache JSON và file âm thanh
    page_cache_manager.clear_all()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Backend API phục vụ Extension Dịch thuật & Đọc web đa luồng chuẩn ReviewMatThon",
    lifespan=lifespan
)

# Cấu hình CORS mở rộng cho phép Extension gọi vào mà không bị chặn
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/", summary="Health check endpoint")
def root():
    return {
        "status": "online",
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "api_docs": "/docs"
    }

