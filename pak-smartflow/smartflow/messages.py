"""Multilingual citizen messaging (English / Roman Urdu / Urdu script).

Three renderings of every notice, because Pakistan is trilingual in practice:
the citizen reads the Urdu voice note, the officer reads English, and WhatsApp
forwarding happens in Roman Urdu. All three are generated from one template so
they can never contradict each other.

No LLM is required. An optional Groq backend can polish wording, but the
deterministic templates are the source of truth -- a demo must never depend on
a network call to produce a legally-worded message.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from .legal import SIMULATION_BANNER
from .models import EscalationStage, Notice

_LADDER_LINE = {
    "en": "Late-fee ladder: +10% after 30 days past due, +25% at 60 days, "
          "+50% at 90 days, and the total is capped at 175% of the base fine.",
    "rm": "Late fee ka silsila: due date se 30 din baad +10%, 60 din par +25%, "
          "90 din par +50%, aur kul jurmana asal fine ka 175% se zyada nahi ho sakta.",
    "ur": "تاخیری فیس کا سلسلہ: مقررہ تاریخ سے 30 دن بعد +10%، 60 دن پر +25%، "
          "90 دن پر +50%، اور کل جرمانہ اصل فیس کے 175% سے زیادہ نہیں ہو سکتا۔",
}

_RIGHTS_LINE = {
    "en": "You have the right to see the evidence, dispute this challan, and "
          "request a payment plan.",
    "rm": "Aap ko haq hai ke saboot dekhein, challan ko challenge karein, aur "
          "kishton mein adaigi ki darkhwast dein.",
    "ur": "آپ کو حق ہے کہ ثبوت دیکھیں، چالان پر اعتراض کریں، اور قسطوں میں "
          "ادائیگی کی درخواست دیں۔",
}

TEMPLATES: Mapping[EscalationStage, Mapping[str, str]] = {
    EscalationStage.ISSUED: {
        "subject": "Challan {challan_id} issued - {violation}",
        "en": "Dear citizen, challan {challan_id} has been issued against vehicle "
              "{plate} for {violation}. Base fine: PKR {amount}. Due date: {due_date}. "
              "Evidence bundle {evidence_root} is available in your portal. " + _RIGHTS_LINE["en"],
        "rm": "Mohtaram shehri, gaari {plate} ke khilaf {violation} ka challan "
              "{challan_id} jari kiya gaya hai. Jurmana: {amount} rupay. Aakhri tareekh: "
              "{due_date}. Saboot aap ke portal par mojood hai. " + _RIGHTS_LINE["rm"],
        "ur": "محترم شہری، گاڑی {plate} کے خلاف {violation} کا چالان {challan_id} جاری کیا گیا ہے۔ "
              "جرمانہ: {amount} روپے۔ آخری تاریخ: {due_date}۔ ثبوت آپ کے پورٹل پر موجود ہے۔ "
              + _RIGHTS_LINE["ur"],
    },
    EscalationStage.REMINDER_1: {
        "subject": "Reminder: challan {challan_id} payment due {due_date}",
        "en": "Gentle reminder: challan {challan_id} for vehicle {plate} is still "
              "unpaid. Amount: PKR {amount}. Due date: {due_date}. Paying within the "
              "first 7 days earns a 10% early-payment discount. " + _RIGHTS_LINE["en"],
        "rm": "Yaad dehani: gaari {plate} ka challan {challan_id} abhi tak ada na hua. "
              "Raqam: {amount} rupay. Aakhri tareekh: {due_date}. Pehle 7 din mein adaigi "
              "par 10% riayat milti hai. " + _RIGHTS_LINE["rm"],
        "ur": "یاد دہانی: گاڑی {plate} کا چالان {challan_id} ابھی تک ادا نہیں ہوا۔ "
              "رقم: {amount} روپے۔ آخری تاریخ: {due_date}۔ پہلے سات دنوں میں ادائیگی پر "
              "10% رعایت ملتی ہے۔ " + _RIGHTS_LINE["ur"],
    },
    EscalationStage.REMINDER_2: {
        "subject": "Second reminder: challan {challan_id} - payment plan available",
        "en": "Second reminder for challan {challan_id} (vehicle {plate}). Amount now: "
              "PKR {amount}. You may split this into {instalments} instalments instead of "
              "paying at once. " + _RIGHTS_LINE["en"],
        "rm": "Doosri yaad dehani: challan {challan_id} (gaari {plate}). Raqam ab: {amount} "
              "rupay. Aap ise {instalments} kishton mein bhi ada kar sakte hain. "
              + _RIGHTS_LINE["rm"],
        "ur": "دوسری یاد دہانی: چالان {challan_id} (گاڑی {plate})۔ رقم اب: {amount} روپے۔ "
              "آپ اسے {instalments} قسطوں میں بھی ادا کر سکتے ہیں۔ " + _RIGHTS_LINE["ur"],
    },
    EscalationStage.FINAL_NOTICE: {
        "subject": "Final notice before enforcement review - {challan_id}",
        "en": "Final notice for challan {challan_id} (vehicle {plate}). Outstanding: "
              "PKR {amount}. " + _LADDER_LINE["en"] + " If payment or a dispute is not "
              "recorded, this case will be prepared for authority review. " + _RIGHTS_LINE["en"],
        "rm": "Aakhri notice: challan {challan_id} (gaari {plate}). Wajib ul ada: {amount} "
              "rupay. " + _LADDER_LINE["rm"] + " Agar adaigi ya aitraaz record na hua to "
              "case authority review ke liye tayyar kiya jayega. " + _RIGHTS_LINE["rm"],
        "ur": "آخری نوٹس: چالان {challan_id} (گاڑی {plate})۔ واجب الادا: {amount} روپے۔ "
              + _LADDER_LINE["ur"] + " اگر ادائیگی یا اعتراض درج نہ ہوا تو کیس "
              "اتھارٹی ریویو کے لیے تیار کیا جائے گا۔ " + _RIGHTS_LINE["ur"],
    },
    EscalationStage.ENFORCEMENT_REQUEST: {
        "subject": "Case {challan_id} prepared for authority review (no action taken)",
        "en": "Vehicle {plate} has {unpaid_count} unpaid challans totalling PKR {amount}. "
              "A review packet has been PREPARED for an authorised officer. No licence, "
              "registration, identity document or account of any kind has been, or will "
              "be, suspended by this system. You may still pay or dispute, and the case "
              "will be withdrawn. " + _RIGHTS_LINE["en"],
        "rm": "Gaari {plate} ke khilaf {unpaid_count} challan baqaya hain, kul {amount} "
              "rupay. Aik review packet authorised officer ke liye TAYYAR kiya gaya hai. "
              "Is system ne kisi license, registration, shanakhti dastaweez ya account par "
              "koi pabandi nahi lagai aur nahi laga sakta. Aap abhi bhi adaigi ya aitraaz "
              "kar sakte hain, case wapas le liya jayega. " + _RIGHTS_LINE["rm"],
        "ur": "گاڑی {plate} کے خلاف {unpaid_count} چالان باقی ہیں، کل {amount} روپے۔ "
              "ایک ریویو پیکٹ مجاز افسر کے لیے تیار کیا گیا ہے۔ اس نظام نے کسی لائسنس، "
              "رجسٹریشن، شناختی دستاویز یا اکاؤنٹ پر کوئی پابندی نہیں لگائی اور نہ لگا سکتا۔ "
              "آپ اب بھی ادائیگی یا اعتراض کر سکتے ہیں، کیس واپس لے لیا جائے گا۔ "
              + _RIGHTS_LINE["ur"],
    },
    EscalationStage.RESOLVED: {
        "subject": "Case {challan_id} resolved - thank you",
        "en": "Payment received for challan {challan_id} (vehicle {plate}). Your case is "
              "closed and the enforcement review has been withdrawn. Thank you for "
              "resolving this voluntarily.",
        "rm": "Challan {challan_id} (gaari {plate}) ki adaigi mil gayi. Aap ka case band "
              "kar diya gaya hai aur enforcement review wapas le liya gaya hai. Khud "
              "adaigi karne ka shukriya.",
        "ur": "چالان {challan_id} (گاڑی {plate}) کی ادائیگی مل گئی۔ آپ کا کیس بند کر دیا "
              "گیا ہے اور انفورسمنٹ ریویو واپس لے لیا گیا ہے۔ خود ادائیگی کرنے کا شکریہ۔",
    },
}

DEFAULT_CONTEXT: Mapping[str, Any] = {
    "challan_id": "-",
    "plate": "-",
    "violation": "-",
    "amount": "0",
    "due_date": "-",
    "due_at": "-",
    "days_overdue": "0",
    "evidence_root": "-",
    "instalments": "3",
    "unpaid_count": "1",
    "policy_version": "-",
}


def render_notice(
    stage: EscalationStage,
    context: Mapping[str, Any],
    channel: str,
    sent_at: datetime,
    requires_human_approval: bool = False,
) -> Notice:
    """Render one notice in all three languages from a single template."""
    if stage not in TEMPLATES:
        raise KeyError(f"no citizen template for stage {stage.value}")
    template = TEMPLATES[stage]
    values = {**DEFAULT_CONTEXT, **context}
    subject = template["subject"].format(**values)

    def body(lang: str) -> str:
        text = template[lang].format(**values)
        if values.get("simulation", True):
            return f"{text}\n\n{SIMULATION_BANNER}"
        return text

    return Notice(
        stage=stage,
        channel=channel,
        sent_at=sent_at,
        subject=subject,
        body_english=body("en"),
        body_roman_urdu=body("rm"),
        body_urdu=body("ur"),
        requires_human_approval=requires_human_approval,
    )


DISPUTE_ACK = {
    "en": "Your dispute for challan {challan_id} has been recorded. The penalty is "
          "paused while the evidence bundle is reviewed by a human officer.",
    "rm": "Challan {challan_id} par aap ka aitraaz record kar liya gaya hai. Insani "
          "afsar saboot ka jaiza lene tak jurmana roka gaya hai.",
    "ur": "چالان {challan_id} پر آپ کا اعتراض درج کر لیا گیا ہے۔ انسانی افسر ثبوت کا "
          "جائزہ لینے تک جرمانہ روک دیا گیا ہے۔",
}

APPEAL_OK = {
    "en": "Dispute for challan {challan_id} accepted: the evidence bundle failed "
          "re-verification. The challan is cancelled and no amount is payable.",
    "rm": "Challan {challan_id} par aitraaz manzoor: saboot dobara tasdeeq mein nakaam "
          "raha. Challan mansookh, koi raqam wajib nahi.",
    "ur": "چالان {challan_id} پر اعتراض منظور: ثبوت دوبارہ تصدیق میں ناکام رہا۔ چالان "
          "منسوخ، کوئی رقم واجب نہیں۔",
}


def render_dispute_ack(challan_id: str, accepted: bool) -> dict[str, str]:
    source = APPEAL_OK if accepted else DISPUTE_ACK
    return {lang: text.format(challan_id=challan_id) for lang, text in source.items()}
