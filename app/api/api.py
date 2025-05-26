from fastapi import APIRouter, Response

from app.api.endpoints import auth, users, agents, tasks, teams, companies, microsoft, profile, workspaces, comments, activities, uploads, categories, reports, attachments, global_signatures, notifications, automations, workflows, canned_replies

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
api_router.include_router(activities.router, tags=["activities"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(attachments.router, tags=["attachments"])
api_router.include_router(global_signatures.router, prefix="/global-signatures", tags=["global-signatures"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(automations.router, prefix="/workspaces", tags=["automations"])
api_router.include_router(workflows.router, prefix="/workspaces", tags=["workflows"])
api_router.include_router(canned_replies.router, prefix="/canned-replies", tags=["canned-replies"])

@api_router.get("/health", tags=["health"])
async def health_check():
    """
    Simple health check endpoint to verify the API is running.
    """
    return {"status": "ok"}
