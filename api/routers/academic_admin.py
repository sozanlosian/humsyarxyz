"""Secure schedule and grade management endpoints."""

from __future__ import annotations

from html import escape
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel, Field

from api.auth import get_current_user
from api.routers.admin_panel import _audit
from database import db
from grade_utils import normalize_grade
from time_utils import TimeContractError, parse_clock_time, parse_gregorian_date, utc_now_iso


router = APIRouter()

ScheduleType = Literal[
    "class",
    "exam",
    "makeup",
]

ScheduleGroup = Literal[
    "1",
    "2",
    "هر دو",
]

FlexType = Literal[
    "fixed",
    "flexible",
]


async def get_schedule_admin_user(user=Depends(get_current_user)) -> dict:
    """Schedule is global, but may be managed by the dedicated Bot RBAC role.

    A scoped content administrator must not gain access to the complete
    schedule just because the old router used the broad content dependency.
    """
    if await db.has_permission(user["id"], "schedules.manage"):
        return user
    scope = await db.get_content_scope(user["id"])
    if scope and scope.get("kind") == "global":
        user["_scope"] = scope
        return user
    raise HTTPException(status_code=403, detail="schedule_admin_only")


async def get_grade_admin_user(user=Depends(get_current_user)) -> dict:
    """Return a grade actor with a mandatory global or intake scope."""
    if await db.has_permission(user["id"], "grades.manage"):
        user["_scope"] = {"kind": "global", "intake": None}
        return user
    content_scope = await db.get_content_scope(user["id"])
    if content_scope and content_scope.get("kind") == "global":
        user["_scope"] = content_scope
        return user
    if await db.has_permission(user["id"], "grades.scoped"):
        intake = await db.get_scoped_intake(user["id"])
        if intake:
            user["_scope"] = {"kind": "scoped", "intake": intake}
            return user
    # Content-scoped operators historically had grade access. Keep that
    # compatibility path, but attach their actual intake before every query.
    if content_scope and content_scope.get("kind") == "scoped":
        user["_scope"] = content_scope
        return user
    raise HTTPException(status_code=403, detail="grade_admin_only")


def _academic_intake(admin: dict, requested=None) -> str | None:
    scope = admin.get("_scope") or {}
    if scope.get("kind") == "scoped":
        own = scope.get("intake") or ""
        if not own:
            raise HTTPException(403, "intake_scope_not_configured")
        if requested not in (None, "", own):
            raise HTTPException(403, "intake_out_of_scope")
        return own
    return (requested or "") if requested is not None else None


async def _assert_student_scope(admin: dict, student_ids) -> None:
    scope = admin.get("_scope") or {}
    if scope.get("kind") != "scoped":
        return
    own = scope.get("intake") or ""
    ids = [int(uid) for uid in student_ids if uid]
    if not ids:
        return
    allowed = await db.users.distinct("user_id", {"user_id": {"$in": ids}, "intake": own})
    if set(ids) != set(allowed):
        raise HTTPException(403, "student_out_of_scope")


def _clean(
    value,
    max_length: int = 200,
) -> str:
    text = " ".join(
        str(value or "").split()
    )

    return text[:max_length]


def _valid_date(
    value: str,
) -> str:
    try:
        parse_gregorian_date(value)

    except (TimeContractError, TypeError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=(
                "تاریخ باید با فرمت "
                "YYYY-MM-DD باشد"
            ),
        )

    return value


def _valid_time(
    value: str,
) -> str:
    value = (
        value or ""
    ).strip()

    if not value:
        return ""

    # support Persian digits and range remnants like "08:00 تا 10:00" -> take first part
    # but canonical store is single HH:MM; range handled separately via end_time
    # if value contains range separator, extract start
    import re as _re
    from time_utils import en_digits as _en
    v = _en(str(value)).strip()
    # if range present, keep first HH:MM
    m = _re.search(r'(\d{1,2}:\d{2})', v)
    if m:
        v = m.group(1)
        # normalize to HH:MM
        if _re.match(r'^\d{1,2}:\d{2}$', v):
            hh, mm = v.split(':')
            v = f"{int(hh):02d}:{mm}"
    else:
        v = value

    try:
        parse_clock_time(v)

    except (TimeContractError, ValueError):
        raise HTTPException(
            status_code=422,
            detail=(
                "ساعت باید با فرمت "
                "HH:MM باشد"
            ),
        )

    return v


def _valid_time_range(start: str, end: str) -> tuple[str, str]:
    s = _valid_time(start)
    e = _valid_time(end)
    if s and e:
        try:
            from time_utils import en_digits as _en2
            # need to compare times
            st = parse_clock_time(s)
            et = parse_clock_time(e)
            # convert to minutes
            sm = st.hour * 60 + st.minute
            em = et.hour * 60 + et.minute
            if em <= sm:
                raise HTTPException(status_code=422, detail="زمان پایان باید بعد از زمان شروع باشد")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(status_code=422, detail="بازه زمانی نامعتبر است")
    return s, e


