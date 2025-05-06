from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime

# Shared properties
class CategoryBase(BaseModel):
    name: str
    workspace_id: Optional[int] = None # Make optional here, will be set in endpoint or required in Create

# Properties to receive on item creation
class CategoryCreate(CategoryBase):
    name: str # Make name required again for creation
    workspace_id: int # Make workspace_id required for creation

# Properties to receive on item update
class CategoryUpdate(CategoryBase):
    name: Optional[str] = None # Allow partial updates

# Properties shared by models stored in DB
class CategoryInDBBase(CategoryBase):
    id: int
    workspace_id: int # workspace_id is always present in DB
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True) # Use model_config for Pydantic v2

# Properties to return to client
class Category(CategoryInDBBase):
    pass

# Properties stored in DB
class CategoryInDB(CategoryInDBBase):
    pass
