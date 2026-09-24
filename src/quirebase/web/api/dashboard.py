from fastapi import APIRouter

from quirebase.library import get_dashboard_data
from quirebase.web.api.dashboard_schemas import DashboardView
from quirebase.web.api.dependencies import ApiUser, Database
from quirebase.web.api.library_schemas import item_search_view
from quirebase.web.api.serialization import enum_value

router = APIRouter(tags=["Dashboard"])


@router.get("/dashboard", response_model=DashboardView)
async def dashboard(workspace_id: str, user: ApiUser, db: Database):
    data = await get_dashboard_data(db, user, workspace_id)
    return {
        "new_items": [item_search_view(item) for item in data["new_items"]],
        "recent_items": [
            {"item": item_search_view(item), "last_read_at": last_read_at}
            for item, last_read_at in data["recent_items"]
        ],
        "projects": [
            {"id": project.id, "name": project.name, "visibility": enum_value(project.visibility)}
            for project in data["projects"]
        ],
        "session_count": len(data["sessions"]),
    }