def _normalize_range_input(value: str) -> tuple[str, str]:
    """Parse strings like '08:00-10:00', '08:00 تا 10:00', '8-10' into (HH:MM, HH:MM)."""
    if not value:
        return "", ""
    import re as _re2
    from time_utils import en_digits as _en3
    raw = _en3(str(value)).strip().replace('—', '-').replace('–', '-').replace('تا', '-')
    # handle interval like 8-10 or 13-15 without colon
    m_range = _re2.findall(r'(\d{1,2})(?::(\d{2}))?', raw)
    # fallback: try HH:MM pattern
    times = _re2.findall(r'(\d{1,2}:\d{2})', raw)
    if len(times) >= 2:
        return f"{int(times[0].split(':')[0]):02d}:{times[0].split(':')[1]}", f"{int(times[1].split(':')[0]):02d}:{times[1].split(':')[1]}"
    if len(times) == 1:
        # maybe interval like 8-10 with single colon?
        # check original contains dash and second hour without colon
        if '-' in raw:
            parts = raw.split('-')
            if len(parts) == 2:
                a = times[0]
                b = _re2.search(r'(\d{1,2})', parts[1])
                if b:
                    bh = int(b.group(1))
                    return a, f"{bh:02d}:00"
        return times[0], ""
    # handle 8-10 without colon at all
    if '-' in raw and not times:
        parts = [p.strip() for p in raw.split('-')]
        if len(parts) == 2:
            try:
                ah = int(_re2.search(r'\d+', parts[0]).group(0))
                bh = int(_re2.search(r'\d+', parts[1]).group(0))
                return f"{ah:02d}:00", f"{bh:02d}:00"
            except Exception:
                pass
    return raw.strip()[:5], ""


def _schedule_document(
    item: dict,
) -> dict:
    # support both old 'time' single and new 'end_time' range
    # also handle legacy 'time' containing range string "08:00-10:00"
    end = item.get("end_time", "") or item.get("time_end", "") or ""
    start = item.get("time", "") or ""
    # if start contains range, split
    if start and ("-" in start or "تا" in start) and not end:
        try:
            s, e = _normalize_range_input(start)
            if s:
                start = s
            if e:
                end = e
        except Exception:
            pass
    # if time stored as range but end empty, try to synthesize end = start+2h for display legacy?
    return {
        "id": str(
            item.get("_id", "")
        ),

        "type": item.get(
            "type",
            "",
        ),

        "lesson": item.get(
            "lesson",
            "",
        ),

        "teacher": item.get(
            "teacher",
            "",
        ),

        "date": item.get(
            "date",
            "",
        ),

        "time": start,
        "end_time": end,

        "location": item.get(
            "location",
            "",
        ),

        "group": (
            item.get("group")
            or "هر دو"
        ),

        "note": (
            item.get("notes")
            or item.get("note", "")
        ),

        "flex_type": (
            item.get("flex_type")
            or "fixed"
        ),

        "flex_note": item.get(
            "flex_note",
            "",
        ),
    }


class ScheduleCreate(BaseModel):
    type: ScheduleType

    lesson: str = Field(
        min_length=2,
        max_length=100,
    )

    teacher: str = Field(
        default="",
        max_length=100,
    )

    date: str = Field(
        min_length=10,
        max_length=10,
    )

    time: str = Field(
        default="",
        max_length=11,
    )

    end_time: str = Field(
        default="",
        max_length=5,
    )

    group: ScheduleGroup = "هر دو"

    location: str = Field(
        default="",
        max_length=100,
    )

    note: str = Field(
        default="",
        max_length=500,
    )

    flex_type: FlexType = "fixed"


class ScheduleUpdate(BaseModel):
    lesson: str = Field(
        min_length=2,
        max_length=100,
    )

    teacher: str = Field(
        default="",
        max_length=100,
    )

    date: str = Field(
        min_length=10,
        max_length=10,
    )

    time: str = Field(
        default="",
        max_length=11,
    )

    end_time: str = Field(
        default="",
        max_length=5,
    )

    group: ScheduleGroup = "هر دو"

    location: str = Field(
        default="",
        max_length=100,
    )

    note: str = Field(
        default="",
        max_length=500,
    )

    flex_type: FlexType = "fixed"


class FlexChange(BaseModel):
    date: str = Field(
        min_length=10,
        max_length=10,
    )

    time: str = Field(
        min_length=5,
        max_length=5,
    )

    end_time: str = Field(
        default="",
        max_length=5,
    )

    note: str = Field(
        default="",
        max_length=500,
    )


@router.get("/schedule")
async def schedule_list(
    stype: ScheduleType | None = Query(
        default=None
    ),

    admin=Depends(
        get_schedule_admin_user
    ),
):
    items = await db.get_schedules(
        stype=stype,
        upcoming=False,
    )

    if not isinstance(items, list):
        items = []

    return {
        "schedule": [
            _schedule_document(item)
            for item in items
            if isinstance(item, dict)
        ],
    }


@router.post("/schedule")
async def schedule_create(
    body: ScheduleCreate,
    admin=Depends(get_schedule_admin_user),
):
    date = _valid_date(body.date)
    # support range in time field like "08:00-10:00" or "08:00 تا 10:00"
    raw_time = body.time or ""
    raw_end = body.end_time or ""
    if raw_time and ("-" in raw_time or "تا" in raw_time) and not raw_end:
        s, e = _normalize_range_input(raw_time)
        raw_time, raw_end = s, e
    time, end_time = _valid_time_range(raw_time, raw_end)
    lesson = _clean(body.lesson, 100)
    teacher = _clean(body.teacher, 100)
    location = _clean(body.location, 100)
    note = str(body.note or "").strip()[:500]
    group = db.normalize_group(body.group) or "هر دو"
    schedule_id = await db.add_schedule(
        stype=body.type, lesson=lesson, teacher=teacher, date=date, time=time, end_time=end_time,
        location=location, notes=note, group=group, flex_type=body.flex_type)
    item = await db.get_schedule_by_id(str(schedule_id)) or {
        "_id": schedule_id, "type": body.type, "lesson": lesson,
        "teacher": teacher, "date": date, "time": time, "end_time": end_time,
        "location": location, "notes": note, "group": group,
    }
    notice = await db.schedule_notify_event(item, "created")
    await _audit(
        admin, "ایجاد برنامه آموزشی", "Schedules", severity="INFO",
        target_id=str(schedule_id), target_type="schedule", target_label=lesson,
        after={"type": body.type, "date": date, "time": time, "end_time": end_time, "group": group,
               "notified": notice.get("notified", 0)},
        tags=["برنامه", body.type, "پنل_وب"],
    )
    # 🌊 W8/UX-05 — هشدار تداخل (غیرمسدودکننده)
    conflicts = await db.schedule_find_conflicts(
        group, date, time, end_time, exclude_id=str(schedule_id))
    return {"ok": True, "id": str(schedule_id),
            "notified": notice.get("notified", 0),
            "warnings": {"schedule_conflicts": conflicts}}


