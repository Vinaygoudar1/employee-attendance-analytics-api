"""
Employee Attendance & Analytics API - STARTER

Run:  uvicorn app.main:app --port 8000
Env:  MONGO_URI, MONGO_DB (a local .env is loaded for convenience)

This file was written quickly by a colleague who has left the company. The happy path
works, but nobody has reviewed it. Read PROBLEM_STATEMENT.docx for what is expected of you,
openapi.yaml for the contract and DATA_MODEL.md for what is stored in MongoDB.
"""

import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional
from bson import json_util

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, field_validator
from pymongo import MongoClient
from fastapi.responses import Response


load_dotenv()

client = MongoClient(os.getenv("MONGO_URI", "mongodb://localhost:27017"))
db = client[os.getenv("MONGO_DB", "attendance_db")]

db.employees.create_index("emp_code", unique=True)
db.employees.create_index(
    [("department", 1), ("joined_on", 1)]
)

db.employees.create_index("joined_on")

db.attendance_logs.create_index(
    [("emp_code", 1), ("date", 1)],
    unique=True
)

db.attendance_logs.create_index(
    [("date", -1), ("emp_code", 1)]
)

IST = timezone(timedelta(hours=5, minutes=30))

app = FastAPI(title="Employee Attendance & Analytics API", version="2.0.0")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def to_utc_datetime(epoch_ms: int) -> datetime:
    """Convert epoch milliseconds to a UTC datetime, truncated to seconds."""
    if isinstance(epoch_ms, bool) or not isinstance(epoch_ms, int):
        raise HTTPException(422, "Timestamp must be an integer in milliseconds")

    try:
        return datetime.fromtimestamp(
            epoch_ms // 1000,
            tz=timezone.utc,
        )
    except (OverflowError, OSError, ValueError):
        raise HTTPException(422, "Timestamp is out of range")


def as_utc(value: datetime) -> datetime:
    """Treat naive MongoDB datetimes as UTC and normalize aware datetimes."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def to_epoch_ms(value: datetime) -> int:
    """Convert a datetime to integer epoch milliseconds."""
    value = as_utc(value)
    return int(value.timestamp() * 1000)


def round_half_up(value: Decimal, places: int = 2) -> Decimal:
    """Round a Decimal using the assignment's half-up rule."""
    quantum = Decimal("1").scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)



def compute_late_minutes(
    punch_in: datetime,
    shift_start: str,
) -> int:
    """Calculate whole minutes late, allowing a 10-minute grace period."""
    local_time = as_utc(punch_in).astimezone(IST)
    hours, minutes = map(int, shift_start.split(":"))

    shift_start_time = local_time.replace(
        hour=hours,
        minute=minutes,
        second=0,
        microsecond=0,
    )

    # For an overnight shift, a punch-in shortly after midnight
    # may belong to the shift that started on the previous day.
    if shift_start_time - local_time > timedelta(hours=12):
        shift_start_time -= timedelta(days=1)
    elif local_time - shift_start_time > timedelta(hours=12):
        shift_start_time += timedelta(days=1)

    elapsed_seconds = int(
        (local_time - shift_start_time).total_seconds()
    )

    if elapsed_seconds <= 0:
        return 0

    if elapsed_seconds <= 600:
        return 0

    return elapsed_seconds // 60



def compute_work_hours(
    punch_in: datetime,
    punch_out: datetime,
) -> float:
    """Calculate work hours rounded half-up to two decimal places."""
    start = as_utc(punch_in)
    end = as_utc(punch_out)

    elapsed_seconds = int((end - start).total_seconds())
    hours = Decimal(elapsed_seconds) / Decimal(3600)

    return float(round_half_up(hours, 2))




def compute_overtime(
    punch_in: datetime,
    punch_out: datetime,
    shift_start: str,
    shift_end: str,
) -> int:
    """Calculate overtime after the employee's scheduled shift end."""
    local_in = as_utc(punch_in).astimezone(IST)
    local_out = as_utc(punch_out).astimezone(IST)

    start_hour, start_minute = map(int, shift_start.split(":"))
    end_hour, end_minute = map(int, shift_end.split(":"))

    shift_start_time = local_in.replace(
        hour=start_hour,
        minute=start_minute,
        second=0,
        microsecond=0,
    )

    # Match the shift date to the punch-in time, including overnight shifts.
    if shift_start_time - local_in > timedelta(hours=12):
        shift_start_time -= timedelta(days=1)
    elif local_in - shift_start_time > timedelta(hours=12):
        shift_start_time += timedelta(days=1)

    shift_end_date = shift_start_time.date()

    if (end_hour, end_minute) <= (start_hour, start_minute):
        shift_end_date += timedelta(days=1)

    shift_end_time = datetime(
        shift_end_date.year,
        shift_end_date.month,
        shift_end_date.day,
        end_hour,
        end_minute,
        tzinfo=IST,
    )

    extra_seconds = int((local_out - shift_end_time).total_seconds())

    if extra_seconds < 1800:
        return 0

    return extra_seconds // 60




# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class EmployeeIn(BaseModel):
    emp_code: str
    name: str
    email: str
    department: str
    shift_start: str = "09:30"
    shift_end: str = "18:30"
    joined_on: str

    @field_validator("emp_code", "name", "email", "department")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("This field cannot be empty")
        return value.strip()

    @field_validator("shift_start", "shift_end")
    @classmethod
    def validate_shift_time(cls, value: str) -> str:
        from datetime import time

        try:
            parsed = time.fromisoformat(value)
        except ValueError:
            raise ValueError("Shift time must use HH:MM format")

        if len(value) != 5 or parsed.strftime("%H:%M") != value:
            raise ValueError("Shift time must use HH:MM format")

        return value

    @field_validator("joined_on")
    @classmethod
    def validate_joined_on(cls, value: str) -> str:
        from datetime import date

        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            raise ValueError("joined_on must use YYYY-MM-DD format")

        if parsed.isoformat() != value:
            raise ValueError("joined_on must use YYYY-MM-DD format")

        return value




class PunchInIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None
    status: str = "PRESENT"

    @field_validator("emp_code")
    @classmethod
    def validate_emp_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("emp_code cannot be empty")
        return value.strip()

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value

        if type(value) is not int or value < 0:
            raise ValueError("punched_at must be a non-negative integer in milliseconds")

        return value

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        allowed = {"PRESENT", "WFH", "ON_DUTY"}
        if value not in allowed:
            raise ValueError(
                "Punch-in status must be PRESENT, WFH, or ON_DUTY"
            )
        return value



