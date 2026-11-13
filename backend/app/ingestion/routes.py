"""Uploading bank files.

The app first tries the formats it knows (NAB today), then a layout this group has saved before.
Anything else needs a column mapping once: the web app asks for it with a preview, and it is saved
so the next file from that bank imports straight away.
"""

import json
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.deps import GroupAccess, group_access
from app.core.models import ImportProfile
from app.core.schemas import ImportResult
from app.db import get_db
from app.ingestion.connectors import recognise
from app.ingestion.connectors.base import ParseError
from app.ingestion.connectors.generic_csv import (
    CsvMapping,
    GenericCsvConnector,
    header_signature,
    read_table,
    suggest_mapping,
)
from app.ingestion.pipeline import import_rows

router = APIRouter(prefix="/api/groups/{group_id}", tags=["imports"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
PREVIEW_ROWS = 8


class PreviewRow(BaseModel):
    date: str
    amount: str
    description: str
    account: str


class ImportPreview(BaseModel):
    status: str  # "recognised" (known bank format), "saved" (a layout saved before) or "needs_mapping"
    format: str | None
    columns: list[str]
    has_header: bool
    sample: list[list[str]]
    suggested: dict
    parsed: list[PreviewRow]
    error: str | None = None


class ProfileOut(BaseModel):
    id: uuid.UUID
    name: str
    institution: str


async def _read(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 10 MB.")
    return data


def _mapping(raw: str | None) -> CsvMapping | None:
    if not raw:
        return None
    try:
        return CsvMapping.model_validate(json.loads(raw))
    except (ValueError, ValidationError) as e:
        msg = e.errors()[0]["msg"] if isinstance(e, ValidationError) else "The column mapping is not valid."
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg.removeprefix("Value error, ")) from None


def _table(data: bytes):
    try:
        return read_table(data)
    except ParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None


def _saved_profile(db: Session, group_id: uuid.UUID, columns: list[str], has_header: bool) -> ImportProfile | None:
    sig = header_signature(columns, has_header)
    return db.scalar(
        select(ImportProfile).where(ImportProfile.group_id == group_id, ImportProfile.header_signature == sig)
    )


def _choose(db: Session, access: GroupAccess, data: bytes, mapping: CsvMapping | None):
    """Returns (connector, format label, status) for a file, or (None, None, "needs_mapping")."""
    if mapping is not None:
        return GenericCsvConnector(mapping), f"{mapping.institution} CSV", "mapping"
    columns, _, has_header = _table(data)
    known = recognise(columns) if has_header else None
    if known is not None:
        return known, known.label, "recognised"
    profile = _saved_profile(db, access.group.id, columns, has_header)
    if profile is not None:
        return GenericCsvConnector(CsvMapping.model_validate(profile.mapping)), profile.name, "saved"
    return None, None, "needs_mapping"


@router.post("/imports/preview", response_model=ImportPreview)
async def preview(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    has_header: bool | None = Form(None),
    access: GroupAccess = Depends(group_access),
    db: Session = Depends(get_db),
):
    """Shows how a file will be read, without saving anything. has_header overrides the guess."""
    data = await _read(file)
    m = _mapping(mapping)
    columns, body, guessed = _table(data)
    wanted = m.has_header if m is not None else has_header
    if wanted is not None and wanted != guessed:
        columns, body, guessed = read_table(data, wanted)
    has_header = guessed
    connector, label, state = _choose(db, access, data, m)
    out = ImportPreview(
        status="needs_mapping" if state in ("needs_mapping", "mapping") and m is None else state,
        format=label,
        columns=columns,
        has_header=has_header,
        sample=[r[: len(columns)] for r in body[:PREVIEW_ROWS]],
        suggested=suggest_mapping(columns, body, has_header),
        parsed=[],
    )
    if connector is not None:
        try:
            rows = connector.parse(data)
            out.parsed = [
                PreviewRow(
                    date=r.posted_date.isoformat(),
                    amount=str(r.amount),
                    description=r.description,
                    account=r.account_ref,
                )
                for r in rows[:PREVIEW_ROWS]
            ]
        except ParseError as e:
            out.error = str(e)
    return out


@router.post("/imports", response_model=ImportResult, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    mapping: str | None = Form(None),
    save_as: str | None = Form(None, max_length=80),
    access: GroupAccess = Depends(group_access),
    db: Session = Depends(get_db),
):
    data = await _read(file)
    m = _mapping(mapping)
    connector, label, state = _choose(db, access, data, m)
    if connector is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This file's layout is new. Match its columns first, and the app will remember them.",
        )
    try:
        rows = connector.parse(data)
    except ParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
    if m is not None:
        columns, _, has_header = read_table(data, m.has_header)
        name = (save_as or "").strip() or label
        profile = _saved_profile(db, access.group.id, columns, has_header)
        if profile is None:
            profile = ImportProfile(
                group_id=access.group.id,
                header_signature=header_signature(columns, has_header),
                created_by=access.user.id,
                name=name,
                mapping={},
            )
            db.add(profile)
        profile.name, profile.mapping = name, m.model_dump()
        audit.log(db, "import_profile.saved", user_id=access.user.id, group_id=access.group.id, name=name)
        label = name
    outcome = import_rows(
        db, group_id=access.group.id, user_id=access.user.id, connector=connector, rows=rows, filename=file.filename
    )
    db.commit()
    b = outcome.batch
    return ImportResult(
        batch_id=b.id,
        rows_total=b.rows_total,
        rows_new=b.rows_new,
        rows_duplicate=b.rows_duplicate,
        rows_pending_replaced=b.rows_pending_replaced,
        accounts_created=outcome.accounts_created,
        accounts=outcome.accounts_in_file,
        transfers_paired=outcome.transfers_paired,
        format=label,
        filename=file.filename,
    )


@router.get("/import-profiles", response_model=list[ProfileOut])
def list_profiles(access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    profiles = db.scalars(
        select(ImportProfile).where(ImportProfile.group_id == access.group.id).order_by(ImportProfile.name)
    )
    return [ProfileOut(id=p.id, name=p.name, institution=p.mapping.get("institution", "")) for p in profiles]


@router.delete("/import-profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_profile(profile_id: uuid.UUID, access: GroupAccess = Depends(group_access), db: Session = Depends(get_db)):
    p = db.get(ImportProfile, profile_id)
    if p is None or p.group_id != access.group.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved layout not found.")
    db.delete(p)
    audit.log(db, "import_profile.deleted", user_id=access.user.id, group_id=access.group.id, name=p.name)
    db.commit()
