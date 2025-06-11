from pydantic import BaseModel
from typing import List, Optional, Dict

from .task import TaskStatus, TaskPriority # Import enums

# Schema for summary statistics
class ReportSummary(BaseModel):
    created_tickets: int
    resolved_tickets: int
    unresolved_tickets: int
    average_response_time: Optional[str] # Placeholder for now
    avg_first_response_time: Optional[str] # Placeholder for now
    # Add counts for charts
    status_counts: Dict[TaskStatus, int] = {}
    priority_counts: Dict[TaskPriority, int] = {}

# Schema for data points in time-based charts (e.g., by hour or day)
class TimeSeriesDataPoint(BaseModel):
    time_unit: str # e.g., "01", "02", ... or "Mon", "Tue", ...
    count: int

# Schema for data points in category-based charts (e.g., by status or priority)
class CategoryDataPoint(BaseModel):
    category_name: str # e.g., "Open", "Closed", "High", "Medium"
    count: int

# Potentially a combined schema if one endpoint returns all data
# We might not need this if we fetch data per chart/section
# class FullReportData(BaseModel):
#     summary: ReportSummary
#     created_by_hour: List[TimeSeriesDataPoint]
#     created_by_day: List[TimeSeriesDataPoint]
#     created_by_status: List<CategoryDataPoint> # Use CategoryDataPoint
#     created_by_priority: List<CategoryDataPoint> # Use CategoryDataPoint

# You might create more specific schemas for each endpoint's response later