class PunchOutIn(BaseModel):
    emp_code: str
    punched_at: Optional[int] = None

    @field_validator("emp_code")
    @classmethod
    def validate_emp_code(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("emp_code cannot be empty")
        return value.strip()

    @field_validator("punched_at", mode="before")
    @classmethod
    def validate_punched_at(cls, value):
        if value is None:
            return value

        if type(value) is not int or not (
            100000000000 <= value <= 4102444800000
        ):
            raise ValueError(
                "punched_at must be a valid epoch-milliseconds integer"
            )

        return value


# --------------------------------------------------------------------------- #
# Endpoints provided
# --------------------------------------------------------------------------- #

@app.get("/health")
def health():
    try:
        db.command("ping")
        return {"status": "ok"}
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Database unavailable"
        )




@app.post("/employees", status_code=201)
def create_employee(body: EmployeeIn):
    doc = body.model_dump()

    doc["created_at"] = datetime.now(timezone.utc)

    try:
        db.employees.insert_one(doc)
    except Exception as exc:
        if db.employees.find_one({"emp_code": body.emp_code}):
            raise HTTPException(
                status_code=409,
                detail="emp_code already exists"
            )
        raise HTTPException(
            status_code=500,
            detail="Failed to create employee"
        ) from exc

    doc.pop("_id", None)
    return doc




@app.get("/employees")
def list_employees(department: Optional[str] = None, page: int = 1, page_size: int = 20):
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page_size must be between 1 and 100")

    q = {}
    if department:
        q["department"] = department

    skip = (page - 1) * page_size
    total = db.employees.count_documents(q)

    items = list(
        db.employees.find(q, {"_id": 0})
        .sort("emp_code", 1)
        .skip(skip)
        .limit(page_size)
    )

    return {"items": items, "total": total, "page": page, "page_size": page_size}




@app.post("/attendance/punch-in", status_code=201)
def punch_in(body: PunchInIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})

    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    # Only these statuses are allowed for punch-in.
    if body.status not in ("PRESENT", "WFH", "ON_DUTY"):
        raise HTTPException(
            status_code=422,
            detail="Status must be PRESENT, WFH, or ON_DUTY",
        )

    if body.punched_at is None:
        ts = datetime.now(timezone.utc)
    else:
        try:
            ts = datetime.fromtimestamp(
                body.punched_at / 1000,
                tz=timezone.utc,
            )
        except (ValueError, OverflowError, OSError):
            raise HTTPException(
                status_code=422,
                detail="Invalid punched_at timestamp",
            )

    ist = timezone(timedelta(hours=5, minutes=30))
    ts = ts.replace(microsecond=0)
    local_ts = ts.astimezone(ist)
    attendance_date = local_ts.date().isoformat()
    stored_ts = ts.replace(tzinfo=None)

    doc = {
        "emp_code": body.emp_code,
        "date": attendance_date,
        "status": body.status,
        "punch_in": stored_ts,
        "punch_out": None,
        "work_hours": None,
        "late_minutes": compute_late_minutes(
            local_ts, emp["shift_start"]
        ),
        "overtime_minutes": 0,
        "half_day": False,
        "history": [],
    }

    try:
        db.attendance_logs.insert_one(doc)
    except Exception as exc:
        if db.attendance_logs.find_one({
            "emp_code": body.emp_code,
            "date": attendance_date,
        }):
            raise HTTPException(
                status_code=409,
                detail="Already punched in for this date",
            )
        raise HTTPException(
            status_code=500,
            detail="Failed to record attendance",
        ) from exc

    doc.pop("_id", None)
    doc["punch_in"] = to_epoch_ms(stored_ts)
    return doc




@app.post("/attendance/punch-out")
def punch_out(body: PunchOutIn):
    emp = db.employees.find_one({"emp_code": body.emp_code})
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    if body.punched_at is None:
        punch_out_ts = datetime.now(timezone.utc)
    else:
        try:
            punch_out_ts = datetime.fromtimestamp(
                body.punched_at / 1000,
                tz=timezone.utc,
            )
        except (ValueError, OverflowError, OSError):
            raise HTTPException(status_code=422, detail="Invalid punched_at timestamp")

    punch_out_ts = punch_out_ts.replace(microsecond=0)
    punch_out_utc = punch_out_ts.replace(tzinfo=None)
    ist = timezone(timedelta(hours=5, minutes=30))
    punch_out_local = punch_out_ts.astimezone(ist)

    # Find the latest open punch-in not later than punch-out.
    record = db.attendance_logs.find_one(
        {
            "emp_code": body.emp_code,
            "punch_in": {"$ne": None, "$lte": punch_out_utc},
            "punch_out": None,
        },
        sort=[("punch_in", -1)],
    )

    if not record:
        # Distinguish no eligible punch-in from an already closed record.
        previous = db.attendance_logs.find_one(
            {
                "emp_code": body.emp_code,
                "punch_in": {"$ne": None, "$lte": punch_out_utc},
            },
            sort=[("punch_in", -1)],
        )
        if previous and previous.get("punch_out") is not None:
            raise HTTPException(status_code=409, detail="Already punched out")
        raise HTTPException(status_code=404, detail="No punch-in found")

    punch_in_utc = record["punch_in"].replace(tzinfo=timezone.utc)
    elapsed_seconds = int((punch_out_ts - punch_in_utc).total_seconds())

    if elapsed_seconds <= 0 or elapsed_seconds > 24 * 60 * 60:
        raise HTTPException(
            status_code=422,
            detail="Punch-out must be after punch-in and within 24 hours",
        )

    work_hours = compute_work_hours(punch_in_utc, punch_out_ts)
    overtime_minutes = compute_overtime(
    punch_in_utc,
    punch_out_ts,
    emp["shift_start"],
    emp["shift_end"],
)
    half_day = Decimal(str(work_hours)) < Decimal("4.50")

    # Atomic update ensures only one simultaneous punch-out succeeds.
    result = db.attendance_logs.update_one(
        {
            "_id": record["_id"],
            "punch_out": None,
        },
        {
            "$set": {
                "punch_out": punch_out_ts.replace(tzinfo=None),
                "work_hours": work_hours,
                "overtime_minutes": overtime_minutes,
                "half_day": half_day,
            }
        },
    )

    if result.modified_count != 1:
        raise HTTPException(status_code=409, detail="Already punched out")

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated.pop("_id", None)

    
    for field in ("punch_in", "punch_out"):
        if updated.get(field) is not None:
            updated[field] = to_epoch_ms(updated[field])

    
    for entry in updated.get("history", []):
        if entry.get("at") is not None:
            entry["at"] = to_epoch_ms(entry["at"])

        for field in ("punch_in", "punch_out"):
            change = entry.get("changes", {}).get(field)
            if change:
                for key in ("from", "to"):
                    if isinstance(change.get(key), datetime):
                        change[key] = to_epoch_ms(change[key])


    return updated