@router.patch("/schedule/{schedule_id}")
async def schedule_update(
    schedule_id: str, body: ScheduleUpdate,
    admin=Depends(get_schedule_admin_user),
):
    date = _valid_date(body.date)
    raw_time = body.time or ""
    raw_end = body.end_time or ""
    if raw_time and ("-" in raw_time or "تا" in raw_time) and not raw_end:
        s, e = _normalize_range_input(raw_time)
        raw_time, raw_end = s, e
    time, end_time = _valid_time_range(raw_time, raw_end)
    old = await db.get_schedule_by_id(schedule_id)
    if not old:
        raise HTTPException(status_code=404, detail="برنامه پیدا نشد")
    group = db.normalize_group(body.group) or "هر دو"
    ok = await db.update_schedule_full(
        schedule_id, _clean(body.lesson, 100), _clean(body.teacher, 100),
        date, time, _clean(body.location, 100),
        str(body.note or "").strip()[:500], group, body.flex_type, end_time=end_time)
    if not ok:
        raise HTTPException(status_code=404, detail="برنامه پیدا نشد")
    item = await db.get_schedule_by_id(schedule_id) or {
        **old, "lesson": _clean(body.lesson, 100),
        "teacher": _clean(body.teacher, 100), "date": date, "time": time, "end_time": end_time,
        "location": _clean(body.location, 100), "notes": str(body.note or "").strip()[:500],
        "group": group, "flex_type": body.flex_type,
    }
    notice = await db.schedule_notify_event(item, "updated")
    await _audit(
        admin, "ویرایش برنامه آموزشی", "Schedules", severity="WARNING",
        target_id=schedule_id, target_type="schedule", target_label=item.get("lesson", ""),
        before={"lesson": old.get("lesson"), "date": old.get("date"),
                "time": old.get("time"), "end_time": old.get("end_time"), "group": old.get("group")},
        after={"lesson": item.get("lesson"), "date": date, "time": time, "end_time": end_time,
               "group": group, "notified": notice.get("notified", 0)},
        tags=["برنامه", old.get("type", ""), "پنل_وب"],
    )
    return {"ok": True, "notified": notice.get("notified", 0)}


@router.delete("/schedule/{schedule_id}")
async def schedule_delete(
    schedule_id: str, admin=Depends(get_schedule_admin_user),
):
    old = await db.get_schedule_by_id(schedule_id)
    if not old:
        raise HTTPException(status_code=404, detail="برنامه پیدا نشد")
    _res = await db.delete_schedule(schedule_id)
    if _res is None:              # 🛡 AUDIT-R6 — خطای دیتابیس، نه حذف موفق
        raise HTTPException(status_code=500, detail="حذف انجام نشد — دوباره تلاش کنید")
    notice = await db.schedule_notify_event(old, "cancelled")
    await _audit(
        admin, "حذف و لغو برنامه آموزشی", "Schedules", severity="HIGH",
        target_id=schedule_id, target_type="schedule", target_label=old.get("lesson", ""),
        before={"type": old.get("type"), "date": old.get("date"), "group": old.get("group")},
        after={"deleted": True, "notified": notice.get("notified", 0)},
        tags=["برنامه", "لغو", old.get("type", ""), "پنل_وب"],
    )
    return {"ok": True, "notified": notice.get("notified", 0)}


@router.get(
    "/schedule/flexible"
)
async def flexible_schedule_list(
    admin=Depends(
        get_schedule_admin_user
    ),
):
    items = await db.get_schedules(
        upcoming=True
    )

    if not isinstance(items, list):
        items = []

    return {
        "items": [
            _schedule_document(item)
            for item in items
            if (
                isinstance(item, dict)
                and item.get(
                    "flex_type"
                ) == "flexible"
            )
        ],
    }


