"""Single permission and scope contract for Question Bank mutations."""
from __future__ import annotations

import os
from typing import Mapping

from .contracts import QuestionDomainError, clean_text


REVIEW_ACTION_PERMISSIONS = {
    "approve": "questions.review",
    "reject": "questions.reject",
    "needs_changes": "questions.reject",
    "edit": "questions.edit",
    "delete": "questions.delete",
    "import": "questions.import",
}


class QuestionPermissionService:
    """Authorizes all Bot/API/WebAdmin question mutations in one place.

    `questions.review_scoped` grants queue access only inside the actor's intake.
    Reject/edit additionally require their granular permission. Import is an
    intentionally owner-only destructive/high-volume capability.
    """

    def __init__(self, database):
        self.db = database

    @staticmethod
    def actor_id(actor: Mapping) -> int:
        return int(actor.get("id") or actor.get("user_id") or 0)

    @staticmethod
    def is_owner(actor: Mapping) -> bool:
        actor_id = QuestionPermissionService.actor_id(actor)
        owner_id = int(os.getenv("ADMIN_ID", "0") or 0)
        return bool(actor.get("is_owner")) or bool(owner_id and actor_id == owner_id)

    async def review_scope(self, actor: Mapping) -> dict:
        uid = self.actor_id(actor)
        if not uid:
            raise QuestionDomainError("review_forbidden", "مجوز بررسی سؤال را ندارید", 403)
        if await self.db.has_permission(uid, "questions.review"):
            return {"kind": "global", "intake": None}
        if await self.db.has_permission(uid, "questions.review_scoped"):
            intake = await self.db.get_scoped_intake(uid)
            if not intake:
                try:
                    info = await self.db.get_user_roles(uid)
                    intake = info.get("scope_intake")
                except Exception:
                    intake = None
            if intake:
                return {"kind": "scoped", "intake": clean_text(intake)}
        raise QuestionDomainError("review_forbidden", "مجوز بررسی سؤال را ندارید", 403)

    async def authorize_review(self, *, actor: Mapping, question: Mapping,
                               action: str) -> dict:
        if action not in {"approve", "reject", "needs_changes", "edit"}:
            raise QuestionDomainError("invalid_review_action", "عملیات بررسی معتبر نیست")
        uid = self.actor_id(actor)
        scope = await self.review_scope(actor)
        required = REVIEW_ACTION_PERMISSIONS[action]
        # Approve is represented by the review permission itself. Other
        # mutations need both queue access and their granular permission.
        if action != "approve" and not await self.db.has_permission(uid, required):
            raise QuestionDomainError("question_permission_denied", "مجوز این عملیات سؤال را ندارید", 403,
                                      {"required": required})
        if scope["kind"] == "scoped" and clean_text(question.get("intake")) != scope["intake"]:
            raise QuestionDomainError("question_out_of_scope", "سؤال خارج از محدوده بررسی شماست", 403)
        # §W10 — قانونِ ضدِ خودتأییدی برداشته شد (تصمیمِ صریحِ محصول).
        #
        # این قانون برای نظارتِ دونفره بود، ولی روی نصبِ تک‌ادمینه نتیجهٔ
        # عملی‌اش «قفلِ دائمی» بود: تنها بازبینِ موجود همان سازنده است، پس
        # سؤال هرگز تأیید نمی‌شد و در پنل هیچ دکمهٔ تأییدی دیده نمی‌شد.
        #
        # امنیت تضعیف نشده: مجوزِ `questions.review` و محدودیتِ scope
        # بالاتر همچنان اجرا می‌شوند، و هر تأیید در تاریخچه و audit با
        # نامِ بازبین ثبت می‌ماند. یعنی «چه کسی تأیید کرد» همچنان
        # قابلِ ردیابی است — فقط دیگر بن‌بست نمی‌سازد.
        #
        # اگر روزی نظارتِ دونفره لازم شد، جای درستش یک تنظیمِ صریح
        # (مثل `require_second_reviewer`) است، نه یک قفلِ سخت‌کدشده.
        return scope

    async def authorize_delete(self, *, actor: Mapping, question: Mapping) -> dict:
        """🛡 §۸۴ — حذفِ سختِ ادمین (تنها مسیرِ اعمالِ `questions.delete`).

        پیش‌تر این کلید در REVIEW_ACTION_PERMISSIONS بود ولی `authorize_review`
        اکشن «delete» را نمی‌پذیرفت، پس هیچ مسیری آن را چک نمی‌کرد: مجوزی که
        روشن/خاموش کردنش در پنل هیچ اثری نداشت.

        قواعد عمداً همان قواعد بررسی‌اند تا رفتار غافلگیرکننده نسازد:
        دسترسی به صف لازم است، مجوزِ ریزدانه‌ی حذف هم جداگانه لازم است، و
        ادمینِ scoped فقط داخل ورودی خودش حذف می‌کند.
        """
        uid = self.actor_id(actor)
        scope = await self.review_scope(actor)
        required = REVIEW_ACTION_PERMISSIONS["delete"]
        if not await self.db.has_permission(uid, required):
            raise QuestionDomainError("question_permission_denied",
                                      "مجوز حذف سؤال را ندارید", 403,
                                      {"required": required})
        if scope["kind"] == "scoped" and clean_text(question.get("intake")) != scope["intake"]:
            raise QuestionDomainError("question_out_of_scope",
                                      "سؤال خارج از محدوده بررسی شماست", 403)
        return scope

    async def authorize_import(self, actor: Mapping) -> None:
        uid = self.actor_id(actor)
        if not self.is_owner(actor):
            raise QuestionDomainError("owner_only_import", "درون‌ریزی JSON فقط برای مالک مجاز است", 403)
        if not await self.db.has_permission(uid, REVIEW_ACTION_PERMISSIONS["import"]):
            raise QuestionDomainError("question_permission_denied", "مجوز درون‌ریزی سؤال را ندارید", 403)

    async def can_receive_review(self, *, user_id: int, question: Mapping) -> bool:
        try:
            await self.authorize_review(actor={"id": int(user_id)}, question=question, action="approve")
            return True
        except QuestionDomainError:
            return False