class RegularizeRequest(BaseModel):
    status: Optional[str] = None
    punch_in: Optional[int] = None
    punch_out: Optional[int] = None
    reason: str
    regularized_by: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value):
        if value is not None and value not in {
            "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
        }:
            raise ValueError("Invalid attendance status")
        return value

    @field_validator("punch_in", "punch_out", mode="before")
    @classmethod
    def validate_timestamp(cls, value):
        if value is not None and (
            type(value) is not int
            or not 100000000000 <= value <= 4102444800000
        ):
            raise ValueError(
                "Timestamp must be a valid epoch-milliseconds integer"
            )
        return value

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value):
        value = value.strip()
        if not 5 <= len(value) <= 200:
            raise ValueError("reason must contain 5 to 200 characters")
        return value

    @field_validator("regularized_by")
    @classmethod
    def validate_regularized_by(cls, value):
        value = value.strip()
        if not 1 <= len(value) <= 50:
            raise ValueError(
                "regularized_by must contain 1 to 50 characters"
            )
        return value


@app.patch("/attendance/{emp_code}/{date}")
def regularize_attendance(
    emp_code: str,
    date: str,
    body: RegularizeRequest,
):
    record = db.attendance_logs.find_one(
        {"emp_code": emp_code, "date": date}
    )
    if not record:
        raise HTTPException(
            status_code=404,
            detail="Attendance record not found",
        )

    changes = {}
    updates = {}
    supplied_fields = body.model_fields_set

    if body.status is not None and body.status != record.get("status"):
        changes["status"] = {
            "from": record.get("status"),
            "to": body.status,
        }
        updates["status"] = body.status

    # Apply only timestamp fields explicitly supplied in the request.
    for field in ("punch_in", "punch_out"):
        if field not in supplied_fields:
            continue

        value = getattr(body, field)
        new_value = to_utc_datetime(value) if value is not None else None
        old_value = record.get(field)
        old_utc = as_utc(old_value) if old_value is not None else None

        if old_utc != new_value:
            changes[field] = {
                "from": to_epoch_ms(old_utc) if old_utc else None,
                "to": to_epoch_ms(new_value) if new_value else None,
            }
            updates[field] = (
                new_value.replace(tzinfo=None)
                if new_value is not None
                else None
            )

    target_status = updates.get("status", record.get("status"))

    # ABSENT and LEAVE records cannot have punch timestamps.
    if target_status in {"ABSENT", "LEAVE"}:
        if any(
            getattr(body, field) is not None
            for field in ("punch_in", "punch_out")
            if field in supplied_fields
        ):
            raise HTTPException(
                status_code=422,
                detail="ABSENT and LEAVE records must have null punch times",
            )

        for field in ("punch_in", "punch_out"):
            old_value = record.get(field)
            effective_value = updates.get(field, old_value)

            if effective_value is not None:
                changes[field] = {
                    "from": to_epoch_ms(as_utc(old_value))
                    if old_value is not None else None,
                    "to": None,
                }
                updates[field] = None

    # Recalculate derived values when status or punch times change.
    if any(
        field in changes
        for field in ("status", "punch_in", "punch_out")
    ):
        new_in = updates.get("punch_in", record.get("punch_in"))
        new_out = updates.get("punch_out", record.get("punch_out"))

        if new_in is not None and new_out is not None:
            if as_utc(new_out) <= as_utc(new_in):
                raise HTTPException(
                    status_code=422,
                    detail="punch_out must be later than punch_in",
                )

            elapsed = (
                as_utc(new_out) - as_utc(new_in)
            ).total_seconds()

            if elapsed > 86400:
                raise HTTPException(
                    status_code=422,
                    detail="Punch interval cannot exceed 24 hours",
                )

        if target_status in {"ABSENT", "LEAVE"}:
            updates.update({
                "work_hours": None,
                "late_minutes": 0,
                "overtime_minutes": 0,
                "half_day": False,
            })
        else:
            emp = db.employees.find_one({"emp_code": emp_code})
            if not emp:
                raise HTTPException(
                    status_code=404,
                    detail="Employee not found",
                )

            updates["late_minutes"] = (
                compute_late_minutes(new_in, emp["shift_start"])
                if new_in is not None else 0
            )

            if new_in is not None and new_out is not None:
                updates["work_hours"] = compute_work_hours(
                    new_in, new_out
                )
                updates["overtime_minutes"] = compute_overtime(
                    new_in,
                    new_out,
                    emp["shift_start"],
                    emp["shift_end"],
                )
                updates["half_day"] = (
                    Decimal(str(updates["work_hours"]))
                    < Decimal("4.50")
                )
            else:
                updates["work_hours"] = None
                updates["overtime_minutes"] = 0
                updates["half_day"] = False

    # Append audit history atomically so concurrent updates don't overwrite
    # each other's history entries.
    if changes:
        history_entry = {
            "at": datetime.now(timezone.utc).replace(microsecond=0),
            "by": body.regularized_by,
            "reason": body.reason,
            "changes": changes,
        }

        update_result = db.attendance_logs.update_one(
            {"_id": record["_id"]},
            {
                "$set": updates,
                "$push": {"history": history_entry},
            },
        )

        if update_result.modified_count != 1:
            raise HTTPException(
                status_code=409,
                detail="Attendance record changed; retry regularization",
            )

    updated = db.attendance_logs.find_one({"_id": record["_id"]})
    updated.pop("_id", None)

    # Support legacy documents missing these fields.
    updated.setdefault("history", [])
    updated.setdefault("half_day", False)

    for field in ("punch_in", "punch_out"):
        if updated.get(field) is not None:
            updated[field] = to_epoch_ms(updated[field])

    for entry in updated.get("history", []):
        if entry.get("at") is not None:
            entry["at"] = to_epoch_ms(entry["at"])

        for field in ("punch_in", "punch_out"):
            change = entry.get("changes", {}).get(field)
            if change:
                for key in ("from", "to"):
                    if isinstance(change.get(key), datetime):
                        change[key] = to_epoch_ms(change[key])

    return updated