@router.post("/schedule/{schedule_id}/flex-change")
async def flexible_schedule_change(
    schedule_id: str, body: FlexChange,
    admin=Depends(get_schedule_admin_user),
):
    date = _valid_date(body.date)
    raw_time = body.time or ""
    raw_end = body.end_time or ""
    if raw_time and ("-" in raw_time or "تا" in raw_time) and not raw_end:
        s, e = _normalize_range_input(raw_time)
        raw_time, raw_end = s, e
    time, end_time = _valid_time_range(raw_time, raw_end)
    schedule = await db.get_schedule_by_id(schedule_id)
    if not schedule:
        raise HTTPException(status_code=404, detail="برنامه پیدا نشد")
    if schedule.get("flex_type") != "flexible":
        raise HTTPException(status_code=422, detail="این برنامه منعطف نیست")
    ok = await db.update_schedule_time(schedule_id, date, time,
                                       str(body.note or "").strip()[:500], end_time=end_time)
    if not ok:
        raise HTTPException(status_code=500, detail="تغییر زمان ذخیره نشد")
    item = {**schedule, "date": date, "time": time, "end_time": end_time,
            "flex_note": str(body.note or "").strip()[:500]}
    notice = await db.schedule_notify_event(item, "time_changed")
    await _audit(
        admin, "اعلام تغییر زمان برنامه", "Schedules", severity="WARNING",
        target_id=schedule_id, target_type="schedule", target_label=schedule.get("lesson", ""),
        before={"date": schedule.get("date"), "time": schedule.get("time"), "end_time": schedule.get("end_time")},
        after={"date": date, "time": time, "end_time": end_time,
               "notified": notice.get("notified", 0)},
        tags=["برنامه", "تغییر_زمان", schedule.get("type", ""), "پنل_وب"],
    )
    return {"ok": True, "notified": notice.get("notified", 0)}


# ══════════════════════════════════════════════════
#  📅 الگوهای هفتگی (شنبه-جمعه) + اسکن هوشیار
# ══════════════════════════════════════════════════

class TemplateSlot(BaseModel):
    weekday: int = Field(ge=0, le=6, description="0=شنبه ... 6=جمعه")
    time: str = Field(min_length=4, max_length=11, description="شروع HH:MM یا بازه HH:MM-HH:MM")
    end_time: str = Field(default="", max_length=5, description="پایان HH:MM اختیاری")
    lesson: str = Field(min_length=1, max_length=120)
    teacher: str = Field(default="", max_length=80)
    location: str = Field(default="", max_length=80)
    group: ScheduleGroup = "هر دو"
    flex_type: FlexType = "fixed"
    notes: str = Field(default="", max_length=300)
    type: ScheduleType = "class"

class TemplateBulk(BaseModel):
    slots: list[TemplateSlot] = Field(min_length=1, max_length=200)
    clear_existing: bool = False
    group: ScheduleGroup | None = None

class TemplateGenerate(BaseModel):
    start_date: str = Field(min_length=8, max_length=12, description="YYYY/MM/DD jalali or YYYY-MM-DD gregorian")
    end_date: str = Field(min_length=8, max_length=12)
    group: ScheduleGroup | None = None
    dry_run: bool = False

def _tpl_doc(item: dict) -> dict:
    # legacy support: if time contains range, split; if end_time stored separately, return both
    start = item.get("time", "") or ""
    end = item.get("end_time", "") or item.get("time_end", "") or ""
    if start and ("-" in start or "تا" in start) and not end:
        try:
            s, e = _normalize_range_input(start)
            if s:
                start = s
            if e:
                end = e
        except Exception:
            pass
    return {
        "weekday": item.get("weekday"),
        "time": start,
        "end_time": end,
        # for compatibility, also expose time_end alias
        "time_end": end,
        "lesson": item.get("lesson", ""),
        "teacher": item.get("teacher", ""),
        "location": item.get("location", ""),
        "group": item.get("group") or "هر دو",
        "flex_type": item.get("flex_type") or "fixed",
        "notes": item.get("notes") or "",
        "type": item.get("type") or "class",
    }

@router.get("/schedule/templates")
async def schedule_templates_list(
    group: ScheduleGroup | None = Query(default=None),
    admin=Depends(get_schedule_admin_user),
):
    items = await db.get_schedule_templates(group=group)
    return {"templates": [_tpl_doc(i) for i in (items or [])], "total": len(items or [])}

@router.post("/schedule/templates/bulk")
async def schedule_templates_bulk(
    body: TemplateBulk,
    admin=Depends(get_schedule_admin_user),
):
    if body.clear_existing:
        await db.clear_schedule_templates(group=body.group)
    # validate times: support range in time field and separate end_time
    normalized_slots = []
    for s in body.slots:
        d = s.model_dump()
        rt = str(d.get("time") or "")
        re_ = str(d.get("end_time") or "")
        # if time contains range like "08:00-10:00" or "08:00 تا 10:00" and end empty, split
        if rt and ("-" in rt or "تا" in rt) and not re_:
            try:
                rs, re2 = _normalize_range_input(rt)
                d["time"] = rs
                d["end_time"] = re2
                rt, re_ = rs, re2
            except Exception:
                pass
        _valid_time_range(rt, re_)
        # normalize empty end_time synthesis: if no end but valid start, keep empty (DB will synthesize +2h if needed for display)
        normalized_slots.append(d)
    result = await db.bulk_upsert_schedule_templates(normalized_slots)
    await _audit(admin, "ثبت الگوی هفتگی", "Schedules", severity="INFO",
                 target_type="schedule_template", target_label=f"{result['total']} ردیف",
                 after=result, tags=["الگوی_هفتگی", "پنل_وب"])
    return {"ok": True, **result}

@router.delete("/schedule/templates")
async def schedule_templates_clear(
    group: ScheduleGroup | None = Query(default=None),
    admin=Depends(get_schedule_admin_user),
):
    n = await db.clear_schedule_templates(group=group)
    await _audit(admin, "پاک‌سازی الگوی هفتگی", "Schedules", severity="WARNING",
                 target_type="schedule_template", target_label=str(group or "همه"),
                 after={"deleted": n}, tags=["الگوی_هفتگی", "پاکسازی", "پنل_وب"])
    return {"ok": True, "deleted": n}

