from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.declarative import declared_attr


class CustomBase:
    # Generate __tablename__ automatically based on class name
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()

    # Add common columns here if needed
    # id = Column(Integer, primary_key=True, index=True)
    # created_at = Column(DateTime, default=datetime.utcnow)
    # updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Use CustomBase as the base for all models
Base = declarative_base(cls=CustomBase) 