@app.get("/attendance")
def list_attendance(
    emp_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
):
    if page < 1:
        raise HTTPException(status_code=422, detail="page must be at least 1")

    if page_size < 1 or page_size > 100:
        raise HTTPException(status_code=422, detail="page_size must be between 1 and 100")

    q = {}

    if emp_code:
        q["emp_code"] = emp_code

    if date_from or date_to:
        date_filter = {}
        if date_from:
            date_filter["$gte"] = date_from
        if date_to:
            date_filter["$lte"] = date_to
        q["date"] = date_filter

    if status:
        allowed = {"PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"}
        if status not in allowed:
            raise HTTPException(status_code=422, detail="Invalid attendance status")
        q["status"] = status

    total = db.attendance_logs.count_documents(q)
    skip = (page - 1) * page_size

    docs = list(
        db.attendance_logs.find(q, {"_id": 1, "emp_code": 1, "date": 1,
                                    "status": 1, "punch_in": 1, "punch_out": 1,
                                    "work_hours": 1, "late_minutes": 1,
                                    "overtime_minutes": 1, "half_day": 1,
                                    "history": 1})
        .sort([("date", -1), ("emp_code", 1)])
        .skip(skip)
        .limit(page_size)
    )

    
    for doc in docs:
        doc.pop("_id", None)

        for field in ("punch_in", "punch_out"):
            if doc.get(field) is not None:
                doc[field] = to_epoch_ms(doc[field])

        for entry in doc.get("history", []):
            if entry.get("at") is not None:
                entry["at"] = to_epoch_ms(entry["at"])

            for field in ("punch_in", "punch_out"):
                change = entry.get("changes", {}).get(field)
                if change:
                    for key in ("from", "to"):
                        if isinstance(change.get(key), datetime):
                            change[key] = to_epoch_ms(change[key])


    return {
        "items": docs,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


# --------------------------------------------------------------------------- #
# TODO - the rest of the contract (see openapi.yaml):
#   POST  /attendance/punch-out
#   PATCH /attendance/{emp_code}/{date}
#   GET   /analytics/employees/{emp_code}/monthly
#   GET   /analytics/departments/summary
#   GET   /analytics/leaderboard/late
#   GET   /analytics/departments/{department}/trend
#   GET   /admin/explain/{endpoint}
# --------------------------------------------------------------------------- #


def month_bounds(month: str):
    try:
        start = date.fromisoformat(month + "-01")
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    if len(month) != 7 or month[4] != "-":
        raise HTTPException(
            status_code=422,
            detail="month must use YYYY-MM format",
        )

    if start.month == 12:
        end = date(start.year + 1, 1, 1)
    else:
        end = date(start.year, start.month + 1, 1)

    return start, end




@app.get("/analytics/employees/{emp_code}/monthly")
def employee_monthly(emp_code: str, month: str = Query(...)):
    employee = db.employees.find_one({"emp_code": emp_code})
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")

    start, end = month_bounds(month)
    
    # Calculate working days using MongoDB aggregation.
    working_pipeline = [
        {"$match": {"emp_code": emp_code}},
        {
            "$set": {
                "work_start": {
                    "$dateFromString": {
                        "dateString": {
                            "$cond": [
                                {"$gt": ["$joined_on", start.isoformat()]},
                                "$joined_on",
                                start.isoformat(),
                            ]
                        },
                        "timezone": "Asia/Kolkata",
                    }
                },
                "work_end": {
                    "$dateFromString": {
                        "dateString": end.isoformat(),
                        "timezone": "Asia/Kolkata",
                    }
                },
            }
        },
        {
            "$set": {
                "day_offsets": {
                    "$range": [
                        0,
                        {
                            "$max": [
                                0,
                                {
                                    "$dateDiff": {
                                        "startDate": "$work_start",
                                        "endDate": "$work_end",
                                        "unit": "day",
                                        "timezone": "Asia/Kolkata",
                                    }
                                },
                            ]
                        },
                    ]
                }
            }
        },
        {
            "$set": {
                "working_days": {
                    "$size": {
                        "$filter": {
                            "input": {
                                "$map": {
                                    "input": "$day_offsets",
                                    "as": "offset",
                                    "in": {
                                        "$dateAdd": {
                                            "startDate": "$work_start",
                                            "unit": "day",
                                            "amount": "$$offset",
                                            "timezone": "Asia/Kolkata",
                                        }
                                    },
                                }
                            },
                            "as": "day",
                            "cond": {
                                "$and": [
                                    {
                                        "$gte": [
                                            {
                                                "$dayOfWeek": {
                                                    "date": "$$day",
                                                    "timezone": "Asia/Kolkata",
                                                }
                                            },
                                            2,
                                        ]
                                    },
                                    {
                                        "$lte": [
                                            {
                                                "$dayOfWeek": {
                                                    "date": "$$day",
                                                    "timezone": "Asia/Kolkata",
                                                }
                                            },
                                            6,
                                        ]
                                    },
                                ]
                            },
                        }
                    }
                }
            }
        },
        {"$project": {"_id": 0, "working_days": 1}},
    ]

    working_result = list(db.employees.aggregate(working_pipeline))
    working_days = (
        working_result[0]["working_days"] if working_result else 0
    )


    pipeline = [
        {
            "$match": {
                "emp_code": emp_code,
                "date": {
                    "$gte": start.isoformat(),
                    "$lt": end.isoformat(),
                },
            }
        },
        {
            "$set": {
                "half_day": {"$ifNull": ["$half_day", False]},
                "late_minutes": {"$ifNull": ["$late_minutes", 0]},
                "overtime_minutes": {
                    "$ifNull": ["$overtime_minutes", 0]
                },
            }
        },
        {
            "$set": {
                "day_of_week": {
                    "$dayOfWeek": {
                        "$dateFromString": {
                            "dateString": "$date",
                            "format": "%Y-%m-%d",
                            "timezone": "Asia/Kolkata",
                        }
                    }
                }
            }
        },
        {
            "$group": {
                "_id": None,
                "present_days": {
                    "$sum": {
                        "$cond": [
                            {
                                "$and": [
                                    {
                                        "$in": [
                                            "$status",
                                            ["PRESENT", "WFH", "ON_DUTY"],
                                        ]
                                    },
                                    {"$gte": ["$day_of_week", 2]},
                                    {"$lte": ["$day_of_week", 6]},
                                ]
                            },
                            {
                                "$cond": [
                                    {"$eq": ["$half_day", True]},
                                    0.5,
                                    1,
                                ]
                            },
                            0,
                        ]
                    }
                },
                "leave_days": {
                    "$sum": {
                        "$cond": [
                            {"$eq": ["$status", "LEAVE"]},
                            1,
                            0,
                        ]
                    }
                },
                "late_count": {
                    "$sum": {
                        "$cond": [
                            {"$gt": ["$late_minutes", 0]},
                            1,
                            0,
                        ]
                    }
                },
                "total_late_minutes": {"$sum": "$late_minutes"},
                "total_overtime_minutes": {
                    "$sum": "$overtime_minutes"
                },
            }
        },
    ]

    result = list(db.attendance_logs.aggregate(pipeline))
    stats = result[0] if result else {}

    present_days = stats.get("present_days", 0)
    leave_days = stats.get("leave_days", 0)
    late_count = stats.get("late_count", 0)
    total_late_minutes = stats.get("total_late_minutes", 0)
    total_overtime_minutes = stats.get("total_overtime_minutes", 0)

    attendance_pct = (
        float(
            round_half_up(
                Decimal(str(present_days)) * Decimal("100")
                / Decimal(working_days),
                4,
            )
        )
        if working_days > 0
        else None
    )

    return {
        "emp_code": emp_code,
        "month": month,
        "working_days": working_days,
        "present_days": present_days,
        "leave_days": leave_days,
        "late_count": late_count,
        "total_late_minutes": total_late_minutes,
        "total_overtime_minutes": total_overtime_minutes,
        "attendance_pct": attendance_pct,
    }





@app.get("/analytics/departments/summary")
def department_summary(
    month: str = Query(...),
    department: Optional[str] = None,
):
    start, end = month_bounds(month)

    employee_match = {
        "joined_on": {"$lt": end.isoformat()}
    }

    if department:
        employee_match["department"] = department

    pipeline = [
        {"$match": employee_match},
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {"code": "$emp_code"},
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$emp_code", "$$code"]},
                                    {"$gte": ["$date", start.isoformat()]},
                                    {"$lt": ["$date", end.isoformat()]},
                                ]
                            }
                        }
                    },
                    {
                        "$set": {
                            "half_day": {"$ifNull": ["$half_day", False]},
                            "late_minutes": {
                                "$ifNull": ["$late_minutes", 0]
                            },
                            "work_hours": {
                                "$ifNull": ["$work_hours", None]
                            },
                        }
                    },
                    {
                        "$set": {
                            "day_of_week": {
                                "$dayOfWeek": {
                                    "$dateFromString": {
                                        "dateString": "$date",
                                        "format": "%Y-%m-%d",
                                        "timezone": "Asia/Kolkata",
                                    }
                                }
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_days": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$status",
                                                        [
                                                            "PRESENT",
                                                            "WFH",
                                                            "ON_DUTY",
                                                        ],
                                                    ]
                                                },
                                                {"$gte": ["$day_of_week", 2]},
                                                {"$lte": ["$day_of_week", 6]},
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {"$eq": ["$half_day", True]},
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                }
                            },
                            "work_hours_sum": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$status",
                                                        [
                                                            "PRESENT",
                                                            "WFH",
                                                            "ON_DUTY",
                                                        ],
                                                    ]
                                                },
                                                {"$ne": ["$work_hours", None]},
                                            ]
                                        },
                                        "$work_hours",
                                        0,
                                    ]
                                }
                            },
                            "work_hours_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$and": [
                                                {
                                                    "$in": [
                                                        "$status",
                                                        [
                                                            "PRESENT",
                                                            "WFH",
                                                            "ON_DUTY",
                                                        ],
                                                    ]
                                                },
                                                {"$ne": ["$work_hours", None]},
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$gt": ["$late_minutes", 0]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "total_late_minutes": {
                                "$sum": "$late_minutes"
                            },
                            "leave_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "LEAVE"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                            "on_duty_count": {
                                "$sum": {
                                    "$cond": [
                                        {"$eq": ["$status", "ON_DUTY"]},
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "attendance",
            }
        },
        {
            "$unwind": {
                "path": "$attendance",
                "preserveNullAndEmptyArrays": True,
            }
        },
        {
            "$group": {
                "_id": "$department",
                "headcount": {"$sum": 1},
                "present_days": {
                    "$sum": {"$ifNull": ["$attendance.present_days", 0]}
                },
                "work_hours_sum": {
                    "$sum": {"$ifNull": ["$attendance.work_hours_sum", 0]}
                },
                "work_hours_count": {
                    "$sum": {"$ifNull": ["$attendance.work_hours_count", 0]}
                },
                "late_count": {
                    "$sum": {"$ifNull": ["$attendance.late_count", 0]}
                },
                "total_late_minutes": {
                    "$sum": {
                        "$ifNull": ["$attendance.total_late_minutes", 0]
                    }
                },
                "leave_count": {
                    "$sum": {"$ifNull": ["$attendance.leave_count", 0]}
                },
                "on_duty_count": {
                    "$sum": {"$ifNull": ["$attendance.on_duty_count", 0]}
                },
            }
        },
        {"$sort": {"_id": 1}},
        {
            "$project": {
                "_id": 0,
                "department": "$_id",
                "headcount": 1,
                "present_days": 1,
                "work_hours_sum": 1,
                "work_hours_count": 1,
                "late_count": 1,
                "total_late_minutes": 1,
                "leave_count": 1,
                "on_duty_count": 1,
            }
        },
    ]

    items = list(db.employees.aggregate(pipeline))

    for item in items:
        count = item.pop("work_hours_count", 0)
        total_hours = item.pop("work_hours_sum", 0)

        if count:
            item["avg_work_hours"] = round_half_up(
                Decimal(str(total_hours)) / Decimal(count),
                2,
            )
        else:
            item["avg_work_hours"] = None

    return {
        "month": month,
        "items": items,
    }