@router.post("/schedule/templates/generate")
async def schedule_templates_generate(
    body: TemplateGenerate,
    admin=Depends(get_schedule_admin_user),
):
    result = await db.generate_schedules_from_templates(
        body.start_date, body.end_date, group=(body.group or None), dry_run=body.dry_run
    )
    if not result.get("ok"):
        raise HTTPException(status_code=422, detail=result.get("error") or "خطا در تولید برنامه")
    if not body.dry_run:
        await _audit(admin, "تولید برنامه از الگوی هفتگی", "Schedules", severity="INFO",
                     target_type="schedule", target_label=f"{body.start_date} تا {body.end_date}",
                     after={"created": result.get("created"), "skipped": result.get("skipped"), "group": body.group},
                     tags=["الگوی_هفتگی", "تولید", "پنل_وب"])
    return result

MAX_SCAN_BYTES = 12 * 1024 * 1024

async def _read_scan_upload(file: UploadFile) -> tuple[bytes, str]:
    if not file or not getattr(file, "filename", None):
        raise HTTPException(status_code=400, detail="فایل عکس ارسال نشده")
    ctype = (file.content_type or "").lower()
    if ctype not in ("image/jpeg", "image/png", "image/webp", "image/jpg", "image/heic", "image/heif"):
        # allow common image types; fallback check filename ext
        name = (file.filename or "").lower()
        if not any(name.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif")):
            raise HTTPException(status_code=415, detail="فرمت عکس باید JPG/PNG/WEBP باشد")
    data = await file.read()
    if not data or len(data) < 200:
        raise HTTPException(status_code=400, detail="فایل خالی یا خراب است")
    if len(data) > MAX_SCAN_BYTES:
        raise HTTPException(status_code=413, detail="حجم عکس بیش از حد زیاد است (حداکثر 12MB)")
    mime = ctype or "image/jpeg"
    if mime == "image/jpg":
        mime = "image/jpeg"
    return data, mime

@router.post("/schedule/templates/scan")
async def schedule_templates_scan(
    file: UploadFile = File(...),
    group: ScheduleGroup | None = Query(default=None, description="اگر جدول یک گروه خاص است"),
    admin=Depends(get_schedule_admin_user),
):
    image_bytes, mime = await _read_scan_upload(file)
    try:
        from ai_solver import scan_weekly_schedule_image
        parsed = await scan_weekly_schedule_image(image_bytes, mime, group_hint=(group or None))
    except Exception as e:
        from ai_solver import AIConfigError, AIError
        if isinstance(e, (AIConfigError, AIError)):
            raise HTTPException(status_code=422, detail=str(e))
        raise HTTPException(status_code=500, detail=f"اسکن ناموفق: {e}")
    slots = parsed.get("slots") or []
    # preview: no DB write yet
    return {"ok": True, "slots": slots, "count": len(slots)}

@router.post("/schedule/templates/scan/confirm")
async def schedule_templates_scan_confirm(
    body: TemplateBulk,
    admin=Depends(get_schedule_admin_user),
):
    # same as bulk but from scan preview — with range support
    if body.clear_existing:
        await db.clear_schedule_templates(group=body.group)
    normalized_slots = []
    for s in body.slots:
        d = s.model_dump()
        rt = str(d.get("time") or "")
        re_ = str(d.get("end_time") or "")
        if rt and ("-" in rt or "تا" in rt) and not re_:
            try:
                rs, re2 = _normalize_range_input(rt)
                d["time"] = rs
                d["end_time"] = re2
                rt, re_ = rs, re2
            except Exception:
                pass
        _valid_time_range(rt, re_)
        normalized_slots.append(d)
    result = await db.bulk_upsert_schedule_templates(normalized_slots)
    await _audit(admin, "تایید اسکن الگوی هفتگی", "Schedules", severity="INFO",
                 target_type="schedule_template", target_label=f"{result['total']} ردیف از اسکن",
                 after=result, tags=["الگوی_هفتگی", "اسکن_هوشیار", "پنل_وب"])
    return {"ok": True, **result}

@router.post("/schedule/exams/scan")
async def schedule_exams_scan(
    file: UploadFile = File(...),
    admin=Depends(get_schedule_admin_user),
):
    image_bytes, mime = await _read_scan_upload(file)
    try:
        from ai_solver import scan_exam_schedule_image
        parsed = await scan_exam_schedule_image(image_bytes, mime)
    except Exception as e:
        from ai_solver import AIConfigError, AIError
        if isinstance(e, (AIConfigError, AIError)):
            raise HTTPException(status_code=422, detail=str(e))
        raise HTTPException(status_code=500, detail=f"اسکن ناموفق: {e}")
    exams = parsed.get("exams") or []
    return {"ok": True, "exams": exams, "count": len(exams)}

class ExamBulkConfirm(BaseModel):
    exams: list[dict] = Field(min_length=1, max_length=100)

@router.post("/schedule/exams/scan/confirm")
async def schedule_exams_scan_confirm(
    body: ExamBulkConfirm,
    admin=Depends(get_schedule_admin_user),
):
    from time_utils import parse_gregorian_date, parse_jalali_date, TimeContractError, en_digits
    created = 0
    skipped = 0
    for raw in body.exams:
        try:
            lesson = str(raw.get("lesson") or "").strip()
            if not lesson:
                skipped += 1
                continue
            raw_date = str(raw.get("date") or "").strip()
            if not raw_date:
                skipped += 1
                continue
            # normalize jalali date to gregorian machine date
            normalized = en_digits(raw_date).replace("/", "-")
            try:
                y = int(normalized.split("-", 1)[0])
                if 1200 <= y <= 1600:
                    gdate = parse_jalali_date(raw_date).isoformat()
                else:
                    gdate = parse_gregorian_date(normalized).isoformat()
            except Exception:
                skipped += 1
                continue
            time_v = str(raw.get("time") or "08:00").strip()
            try:
                parse_clock_time(time_v)
            except Exception:
                time_v = "08:00"
            group = db.normalize_group(raw.get("group") or "هر دو") or "هر دو"
            location = str(raw.get("location") or "").strip()[:80]
            # idempotent by date+time+lesson
            exists = await db.schedules.find_one({"date": gdate, "type": "exam", "lesson": lesson, "time": time_v})
            if exists:
                skipped += 1
                continue
            await db.add_schedule("exam", lesson, "", gdate, time_v, location, "", group)
            created += 1
        except Exception:
            skipped += 1
            continue
    await _audit(admin, "تایید اسکن امتحانات", "Schedules", severity="INFO",
                 target_type="schedule", target_label=f"{created} امتحان از اسکن",
                 after={"created": created, "skipped": skipped}, tags=["امتحان", "اسکن_هوشیار", "پنل_وب"])
    return {"ok": True, "created": created, "skipped": skipped}


class GradeEntry(BaseModel):
    user_id: int = Field(
        gt=0
    )

    score: float = Field(
        ge=0,
        le=20,
    )


class GradeBulkCreate(BaseModel):
    entries: list[GradeEntry] = Field(
        min_length=1,
        max_length=500,
    )

    lesson: str = Field(
        min_length=2,
        max_length=100,
    )

    exam_title: str = Field(
        min_length=2,
        max_length=100,
    )

    exam_date: str = Field(
        min_length=10,
        max_length=10,
    )

    # 🛡 §۸۲-ج — ترمِ صریح و طبقه‌بندی‌شده.
    # ترم الزامی است: اگر خالی/None باشد سرور از روی bs_lessons حدس می‌زند؛
    # اما اگر درس در فهرست نباشد ثبت «بدون ترم» ممنوع است و باید ۴۲۲ برگردد
    # تا ادمین ترم را صریحاً انتخاب کند (هر ترم بلوک جدا با میانگین جدا).
    term: str | None = Field(
        default=None,
        max_length=40,
        description="ترم الزامی — مثل «ترم ۱»؛ خالی فقط اگر درس در bs_lessons ترم داشته باشد",
    )


class GradeUpdate(BaseModel):
    score: float = Field(
        ge=0,
        le=20,
    )


@router.post("/grades/bulk")
async def grades_bulk_create(
    body: GradeBulkCreate,

    admin=Depends(
        get_grade_admin_user
    ),
):
    exam_date = _valid_date(
        body.exam_date
    )

    lesson = _clean(
        body.lesson,
        100,
    )

    exam_title = _clean(
        body.exam_title,
        100,
    )

    term = _clean(
        body.term or "",
        40,
    ) or None
    # 🛡 §۸۲-ج — ترم الزامی + حدس خودکارِ هوشمند
    # اگر ترم صریح نیامده، از روی درس حدس زده می‌شود؛ ولی اگر حتی حدس هم
    # خالی ماند، ثبت «بدون ترم» ممنوع است و باید کاربر را مجبور به انتخاب کنیم.
    if not term:
        try:
            inferred = await db.lesson_term(lesson)
            if inferred and str(inferred).strip():
                term = str(inferred).strip()[:40]
        except Exception:
            pass
    if not term:
        raise HTTPException(
            status_code=422,
            detail="ترم الزامی است — لطفاً ترم مربوط به درس را انتخاب کنید (مثلاً «ترم ۱»). اگر درس در فهرست نیست، ترم را به‌صورت دستی مشخص کنید.",
        )

    user_ids = [
        entry.user_id
        for entry in body.entries
    ]
    await _assert_student_scope(admin, user_ids)

    if (
        len(user_ids)
        != len(set(user_ids))
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "هر دانشجو فقط یک بار "
                "باید در لیست باشد"
            ),
        )

    users = await db.users.find(
        {
            "user_id": {
                "$in": user_ids,
            },

            "approved": True,
        },
        {
            "user_id": 1,
        },
    ).to_list(
        len(user_ids)
    )

    valid_ids = {
        int(user["user_id"])
        for user in users
        if user.get("user_id")
    }

    if any(
        user_id not in valid_ids
        for user_id in user_ids
    ):
        raise HTTPException(
            status_code=422,
            detail=(
                "یک یا چند دانشجو "
                "معتبر یا تأییدشده نیستند"
            ),
        )

    saved = await db.grade_bulk_upsert(
        entries=[
            entry.model_dump()
            for entry in body.entries
        ],

        lesson=lesson,

        exam_title=exam_title,

        exam_date=exam_date,

        entered_by=admin["id"],

        # 🛡 §۸۲-ج — ترم در این نقطه حتماً پر است (یا صریح یا حدس‌زده‌شده)؛
        # db-grade_bulk_upsert دیگر حدسِ دوباره نمی‌زند و «بدون ترم» تولید نمی‌شود.
        term=term,
    )

    notified = 0

    try:
        collection = (
            db.client["medicalbot"]
            ["bot_notifications"]
        )

        safe_lesson = escape(
            lesson
        )

        safe_title = escape(
            exam_title
        )

        documents = [
            {
                "type":
                    "grade_notif",

                "chat_id":
                    item["student_id"],

                "text": (
                    "📊 <b>نمره‌ی جدید "
                    "ثبت شد</b>"

                    f"\n📚 "
                    f"{safe_lesson} — "
                    f"{safe_title}"

                    f"\n🎯 نمره: "
                    f"{item['score']}/20"
                ),

                "sent":
                    False,

                "created_at":
                    utc_now_iso(),
            }

            for item in saved
        ]

        if documents:
            await collection.insert_many(
                documents
            )

        notified = len(documents)

        # 🔔 موج ۴.۹۰ — اینباکس مینی‌اپ (نمره → تب کارنامه)
        from urllib.parse import quote as _qq3
        await db.inbox_add_many([
            {'user_id': item['student_id'], 'type': 'grade',
             'title': "📊 نمره‌ی جدید ثبت شد",
             'body': (f"📚 {lesson} — {exam_title}\n"
                      f"🎯 نمره: {item['score']}/20"),
             'link': '/grades?hl=' + _qq3(str(lesson or ''))}
            for item in saved if item.get('student_id')
        ])

    except Exception:
        notified = 0

    await _audit(
        admin, "ثبت گروهی نمره", "Grades", severity="WARNING",
        target_type="grades", target_label=f"{len(saved)} دانشجو",
        after={"lesson": lesson, "exam_title": exam_title,
               # ترمِ نهایی از خودِ رکوردِ ذخیره‌شده خوانده می‌شود، نه از ورودی،
               # تا لاگ حدسِ خودکار را هم ثبت کند نه فقط انتخابِ دستی را.
               "term": (saved[0].get("term") if saved else term) or "",
               "term_explicit": bool(term),
               "updated": len(saved), "notified": notified},
        tags=["نمرات", "ثبت_گروهی", "پنل_وب"],
    )
    return {
        "ok": True,
        "updated": len(saved),
        "notified": notified,
    }


