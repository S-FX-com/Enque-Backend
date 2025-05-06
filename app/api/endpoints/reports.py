from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
# Corrected imports: remove extract, ensure func and case are present
from sqlalchemy import func, case 
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta

from app.api import dependencies
from app.database.session import get_db
from app.models.agent import Agent
from app.models.task import Task # Import Task model
from app.schemas.task import TaskStatus, TaskPriority # Import enums
from app.schemas import report as report_schema # Import report schemas

router = APIRouter()

# Use the specific response model
@router.get("/summary", response_model=report_schema.ReportSummary, status_code=status.HTTP_200_OK)
def get_report_summary(
    *,
    db: Session = Depends(dependencies.get_db),
    current_user: Agent = Depends(dependencies.get_current_active_user),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering (ISO format)")
):
    """
    Endpoint to retrieve summary report statistics.
    """
    # Placeholder logic - replace with actual calculations
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date:
        end_date = datetime.utcnow()

    # Define base_query first
    base_query = db.query(Task).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.created_at >= start_date,
        Task.created_at <= end_date
    )

    # Calculate counts using conditional aggregation *after* defining base_query
    counts = base_query.with_entities(
        func.count(Task.id).label("created_tickets"),
        func.sum(case((Task.status == TaskStatus.CLOSED, 1), else_=0)).label("resolved_tickets"),
        func.sum(case((Task.status != TaskStatus.CLOSED, 1), else_=0)).label("unresolved_tickets"),
        # Group by status
        func.count(case((Task.status == TaskStatus.OPEN, Task.id))).label("open_count"),
        func.count(case((Task.status == TaskStatus.CLOSED, Task.id))).label("closed_count"),
        func.count(case((Task.status == TaskStatus.UNREAD, Task.id))).label("unread_count"),
         # Group by priority
        func.count(case((Task.priority == TaskPriority.LOW, Task.id))).label("low_priority_count"),
        func.count(case((Task.priority == TaskPriority.MEDIUM, Task.id))).label("medium_priority_count"),
        func.count(case((Task.priority == TaskPriority.HIGH, Task.id))).label("high_priority_count")
    ).first()

    # TODO: Calculate Avg Response Times (more complex, requires joining comments/activities)

    # Prepare response data
    summary_data = {
        "created_tickets": counts.created_tickets or 0,
        "resolved_tickets": counts.resolved_tickets or 0,
        "unresolved_tickets": counts.unresolved_tickets or 0,
        "average_response_time": "N/A", # Placeholder
        "avg_first_response_time": "N/A", # Placeholder
        "status_counts": {
            TaskStatus.OPEN: counts.open_count or 0,
            TaskStatus.CLOSED: counts.closed_count or 0,
            TaskStatus.UNREAD: counts.unread_count or 0,
        },
        "priority_counts": {
            TaskPriority.LOW: counts.low_priority_count or 0,
            TaskPriority.MEDIUM: counts.medium_priority_count or 0,
            TaskPriority.HIGH: counts.high_priority_count or 0,
        }
    }

    # Return data conforming to the ReportSummary schema
    return report_schema.ReportSummary(**summary_data)


@router.get("/created_by_hour", response_model=List[report_schema.TimeSeriesDataPoint], status_code=status.HTTP_200_OK)
def get_tickets_created_by_hour(
    *,
    db: Session = Depends(dependencies.get_db),
    current_user: Agent = Depends(dependencies.get_current_active_user),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering (ISO format)")
):
    """
    Get the count of tickets created per hour within a date range.
    """
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date:
        end_date = datetime.utcnow()

    # Query to group by hour and count tickets
    results = db.query(
        func.extract('hour', Task.created_at).label('hour'), # Use func.extract for hour
        func.count(Task.id).label('count')
    ).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.created_at >= start_date,
        Task.created_at <= end_date
    ).group_by(
        func.extract('hour', Task.created_at) # Group by hour
    ).order_by(
        func.extract('hour', Task.created_at) # Order by hour
    ).all()

    # Format results into the TimeSeriesDataPoint schema
    # Create a dictionary for all 24 hours initialized to 0
    hourly_counts = {f"{h:02d}": 0 for h in range(24)}
    for row in results:
        hour_str = f"{int(row.hour):02d}" # Format hour as two digits (e.g., 01, 09, 15)
        hourly_counts[hour_str] = row.count

    # Convert the dictionary to the list format required by the schema
    formatted_results = [
        report_schema.TimeSeriesDataPoint(time_unit=hour, count=count)
        for hour, count in hourly_counts.items()
    ]

    return formatted_results


@router.get("/created_by_day", response_model=List[report_schema.TimeSeriesDataPoint], status_code=status.HTTP_200_OK)
def get_tickets_created_by_day(
    *,
    db: Session = Depends(dependencies.get_db),
    current_user: Agent = Depends(dependencies.get_current_active_user),
    start_date: Optional[datetime] = Query(None, description="Start date for filtering (ISO format)"),
    end_date: Optional[datetime] = Query(None, description="End date for filtering (ISO format)")
):
    """
    Get the count of tickets created per day of the week within a date range.
    """
    if not start_date:
        start_date = datetime.utcnow() - timedelta(days=7)
    if not end_date:
        end_date = datetime.utcnow()

    # Corrected: Use func.weekday for MySQL compatibility (0=Mon, 6=Sun)
    results = db.query(
        func.weekday(Task.created_at).label('weekday'), 
        func.count(Task.id).label('count')
    ).filter(
        Task.workspace_id == current_user.workspace_id,
        Task.created_at >= start_date,
        Task.created_at <= end_date
    ).group_by(
        func.weekday(Task.created_at) 
    ).order_by(
        func.weekday(Task.created_at) 
    ).all()

    # Format results into the TimeSeriesDataPoint schema (Mon-Sun)
    days_of_week = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    daily_counts = {day: 0 for day in days_of_week}

    for row in results:
        day_index = int(row.weekday)
        # Ensure index is within bounds (should be 0-6)
        if 0 <= day_index < len(days_of_week):
            day_name = days_of_week[day_index] # Map index to name
            daily_counts[day_name] = row.count
        else:
            # Log unexpected weekday index if necessary
            print(f"Warning: Unexpected weekday index {day_index} encountered.")


    # Convert the dictionary to the list format required by the schema, maintaining order
    formatted_results = [
        report_schema.TimeSeriesDataPoint(time_unit=day, count=daily_counts[day])
        for day in days_of_week
    ]

    return formatted_results


# Add more endpoints here for other report types