@app.get("/analytics/leaderboard/late")
def late_leaderboard(
    month: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    department: Optional[str] = None,
):
    start, end = month_bounds(month)

    pipeline = [
        {
            "$match": {
                "date": {
                    "$gte": start.isoformat(),
                    "$lt": end.isoformat(),
                },
                "late_minutes": {"$gt": 0},
            }
        },
        {
            "$group": {
                "_id": "$emp_code",
                "total_late_minutes": {"$sum": "$late_minutes"},
                "late_count": {"$sum": 1},
            }
        },
        {
            "$lookup": {
                "from": "employees",
                "localField": "_id",
                "foreignField": "emp_code",
                "as": "employee",
            }
        },
        {"$unwind": "$employee"},
    ]

    if department:
        pipeline.append(
            {"$match": {"employee.department": department}}
        )

    pipeline.extend([
        {
            "$setWindowFields": {
                "sortBy": {"total_late_minutes": -1},
                "output": {
                    "rank": {"$rank": {}},
                },
            }
        },
        {"$match": {"rank": {"$lte": limit}}},
        {
            "$sort": {
                "rank": 1,
                "total_late_minutes": -1,
                "_id": 1,
            }
        },
        {
            "$project": {
                "_id": 0,
                "rank": 1,
                "emp_code": "$_id",
                "name": "$employee.name",
                "department": "$employee.department",
                "total_late_minutes": 1,
                "late_count": 1,
            }
        },
    ])

    items = list(db.attendance_logs.aggregate(pipeline))

    return {
        "month": month,
        "items": items,
    }