@router.get("/grades/term-options")
async def grades_term_options(
    admin=Depends(get_grade_admin_user),
):
    """🛡 §۸۲-ب — گزینه‌های ترم برای فرمِ ثبت نمره.

    فقط `grade_terms()` کافی نیست: آن فقط ترم‌هایی را می‌دهد که *از قبل*
    نمره دارند، پس ترمِ تازه هرگز در منو ظاهر نمی‌شد (مشکل مرغ‌وتخم‌مرغ).
    اینجا ترم‌های تعریف‌شده‌ی برنامه‌ی درسی با ترم‌های دارای نمره ادغام
    می‌شوند و با همان `_term_rank` مرتب می‌شوند تا «ترم ۱۰» بعد از «ترم ۲»
    بیاید، نه بینِ ۱ و ۲.
    """
    from grade_utils import _term_rank, TERM_ORDER

    known: list[str] = []
    try:
        from api.routers.content_admin import TERMS as _TERMS
        known = [str(t).strip() for t in (_TERMS or []) if str(t).strip()]
    except Exception:
        known = []
    # 🛡 §۸۲-ج — برنامه‌ی درسی ۸ ترمه است؛ منوی ثبت باید همه‌ی ۸ ترم را نشان دهد،
    # حتی اگر هنوز نمره‌ای برای ترم ۶-۸ ثبت نشده (وگرنه طبقه‌بندی ناقص می‌ماند).
    try:
        for t in TERM_ORDER:
            tt = str(t).strip()
            if tt and tt not in known:
                known.append(tt)
    except Exception:
        pass

    used: list[str] = []
    try:
        used = [str(t).strip() for t in (await db.grade_terms() or []) if str(t).strip()]
    except Exception:
        used = []

    merged = sorted(set(known) | set(used), key=_term_rank)
    return {"terms": merged, "defined": known, "used": used}


