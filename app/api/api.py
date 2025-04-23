from fastapi import APIRouter, Response

# Add activities to the import
from app.api.endpoints import auth, users, agents, tasks, teams, companies, microsoft, profile, workspaces, comments, activities

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(microsoft.router, prefix="/microsoft", tags=["microsoft"])
api_router.include_router(profile.router, tags=["profile"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
api_router.include_router(comments.router, tags=["comments"])
api_router.include_router(activities.router, tags=["activities"]) # Include activities router

# Simple health check endpoint directly in the main router
@api_router.get("/health", tags=["health"])
async def health_check():
    """
    Simple health check endpoint to verify the API is running.
    """
    return {"status": "ok"}