def build_department_trend_pipeline(
    department: str,
    from_date: str,
    to_date: str,
):
    """Build the shared MongoDB aggregation for department trends."""
    number_of_days = (
        date.fromisoformat(to_date) - date.fromisoformat(from_date)
    ).days + 1

    pipeline = [
        {"$match": {"department": department}},
        {
            "$group": {
                "_id": None,
                "emp_codes": {"$addToSet": "$emp_code"},
                "employees": {
                    "$push": {
                        "emp_code": "$emp_code",
                        "joined_on": "$joined_on",
                    }
                },
            }
        },
        {
            "$set": {
                "days": {
                    "$map": {
                        "input": {"$range": [0, number_of_days]},
                        "as": "offset",
                        "in": {
                            "$dateAdd": {
                                "startDate": {
                                    "$dateFromString": {
                                        "dateString": from_date,
                                        "timezone": "Asia/Kolkata",
                                    }
                                },
                                "unit": "day",
                                "amount": "$$offset",
                                "timezone": "Asia/Kolkata",
                            }
                        },
                    }
                }
            }
        },
        {"$unwind": "$days"},
        {
            "$set": {
                "day_string": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$days",
                        "timezone": "Asia/Kolkata",
                    }
                },
                "day_of_week": {
                    "$dayOfWeek": {
                        "date": "$days",
                        "timezone": "Asia/Kolkata",
                    }
                },
            }
        },
        {
            "$lookup": {
                "from": "attendance_logs",
                "let": {
                    "day_string": "$day_string",
                    "codes": "$emp_codes",
                },
                "pipeline": [
                    {
                        "$match": {
                            "$expr": {
                                "$and": [
                                    {"$eq": ["$date", "$$day_string"]},
                                    {"$in": ["$emp_code", "$$codes"]},
                                ]
                            }
                        }
                    },
                    {
                        "$group": {
                            "_id": None,
                            "present_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$in": [
                                                "$status",
                                                [
                                                    "PRESENT",
                                                    "WFH",
                                                    "ON_DUTY",
                                                ],
                                            ]
                                        },
                                        {
                                            "$cond": [
                                                {
                                                    "$eq": [
                                                        {
                                                            "$ifNull": [
                                                                "$half_day",
                                                                False,
                                                            ]
                                                        },
                                                        True,
                                                    ]
                                                },
                                                0.5,
                                                1,
                                            ]
                                        },
                                        0,
                                    ]
                                }
                            },
                            "late_count": {
                                "$sum": {
                                    "$cond": [
                                        {
                                            "$gt": [
                                                {
                                                    "$ifNull": [
                                                        "$late_minutes",
                                                        0,
                                                    ]
                                                },
                                                0,
                                            ]
                                        },
                                        1,
                                        0,
                                    ]
                                }
                            },
                        }
                    },
                ],
                "as": "daily",
            }
        },
        {
            "$set": {
                "daily": {
                    "$ifNull": [
                        {"$arrayElemAt": ["$daily", 0]},
                        {},
                    ]
                },
                "headcount": {
                    "$size": {
                        "$filter": {
                            "input": "$employees",
                            "as": "employee",
                            "cond": {
                                "$lte": [
                                    "$$employee.joined_on",
                                    "$day_string",
                                ]
                            },
                        }
                    }
                },
            }
        },
        {
            "$set": {
                "is_working_day": {
                    "$and": [
                        {"$gte": ["$day_of_week", 2]},
                        {"$lte": ["$day_of_week", 6]},
                    ]
                },
                "present_count": {
                    "$ifNull": ["$daily.present_count", 0]
                },
                "late_count": {
                    "$ifNull": ["$daily.late_count", 0]
                },
            }
        },
        {
            "$set": {
                "attendance_rate_raw": {
                    "$cond": [
                        {
                            "$and": [
                                "$is_working_day",
                                {"$gt": ["$headcount", 0]},
                            ]
                        },
                        {
                            "$divide": [
                                "$present_count",
                                "$headcount",
                            ]
                        },
                        None,
                    ]
                }
            }
        },
        {
            "$set": {
                "attendance_rate": {
                    "$cond": [
                        {"$eq": ["$attendance_rate_raw", None]},
                        None,
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    "$attendance_rate_raw",
                                                    10000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                    ]
                }
            }
        },
        {
            "$setWindowFields": {
                "sortBy": {"days": 1},
                "output": {
                    "moving_avg_raw": {
                        "$avg": "$attendance_rate",
                        "window": {"documents": [-6, 0]},
                    }
                },
            }
        },
        {
            "$set": {
                "moving_avg_7d": {
                    "$cond": [
                        {"$eq": ["$moving_avg_raw", None]},
                        None,
                        {
                            "$divide": [
                                {
                                    "$floor": {
                                        "$add": [
                                            {
                                                "$multiply": [
                                                    "$moving_avg_raw",
                                                    10000,
                                                ]
                                            },
                                            0.5,
                                        ]
                                    }
                                },
                                10000,
                            ]
                        },
                    ]
                }
            }
        },
        {
            "$project": {
                "_id": 0,
                "date": "$day_string",
                "is_working_day": 1,
                "headcount": 1,
                "present_count": 1,
                "late_count": 1,
                "attendance_rate": 1,
                "moving_avg_7d": 1,
            }
        },
        {"$sort": {"date": 1}},
    ]

    return pipeline


