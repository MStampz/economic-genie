from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.deps import GroupAccess, group_access
from app.core.schemas import ImportResult
from app.db import get_db
from app.ingestion.connectors.base import ParseError
from app.ingestion.connectors.nab_csv import CONNECTORS
from app.ingestion.pipeline import import_rows

router = APIRouter(prefix="/api/groups/{group_id}/imports", tags=["imports"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("", response_model=ImportResult, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    source: str = Form("nab_csv"),
    access: GroupAccess = Depends(group_access),
    db: Session = Depends(get_db),
):
    connector = CONNECTORS.get(source)
    if connector is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown source '{source}'.")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "The file is larger than 10 MB.")
    try:
        rows = connector.parse(data)
    except ParseError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(e)) from None
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
        transfers_paired=outcome.transfers_paired,
    )
