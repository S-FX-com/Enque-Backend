from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Enum, ForeignKey, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database.base_class import Base
import enum


class ConditionType(enum.Enum):
    DESCRIPTION = "DESCRIPTION"
    NOTE = "NOTE"
    USER = "USER"
    AGENT = "AGENT"
    COMPANY = "COMPANY"
    PRIORITY = "PRIORITY"
    CATEGORY = "CATEGORY"


class ConditionOperator(enum.Enum):
    EQL = "eql"
    NEQL = "neql"
    CON = "con"
    NCON = "ncon"


class ActionType(enum.Enum):
    SET_AGENT = "SET_AGENT"
    SET_PRIORITY = "SET_PRIORITY"
    SET_STATUS = "SET_STATUS"
    SET_TEAM = "SET_TEAM"


class Automation(Base):
    __tablename__ = "automations"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_by = Column(Integer, ForeignKey("agents.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    conditions = relationship("AutomationCondition", back_populates="automation", cascade="all, delete-orphan")
    actions = relationship("AutomationAction", back_populates="automation", cascade="all, delete-orphan")
    
    # Foreign key relationships
    workspace = relationship("Workspace")
    creator = relationship("Agent", foreign_keys=[created_by])


class AutomationCondition(Base):
    __tablename__ = "automation_conditions"

    id = Column(Integer, primary_key=True, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id", ondelete="CASCADE"), nullable=False)
    condition_type = Column(Enum(ConditionType), nullable=False)
    condition_operator = Column(Enum(ConditionOperator), default=ConditionOperator.EQL)
    condition_value = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    automation = relationship("Automation", back_populates="conditions")


class AutomationAction(Base):
    __tablename__ = "automation_actions"

    id = Column(Integer, primary_key=True, index=True)
    automation_id = Column(Integer, ForeignKey("automations.id", ondelete="CASCADE"), nullable=False)
    action_type = Column(Enum(ActionType), nullable=False)
    action_value = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    automation = relationship("Automation", back_populates="actions") 