@app.get("/analytics/departments/{department}/trend")
def department_trend(
    department: str,
    from_date: str = Query(..., alias="from"),
    to_date: str = Query(..., alias="to"),
):
    """Return daily attendance trends for the requested date range."""
    try:
        start_date = date.fromisoformat(from_date)
        end_date = date.fromisoformat(to_date)

        if start_date.isoformat() != from_date:
            raise ValueError
        if end_date.isoformat() != to_date:
            raise ValueError
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="from and to must use YYYY-MM-DD format",
        )

    if end_date < start_date:
        raise HTTPException(
            status_code=422,
            detail="to must be on or after from",
        )

    number_of_days = (end_date - start_date).days + 1

    if number_of_days > 92:
        raise HTTPException(
            status_code=422,
            detail="Date range cannot exceed 92 days",
        )

    if not db.employees.find_one({"department": department}):
        raise HTTPException(
            status_code=404,
            detail="Department not found",
        )

    pipeline = build_department_trend_pipeline(
        department,
        from_date,
        to_date,
    )

    items = list(db.employees.aggregate(pipeline))

    return {
        "department": department,
        "items": items,
    }





@app.get("/admin/explain/{endpoint}")
def explain_endpoint(
    endpoint: str,
    emp_code: Optional[str] = None,
    month: Optional[str] = None,
    department: Optional[str] = None,
    limit: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    from_date: Optional[str] = Query(None, alias="from"),
    to_date: Optional[str] = Query(None, alias="to"),
):
    allowed = {
        "attendance_list",
        "employee_monthly",
        "department_summary",
        "late_leaderboard",
        "department_trend",
    }

    if endpoint not in allowed:
        raise HTTPException(
            status_code=422,
            detail="Unsupported endpoint",
        )

    def explain_find(collection, query, sort=None, skip=0, size=None):
        command = {
            "find": collection,
            "filter": query,
        }

        if sort:
            command["sort"] = sort
        if skip:
            command["skip"] = skip
        if size is not None:
            command["limit"] = size

        return db.command(
            "explain",
            command,
            verbosity="executionStats",
        )

    def explain_aggregate(collection, pipeline):
        return db.command(
            "explain",
            {
                "aggregate": collection,
                "pipeline": pipeline,
                "cursor": {},
            },
            verbosity="executionStats",
        )

    if endpoint == "attendance_list":
        query = {}

        if emp_code:
            query["emp_code"] = emp_code

        if date_from or date_to:
            date_filter = {}
            if date_from:
                date_filter["$gte"] = date_from
            if date_to:
                date_filter["$lte"] = date_to
            query["date"] = date_filter

        if status:
            if status not in {
                "PRESENT", "WFH", "ON_DUTY", "ABSENT", "LEAVE"
            }:
                raise HTTPException(
                    status_code=422,
                    detail="Invalid attendance status",
                )
            query["status"] = status

        result = explain_find(
            "attendance_logs",
            query,
            sort={"date": -1, "emp_code": 1},
            skip=(page - 1) * page_size,
            size=page_size,
        )
        collection = "attendance_logs"

    elif endpoint == "employee_monthly":
        if not emp_code or not month:
            raise HTTPException(
                status_code=422,
                detail="emp_code and month are required",
            )

        start, end = month_bounds(month)

        pipeline = [
            {
                "$match": {
                    "emp_code": emp_code,
                    "date": {
                        "$gte": start.isoformat(),
                        "$lt": end.isoformat(),
                    },
                }
            },
            {
                "$set": {
                    "half_day": {"$ifNull": ["$half_day", False]},
                    "late_minutes": {"$ifNull": ["$late_minutes", 0]},
                    "overtime_minutes": {
                        "$ifNull": ["$overtime_minutes", 0]
                    },
                }
            },
            {
                "$set": {
                    "day_of_week": {
                        "$dayOfWeek": {
                            "$dateFromString": {
                                "dateString": "$date",
                                "format": "%Y-%m-%d",
                                "timezone": "Asia/Kolkata",
                            }
                        }
                    }
                }
            },
            {
                "$group": {
                    "_id": None,
                    "present_days": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {
                                            "$in": [
                                                "$status",
                                                ["PRESENT", "WFH", "ON_DUTY"],
                                            ]
                                        },
                                        {"$gte": ["$day_of_week", 2]},
                                        {"$lte": ["$day_of_week", 6]},
                                    ]
                                },
                                {
                                    "$cond": [
                                        {"$eq": ["$half_day", True]},
                                        0.5,
                                        1,
                                    ]
                                },
                                0,
                            ]
                        }
                    },
                    "leave_days": {
                        "$sum": {
                            "$cond": [
                                {"$eq": ["$status", "LEAVE"]},
                                1,
                                0,
                            ]
                        }
                    },
                    "late_count": {
                        "$sum": {
                            "$cond": [
                                {"$gt": ["$late_minutes", 0]},
                                1,
                                0,
                            ]
                        }
                    },
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "total_overtime_minutes": {
                        "$sum": "$overtime_minutes"
                    },
                }
            },
        ]

        result = explain_aggregate("attendance_logs", pipeline)
        collection = "attendance_logs"

    
    elif endpoint == "department_summary":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required",
            )

        start, end = month_bounds(month)
        employee_match = {"joined_on": {"$lt": end.isoformat()}}

        if department:
            employee_match["department"] = department

        pipeline = [
            {"$match": employee_match},
            {
                "$lookup": {
                    "from": "attendance_logs",
                    "let": {"code": "$emp_code"},
                    "pipeline": [
                        {
                            "$match": {
                                "$expr": {
                                    "$and": [
                                        {"$eq": ["$emp_code", "$$code"]},
                                        {"$gte": ["$date", start.isoformat()]},
                                        {"$lt": ["$date", end.isoformat()]},
                                    ]
                                }
                            }
                        },
                        {
                            "$set": {
                                "half_day": {"$ifNull": ["$half_day", False]},
                                "late_minutes": {
                                    "$ifNull": ["$late_minutes", 0]
                                },
                                "work_hours": {
                                    "$ifNull": ["$work_hours", None]
                                },
                            }
                        },
                        {
                            "$set": {
                                "day_of_week": {
                                    "$dayOfWeek": {
                                        "$dateFromString": {
                                            "dateString": "$date",
                                            "format": "%Y-%m-%d",
                                            "timezone": "Asia/Kolkata",
                                        }
                                    }
                                }
                            }
                        },
                        {
                            "$group": {
                                "_id": None,
                                "present_days": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"],
                                                        ]
                                                    },
                                                    {"$gte": ["$day_of_week", 2]},
                                                    {"$lte": ["$day_of_week", 6]},
                                                ]
                                            },
                                            {
                                                "$cond": [
                                                    {"$eq": ["$half_day", True]},
                                                    0.5,
                                                    1,
                                                ]
                                            },
                                            0,
                                        ]
                                    }
                                },
                                "work_hours_sum": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"],
                                                        ]
                                                    },
                                                    {"$ne": ["$work_hours", None]},
                                                ]
                                            },
                                            "$work_hours",
                                            0,
                                        ]
                                    }
                                },
                                "work_hours_count": {
                                    "$sum": {
                                        "$cond": [
                                            {
                                                "$and": [
                                                    {
                                                        "$in": [
                                                            "$status",
                                                            ["PRESENT", "WFH", "ON_DUTY"],
                                                        ]
                                                    },
                                                    {"$ne": ["$work_hours", None]},
                                                ]
                                            },
                                            1,
                                            0,
                                        ]
                                    }
                                },
                                "late_count": {
                                    "$sum": {
                                        "$cond": [
                                            {"$gt": ["$late_minutes", 0]},
                                            1,
                                            0,
                                        ]
                                    }
                                },
                                "total_late_minutes": {"$sum": "$late_minutes"},
                                "leave_count": {
                                    "$sum": {
                                        "$cond": [
                                            {"$eq": ["$status", "LEAVE"]},
                                            1,
                                            0,
                                        ]
                                    }
                                },
                                "on_duty_count": {
                                    "$sum": {
                                        "$cond": [
                                            {"$eq": ["$status", "ON_DUTY"]},
                                            1,
                                            0,
                                        ]
                                    }
                                },
                            }
                        },
                    ],
                    "as": "attendance",
                }
            },
            {
                "$unwind": {
                    "path": "$attendance",
                    "preserveNullAndEmptyArrays": True,
                }
            },
            {
                "$group": {
                    "_id": "$department",
                    "headcount": {"$sum": 1},
                    "present_days": {
                        "$sum": {"$ifNull": ["$attendance.present_days", 0]}
                    },
                    "work_hours_sum": {
                        "$sum": {"$ifNull": ["$attendance.work_hours_sum", 0]}
                    },
                    "work_hours_count": {
                        "$sum": {"$ifNull": ["$attendance.work_hours_count", 0]}
                    },
                    "late_count": {
                        "$sum": {"$ifNull": ["$attendance.late_count", 0]}
                    },
                    "total_late_minutes": {
                        "$sum": {
                            "$ifNull": ["$attendance.total_late_minutes", 0]
                        }
                    },
                    "leave_count": {
                        "$sum": {"$ifNull": ["$attendance.leave_count", 0]}
                    },
                    "on_duty_count": {
                        "$sum": {"$ifNull": ["$attendance.on_duty_count", 0]}
                    },
                }
            },
            {"$sort": {"_id": 1}},
            {
                "$project": {
                    "_id": 0,
                    "department": "$_id",
                    "headcount": 1,
                    "present_days": 1,
                    "work_hours_sum": 1,
                    "work_hours_count": 1,
                    "late_count": 1,
                    "total_late_minutes": 1,
                    "leave_count": 1,
                    "on_duty_count": 1,
                }
            },
        ]

        result = explain_aggregate("employees", pipeline)
        collection = "employees"


    
    elif endpoint == "late_leaderboard":
        if not month:
            raise HTTPException(
                status_code=422,
                detail="month is required",
            )

        start, end = month_bounds(month)

        pipeline = [
            {
                "$match": {
                    "date": {
                        "$gte": start.isoformat(),
                        "$lt": end.isoformat(),
                    },
                    "late_minutes": {"$gt": 0},
                }
            },
            {
                "$group": {
                    "_id": "$emp_code",
                    "total_late_minutes": {"$sum": "$late_minutes"},
                    "late_count": {"$sum": 1},
                }
            },
            {
                "$lookup": {
                    "from": "employees",
                    "localField": "_id",
                    "foreignField": "emp_code",
                    "as": "employee",
                }
            },
            {"$unwind": "$employee"},
        ]

        if department:
            pipeline.append(
                {"$match": {"employee.department": department}}
            )

        pipeline.extend([
            {
                "$setWindowFields": {
                    "sortBy": {"total_late_minutes": -1},
                    "output": {"rank": {"$rank": {}}},
                }
            },
            {"$match": {"rank": {"$lte": limit}}},
            {
                "$sort": {
                    "rank": 1,
                    "total_late_minutes": -1,
                    "_id": 1,
                }
            },
            {
                "$project": {
                    "_id": 0,
                    "rank": 1,
                    "emp_code": "$_id",
                    "name": "$employee.name",
                    "department": "$employee.department",
                    "total_late_minutes": 1,
                    "late_count": 1,
                }
            },
        ])

        result = explain_aggregate("attendance_logs", pipeline)
        collection = "attendance_logs"


    
    else:  # department_trend
        if not department or not from_date or not to_date:
            raise HTTPException(
                status_code=422,
                detail="department, from, and to are required",
            )

        try:
            start_date = date.fromisoformat(from_date)
            end_date = date.fromisoformat(to_date)

            if start_date.isoformat() != from_date:
                raise ValueError
            if end_date.isoformat() != to_date:
                raise ValueError
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail="from and to must use YYYY-MM-DD format",
            )

        if end_date < start_date:
            raise HTTPException(
                status_code=422,
                detail="to must be on or after from",
            )

        if (end_date - start_date).days + 1 > 92:
            raise HTTPException(
                status_code=422,
                detail="Date range cannot exceed 92 days",
            )

        if not db.employees.find_one({"department": department}):
            raise HTTPException(
                status_code=404,
                detail="Department not found",
            )

        pipeline = build_department_trend_pipeline(
            department,
            from_date,
            to_date,
        )

        result = explain_aggregate("employees", pipeline)
        collection = "employees"


    return Response(
        content=json_util.dumps({
            "endpoint": endpoint,
            "collection": collection,
            "explain": result,
        }),
        media_type="application/json",
    )
