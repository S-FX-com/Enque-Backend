from sqlalchemy.orm import Session
from sqlalchemy import and_
from fastapi import HTTPException, Request

from app.models.comment import Comment
from app.schemas.comment import CommentCreate, CommentUpdate


def create_comment(db: Session, comment_data: CommentCreate) -> Comment:
    db_comment = Comment(**comment_data.dict())
    db.add(db_comment)
    db.commit()
    db.refresh(db_comment)
    return db_comment


def get_comments(db: Session, request: Request, skip: int, limit: int) -> list[Comment]:
    query = db.query(Comment)

    filter_conditions = []
    for key, value in request.query_params.items():
        if key.startswith("filter[") and key.endswith("]"):
            field_name = key[7:-1]
            if hasattr(Comment, field_name):
                column = getattr(Comment, field_name)

                if column.property.columns[0].type.python_type == int:
                    value = int(value)
                elif column.property.columns[0].type.python_type == float:
                    value = float(value)
                elif column.property.columns[0].type.python_type == bool:
                    value = value.lower() in ["true", "1", "yes"]

                if isinstance(value, str):
                    filter_conditions.append(column.ilike(f"%{value}%"))
                else:
                    filter_conditions.append(column == value)

    if filter_conditions:
        query = query.filter(and_(*filter_conditions))

    return query.offset(skip).limit(limit).all()


def get_comment(db: Session, comment_id: int) -> Comment:
    comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")
    return comment


def update_comment(db: Session, comment_id: int, comment_data: CommentUpdate) -> Comment:
    db_comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if db_comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    update_data = comment_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_comment, key, value)

    db.commit()
    db.refresh(db_comment)
    return db_comment


def delete_comment(db: Session, comment_id: int) -> None:
    db_comment = db.query(Comment).filter(Comment.id == comment_id).first()
    if db_comment is None:
        raise HTTPException(status_code=404, detail="Comment not found")

    db.delete(db_comment)
    db.commit()
