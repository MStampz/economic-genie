"""Budget setup: headings, posts, their categories and monthly amounts."""

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.categories import get_or_create_category
from app.core.deps import GroupAccess, group_access
from app.core.models import Category
from app.db import get_db
from app.modules.budgets.models import COLOR_SLOTS, BudgetHeading, BudgetPost, BudgetPostCategory
from app.modules.budgets.starter import PROTOTYPE_BUDGET

router = APIRouter(prefix="/api/groups/{group_id}/budget", tags=["budget"])


class PostOut(BaseModel):
    id: uuid.UUID
    heading_id: uuid.UUID
    name: str
    color: int
    position: int
    monthly_amount: Decimal | None
    category_ids: list[uuid.UUID]


class HeadingOut(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    posts: list[PostOut]


class BudgetOut(BaseModel):
    headings: list[HeadingOut]


class HeadingIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PostIn(BaseModel):
    heading_id: uuid.UUID
    name: str = Field(min_length=1, max_length=80)
    color: int | None = Field(default=None, ge=1, le=COLOR_SLOTS)
    monthly_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"))
    category_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class PostPatch(BaseModel):
    heading_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: int | None = Field(default=None, ge=1, le=COLOR_SLOTS)
    monthly_amount: Decimal | None = Field(default=None, ge=0, le=Decimal("10000000"))
    clear_amount: bool = False
    category_ids: list[uuid.UUID] | None = Field(default=None, max_length=100)


class OrderIn(BaseModel):
    """The full order: headings top to bottom, each with its posts top to bottom."""

    headings: list[dict] = Field(max_length=100)  # [{"id": heading id, "post_ids": [post ids]}]


def load_budget(db: Session, group_id: uuid.UUID) -> BudgetOut:
    headings = db.scalars(
        select(BudgetHeading).where(BudgetHeading.group_id == group_id).order_by(BudgetHeading.position)
    ).all()
    posts = db.scalars(select(BudgetPost).where(BudgetPost.group_id == group_id).order_by(BudgetPost.position)).all()
    links: dict[uuid.UUID, list[uuid.UUID]] = {}
    for link in db.scalars(select(BudgetPostCategory).where(BudgetPostCategory.group_id == group_id)):
        links.setdefault(link.post_id, []).append(link.category_id)
    return BudgetOut(
        headings=[
            HeadingOut(
                id=h.id,
                name=h.name,
                position=h.position,
                posts=[
                    PostOut(
                        id=p.id,
                        heading_id=p.heading_id,
                        name=p.name,
                        color=p.color,
                        position=p.position,
                        monthly_amount=p.monthly_amount,
                        category_ids=links.get(p.id, []),
                    )
                    for p in posts
                    if p.heading_id == h.id
                ],
            )
            for h in headings
        ]
    )


@router.get("", response_model=BudgetOut)
def get_budget(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    return load_budget(db, access.group.id)


@router.post("/starter", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def create_starter(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    """Creates the prototype's budget structure, without amounts. Only for a group with no budget yet."""
    gid = access.group.id
    if db.scalar(select(func.count()).select_from(BudgetHeading).where(BudgetHeading.group_id == gid)):
        raise HTTPException(status.HTTP_409_CONFLICT, "This group already has a budget.")
    slot = 0
    for hpos, (heading_name, posts) in enumerate(PROTOTYPE_BUDGET):
        h = BudgetHeading(group_id=gid, name=heading_name, position=hpos)
        db.add(h)
        db.flush()
        for ppos, (post_name, cats) in enumerate(posts):
            p = BudgetPost(group_id=gid, heading_id=h.id, name=post_name, position=ppos, color=slot % COLOR_SLOTS + 1)
            slot += 1
            db.add(p)
            db.flush()
            for cat_name in cats:
                c = get_or_create_category(db, gid, cat_name)
                db.add(BudgetPostCategory(group_id=gid, post_id=p.id, category_id=c.id))
    audit.log(db, "budget.starter_created", user_id=access.user.id, group_id=gid)
    db.commit()
    return load_budget(db, gid)


@router.post("/headings", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def add_heading(body: HeadingIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    gid = access.group.id
    last = db.scalar(select(func.max(BudgetHeading.position)).where(BudgetHeading.group_id == gid))
    db.add(BudgetHeading(group_id=gid, name=body.name.strip(), position=(last or 0) + 1))
    audit.log(db, "budget.heading_added", user_id=access.user.id, group_id=gid, name=body.name)
    db.commit()
    return load_budget(db, gid)


@router.patch("/headings/{heading_id}", response_model=BudgetOut)
def rename_heading(
    heading_id: uuid.UUID, body: HeadingIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)
):
    h = _get(db, BudgetHeading, heading_id, access)
    h.name = body.name.strip()
    db.commit()
    return load_budget(db, access.group.id)


@router.delete("/headings/{heading_id}", response_model=BudgetOut)
def delete_heading(heading_id: uuid.UUID, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    """Deletes a heading and its posts. The transactions and categories are not touched."""
    h = _get(db, BudgetHeading, heading_id, access)
    post_ids = select(BudgetPost.id).where(BudgetPost.heading_id == h.id)
    db.execute(delete(BudgetPostCategory).where(BudgetPostCategory.post_id.in_(post_ids)))
    db.execute(delete(BudgetPost).where(BudgetPost.heading_id == h.id))
    db.delete(h)
    audit.log(db, "budget.heading_deleted", user_id=access.user.id, group_id=access.group.id, name=h.name)
    db.commit()
    return load_budget(db, access.group.id)


@router.post("/posts", response_model=BudgetOut, status_code=status.HTTP_201_CREATED)
def add_post(body: PostIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    gid = access.group.id
    _get(db, BudgetHeading, body.heading_id, access)
    count = db.scalar(select(func.count()).select_from(BudgetPost).where(BudgetPost.group_id == gid)) or 0
    last = db.scalar(select(func.max(BudgetPost.position)).where(BudgetPost.heading_id == body.heading_id))
    p = BudgetPost(
        group_id=gid,
        heading_id=body.heading_id,
        name=body.name.strip(),
        color=body.color or count % COLOR_SLOTS + 1,
        position=(last if last is not None else -1) + 1,
        monthly_amount=body.monthly_amount,
    )
    db.add(p)
    db.flush()
    _set_categories(db, access, p, body.category_ids)
    audit.log(db, "budget.post_added", user_id=access.user.id, group_id=gid, name=p.name)
    db.commit()
    return load_budget(db, gid)


@router.patch("/posts/{post_id}", response_model=BudgetOut)
def update_post(
    post_id: uuid.UUID, body: PostPatch, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)
):
    p = _get(db, BudgetPost, post_id, access)
    if body.heading_id is not None:
        _get(db, BudgetHeading, body.heading_id, access)
        p.heading_id = body.heading_id
    if body.name is not None:
        p.name = body.name.strip()
    if body.color is not None:
        p.color = body.color
    if body.clear_amount:
        p.monthly_amount = None
    elif body.monthly_amount is not None:
        p.monthly_amount = body.monthly_amount
    if body.category_ids is not None:
        _set_categories(db, access, p, body.category_ids)
    audit.log(db, "budget.post_updated", user_id=access.user.id, group_id=access.group.id, name=p.name)
    db.commit()
    return load_budget(db, access.group.id)


@router.delete("/posts/{post_id}", response_model=BudgetOut)
def delete_post(post_id: uuid.UUID, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    p = _get(db, BudgetPost, post_id, access)
    db.execute(delete(BudgetPostCategory).where(BudgetPostCategory.post_id == p.id))
    db.delete(p)
    audit.log(db, "budget.post_deleted", user_id=access.user.id, group_id=access.group.id, name=p.name)
    db.commit()
    return load_budget(db, access.group.id)


@router.put("/order", response_model=BudgetOut)
def reorder(body: OrderIn, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    gid = access.group.id
    headings = {h.id: h for h in db.scalars(select(BudgetHeading).where(BudgetHeading.group_id == gid))}
    posts = {p.id: p for p in db.scalars(select(BudgetPost).where(BudgetPost.group_id == gid))}
    try:
        for hpos, item in enumerate(body.headings):
            h = headings[uuid.UUID(str(item["id"]))]
            h.position = hpos
            for ppos, pid in enumerate(item.get("post_ids", [])):
                p = posts[uuid.UUID(str(pid))]
                p.heading_id, p.position = h.id, ppos
    except (KeyError, ValueError, TypeError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown heading or post in the order.") from None
    db.commit()
    return load_budget(db, gid)


def _get(db: Session, model, obj_id: uuid.UUID, access: GroupAccess):
    obj = db.get(model, obj_id)
    if obj is None or obj.group_id != access.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found.")
    return obj


def _set_categories(db: Session, access: GroupAccess, post: BudgetPost, category_ids: list[uuid.UUID]) -> None:
    """A category lives in one post only, so adding it here moves it from wherever it was."""
    gid = access.group.id
    ids = list(dict.fromkeys(category_ids))
    if ids:
        valid = set(
            db.scalars(
                select(Category.id).where(
                    Category.id.in_(ids), (Category.group_id.is_(None)) | (Category.group_id == gid)
                )
            ).all()
        )
        if len(valid) != len(ids):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown category.")
        db.execute(
            delete(BudgetPostCategory).where(
                BudgetPostCategory.group_id == gid, BudgetPostCategory.category_id.in_(ids)
            )
        )
    db.execute(delete(BudgetPostCategory).where(BudgetPostCategory.post_id == post.id))
    db.flush()
    for cid in ids:
        db.add(BudgetPostCategory(group_id=gid, post_id=post.id, category_id=cid))