@router.get("/grades/lesson-term")
async def grades_lesson_term(
    lesson: str = Query(..., min_length=1, max_length=120),
    admin=Depends(get_grade_admin_user),
):
    """🛡 §۸۲-ج — حدسِ ترم از روی نامِ درس (برای پرکردن خودکار منوی ترم).

    پنل وب/مینی‌اپ هنگام تایپِ درس این را صدا می‌زند تا ترمِ پیشنهادی
    پررنگ نشان داده شود؛ ولی ثبت نهایی همچنان ترمِ صریحِ انتخاب‌شده را
    می‌خواهد (بدون ترم ممنوع).
    """
    term = ""
    try:
        term = await db.lesson_term(lesson.strip())
    except Exception:
        term = ""
    return {"lesson": lesson.strip()[:120], "term": (term or "").strip()[:40]}


@router.get("/grades/recent")
async def grades_recent(
    skip: int = Query(
        default=0,
        ge=0,
    ),

    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),

    intake: str | None = Query(default=None, max_length=50),
    group: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=100),
    lesson: str | None = Query(default=None, max_length=100),
    date_from: str | None = Query(default=None, max_length=10),
    date_to: str | None = Query(default=None, max_length=10),
    # 🛡 AUDIT-§۸۲ — فیلتر ترم (§۸۲): «نمرات ترم ۲» جدا از ترم ۱/۳/۴
    term: str | None = Query(default=None, max_length=40),

    admin=Depends(
        get_grade_admin_user
    ),
):
    intake = _academic_intake(admin, intake)
    term = term.strip()[:40] if isinstance(term, str) and term.strip() else None
    group = group if isinstance(group, str) else None
    q = q if isinstance(q, str) else None
    lesson = lesson if isinstance(lesson, str) else None
    date_from = _valid_date(date_from) if isinstance(date_from, str) else None
    date_to = _valid_date(date_to) if isinstance(date_to, str) else None
    records = (
        await db.grade_list_recent(
            skip=skip, limit=limit, intake=intake,
            group=group, q=q, lesson=lesson, date_from=date_from, date_to=date_to,
            term=term,
        )
    )

    if not isinstance(records, list):
        records = []

    total = (
        await db.grade_count_recent(
            intake=intake, group=group, q=q, lesson=lesson,
            date_from=date_from, date_to=date_to, term=term,
        )
    )

    # تفکیک ترم روی *کل* فیلتر (نه فقط صفحه‌ی جاری) تا میانگین‌ها با
    # صفحه‌بندی تغییر نکنند.
    by_term = await db.grade_term_breakdown(
        intake=intake, group=group, q=q, lesson=lesson,
        date_from=date_from, date_to=date_to, term=None)
    terms = await db.grade_terms()

    user_ids = list({
        item.get("student_id")
        for item in records
        if item.get("student_id")
    })

    if user_ids:
        users = await db.users.find(
            {
                "user_id": {
                    "$in": user_ids,
                }
            },
            {
                "user_id": 1,
                "name": 1,
                "student_id": 1,
            },
        ).to_list(
            len(user_ids)
        )

    else:
        users = []

    users_by_id = {
        item.get("user_id"): item
        for item in users
    }

    result = []

    for record in records:
        grade = normalize_grade(
            record
        )

        if grade is None:
            continue

        user_id = record.get(
            "student_id"
        )

        student = users_by_id.get(
            user_id,
            {},
        )

        result.append({
            **grade,

            "student_id":
                user_id,

            "student_name": (
                student.get("name")
                or f"#{user_id}"
            ),

            "student_number":
                student.get(
                    "student_id",
                    "",
                ),
        })

    return {
        "total": max(
            0,
            int(total or 0),
        ),

        "grades": result,

        # 🛡 AUDIT-§۸۲ — پنل با این دو، سربرگِ ترم و شمارش/میانگین می‌سازد
        "by_term": by_term,
        "terms": terms,
    }


