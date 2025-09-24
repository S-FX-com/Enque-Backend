from fastapi import APIRouter, Response

from app.api.endpoints import (
    agents, auth, comments, microsoft, tasks, users, workspaces, teams, attachments, 
    workflows, canned_replies, automations, companies, profile, activities, uploads, 
    categories, reports, global_signatures, notifications, dashboard,
    tasks_optimized, automation_settings, scheduled_comments, teams_redirect
)

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(agents.router, prefix="/agents", tags=["agents"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(teams.router, prefix="/teams", tags=["teams"])
api_router.include_router(teams_redirect.router, prefix="/teams", tags=["teams"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(microsoft.router, prefix="/microsoft", tags=["microsoft"])
api_router.include_router(profile.router, prefix="/profile", tags=["profile"])
api_router.include_router(workspaces.router, prefix="/workspaces", tags=["workspaces"])
api_router.include_router(activities.router, tags=["activities"])
api_router.include_router(comments.router, tags=["comments"])
api_router.include_router(uploads.router, prefix="/uploads", tags=["uploads"])
api_router.include_router(categories.router, prefix="/categories", tags=["categories"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(attachments.router, tags=["attachments"])
api_router.include_router(global_signatures.router, prefix="/global-signatures", tags=["global-signatures"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(workflows.router, prefix="/workspaces", tags=["workflows"])
api_router.include_router(canned_replies.router, prefix="/canned-replies", tags=["canned-replies"])
api_router.include_router(automations.router, prefix="/automations", tags=["automations"])
api_router.include_router(automation_settings.router, prefix="/automation-settings", tags=["automation-settings"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(tasks_optimized.router, prefix="/tasks-optimized", tags=["tasks-optimized"])
api_router.include_router(scheduled_comments.router, tags=["scheduled-comments"])
