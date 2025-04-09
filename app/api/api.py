from fastapi import APIRouter

from app.api.endpoints import agents, auth, workspaces, tickets, teams, comments, activities, users, companies, microsoft

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(agents.router, prefix="/agents", tags=["Agents"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["Workspaces"])
api_router.include_router(tickets.router, prefix="/tickets", tags=["Tickets"])
api_router.include_router(teams.router, prefix="/teams", tags=["Teams"])
api_router.include_router(comments.router, prefix="/comments", tags=["Comments"])
api_router.include_router(activities.router, prefix="/activities", tags=["Activities"])
api_router.include_router(users.router, prefix="/users", tags=["Users"])
api_router.include_router(companies.router, prefix="/companies", tags=["Companies"])
api_router.include_router(microsoft.router, prefix="/microsoft", tags=["Microsoft"])

