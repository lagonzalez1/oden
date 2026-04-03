from fastapi import APIRouter

from api.records import router as records_router

api_router = APIRouter()

# v1 routes — add more routers here as the project grows
api_router.include_router(records_router, prefix="/v1")