@router.get(
    "/grades/find-student"
)
async def grades_find_student(
    query: str = Query(
        min_length=2,
        max_length=100,
    ),

    admin=Depends(
        get_grade_admin_user
    ),
):
    users = await db.search_users(
        query.strip()
    )
    scope = admin.get("_scope") or {}
    if scope.get("kind") == "scoped":
        own = scope.get("intake") or ""
        users = [user for user in users if (user.get("intake") or "") == own]

    return {
        "students": [
            {
                "id":
                    user.get("user_id"),

                "name":
                    user.get("name", ""),

                "student_id":
                    user.get(
                        "student_id",
                        "",
                    ),

                "group":
                    user.get(
                        "group",
                        "",
                    ),

                "intake":
                    user.get(
                        "intake",
                        "",
                    ),
            }

            for user in users

            if (
                user.get("approved")
                and user.get("user_id")
            )
        ],
    }


@router.patch("/grades/{grade_id}")
async def grade_update(
    grade_id: str, body: GradeUpdate,
    admin=Depends(get_grade_admin_user),
):
    old = await db.grade_get(grade_id)
    if not old:
        raise HTTPException(status_code=404, detail="نمره پیدا نشد")
    await _assert_student_scope(admin, [old.get("student_id")])
    ok = await db.grade_update_score(grade_id, body.score, admin["id"])
    if not ok:
        raise HTTPException(status_code=500, detail="اصلاح نمره انجام نشد")
    uid = old.get("student_id")
    if uid:
        await db.notify_user(
            uid, "grade", title="📊 نمره‌ات اصلاح شد",
            body=(f"📚 {old.get('lesson','')} — {old.get('exam_title','')}\n"
                  f"🎯 نمره جدید: {body.score}/20"),
            link="/grades", dm=(
                f"📊 <b>نمره‌ات اصلاح شد</b>\n\n"
                f"📚 {old.get('lesson','')} — {old.get('exam_title','')}\n"
                f"🎯 نمره جدید: <b>{body.score}/20</b>"),
        )
    await _audit(
        admin, "اصلاح نمره دانشجو", "Grades", severity="HIGH",
        target_id=grade_id, target_type="grade", target_label=str(uid or ""),
        before={"score": old.get("score")}, after={"score": body.score},
        tags=["نمرات", "اصلاح", "پنل_وب"],
    )
    return {"ok": True, "score": body.score}


@router.delete("/grades/{grade_id}")
async def grade_delete(
    grade_id: str, admin=Depends(get_grade_admin_user),
):
    old = await db.grade_get(grade_id)
    if not old:
        raise HTTPException(status_code=404, detail="نمره پیدا نشد")
    await _assert_student_scope(admin, [old.get("student_id")])
    ok = await db.grade_delete(grade_id)
    if not ok:
        raise HTTPException(status_code=500, detail="حذف نمره انجام نشد")
    uid = old.get("student_id")
    if uid:
        await db.notify_user(
            uid, "grade", title="📊 یک نمره از کارنامه حذف شد",
            body=f"📚 {old.get('lesson','')} — {old.get('exam_title','')}",
            link="/grades", dm=(
                f"📊 <b>یک نمره از کارنامه‌ات حذف شد</b>\n\n"
                f"📚 {old.get('lesson','')} — {old.get('exam_title','')}"),
        )
    await _audit(
        admin, "حذف نمره دانشجو", "Grades", severity="HIGH",
        target_id=grade_id, target_type="grade", target_label=str(uid or ""),
        before={"lesson": old.get("lesson"), "exam_title": old.get("exam_title"),
                "score": old.get("score")}, after={"deleted": True},
        tags=["نمرات", "حذف", "پنل_وب"],
    )
    return {"ok": True}
