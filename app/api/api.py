from fastapi import APIRouter

from app.api.endpoints import auth, users, agents, tasks, teams, companies, microsoft, profile

api_router = APIRouter()
api_router.include_router(auth.router, tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(microsoft.router, prefix="/microsoft", tags=["microsoft"])
api_router.include_router(profile.router, tags=["profile"]) 