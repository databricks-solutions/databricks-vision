from .batches import router as batches_router
from .batch_images import router as batch_images_router
from .search import router as search_router
from .volumes import router as volumes_router
from .gallery import router as gallery_router
from .generate import router as generate_router
from .settings import router as settings_router
from .style_guidelines import router as style_guidelines_router

__all__ = [
    "batches_router",
    "batch_images_router",
    "search_router",
    "volumes_router",
    "gallery_router",
    "generate_router",
    "settings_router",
    "style_guidelines_router",
]
