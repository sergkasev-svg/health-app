"""
API личного кабинета: настройки, профиль, виталы, документы, severity, чат, симптомы, рекомендации.
Идентификация: при валидном Bearer — user_id из сессии; иначе X-User-Id; при отсутствии — default.
"""
import logging
import mimetypes
import json
import re
import uuid
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from app.api.upload import get_upload_file_path
from app.config import get_settings as get_app_settings
from app.services.document_extraction import extract_text_from_file
from app.services.user_store import (
    add_document as store_add_document,
    add_notification,
    add_symptom_entry,
    append_chat_message,
    append_emergency_audit_event,
    clear_chat_history,
    set_chat_history,
    enforce_chat_retention_policy,
    clear_all_documents,
    delete_document as store_delete_document,
    restore_document as store_restore_document,
    permanent_delete_document as store_permanent_delete_document,
    get_chat_history,
    get_consultation_report_item,
    get_consultation_reports_list,
    get_document_by_id,
    get_documents,
    get_emergency_analytics_snapshot,
    get_last_consultation_report_context,
    get_notifications,
    clear_notifications,
    get_or_create_user_id,
    normalize_subject_id,
    get_lab_cases,
    mark_notifications_read,
    get_latest_action_sequence,
    get_profile,
    get_severity,
    get_settings,
    get_symptom_entries,
    delete_symptom_entries as store_delete_symptom_entries,
    clear_symptom_entries as store_clear_symptom_entries,
    get_vitals,
    resume_chat_from_today_voice_diary,
    save_conversation_as_report,
    save_profile,
    create_lab_case,
    clear_consultation_state,
    get_consultation_state,
    create_share_access,
    create_family_access,
    delete_lab_case,
    clear_all_consultation_reports,
    delete_consultation_report,
    restore_consultation_report,
    permanent_delete_consultation_report as store_permanent_delete_consultation_report,
    purge_deleted_older_than_30_days,
    save_action_sequence,
    save_consultation_state,
    save_severity,
    save_settings,
    save_vitals,
    update_lab_case,
    get_share_accesses,
    get_shared_snapshot_by_token,
    revoke_share_access,
    save_voice_concierge_turn_to_labs,
    update_document as store_update_document,
    archive_voice_dialog,
    get_archived_voice_dialogs,
    restore_voice_dialog,
    delete_archived_voice_dialog,
    clear_archived_voice_dialogs,
)
from app.database import get_db
from app.models import User
from app.services.chat_intent import detect_intent
from app.services.consultation_assistant import run_consultation_turn, run_dialog_companion_turn
from app.services.consultation_engine import run_mikhail_consultation
from app.services.consultation_orchestrator import ConsultationOrchestratorAdapter
from app.services.mikhail_memory_engine import run_mikhail_with_memory
from app.services.red_flag_screening import get_red_flags_faq_response
from app.services.complaint_reference import (
    _has_acne_skin_hormonal_women_query,
    _has_adolescent_anhedonia_apathy_query,
    _has_chronic_fatigue_months_no_recovery_query,
    _has_edema_swelling_women_query,
    _has_gas_bloating_digestion_query,
    _has_hair_loss_diffuse_women_query,
    _has_heavy_menses_iron_priority_context,
    _has_heavy_menstrual_fatigue_hair_loss_query,
    _has_health_anxiety_mortality_fear_query,
    _has_irregular_cycle_women_query,
    _has_knee_postinjury_training_return_query,
    _has_low_mood_apathy_women_query,
    _has_nutrition_supplements_where_to_start_query,
    _has_painful_periods_dysmenorrhea_women_query,
    _has_persistent_fatigue_women_query,
    _has_premenstrual_mood_sweet_craving_query,
    _has_prolonged_appetite_loss_query,
    _has_sweet_craving_standalone_women_query,
    _has_weight_plateau_women_query,
    get_complaint_reference_item_by_id,
    search_complaint_reference,
)
from app.womens_health_canned_texts import WOMENS_HEALTH_SCENARIO_CANNED
from app.services.user_phrase_router import match_user_phrase_preset
from app.services.labs_layer_lookup import get_lab_panel_preview
from app.services.integration_bridge import build_bridge_complaint_protocol
from app.services.female_health_scenarios import (
    COMPLAINT_ID_TO_SCENARIO_ID,
    female_health_extra_structured,
    format_female_health_appendix_for_complaint,
)

_FEMALE_HEALTH_LIBRARY_COMPLAINT_IDS: frozenset[str] = frozenset(COMPLAINT_ID_TO_SCENARIO_ID.keys())
from app.services.fatigue_scenarios import (
    fatigue_extra_structured,
    format_fatigue_appendix_for_complaint,
)
from app.services.gi_scenarios import (
    gi_extra_structured,
    format_gi_appendix_for_complaint,
)
try:
    from app.medical_core.engine import MedicalCoreEngine
except Exception:  # optional add-only overlay
    MedicalCoreEngine = None
from app.services.voice_turn_policy import (
    build_voice_meta,
    default_voice_state,
    normalize_voice_state,
)
from app.services.voice_followup_bridge import merge_voice_turn_into_payload
from app.services.final_relevance_gate import apply_final_relevance_gate
from app.services.substantive_clinical_core import clinical_core_envelope, tag_unified_snapshot
from sqlalchemy.orm import Session

# Превью ответа (response_simple / push): 1200 символов обрезало эталон по астении до «нервная сист…».
_RESPONSE_SIMPLE_MAX_CHARS = 6000


def _get_db_user_optional(db: Session, user_id_str: str) -> Optional[User]:
    """Для умного Михаила с памятью: получить User по строковому id (X-User-Id)."""
    if not user_id_str or user_id_str == "default":
        return None
    try:
        user_id_int = int(user_id_str) if user_id_str.isdigit() else None
    except (TypeError, ValueError):
        return None
    if not user_id_int:
        return None
    user = db.query(User).filter(User.id == user_id_int).first()
    if not user:
        try:
            user = User(id=user_id_int)
            db.add(user)
            db.commit()
            db.refresh(user)
        except Exception:
            return None
    return user


def _is_repeat_request(message: str) -> bool:
    """Запросы вроде «Повтори», «Повтори ещё раз», «Повтори пожалуйста» — повтор последних рекомендаций."""
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    if not t:
        return False
    repeat_phrases = (
        "повтори",
        "повторите",
        "повтори ещё раз",
        "ещё раз повтори",
        "повтори пожалуйста",
        "повторите пожалуйста",
        "можно повторить",
        "повторить",
        "скажи ещё раз",
        "скажите ещё раз",
        "озвучь ещё раз",
        "озвучьте ещё раз",
        "я не услышал",
        "не услышал тебя",
        "не услышал вас",
        "не расслышал",
        "плохо слышно",
    )
    return any(p in t for p in repeat_phrases) or t in ("повтори", "повторите", "повторить")


def _is_red_flags_faq_request(message: str) -> bool:
    """Запросы вроде «что такое ред флаги», «ред флаг что это» — отдаём структурированный список красных флагов."""
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    if not t:
        return False
    keywords = (
        "ред флаг",
        "редкие флаги",
        "красные флаги",
        "красный флаг",
        "что такое ред",
        "что такое красные флаги",
        "ред флаги что",
        "объясни ред флаг",
        "расскажи про ред флаги",
    )
    return any(k in t for k in keywords) or t in ("ред флаги", "ред флаг", "красные флаги", "красный флаг")


def _is_small_talk_request(message: str) -> bool:
    """Небольшой бытовой диалог (приветствия/как дела), который не должен запускать мед-триаж."""
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    if not t:
        return False
    if _user_constitutional_fatigue_primary(message):
        return False
    small_talk_markers = (
        "привет",
        "здравствуй",
        "здравствуйте",
        "доброе утро",
        "добрый день",
        "добрый вечер",
        "как дела",
        "как у тебя дела",
        "как твои дела",
        "как твое дело",
        "как жизнь",
        "как сам",
        "как поживаешь",
        "как настроение",
        "что нового",
        "погода",
        "на улице",
        "дождь",
        "снег",
        "ветер",
        "жара",
        "холодно",
    )
    has_small_talk = any(m in t for m in small_talk_markers)
    has_medical = _contains_medical_markers(t)
    return has_small_talk and not has_medical


def _small_talk_response(message: str) -> str:
    """Короткий человеческий ответ без перевода в симптомный сценарий."""
    t = (message or "").strip().lower()
    if "спасибо" in t or "благодар" in t:
        return "Рад помочь. Если будет медицинский вопрос — разберём спокойно и по шагам."
    if "погод" in t or "дожд" in t or "снег" in t or "ветер" in t:
        return "Про погоду могу поболтать коротко, но точный прогноз не даю. Если хотите, подскажу, как одеться по самочувствию и погоде."
    if "что нового" in t:
        return "На связи и готов помочь по здоровью. Можете рассказать, что вас беспокоит."
    if "привет" in t or "здравств" in t or "добр" in t:
        return "Здравствуйте. Я на связи и готов помочь."
    return (
        "Я на связи. Если вопрос про самочувствие — напишите одним сообщением, "
        "что именно беспокоит и как давно это началось."
    )


def _is_presence_check_request(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    markers = (
        "ты здесь",
        "ты тут",
        "михаил ты здесь",
        "михаил ты тут",
        "ты на связи",
        "вы на связи",
    )
    return any(m in t for m in markers)


def _presence_check_response() -> str:
    return "Да, я здесь и на связи. Готов помочь по вашему вопросу."


def _is_audio_clarity_request(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    markers = (
        "не услышал",
        "не расслышал",
        "плохо слышно",
        "я тебя не слышу",
        "я вас не слышу",
        "не слышу тебя",
        "не слышу вас",
        "не слышу михаил",
        "не слышу тебя михаил",
        "ты меня слышишь",
        "вы меня слышите",
        "слышно меня",
        "повтори",
        "повтори",
        "повторите",
    )
    return any(m in t for m in markers)


def _audio_clarity_response() -> str:
    return "Я на связи. Повторяю: опишите, пожалуйста, вашу жалобу одним предложением."


def _is_clarify_rephrase_request(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    markers = (
        "не понял вопрос",
        "не понял",
        "непонятно",
        "не ясно",
        "неясно",
        "что за вопрос",
        "повтори вопрос",
        "переформулируй",
        "что ты имеешь в виду",
    )
    return any(m in t for m in markers)


def _clarify_rephrase_response(question: str) -> str:
    q = str(question or "").strip()
    if not q:
        return "Переформулирую короче: что именно сейчас беспокоит?"
    return f"Переформулирую короче: {q}"


def _is_dialog_reset_request(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    markers = (
        "о чем ты",
        "о чём ты",
        "что за диалог",
        "что это за диалог",
        "не в ту сторону",
        "не туда",
        "ты сейчас о чем",
        "ты сейчас о чём",
        "я не озвучил",
        "какая температура",
        "какие симптомы",
        "я не говорил про болезнь",
        "что ты собираешься собирать",
        "что ты несешь",
        "что ты несёшь",
        "непонятный ответ",
        "не понимаю твой ответ",
        "это бред",
    )
    return any(m in t for m in markers)


def _dialog_reset_response() -> str:
    return "Понял, ушёл не туда. Давайте заново: коротко скажите, что именно сейчас беспокоит."


def _symptom_marker_blood_or_trauma_krov(t: str) -> bool:
    """
    Подстрока «кров» ловит и кровотечение, и ложно — «кровать/кровати».
    Считаем маркером только вхождения, которые не начинают слово «кроват…».
    """
    if "кров" not in t:
        return False
    i = 0
    while True:
        j = t.find("кров", i)
        if j < 0:
            return False
        tail = t[j : j + 6]
        if not tail.startswith("кроват"):
            return True
        i = j + 4


def _looks_like_full_complaint_message(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    if not _contains_medical_markers(t):
        return False
    symptom_markers = (
        "болит",
        "боль",
        "температур",
        "кашл",
        "горл",
        "одыш",
        "упал",
        "удар",
        "рана",
        "ссад",
        "травм",
    )
    vitality_hormone_markers = (
        "гормон",
        "настроен",
        "настроение",
        "скачет",
        "перепад",
        "устал",
        "апат",
        "тревог",
        "энерг",
        "сон",
        "щитовид",
        "пролактин",
        "менстру",
    )
    words = [w for w in re.split(r"\s+", t) if w]
    if len(words) < 6:
        # Метаболический контекст без классических «болит/температура» — тоже полноценная жалоба.
        if len(words) >= 4 and any(
            m in t
            for m in (
                "сбросить вес",
                "похуд",
                "вес не уходит",
                "вес не снижается",
                "не худею",
                "не худеет",
                "лишний вес",
                "набор веса",
                "ожирен",
            )
        ):
            return True
        if _contains_whole_word(t, "вес") and len(words) >= 5 and any(
            m in t
            for m in (
                "уже год",
                "уже полгода",
                "полгода",
                "целый год",
                "пробовал всё",
                "пробовал все",
                "не могу сбросить",
            )
        ):
            return True
        if len(words) >= 4 and _contains_medical_markers(t) and any(k in t for k in vitality_hormone_markers):
            return True
        return False
    if any(m in t for m in symptom_markers):
        return True
    if any(
        m in t
        for m in (
            "сбросить вес",
            "похуд",
            "вес не уходит",
            "вес не снижается",
            "не худею",
            "не худеет",
            "лишний вес",
            "набор веса",
            "ожирен",
        )
    ):
        return True
    if _contains_whole_word(t, "вес") and any(
        m in t
        for m in (
            "уже год",
            "уже полгода",
            "полгода",
            "целый год",
            "пробовал всё",
            "пробовал все",
            "не могу сбросить",
        )
    ):
        return True
    if _symptom_marker_blood_or_trauma_krov(t):
        return True
    # Гормоны / перепады настроения / усталость без «болит» — всё равно полноценная жалоба (не «двусмысленный чат»).
    if len(words) >= 5 and _contains_medical_markers(t) and any(k in t for k in vitality_hormone_markers):
        return True
    return False


def _classify_priority_intent(message: str) -> str:
    """
    Приоритетный роутинг интентов:
    STOP/CLOSE > PRESENCE > HEAR_ME > RESET > NEW_COMPLAINT > SMALL_TALK.
    """
    t = (message or "").strip()
    if not t:
        return ""
    if _is_conversation_stop_request(t):
        return "stop"
    if _is_presence_check_request(t):
        return "presence"
    if _is_audio_clarity_request(t):
        return "hear_me"
    if _is_dialog_reset_request(t):
        return "reset"
    if _looks_like_full_complaint_message(t):
        return "new_complaint"
    if _is_small_talk_request(t):
        return "small_talk"
    return ""


def _tokenize_ru_lower(text: str) -> List[str]:
    """Грубая токенизация для русских фраз: буквы/цифры, lower-case."""
    return re.findall(r"[0-9a-zа-яё]+", (text or "").lower())


def _contains_whole_word(haystack: str, word: str) -> bool:
    """Целое слово, без ложных совпадений вроде 'пока' внутри 'покачал'."""
    if not haystack or not word:
        return False
    w = word.lower().strip()
    if not w:
        return False
    return re.search(rf"(?<!['’`A-Za-zА-Яа-яЁё]){re.escape(w)}(?!['’`A-Za-zА-Яа-яЁё])", haystack.lower()) is not None


# Явное завершение диалога (не путать с «я всё время усталый…»).
_STRICT_EXPLICIT_DIALOG_CLOSE_MARKERS: tuple[str, ...] = (
    "на сегодня всё",
    "на сегодня все",
    "до свидания",
    "всего доброго",
    "закрыть диалог",
    "можно завершить",
    "закрой чат",
    "сверни чат",
)


def _normalize_whole_message_for_stop_phrase(message: str) -> str:
    """Нормализация целой реплики для сравнения только по полному совпадению (не по подстроке)."""
    x = re.sub(r"\s+", " ", str(message or "").strip().lower().replace("ё", "е"))
    x = re.sub(r"[,;]+", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    x = re.sub(r"[.!?…]+$", "", x).strip()
    return x


# Прощание только если вся реплика совпадает с одной из форм (после нормализации).
# «пробовал всё», «на сегодня всё» и т.п. сюда не попадают.
_STOP_PHRASES_EXACT_NORMALIZED: frozenset[str] = frozenset(
    {
        _normalize_whole_message_for_stop_phrase(p)
        for p in (
            "всё пока",
            "все пока",
            "пока",
            "всё спасибо",
            "все спасибо",
            "понял спасибо",
            "понял, спасибо",
            "больше ничего",
            "достаточно",
            "достаточно, спасибо",
            "хватит",
            "стоп",
            "можешь закрыться",
            "можно завершить",
            "закрывай",
            "закрыть диалог",
            "на сегодня всё",
            "на сегодня все",
            "не надо",
            "не нужно",
            "до свидания",
            "досвидания",
            "всего доброго",
            "свернуться",
            "закрыться",
            "свернуть",
            "закрыть",
            "закрой окно",
            "сверни окно",
            "закрой чат",
            "сверни чат",
            "ладно пока",
            "ок пока",
            "окей пока",
            "давай пока",
            "спасибо пока",
            "всё хорошо пока",
            "все хорошо пока",
            "всё ок пока",
            "все ок пока",
            "пока спасибо",
            "стоп все достаточно",
        )
    }
)


def _is_conversation_stop_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    if not t:
        return False
    # Астенический синдром без явного «до свидания/закрой чат» — никогда не трактуем как stop.
    if _user_constitutional_fatigue_primary(message) and not any(m in t for m in _STRICT_EXPLICIT_DIALOG_CLOSE_MARKERS):
        return False
    # Плато веса / похудение — не завершение диалога (часто «пробовал всё», без явного «пока/до свидания»).
    if any(
        k in t
        for k in (
            "сбросить вес",
            "похуд",
            "лишний вес",
            "вес не уходит",
            "вес не снижается",
            "набор веса",
            "ожирен",
            "имт",
        )
    ) or (_contains_whole_word(t, "вес") and any(k in t for k in ("уже год", "уже полгода", "полгода", "целый год", "не худею", "не худеет", "пробовал всё", "пробовал все"))):
        if not any(m in t for m in _STRICT_EXPLICIT_DIALOG_CLOSE_MARKERS):
            return False
    # Длинная реплика с претензией/продолжением жалобы — почти никогда не про «закрой чат».
    if len(t) > 32 and any(
        x in t
        for x in (
            "почему ты",
            "почему вы",
            "игнор",
            "не устраивает",
            "туфта",
            "беспокоит меня",
            "не задал",
            "не задала",
            "дополнительных вопрос",
            "надоело",
            "один вопрос",
            "три вопроса",
            "пять вопросов",
            "не релевант",
            "рекомендовал",
            "витамин",
            "добавк",
            "свежего воздуха",
        )
    ):
        return False

    soft_t = re.sub(r"[.!?,;:]+$", "", t).strip()
    nf = _normalize_whole_message_for_stop_phrase(soft_t)
    if nf in _STOP_PHRASES_EXACT_NORMALIZED:
        return True

    # Не завершаем диалог по "ложным" совпадениям внутри медицинского сообщения.
    # Пример: "я всё время говорю о здоровье..." не должен срабатывать как stop.
    if _contains_medical_markers(t) and not any(m in t for m in _STRICT_EXPLICIT_DIALOG_CLOSE_MARKERS):
        return False

    # Guard: users can start frustrated medical messages with "до свидания/пока",
    # but then continue complaint text ("у меня жалоба", "я задал вопрос").
    # In such cases we must keep medical flow, not terminate dialogue.
    soft_tokens = _tokenize_ru_lower(soft_t)
    if ("до свидания" in soft_t or _contains_whole_word(soft_t, "пока")) and len(soft_tokens) > 4:
        if _contains_medical_markers(soft_t) or any(
            x in soft_t
            for x in (
                "жалоб",
                "вопрос",
                "не получил ответ",
                "игнор",
                "почему",
                "что делать",
            )
        ):
            return False

    # Поддержка коротких комбинированных фраз вроде "стоп, все, достаточно".
    # Применяем только для коротких реплик без явного медконтекста.
    if len(soft_t) <= 80:
        if _is_audio_clarity_request(soft_t):
            return False
        if _contains_medical_markers(soft_t):
            return False

        tokens = _tokenize_ru_lower(soft_t)

        # "пока" как прощание часто идёт последним токеном ("ладно пока"), но как союз —
        # часто первым ("пока болит ...", "пока я жду ..."). Не используем подстроку:
        # иначе ловим "пока" внутри других слов и ломаем медицинский поток.
        if tokens:
            temporal_poka_seconds = {
                "не",
                "я",
                "мы",
                "вы",
                "он",
                "она",
                "они",
                "оно",
                "тут",
                "там",
                "здесь",
                "еще",
                "ещё",
                "только",
                "просто",
                "жду",
                "ждём",
                "ждем",
                "ждете",
                "ждёте",
                "болит",
                "болело",
                "болею",
                "болели",
                "болят",
            }
            # Не включаем «всё/все» после «пока» — иначе ловим «пока всё нормально» и смежные смыслы.
            goodbye_poka_seconds = {
                "спасибо",
                "благодарю",
                "хватит",
                "стоп",
                "ладно",
                "ок",
                "окей",
                "давай",
            }

            if tokens[-1] == "пока" and len(tokens) <= 6:
                if len(tokens) > 4 and (
                    _contains_medical_markers(soft_t)
                    or any(
                        x in soft_t
                        for x in (
                            "жалоб",
                            "вопрос",
                            "не получил ответ",
                            "игнор",
                            "почему",
                            "что делать",
                        )
                    )
                ):
                    return False
                if len(tokens) > 1 and tokens[0] == "пока":
                    second = tokens[1]
                    if second in temporal_poka_seconds:
                        return False
                    if second in goodbye_poka_seconds:
                        return True
                    return False
                # «… пока» без целой фразы из whitelist (уже проверено через nf) — не прощаемся.
                return False

        strong_single_words = ("стоп", "хватит", "достаточно")
        if any(_contains_whole_word(soft_t, w) for w in strong_single_words):
            tl = soft_t.lower()
            # «Достаточно/хватит» часто означает «хватит нести чушь», а не завершение диалога.
            if (_contains_whole_word(soft_t, "достаточно") or _contains_whole_word(soft_t, "хватит")) and not _contains_whole_word(
                soft_t, "стоп"
            ):
                if any(
                    k in tl
                    for k in (
                        "пург",
                        "пургу",
                        "бред",
                        "чушь",
                        "чепух",
                        "лажа",
                        "лажи",
                        "дичь",
                        "фигню",
                        "фигня",
                        "несёшь",
                        "несешь",
                        "не неси",
                    )
                ):
                    return False
            return True

        strong_phrases = ("закрыть диалог", "закрой чат", "сверни чат", "до свидания")
        if any(p in soft_t for p in strong_phrases):
            return True
    return False


def _conversation_stop_response(message: str) -> str:
    variants = (
        "До свидания. До следующих встреч.",
        "Пока. Увидимся.",
        "До встречи. Если что, я рядом.",
        "До свидания. Обращайтесь в любой момент.",
    )
    idx = sum(ord(ch) for ch in (message or "")) % len(variants)
    return variants[idx]


def _contains_medical_markers(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    markers = (
        "боль",
        "болит",
        "болят",
        "симптом",
        "жалоб",
        "устал",
        "устав",
        "неохот",
        "не хочет",
        "слабост",
        "вял",
        "нет сил",
        "разбит",
        "сонлив",
        "апат",
        "температур",
        "кашл",
        "горл",
        "давлен",
        "анализ",
        "врач",
        "лечение",
        "таблет",
        "диагноз",
        "тошн",
        "рвот",
        "сып",
        "одыш",
        "пульс",
        "кров",
        "гемор",
        "геморро",
        "анус",
        "анальн",
        "прямой киш",
        "прямая киш",
        "дефекац",
        "задний проход",
        "кровь после стула",
        "самочувств",
        "здоров",
        "рекомендац",
        "рекомендовал",
        "совет",
        "беспокоит",
        "симптом",
        "витамин",
        "добавк",
        "не задал",
        "не задала",
        "травм",
        "упал",
        "удар",
        "ушиб",
        "рана",
        "ссад",
        "колен",
        "нога",
        "лимфоцит",
        "лейкоцит",
        "тромбоцит",
        "гемоглобин",
        "аппетит",
        "щитовид",
        "сколиоз",
        "пролактин",
        "месячн",
        "менстру",
        "цикл",
        "тревог",
        "либидо",
        "сердц",
        "колот",
        "бессон",
        "сплю",
        "спать",
        "сон",
        "омега",
        "жирн",
        "кож",
        "морщин",
        "волос",
        "прыщ",
        "акне",
        "подбород",
        "трениров",
        "телефон",
        "ночь",
        "ночи",
        "голос",
        "похуд",
        "худею",
        "худеет",
        "ожирен",
        "имт",
        "калори",
        "диет",
        "набор вес",
        "гормон",
        "эндокрин",
        "настроен",
        "скачет",
        "перепад",
    )
    if _contains_whole_word(t, "вес"):
        return True
    return any(m in t for m in markers)


def _is_non_medical_chat_request(message: str) -> bool:
    """Бытовые/общие вопросы, которые нужно держать вне medical-core."""
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    if not t:
        return False
    if _contains_medical_markers(t):
        return False
    everyday_markers = (
        "погод",
        "на улице",
        "дожд",
        "снег",
        "ветер",
        "жара",
        "холодно",
        "стол",
        "компьютер",
        "ноутбук",
        "монитор",
        "клавиатур",
        "мыш",
        "купить",
        "выбрать",
        "посоветуй",
        "какой лучше",
        "фильм",
        "музык",
        "игр",
        "бюджет",
        "руб",
        "рубл",
        "цена",
        "стоимость",
        "до ",
        "тыс",
        "р.",
        "₽",
    )
    return any(m in t for m in everyday_markers)


def _is_non_medical_followup(message: str, chat_history: Optional[list[dict[str, Any]]]) -> bool:
    """Короткое продолжение бытовой темы (например: бюджет/цена после вопроса про стол)."""
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    if not t:
        return False
    # «Хочу проверить гормоны…» содержит маркер follow-up «хочу», но это не бытовой follow-up.
    if _contains_medical_markers(t):
        return False
    if _is_non_medical_chat_request(t):
        return True
    short_followup_tokens = (
        "говорю",
        "ага",
        "угу",
        "ок",
        "окей",
        "поехали",
        "давай",
        "да",
        "хорошо",
    )
    if len(t) <= 14 and any(tok == t for tok in short_followup_tokens):
        history = chat_history or []
        for row in reversed(history):
            if not isinstance(row, dict):
                continue
            if str(row.get("role") or "") != "user":
                continue
            prev = str(row.get("content") or "").strip().lower()
            if not prev:
                continue
            return _is_non_medical_chat_request(prev)
        return False
    followup_markers = (
        "бюджет",
        "руб",
        "рубл",
        "₽",
        "цена",
        "стоимость",
        "до ",
        "тыс",
        "адапт",
        "режим",
        "одежд",
        "по погод",
        "давай",
        "хочу",
        "да,",
        "да ",
        "размер",
        "ширина",
        "глубина",
        "высота",
        "цвет",
        "материал",
        "вот этот",
        "а этот",
        "а если",
    )
    if not any(m in t for m in followup_markers):
        # Мета-вопросы к предыдущему бытовому ответу: "как ты собираешься это сделать?"
        meta_followup_markers = (
            "как ты собираешься",
            "как вы собираетесь",
            "как именно",
            "каким образом",
            "что ты предлагаешь",
            "что вы предлагаете",
            "как это сделать",
            "что дальше",
        )
        if not any(m in t for m in meta_followup_markers):
            return False
        history = chat_history or []
        for row in reversed(history):
            if not isinstance(row, dict):
                continue
            if str(row.get("role") or "") != "assistant":
                continue
            prev_assistant = str(row.get("content") or "").strip().lower()
            if not prev_assistant:
                continue
            non_medical_assistant_markers = (
                "погод",
                "режим дня",
                "одежд",
                "нагрузк",
                "под текущие условия",
                "можем спокойно поболтать",
                "не про здоровье",
                "по этой теме лучше посмотреть в поиске",
            )
            return any(m in prev_assistant for m in non_medical_assistant_markers)
        return False
    history = chat_history or []
    recent_users: list[str] = []
    for row in reversed(history):
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "") != "user":
            continue
        txt = str(row.get("content") or "").strip().lower()
        if txt:
            recent_users.append(txt)
        if len(recent_users) >= 4:
            break
    if not recent_users:
        return False
    return any(_is_non_medical_chat_request(prev) for prev in recent_users)


def _dialog_companion_active(state: Optional[dict[str, Any]]) -> bool:
    if not isinstance(state, dict):
        return False
    dc = state.get("dialog_companion")
    return isinstance(dc, dict) and bool(dc.get("active"))


def _should_force_exit_companion(message: str) -> bool:
    """Вернуться к обычной медконсультации при явной жалобе или медицинском запросе."""
    if not (message or "").strip():
        return False
    if _is_clearly_medical_request(message):
        return True
    if _looks_like_full_complaint_message(message):
        return True
    return False


def _companion_activation_explicit(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    negation_markers = (
        "не поболта",
        "не болтать",
        "не поговор",
        "не пообща",
        "не хочу болтать",
        "не хочу говорить не про здоровье",
    )
    if any(m in t for m in negation_markers):
        return False
    markers = (
        "поболта",
        "просто пообща",
        "не про здоров",
        "не про медицин",
        "не про симптом",
        "отвлеч",
        "просто чат",
        "лайт режим",
        "без медицин",
        "разговор не о здоров",
        "общение не о болезн",
        "просто поговор",
    )
    return any(m in t for m in markers)


def _is_non_medical_turn(
    message: str,
    chat_history: Optional[list[dict[str, Any]]],
    companion_active: bool,
) -> bool:
    # Сначала меджалоба: не отправляем в «поболтаем», даже если dialog_companion ещё true в состоянии.
    if _should_force_exit_companion(message):
        return False
    if companion_active:
        return True
    if _companion_activation_explicit(message):
        return True
    if _is_non_medical_chat_request(message):
        return True
    if _is_non_medical_followup(message, chat_history):
        return True
    return False


def _non_medical_lively_prefix(message: str) -> str:
    variants = (
        "Супер, поехали.",
        "Окей, двигаемся.",
        "Отлично, давайте быстро.",
        "Класс, сейчас разберём.",
        "Хорошо, делаем.",
    )
    idx = sum(ord(ch) for ch in (message or "")) % len(variants)
    return variants[idx]


def _non_medical_chat_response(message: str, tone: str = "friendly") -> str:
    t = (message or "").strip().lower()
    tone = str(tone or "friendly").strip().lower()
    # Аварийный предохранитель: даже при ошибочном роутинге не отдаём «поболтаем»
    # для явно медицинских запросов.
    if _contains_medical_markers(t) or _is_endocrine_asthenic_switch_request(t):
        return (
            "Понял вас. Возвращаюсь к медицинскому вопросу. "
            "По сочетанию усталости и перепадов настроения стоит исключить гормональные и дефицитные причины. "
            "Базово: ТТГ, свободный Т4, ОАК, ферритин, B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца)."
        )
    if "стол" in t:
        asks_buy_help = any(x in t for x in ("куп", "выб", "посовет", "предлож", "какой", "не знаю", "что лучше"))
        if asks_buy_help or "компьютер" in t or "ноутбук" in t:
            if tone == "lively":
                return (
                    _non_medical_lively_prefix(t) + " Есть рабочее предложение. База для стола под компьютер: ширина 120-140 см, "
                    "глубина 70-80 см, высота 72-75 см, столешница ЛДСП 22-25 мм. "
                    "Чтобы попасть точно в ваш вариант, ответьте на 3 вопроса: "
                    "1) ваш бюджет, 2) размер свободного места, 3) нужен ли один или два монитора."
                )
            if tone == "friendly":
                return (
                    "Да, предложу конкретно. Универсальный вариант: ширина 120-140 см, глубина 70-80 см, "
                    "высота 72-75 см, столешница ЛДСП 22-25 мм. "
                    "Чтобы подобрать точнее, подскажите 3 вещи: бюджет, размер места в комнате и "
                    "сколько мониторов планируете использовать."
                )
            return (
                "Рекомендую базовый формат стола: 120-140 см по ширине, 70-80 см по глубине, "
                "высота 72-75 см, столешница ЛДСП 22-25 мм. Для точного подбора нужны: бюджет, "
                "размер места и количество мониторов."
            )
        if tone == "lively":
            return (
                _non_medical_lively_prefix(t) + " Для компьютера чаще всего удобно: ширина 120-140 см, "
                "глубина от 70 см и высота 72-75 см. Если хотите, накину 2-3 удачных варианта "
                "под ваш бюджет и размер комнаты."
            )
        if tone == "friendly":
            return (
                "Хороший вопрос. Для компьютера обычно удобен стол шириной 120-140 см, "
                "глубиной от 70 см и высотой 72-75 см. Если хотите, помогу подобрать "
                "несколько вариантов под ваш бюджет."
            )
        return (
            "Для компьютера обычно подходит стол шириной 120-140 см, глубиной от 70 см "
            "и высотой 72-75 см. При необходимости подберу несколько вариантов по бюджету."
        )
    if "погод" in t or "на улице" in t or "дожд" in t or "снег" in t or "ветер" in t:
        if tone == "lively":
            return _non_medical_lively_prefix(t) + " Погода капризная. Подскажу, как скорректировать режим дня и одежду под такие условия."
        if tone == "friendly":
            return "Понимаю, погода влияет на самочувствие. Если хотите, подскажу, как адаптировать режим и одежду под текущие условия."
        return "Погода может влиять на самочувствие. Могу подсказать базовую адаптацию режима дня и одежды."
    if tone == "lively":
        return _non_medical_lively_prefix(t) + " Давайте просто поболтаем. Если захотите, мягко вернёмся к теме здоровья."
    if tone == "friendly":
        return "Понял вас. Можем спокойно поболтать на эту тему. Если захотите, вернёмся к вопросам здоровья."
    return "Принял. Готов обсудить эту тему. При необходимости перейдём к вопросам здоровья."


def _augment_non_medical_with_web_search(message: str, base_response: str) -> str:
    cfg = get_app_settings()
    if not bool(getattr(cfg, "non_medical_web_search_enabled", False)):
        return base_response
    query = str(message or "").strip()
    if not query:
        return base_response
    if _contains_medical_markers(query):
        return base_response
    whitelist = getattr(cfg, "non_medical_web_search_whitelist", None) or []
    whitelist = [str(x).strip().lower() for x in whitelist if str(x).strip()]
    if whitelist and not any(k in query.lower() for k in whitelist):
        return base_response
    encoded = quote(query)
    yandex_url = "https://yandex.ru/search/?text=" + encoded
    google_url = "https://www.google.com/search?q=" + encoded
    redirect_note = (
        "По этой теме лучше посмотреть в поиске. "
        f"Яндекс: {yandex_url} | Google: {google_url}\n"
        "Мы в первую очередь специализируемся на вопросах здоровья."
    )
    return base_response + "\n\n" + redirect_note


def _resolve_non_medical_tone(message_text: str) -> str:
    t = (message_text or "").lower()
    if any(k in t for k in ("пошути", "весел", "пободр", "живее", "проще", "дружелюб")):
        return "lively"
    if any(k in t for k in ("спокой", "нейтрал", "короче", "по делу", "официально")):
        return "neutral"
    if any(k in t for k in ("друж", "мягч", "тепл", "поддерж")):
        return "friendly"
    return ""


def _is_clearly_medical_request(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    return _contains_medical_markers(t)


def _parse_route_choice(message: str) -> str:
    t = (message or "").strip().lower()
    if not t:
        return "unknown"
    if _is_clearly_medical_request(t):
        return "health"
    talk_markers = ("поговор", "поболт", "просто поговор", "не про здоровье", "просто чат")
    health_markers = ("к здоров", "здоров", "по медиц", "медицин", "про симптомы", "лечени")
    if any(m in t for m in talk_markers):
        return "talk"
    if any(m in t for m in health_markers):
        return "health"
    return "unknown"


def _is_ambiguous_route_request(message: str) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    if _is_small_talk_request(t) or _is_non_medical_chat_request(t) or _is_clearly_medical_request(t) or _is_trauma_context_message(t):
        return False
    if len(t) < 8 or len(t) > 140:
        return False
    # Лабораторные/онко-тревога — однозначно медицинский контекст (не «общий чат»).
    if re.search(r"\b(лимфоцит|лейкоцит|тромбоцит|гемоглобин|онкомарк|биопс)\w*\b", t, re.IGNORECASE):
        return False
    if "боюсь" in t and any(
        k in t for k in ("умру", "умер", "смерт", " рак", "рак ", "рак,", "рак.", "болезн", "серьёзн", "серьезн", "здоров")
    ):
        return False
    # «что» как отдельное слово-вопрос ≠ подстрока в «что-то» / «кое-что».
    generic_q = ("какой", "какая", "какие", "как ", " как", "посоветуй", "подскажи", "помоги")
    if any(w in t for w in generic_q):
        return True
    # «потому что» — не вопрос «что?»; иначе фраза про гормоны уходит в уточнение маршрута вместо триажа.
    t_for_what = re.sub(r"\bпотому\s+что\b", " ", t, flags=re.IGNORECASE)
    if re.search(r"(^|[\s,.;:!?«\"(])что([\s,.;:!?»\"'\-]|$)", t_for_what):
        return True
    return False


def _clarify_route_question() -> str:
    return "Я не до конца понял контекст. Вы хотите просто поговорить или вернёмся к вопросу вашего здоровья?"


def _normalize_subscription_plan(raw_plan: str) -> str:
    p = str(raw_plan or "").strip().lower()
    alias = {
        "free": "free",
        "start": "start",
        "starter": "start",
        "full": "full",
        "premium": "premium",
        "family": "family",
        "subscription": "full",
    }
    return alias.get(p, "free")


def _is_subscription_active(settings_payload: dict[str, Any]) -> bool:
    status = str((settings_payload or {}).get("subscription_status") or "active").strip().lower()
    if status in {"expired", "cancelled"}:
        return False
    expires_raw = str((settings_payload or {}).get("subscription_expires_at") or "").strip()
    if not expires_raw:
        return True
    try:
        expiry = datetime.fromisoformat(expires_raw.replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry >= datetime.now(timezone.utc)
    except Exception:
        return True


def _plan_limits(plan_type: str) -> dict[str, Any]:
    plan = _normalize_subscription_plan(plan_type)
    if plan == "start":
        return {"messages_per_day": 30, "deep_coaching": "partial"}
    if plan in {"full", "family", "premium"}:
        return {"messages_per_day": None, "deep_coaching": "full"}
    return {"messages_per_day": 5, "deep_coaching": "none"}


def _count_user_messages_today(chat_history: Optional[list[dict[str, Any]]]) -> int:
    items = chat_history or []
    today = datetime.now(timezone.utc).date()
    total = 0
    for row in items:
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "") != "user":
            continue
        ts = row.get("ts")
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else None
        except Exception:
            dt = None
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt and dt.date() == today:
            total += 1
    return total


def _paywall_response_for_plan(plan_type: str) -> str:
    plan = _normalize_subscription_plan(plan_type)
    if plan == "free":
        return (
            "Я могу поговорить с тобой подробнее и поддержать. "
            "Для этого нужна подписка «Михаил Полный». Хочешь посмотреть условия?"
        )
    if plan == "start":
        return (
            "Лимит сообщений на тарифе «Михаил Старт» на сегодня исчерпан. "
            "Чтобы продолжить без ограничений и получить глубокую поддержку, открой «Михаил Полный»."
        )
    return "Чтобы продолжить диалог, проверь статус подписки в профиле."


def _is_deep_coaching_request(message: str, chat_history: Optional[list[Any]] = None) -> bool:
    t = (message or "").strip().lower()
    if not t:
        return False
    # Жалоба на выраженную усталость/апатию — медицинский триаж, а не витрина «эмоционального тарифа».
    if _constitutional_fatigue_thread_active(message, chat_history):
        return False
    # Кардио/дыхательные симптомы вместе с тревогой — сначала медицинская оценка, не paywall коучинга.
    if any(
        k in t
        for k in (
            "сердц",
            "колот",
            "удуш",
            "не хватает воздуха",
            "воздуха не хватает",
            "одыш",
            "боль в груди",
            "болит в груди",
        )
    ):
        return False
    if "мыш" in t and any(x in t for x in ("свод", "судорог", "кал", "сводит")):
        return False
    if "не могу" in t and any(x in t for x in ("спат", "сплю", "сон", "бессон")):
        return False
    markers = (
        "поддерж",
        "поговори со мной",
        "мне очень плохо",
        "не вывожу",
        "депресс",
        "тревог",
        "паник",
        "апат",
        "нет сил",
        "не хочу ничего",
        "нет смысла",
        "разбит",
        "эмоциональ",
        "коуч",
    )
    return any(m in t for m in markers)


def _build_deep_coaching_gate_payload(uid: str, plan_type: str, response_source: str) -> dict[str, Any]:
    plan = _normalize_subscription_plan(plan_type)
    if plan == "free":
        response = (
            "Я рядом и готов поддержать тебя. Для глубокого эмоционального сопровождения доступен "
            "тариф «Михаил Полный». Хочешь посмотреть условия?"
        )
    else:
        response = (
            "Могу дать короткую поддержку уже сейчас: сделай 3 медленных вдоха, выпей воды и "
            "опиши, что тревожит сильнее всего в одном предложении. Для глубокого сопровождения "
            "без ограничений доступен тариф «Михаил Полный»."
        )
    payload = _build_paywall_payload(uid, plan, None, 0, response_source)
    payload["response"] = response
    payload["response_simple"] = response
    payload["paywall"]["reason"] = "deep_coaching_locked"
    return payload


def _record_paywall_event(*, source: str, plan_type: str, reason: str, message: str) -> None:
    try:
        record_runtime_event(
            source=source,
            llm_used=False,
            model_used="plan:" + _normalize_subscription_plan(plan_type),
            protocol_source="paywall",
            complaint=(message or "")[:300],
            cluster="paywall",
            severity=reason[:32],
            prompt_chars=0,
            response_chars=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0,
        )
    except Exception:
        pass


def _build_paywall_payload(uid: str, plan_type: str, limit: Optional[int], used: int, response_source: str) -> dict[str, Any]:
    plan = _normalize_subscription_plan(plan_type)
    response = _paywall_response_for_plan(plan)
    return {
        "user_id": uid,
        "response": response,
        "response_simple": response,
        "conclusion": False,
        "report_id": None,
        "report": None,
        "suggest_pdf": False,
        "severity": None,
        "red_flags_present": False,
        "red_flag_matches": [],
        "llm_used": False,
        "response_source": response_source,
        "medical_core_bypassed": True,
        "paywall_triggered": True,
        "paywall": {
            "required_plan": "full",
            "current_plan": plan,
            "messages_today": used,
            "messages_limit": limit,
        },
        "model_used": None,
        "worker_used": False,
        "request_id": None,
        "orchestrator_state": None,
        "consultation_case": None,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "estimated_cost_usd": 0.0,
        "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
        "symptom_payload": None,
        "knowledge_context": None,
        "action_sequence": [],
    }


def _load_non_medical_tone(user_id: str) -> str:
    try:
        settings = get_settings(user_id)
    except Exception:
        return "friendly"
    tone = str((settings or {}).get("non_medical_tone") or "").strip().lower()
    if tone in {"neutral", "friendly", "lively"}:
        return tone
    return "friendly"


def _save_non_medical_tone(user_id: str, tone: str) -> None:
    t = str(tone or "").strip().lower()
    if t not in {"neutral", "friendly", "lively"}:
        return
    try:
        save_settings(user_id, {"non_medical_tone": t})
    except Exception:
        return


def _is_acute_injury_bleeding_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    injury_markers = (
        "порез",
        "порезал",
        "порезалс",
        "порезалась",
        "рана",
        "ранк",
        "ссадин",
        "рассек",
        "разрез",
        "разбил",
        "травм",
        "повредил",
        "палец",
        "пальц",
        "ногт",
        "стоп",
        "ступн",
        "нога",
        "рука",
        "из пальц",
    )
    blood_markers = (
        "кров",
        "кровотеч",
        "вытекла кровь",
        "идет кровь",
        "идёт кровь",
    )
    has_injury = any(m in t for m in injury_markers)
    # Частая разговорная форма: "идет/идёт кровь из пальца/ноги".
    if not has_injury and ("из " in t) and any(m in t for m in ("пальц", "ногт", "стоп", "ступн", "рук", "ног")):
        has_injury = True
    has_blood = any(m in t for m in blood_markers)
    return has_injury and has_blood


def _acute_injury_bleeding_response(message: str = "") -> str:
    t = _norm_text_for_compare(message or "")
    if any(x in t for x in ("колен", "нога", "голен", "ступн", "стоп")):
        return (
            "Похоже на травму колена/ноги с ссадиной и кровью. Действуйте сразу по шагам:\n"
            "1) Прижмите ссадину чистой салфеткой 10–15 минут.\n"
            "2) Промойте края раны чистой водой, обработайте антисептиком вокруг и наложите стерильную повязку.\n"
            "3) Держите ногу в покое и приподнятой, приложите холод через ткань на 10–15 минут.\n"
            "4) Проверьте, сгибается ли колено и можете ли наступать без резкой боли.\n"
            "5) Если трудно наступать, колено не сгибается/заклинивает, быстро растет отек или кровь не останавливается 15–20 минут — сегодня в травмпункт, при резком ухудшении 103.\n"
            "6) Проверьте вакцинацию от столбняка: при грязной ране и давней прививке нужна очная оценка сегодня.\n"
            + _medication_notice_block(
                [
                    "местные антисептики для обработки краев раны",
                    "обезболивающие (например, парацетамол/ибупрофен) при боли",
                    "перевязочные средства (стерильная повязка/пластырь)",
                ]
            )
        )
    return (
        "Похоже на свежий порез с кровотечением. Действуйте сразу по шагам:\n"
        "1) Прижмите рану чистой салфеткой/бинтом 10–15 минут без проверки каждую минуту.\n"
        "2) Поднимите травмированную конечность выше уровня сердца.\n"
        "3) Промойте края раны чистой водой, обработайте антисептиком вокруг (не лейте агрессивный раствор глубоко в рану).\n"
        "4) Наложите стерильную повязку или пластырь.\n"
        "5) Если кровотечение не останавливается 15–20 минут, кровь пульсирует, рана глубокая/края расходятся, есть онемение или нарушено движение — срочно в травмпункт/103.\n"
        "6) Проверьте вакцинацию от столбняка: при грязной ране и давней прививке нужна очная оценка сегодня.\n"
        + _medication_notice_block(
            [
                "местные антисептики для обработки краев раны",
                "обезболивающие (например, парацетамол/ибупрофен) при боли",
                "перевязочные средства (стерильная повязка/пластырь)",
            ]
        )
    )


def _acute_injury_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Кровотечение остановилось после плотного прижатия 10–15 минут?",
            "Рана глубокая или края расходятся?",
            "Когда была последняя прививка от столбняка?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
    }


def _is_food_overload_reaction_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    intake_markers = (
        "поел",
        "съел",
        "после еды",
        "после ужина",
        "после обеда",
        "после завтрака",
        "много",
        "большое количество",
        "переел",
        "переед",
    )
    food_markers = (
        "семеч",
        "жарен",
        "жирн",
        "творог",
        "сыр",
        "молоч",
        "вино",
        "копчен",
        "копчён",
        "копч",
        "алког",
        "сладк",
        "десерт",
        "шоколад",
    )
    symptom_markers = (
        "тошн",
        "мутит",
        "голов",
        "тяжесть",
        "слабост",
        "живот",
        "изжог",
        "отрыж",
        "жжени",
        "вздут",
        "газ",
        "урчан",
        "диаре",
        "запор",
    )
    has_intake = any(m in t for m in intake_markers) or any(m in t for m in ("после", "через"))
    has_food = any(m in t for m in food_markers)
    has_symptom = any(m in t for m in symptom_markers)
    return has_intake and has_food and has_symptom


def _is_upper_abdominal_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    upper_markers = (
        "верхней части живота",
        "верх живота",
        "эпигастр",
        "подложеч",
        "подреб",
        "под рёбра",
        "под ребра",
        "под ребра",
    )
    symptom_markers = (
        "тошн",
        "тяжест",
        "изжог",
        "жжен",
        "кисл",
        "гореч",
        "дискомфорт",
        "рвот",
        "болит",
    )
    has_upper = any(m in t for m in upper_markers)
    has_symptom = any(m in t for m in symptom_markers)
    if has_upper and has_symptom:
        return True
    has_food_time = any(m in t for m in ("после еды", "после жирн", "после жарен", "после ужина", "после обеда"))
    has_gi = any(m in t for m in ("изжог", "отрыж", "верхн", "подреб", "эпигастр", "боль в животе", "дискомфорт вверху"))
    return has_food_time and has_gi


def _is_postmeal_bloating_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    bowel_markers = (
        "вздут",
        "урчан",
        "газы",
        "понос",
        "диаре",
        "жидкий стул",
        "послабл",
        "позывы",
    )
    trigger_markers = (
        "после еды",
        "после молок",
        "после молоч",
        "после фрукт",
        "после сладк",
        "после жирн",
        "поел",
        "съел",
    )
    has_bowel = any(m in t for m in bowel_markers)
    has_trigger = any(m in t for m in trigger_markers)
    return has_bowel and has_trigger


def _is_postmeal_systemic_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    has_trigger = any(
        m in t
        for m in (
            "после еды",
            "после ужина",
            "после обеда",
            "после завтрака",
            "после сладк",
            "после десерт",
            "после жирн",
            "поел",
            "съел",
            "покушал",
        )
    )
    core_systemic_markers = ("слаб", "дурнот", "головокруж", "сонлив", "дрож", "потлив", "ватн")
    support_markers = ("тошн", "голов", "плохо")
    has_core_systemic = any(m in t for m in core_systemic_markers)
    has_support = any(m in t for m in support_markers)
    has_systemic_red = any(m in t for m in ("обмор", "одыш", "боль в груди", "спутан", "не могу стоять", "сильная слаб"))
    bowel_dominant = any(m in t for m in ("понос", "диаре", "вздут", "газы", "урчан", "жидкий стул"))
    upper_abd_dominant = any(m in t for m in ("верхней части живота", "эпигастр", "подреб", "изжог", "кислая отрыжка"))
    return has_trigger and (has_systemic_red or (has_core_systemic and has_support)) and not bowel_dominant and not upper_abd_dominant


def _is_food_symptom_super_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    has_postmeal = any(
        x in t
        for x in (
            "после еды",
            "после ужина",
            "после обеда",
            "после завтрака",
            "после жирн",
            "после жарен",
            "после молок",
            "после молоч",
            "после сладк",
            "поел",
            "съел",
            "покушал",
        )
    )
    has_relevant_symptoms = any(
        x in t
        for x in (
            "тошн",
            "изжог",
            "отрыж",
            "тяжест",
            "верхн",
            "подреб",
            "вздут",
            "газы",
            "урчан",
            "понос",
            "диаре",
            "слаб",
            "дурнот",
            "голов",
            "головокруж",
            "плохо",
        )
    )
    return has_postmeal and has_relevant_symptoms


def _is_histamine_dominant_food_trigger(message: str) -> bool:
    try:
        from app.services.food_reaction_master_loader import is_histamine_pattern

        return is_histamine_pattern(message or "")
    except Exception:
        t = _norm_text_for_compare(message or "")
        if not t:
            return False
        histamine_food_markers = ("вино", "сыр", "копчен", "копчён", "копч", "выдержан", "фермент")
        histamine_symptom_markers = ("покраснен", "зуд", "сып", "залож", "сердц", "тахикард", "прилив")
        return any(m in t for m in histamine_food_markers) and any(m in t for m in histamine_symptom_markers)


def _food_trigger_matrix_tags(message: str) -> dict[str, bool]:
    t = _norm_text_for_compare(message or "")
    return {
        "fatty_fried": any(m in t for m in ("жирн", "жарен", "фри", "семеч", "орех", "шашлык", "фастфуд", "картоф", "чипс")),
        "histamine_foods": any(m in t for m in ("вино", "сыр", "копчен", "копчён", "копч", "фермент", "выдержан")),
        "dairy": any(m in t for m in ("молок", "творог", "сливк", "йогурт", "кефир")),
        "sugar_fat": any(m in t for m in ("сладк", "десерт", "торт", "пирож", "шоколад")) and any(m in t for m in ("жирн", "жарен", "масл", "сливк", "семеч", "орех")),
        "alcohol": any(m in t for m in ("алког", "вино", "пиво", "крепк")),
    }


def _food_trigger_matrix_block(tags: dict[str, bool]) -> str:
    lines: list[str] = ["Матрица причин (по продуктам и реакциям):"]
    if tags.get("fatty_fried"):
        lines.append("- Жирная/жареная пища: перегрузка ферментов, реакция желчного пузыря, замедление переваривания.")
    if tags.get("histamine_foods"):
        lines.append("- Гистаминовые продукты: Histamine intolerance вероятна только при типичных признаках (покраснение, зуд, заложенность, сердцебиение).")
    if tags.get("dairy"):
        lines.append("- Молочные продукты: возможны лактазная недостаточность и/или чувствительность к жирности.")
    if tags.get("sugar_fat"):
        lines.append("- Сахар + жир: возможна сосудисто-метаболическая реакция (скачки самочувствия).")
    if tags.get("alcohol"):
        lines.append("- Алкоголь: токсическая и сосудистая нагрузка, часто усиливает симптомы.")
    if len(lines) == 1:
        lines.append("- Доминирует перегрузка ЖКТ после тяжелой еды; альтернативы и усилители оцениваем по динамике.")
    return "\n".join(lines)


def _food_cause_hint(cause_id: str) -> str:
    hints = {
        "fatty_fried_overload": "перегрузка ЖКТ жирной или жареной пищей",
        "functional_dyspepsia_or_gastric_irritation": "диспепсия или раздражение желудка",
        "biliary_reaction": "реакция желчного пузыря на жирную пищу",
        "pancreatic_overload": "ферментная перегрузка поджелудочной",
        "reflux_trigger": "рефлюкс после еды",
        "dairy_lactose_or_milk_sensitivity": "паттерн непереносимости молочного",
        "postprandial_vascular_reaction": "постпрандиальная сосудисто-вегетативная реакция",
        "simple_overeating": "простое переедание",
        "ibs_food_trigger": "пищевой триггер при IBS-паттерне",
        "histamine_trigger_conditional": "гистамин как условный усилитель (не базовая ветка)",
        "sugar_load_reaction": "реакция на избыток сладкого",
        "alcohol_related_reaction": "алкогольная или смешанная реакция",
    }
    return hints.get(cause_id, cause_id.replace("_", " "))


def _food_overload_reaction_response(message: str = "") -> str:
    msg = _norm_text_for_compare(message or "")
    include_seeds_note = any(x in msg for x in ("семеч",))
    opening = "Похоже на пищевую реакцию после тяжёлой еды"
    if include_seeds_note:
        opening += " (в т.ч. семечек)"
    opening += ".\n"

    try:
        from app.services.food_reaction_master_loader import (
            master_red_flags,
            prioritize_food_causes,
            recurrent_food_tests,
            single_episode_tests_not_needed_message,
        )

        top_causes = prioritize_food_causes(message, limit=5)
        red_flags = master_red_flags()
        recurrent_tests = recurrent_food_tests()
        single_msg = single_episode_tests_not_needed_message()
    except Exception:
        top_causes = []
        red_flags = []
        recurrent_tests = []
        single_msg = "При единичном лёгком эпизоде без красных флагов анализы обычно не нужны."

    tags = _food_trigger_matrix_tags(message)
    matrix_block = _food_trigger_matrix_block(tags)
    likely = top_causes[0] if top_causes else {"id": "fatty_fried_overload", "title": "Перегрузка ЖКТ жирной или жареной пищей"}

    what_it_may_be_lines = [f"1) Наиболее вероятно: {likely.get('title') or _food_cause_hint(str(likely.get('id') or ''))}."]
    for idx, cause in enumerate(top_causes[1:4], start=2):
        cid = str(cause.get("id") or "")
        label = str(cause.get("title") or "").strip() or _food_cause_hint(cid)
        prefix = "Также возможно" if idx == 2 else "Реже"
        what_it_may_be_lines.append(f"{idx}) {prefix}: {label}.")
    if not top_causes:
        what_it_may_be_lines.extend(
            [
                "2) Также возможно: реакция желчного пузыря на жирную пищу.",
                "3) Реже: ферментная перегрузка поджелудочной и/или рефлюкс после еды.",
            ]
        )

    urgent_lines = red_flags[:8] if red_flags else [
        "сильная или нарастающая боль в верхней части живота",
        "многократная рвота",
        "одышка или боль в груди",
        "пожелтение кожи или глаз",
        "чёрный стул или кровь в рвоте",
    ]
    tests_line = ", ".join(recurrent_tests) if recurrent_tests else "АЛТ, АСТ, билирубин, ГГТ, амилаза, липаза, УЗИ органов брюшной полости"
    histamine_note = (
        "Гистаминовую ветку поднимаем только при типичном повторяемом паттерне (вино/сыр/копчёности + flushing/сердцебиение/зуд/заложенность)."
    )
    if _is_histamine_dominant_food_trigger(message):
        histamine_note = (
            "Есть признаки, что гистамин может быть значимым усилителем; всё равно базово сначала исключаем более частые причины ЖКТ."
        )

    return (
        opening
        + "Что вероятнее всего:\n"
        + "\n".join(what_it_may_be_lines)
        + "\nОдна жалоба — не одна причина: держим основные и альтернативные версии одновременно.\n"
        + matrix_block
        + "\nЧто может усиливать симптомы:\n"
        "- жирная/жареная еда, поздний ужин, алкоголь, переедание, сочетание жирного и сладкого;\n"
        f"- {histamine_note}\n"
        "Что делать сейчас:\n"
        "1) Пейте воду маленькими глотками.\n"
        "2) Не ложитесь сразу после еды.\n"
        "3) Сделайте паузу в жирной и тяжёлой пище на 6-8 часов.\n"
        "4) Зафиксируйте продукт-триггер и время появления симптомов.\n"
        "Когда нужен врач без ожидания:\n"
        + "\n".join(f"- {line}." for line in urgent_lines)
        + "\nНужны ли анализы:\n"
        + f"- {single_msg}\n"
        + f"- При повторяемом паттерне после жирной еды: {tests_line}.\n"
        + "- Не назначаем всем подряд DAO, гистамин в крови и IgG-панели совместимости продуктов.\n"
        + "Если симптомы повторяются, можно загрузить результаты в раздел «Анализы» — система поможет разобрать их и подскажет следующий шаг."
    )


def _upper_abdominal_response(message: str = "") -> tuple[str, list[str], bool]:
    msg = _norm_text_for_compare(message or "")
    try:
        from app.services.upper_abdominal_master_loader import (
            detect_upper_abdominal_red_flags,
            prioritize_upper_abdominal_causes,
            recurrent_fatty_or_ruq_tests,
            single_episode_message,
        )

        red_matches = detect_upper_abdominal_red_flags(message)
        ranked = prioritize_upper_abdominal_causes(message, limit=5)
        recurrent_tests = recurrent_fatty_or_ruq_tests()
        single_msg = single_episode_message()
    except Exception:
        red_matches = []
        ranked = []
        recurrent_tests = []
        single_msg = "Если это единичный лёгкий эпизод и симптомы проходят, срочные анализы обычно не нужны."

    urgent = bool(red_matches)
    likely = ranked[0]["title"] if ranked else "Диспепсия / раздражение желудка"
    alternatives = [str(x.get("title") or "").strip() for x in ranked[1:4] if str(x.get("title") or "").strip()]
    tests_line = ", ".join(recurrent_tests) if recurrent_tests else "АЛТ, АСТ, билирубин, ГГТ, амилаза, липаза, УЗИ органов брюшной полости"

    if urgent:
        response = (
            "По описанию есть красные флаги, поэтому бытовую интерпретацию лучше остановить.\n"
            "Когда нужен врач срочно:\n"
            + "\n".join(f"- {x}." for x in red_matches)
            + "\nСейчас: не ешьте, пейте воду маленькими глотками, не ложитесь и организуйте очную срочную оценку (неотложка/103 при ухудшении).\n"
            + _medication_notice_block(
                [
                    "симптоматические средства для ЖКТ по назначению врача",
                    "спазмолитики при боли - только после очной оценки",
                    "при рвоте/диарее - растворы для регидратации",
                ]
            )
        )
        return response, red_matches, True

    possible_lines = [f"1) Наиболее вероятно: {likely}."]
    if alternatives:
        possible_lines.append(f"2) Также возможно: {alternatives[0]}.")
    if len(alternatives) > 1:
        possible_lines.append(f"3) Реже: {alternatives[1]}.")
    if len(alternatives) > 2:
        possible_lines.append(f"4) Дополнительно: {alternatives[2]}.")

    response = (
        "Что вероятнее всего:\n"
        + "\n".join(possible_lines)
        + "\nЧто делать сейчас:\n"
        "1) Пейте воду маленькими глотками.\n"
        "2) Не ложитесь сразу после еды.\n"
        "3) Сделайте паузу в жирной и тяжёлой пище на 6-8 часов.\n"
        "4) При изжоге избегайте позднего ужина и положения лёжа после еды.\n"
        "Когда нужен врач без ожидания:\n"
        "- сильная или нарастающая боль в верхней части живота;\n"
        "- сильная боль справа под рёбрами;\n"
        "- боль с иррадиацией в спину, многократная рвота, температура;\n"
        "- чёрный стул, кровь в рвоте, обморок, желтуха, боль в груди или одышка.\n"
        "Нужны ли анализы, если это повторяется:\n"
        f"- {single_msg}\n"
        f"- При повторяемом паттерне после жирной еды/боли справа: {tests_line}.\n"
        "- При частой диспепсии/дискомфорте вверху живота обсудите с врачом H. pylori и факторы риска (в т.ч. НПВП)."
        "\n"
        + _medication_notice_block(
            [
                "антациды/альгинаты или другие симптоматические средства для ЖКТ по назначению врача",
                "спазмолитики при боли - по инструкции и после очной оценки",
                "при необходимости обезболивающие с учетом противопоказаний",
            ]
        )
    )
    return response, [], False


def _postmeal_bloating_response(message: str = "") -> tuple[str, list[str], bool]:
    msg = _norm_text_for_compare(message or "")
    try:
        from app.services.postmeal_bloating_master_loader import (
            detect_red_flags,
            prioritize_causes,
            single_mild_message,
        )

        red_matches = detect_red_flags(message)
        ranked = prioritize_causes(message, limit=5)
        single_msg = single_mild_message()
    except Exception:
        red_matches = []
        ranked = []
        single_msg = "При единичном лёгком эпизоде срочные анализы обычно не нужны."

    urgent = bool(red_matches)
    likely = ranked[0]["title"] if ranked else "Переедание или слишком быстрый приём пищи"
    alternatives = [str(x.get("title") or "").strip() for x in ranked[1:4] if str(x.get("title") or "").strip()]

    if urgent:
        response = (
            "По описанию есть признаки, где домашную интерпретацию лучше остановить.\n"
            "Когда нужна срочная очная помощь:\n"
            + "\n".join(f"- {x}." for x in red_matches)
            + "\nСейчас: регидратация маленькими порциями и срочная очная оценка (неотложка/103 при ухудшении).\n"
            + _medication_notice_block(
                [
                    "оральные растворы для регидратации",
                    "симптоматические средства для ЖКТ по назначению врача",
                    "при боли - спазмолитики по инструкции и после очной оценки",
                ]
            )
        )
        return response, red_matches, True

    possible_lines = [f"1) Наиболее вероятно: {likely}."]
    if alternatives:
        possible_lines.append(f"2) Также возможно: {alternatives[0]}.")
    if len(alternatives) > 1:
        possible_lines.append(f"3) Реже: {alternatives[1]}.")
    if len(alternatives) > 2:
        possible_lines.append(f"4) Дополнительно: {alternatives[2]}.")

    has_dairy = any(x in msg for x in ("молок", "молоч", "творог", "сливк", "кефир", "йогурт"))
    has_fodmap = any(x in msg for x in ("лук", "чеснок", "боб", "фрукт", "сок", "мед", "мёд", "сорбит", "ксилит"))
    ibs_note = "IBS не подтверждаем по одному эпизоду: нужна повторяемость, связь боли с дефекацией и изменение стула."

    response = (
        "Что вероятнее всего:\n"
        + "\n".join(possible_lines)
        + "\n"
        + ("Похоже на молочный паттерн: стоит оценить повторяемость именно на молочном.\n" if has_dairy else "")
        + ("Похоже на FODMAP-ветку: чаще это брожение углеводов у чувствительного кишечника.\n" if has_fodmap else "")
        + ibs_note
        + "\nЧто делать сейчас:\n"
        "1) Пейте жидкость маленькими порциями.\n"
        "2) На сутки уберите тяжёлую, жирную и раздражающую пищу.\n"
        "3) Зафиксируйте, после какого продукта начались вздутие/газы/стул.\n"
        "4) Не используем «дисбактериоз» как объяснение по умолчанию.\n"
        "Когда нужен врач без ожидания:\n"
        "- кровь в стуле или чёрный стул;\n"
        "- неукротимая рвота, выраженная слабость, обморок;\n"
        "- признаки обезвоживания (сухость, редкое мочеиспускание, вялость);\n"
        "- высокая температура или нарастающая боль в животе.\n"
        "Нужны ли анализы:\n"
        f"- {single_msg}\n"
        "- Если паттерн повторяется, нужна клиническая оценка по триггерам (молочное/FODMAP/кишечный паттерн)."
        "\n"
        + _medication_notice_block(
            [
                "растворы для регидратации при потере жидкости",
                "пробиотики/симптоматические средства - только по рекомендации врача",
                "при спазмах - спазмолитики по инструкции",
            ]
        )
    )
    return response, [], False


def _postmeal_systemic_response(message: str = "") -> tuple[str, list[str], bool]:
    try:
        from app.services.postmeal_systemic_master_loader import (
            detect_red_flags,
            prioritize_causes,
            recurrent_tests,
        )

        red_matches = detect_red_flags(message)
        ranked = prioritize_causes(message, limit=5)
        tests = recurrent_tests()
    except Exception:
        red_matches = []
        ranked = []
        tests = ["глюкоза крови", "биохимия", "оценка ЖКТ при необходимости"]

    urgent = bool(red_matches)
    likely = ranked[0]["title"] if ranked else "Сосудистая реакция после еды"
    alternatives = [str(x.get("title") or "").strip() for x in ranked[1:4] if str(x.get("title") or "").strip()]
    tests_line = ", ".join(tests)

    if urgent:
        response = (
            "По симптомам есть тревожные признаки, поэтому нужна срочная очная оценка.\n"
            "Когда обращаться без ожидания:\n"
            + "\n".join(f"- {x}." for x in red_matches)
            + "\nСейчас: сядьте/лягте с приподнятой головой, не нагружайте себя, при ухудшении вызывайте 103.\n"
            + _medication_notice_block(
                [
                    "симптоматические препараты для ЖКТ и вегетативных симптомов - только по назначению врача",
                    "растворы для регидратации при слабости/тошноте",
                    "обезболивающие при головной боли по инструкции",
                ]
            )
        )
        return response, red_matches, True

    response = (
        f"Вероятнее всего: {likely}.\n"
        "Также учитываем, что после еды это может быть смешанная реакция: ЖКТ + сосуды + глюкоза + вегетативная система.\n"
        + ("Альтернативы: " + "; ".join(alternatives) + ".\n" if alternatives else "")
        + "Что делать сейчас:\n"
        "1) Пейте воду небольшими глотками.\n"
        "2) Сядьте или прилягте с приподнятой головой.\n"
        "3) Сегодня избегайте тяжёлой и жирной еды, а также избытка сладкого.\n"
        "4) Если симптом связан со сладким — держим в приоритете реакцию на глюкозу.\n"
        "Когда нужен врач без ожидания:\n"
        "- обморок, выраженная слабость, невозможность стоять;\n"
        "- боль в груди, одышка;\n"
        "- спутанность сознания, резкое ухудшение.\n"
        "Нужны ли анализы:\n"
        "- При единичном эпизоде обычно не нужны.\n"
        f"- При повторяемом паттерне: {tests_line}."
        "\n"
        + _medication_notice_block(
            [
                "симптоматические средства для ЖКТ по назначению врача",
                "растворы для регидратации при тошноте/слабости",
                "обезболивающие при головной боли по инструкции",
            ]
        )
    )
    return response, [], False


def _food_symptom_super_response(message: str = "") -> dict[str, Any]:
    tests: list[str] = ["глюкоза крови", "биохимия", "оценка ЖКТ при необходимости"]
    single_msg = "При единичном эпизоде расширенные анализы обычно не нужны; при повторяемости — очная консультация."
    try:
        from app.services.food_symptom_super_master_loader import (
            build_patient_safe_response,
            classify_super,
        )
        msg_norm = _norm_text_for_compare(message or "")
        recurrent = any(x in msg_norm for x in ("повтор", "снова", "каждый раз", "регулярно", "часто"))
        super_ctx = classify_super(message, recurrent=recurrent)
        red_matches = list(super_ctx.get("red_flags") or [])
        zone = str(super_ctx.get("zone") or "upper_gi_zone")
        template = str(super_ctx.get("template") or "base_response")
        trigger_groups = [str(x).strip() for x in (super_ctx.get("trigger_groups") or []) if str(x).strip()]
        causes = list(super_ctx.get("ranked_causes") or [])
        rt = super_ctx.get("recurrent_tests") or super_ctx.get("follow_up_tests")
        if isinstance(rt, (list, tuple)) and rt:
            tests = [str(x).strip() for x in rt if str(x).strip()]
        sm = super_ctx.get("single_episode_tests_message") or super_ctx.get("single_episode_message")
        if isinstance(sm, str) and sm.strip():
            single_msg = sm.strip()
    except Exception:
        red_matches = []
        zone = "upper_gi_zone"
        template = "base_response"
        trigger_groups = []
        causes = []
        build_patient_safe_response = None

    if red_matches:
        response = _append_rx_footer_if_missing(
            "Есть признаки срочного сценария, поэтому бытовую интерпретацию лучше остановить.\n"
            "Когда обращаться без ожидания:\n"
            + "\n".join(f"- {x}." for x in red_matches)
            + "\nСейчас: не перегружайте ЖКТ, пейте воду небольшими глотками и организуйте срочную очную оценку (при ухудшении 103)."
        )
        return {
            "response": response,
            "red_flag_matches": red_matches,
            "red_flags_present": True,
            "severity": "YELLOW",
            "response_source": "food_symptom_super_guard",
            "structured": _postmeal_systemic_structured(),
        }

    msg_norm = _norm_text_for_compare(message or "")
    has_core_systemic = any(x in msg_norm for x in ("слаб", "дурнот", "головокруж", "ватн", "сонлив", "дрож", "потлив"))
    has_headache_like = any(x in msg_norm for x in ("голов", "голова бол", "головная боль"))
    has_upper_specific = any(x in msg_norm for x in ("верхн", "эпигастр", "подреб", "изжог", "кисл", "отрыж", "гореч"))
    if "fatty_fried" in trigger_groups and has_headache_like and not has_upper_specific and not has_core_systemic:
        response = _append_rx_footer_if_missing(_food_overload_reaction_response(message))
        return {
            "response": response,
            "red_flag_matches": [],
            "red_flags_present": False,
            "severity": "GREEN",
            "response_source": "food_overload_guard",
            "structured": _food_overload_structured(),
        }
    if has_core_systemic and not has_upper_specific and zone in ("upper_gi_zone", "systemic_zone"):
        response, red, urgent = _postmeal_systemic_response(message)
        return {
            "response": response,
            "red_flag_matches": red,
            "red_flags_present": urgent,
            "severity": "YELLOW" if urgent else "GREEN",
            "response_source": "postmeal_systemic_guard",
            "structured": _postmeal_systemic_structured(),
        }

    if zone in ("upper_gi_zone", "right_upper_abdominal_zone"):
        response, red, urgent = _upper_abdominal_response(message)
        return {
            "response": response,
            "red_flag_matches": red,
            "red_flags_present": urgent,
            "severity": "YELLOW" if urgent else "GREEN",
            "response_source": "upper_abdominal_guard",
            "structured": _upper_abdominal_structured(),
        }
    if zone == "bowel_zone":
        response, red, urgent = _postmeal_bloating_response(message)
        return {
            "response": response,
            "red_flag_matches": red,
            "red_flags_present": urgent,
            "severity": "YELLOW" if urgent else "GREEN",
            "response_source": "postmeal_bloating_guard",
            "structured": _postmeal_bloating_structured(),
        }
    if zone == "systemic_zone":
        response, red, urgent = _postmeal_systemic_response(message)
        return {
            "response": response,
            "red_flag_matches": red,
            "red_flags_present": urgent,
            "severity": "YELLOW" if urgent else "GREEN",
            "response_source": "postmeal_systemic_guard",
            "structured": _postmeal_systemic_structured(),
        }

    if build_patient_safe_response:
        response = build_patient_safe_response(
            template_id=template or "base_response",
            ranked_causes=causes,
            recurrent=any(x in msg_norm for x in ("повтор", "снова", "регулярно", "часто")),
        )
    else:
        likely = str((causes[0] or {}).get("title") or "Пищевая постпрандиальная реакция") if causes else "Пищевая постпрандиальная реакция"
        alternatives = [str(x.get("title") or "").strip() for x in causes[1:3] if str(x.get("title") or "").strip()]
        response = (
            f"Что вероятнее всего: {likely}.\n"
            + ("Какие ещё причины возможны: " + "; ".join(alternatives) + ".\n" if alternatives else "")
            + "Что делать сейчас: пейте воду небольшими порциями, не ложитесь сразу после еды, временно избегайте жирной и тяжёлой пищи.\n"
            + "Когда срочно обращаться: при обмороке, боли в груди, одышке, многократной рвоте, крови в стуле/рвоте, резком ухудшении.\n"
            + "Нужны ли анализы, если повторяется: "
            + (", ".join(tests) if tests else single_msg)
            + "."
        )
    response = _append_rx_footer_if_missing(response)
    return {
        "response": response,
        "red_flag_matches": [],
        "red_flags_present": False,
        "severity": "GREEN",
        "response_source": "food_symptom_super_guard",
        "structured": _food_overload_structured(),
    }


def _postmeal_systemic_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "После какой еды становится хуже: жирной, сладкой или смешанной?",
            "Есть ли выраженная слабость, предобморок, потливость или дрожь?",
            "Были ли боль в груди, одышка или эпизод потери сознания?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
    }


def _postmeal_bloating_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Есть ли чёткая связь с молочными продуктами или конкретными углеводными триггерами (лук, чеснок, соки, мёд)?",
            "Это разовый эпизод или повторяется, и есть ли связь боли с дефекацией/изменением стула?",
            "Есть ли температура, кровь в стуле, выраженная слабость или признаки обезвоживания?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
    }


def _upper_abdominal_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Где именно сильнее: строго вверху живота или больше справа под рёбрами?",
            "Есть ли изжога, кислый привкус или ухудшение в положении лёжа?",
            "Были ли многократная рвота, температура, чёрный стул или кровь в рвоте?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
    }


def _food_overload_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Через сколько после еды начались симптомы и сколько они обычно длятся?",
            "Есть ли боль справа под рёбрами, рвота или горечь во рту?",
            "Повторяется ли такое на вино, сыр, копчёности или молочные продукты?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
    }


def _rx_only_medication_footer() -> str:
    """Единый дисклеймер: примеры препаратов не равняются самостоятельному назначению."""
    return (
        "Конкретный препарат, доза и длительность курса — только по рецепту или прямому назначению врача; "
        "самолечением курс не подбирайте."
    )


def _response_includes_unified_rx_footer(text: str) -> bool:
    tn = _norm_text_for_compare(text or "")
    return "по рецепту или прямому назначению врача" in tn or "самолечением курс не подбирайте" in tn


def _append_rx_footer_if_missing(response: str) -> str:
    """Добавить единый дисклеймер, если в тексте ещё нет блока про рецепт/врача (избегаем дублей)."""
    body = str(response or "").rstrip()
    if not body:
        return _rx_only_medication_footer()
    if _response_includes_unified_rx_footer(body):
        return body
    return body + "\n\n" + _rx_only_medication_footer()


def _medication_block_intro_similar_cases() -> str:
    return "В сходных ситуациях при похожей симптоматике нередко используют следующие группы препаратов:"


def _medication_notice_block(items: list[str]) -> str:
    clean = [str(x).strip() for x in (items or []) if str(x).strip()]
    if not clean:
        return ""
    return (
        _medication_block_intro_similar_cases()
        + "\n- "
        + "\n- ".join(clean[:3])
        + "\n"
        + _rx_only_medication_footer()
    )


def _is_anorectal_bleeding_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    anorectal_markers = (
        "гемор",
        "геморрой",
        "анальн",
        "прямая кишк",
        "задний проход",
        "узел",
        "шишка",
    )
    blood_markers = (
        "кров",
        "кровит",
        "кровотеч",
        "течет кровь",
        "течёт кровь",
    )
    pain_markers = ("боль", "жжет", "жжёт", "зуд", "жжение")
    has_anorectal = any(m in t for m in anorectal_markers)
    has_blood = any(m in t for m in blood_markers)
    has_pain = any(m in t for m in pain_markers)
    return has_anorectal and (has_blood or has_pain)


def _anorectal_bleeding_response() -> str:
    return (
        "Похоже на обострение геморроя с кровью. Что делать сейчас:\n"
        "1) Если кровь ярко-алая и немного — остановите натуживание, подмойтесь прохладной водой, наложите чистую прокладку/салфетку.\n"
        "2) Не поднимайте тяжести и не сидите долго без перерывов.\n"
        "3) Стул должен быть мягким: вода, пищевые волокна, без запоров.\n"
        "4) "
        + _medication_block_intro_similar_cases()
        + " местные противовоспалительные средства (свечи/кремы), мягкие слабительные при запоре, обезболивающие по инструкции. "
        + _rx_only_medication_footer()
        + "\n"
        "5) Срочно в неотложку/103, если кровь идёт обильно, есть слабость/головокружение, тёмный стул, сильная боль или температура."
    )


def _anorectal_bleeding_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Крови немного на бумаге/салфетке или кровотечение более обильное?",
            "Есть ли сильная боль, температура, слабость или головокружение?",
            "Были ли запоры/натуживание в последние дни?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
    }


def _is_headache_autonomic_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    headache_markers = ("голов", "мигрен", "болит голова", "головная боль")
    autonomic_markers = (
        "поте",
        "потлив",
        "красн лиц",
        "лицо красн",
        "лицо гор",
        "дрож",
        "тремор",
        "тошн",
        "пульс",
        "сердц",
        "тахик",
        "жар",
    )
    has_headache = any(m in t for m in headache_markers)
    auto_hits = sum(1 for m in autonomic_markers if m in t)
    return has_headache and auto_hits >= 2


def _headache_autonomic_response() -> str:
    return (
        "Понял. Здесь важно сначала найти причину, а не давать общий шаблон.\n"
        "Рабочие гипотезы:\n"
        "- колебания давления (вверх/вниз)\n"
        "- вегетативная реакция на перегрев, стресс или нагрузку\n"
        "- реже: эндокринный фактор (например, щитовидная железа)\n"
        "Чтобы сузить причину, ответьте коротко:\n"
        "- Какое сейчас давление и пульс (2 измерения с интервалом 5-10 минут)?\n"
        "- Был ли перегрев (солнце/баня/парилка), интенсивная нагрузка или стресс?\n"
        "- Была ли травма головы в последние дни?\n"
        "- Есть ли боль в груди, одышка, онемение/слабость, нарушение речи?\n"
        "- После отдыха и воды становится легче или нет?\n"
        "Пока до уточнений: покой, вода, без нагрузки, контроль давления/пульса.\n"
        + _medication_notice_block(
            [
                "обезболивающие (например, парацетамол/ибупрофен) по инструкции",
                "при мигренозном профиле - только ранее назначенная врачом терапия",
                "самостоятельно не комбинировать несколько препаратов от давления",
            ]
        )
        + "\n"
        "Срочно 103, если появилась сильная боль в груди, неврологические симптомы, обморок или выраженная одышка."
    )


def _headache_autonomic_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Какое сейчас давление и пульс (2 измерения)?",
            "Был ли перегрев, баня/парилка, нагрузка или сильный стресс перед началом?",
            "Была ли травма головы в последние дни?",
            "Есть ли боль в груди, одышка, онемение/слабость, нарушение речи?",
            "После отдыха и воды стало легче или без изменений?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
        "library_topic": "headache_autonomic_guard",
    }


def _is_nosebleed_request(message: str) -> bool:
    if not message or not isinstance(message, str):
        return False
    t = _norm_text_for_compare(message)
    if not t:
        return False
    nose_markers = ("нос", "носа", "носов", "ноздр")
    blood_markers = ("кров", "кровотеч", "идет кровь", "идёт кровь")
    return any(n in t for n in nose_markers) and any(b in t for b in blood_markers)


def _nosebleed_response() -> str:
    return (
        "Понял. Это похоже на носовое кровотечение. Действуйте сразу:\n"
        "1) Сядьте, слегка наклонитесь вперед (не запрокидывать голову).\n"
        "2) Плотно зажмите мягкую часть носа на 10-15 минут без проверки каждую минуту.\n"
        "3) Холод на переносицу/лоб.\n"
        "4) Не сморкайтесь и не трогайте нос 2-3 часа после остановки.\n"
        "Чтобы понять причину и риски, уточню:\n"
        "- Какое сейчас давление и пульс?\n"
        "- Была ли травма носа, перегрев, сухой воздух или физнагрузка?\n"
        "- Кровотечение остановилось за 15 минут или продолжается?\n"
        "- Есть ли выраженная головная боль, слабость, головокружение?\n"
        + _medication_notice_block(
            [
                "солевые увлажняющие средства для слизистой носа",
                "местные гемостатические средства - только по рекомендации врача",
                "обезболивающие при головной боли (избегать препаратов, усиливающих кровотечение, без консультации врача)",
            ]
        )
        + "\n"
        "Срочно 103, если кровь не останавливается >20 минут, течет обильно, есть сильная слабость/обморок, или выраженная головная боль с очень высоким давлением."
    )


def _nosebleed_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Какое сейчас давление и пульс (2 измерения)?",
            "Кровотечение остановилось в течение 10-15 минут при плотном зажатии носа?",
            "Была ли травма носа, перегрев, баня/парилка или интенсивная нагрузка?",
            "Есть ли сильная головная боль, слабость, головокружение?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
        "library_topic": "nosebleed_guard",
    }


def _is_amenorrhea_galactorrhea_concern(message: str) -> bool:
    """
    Вторичная аменорея + выделения из груди — отдельный клинический контекст;
    не подменять вопросами про «боль в начале цикла» из библиотеки несоответствующих жалоб.
    """
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    if any(k in t for k in ("кормлю груд", "лактац", "грудное вскарм")):
        return False
    breast = any(k in t for k in ("груд", "соск"))
    discharge = any(k in t for k in ("молок", "молозив", "выдел", "капел", "капли"))
    if not (breast and discharge):
        return False
    cycle = any(k in t for k in ("месячн", "менстру", "цикл"))
    loss = any(
        k in t
        for k in (
            "пропал",
            "пропали",
            "нет месячн",
            "нет менстру",
            "не было месячн",
            "аменор",
            "задержк",
            "нет цикла",
        )
    )
    return bool(cycle and loss)


def _amenorrhea_galactorrhea_response() -> str:
    return (
        "Понял. Сочетание отсутствия менструации и выделений из груди, похожих на молоко, "
        "нужно разбирать очно: это может быть связано с гормонами (например, с уровнем пролактина) и с другими причинами, "
        "которые в чате надёжно не исключают и не подтверждают.\n\n"
        "Что важно сделать:\n"
        "- Запишитесь к гинекологу и/или эндокринологу в ближайшие дни (не откладывайте на «потом» без причины).\n"
        "- На приёме обычно уточняют историю и назначают целевые анализы/обследования (часто включают пролактин и связанные тесты — по решению врача).\n\n"
        "Уточните коротко:\n"
        "- Есть ли беременность или вы сейчас кормите грудью?\n"
        "- Принимаете ли антидепрессанты, противосудорожные, противорвотные/прокинетики (например, метоклопрамид) или другие препараты, влияющие на гормоны?\n"
        "- Были ли сильные головные боли или ухудшение зрения по периферии?\n"
        "- Как давно нет менструации и как давно появились выделения?\n\n"
        "Срочно 103/112, если появились сильная стойкая головная боль, выраженное ухудшение зрения, сильная слабость или обмороки.\n"
        + _medication_notice_block(
            [
                "не начинать и не отменять гормональные препараты самостоятельно без врача",
                "не подбирать «домашние» схемы снижения пролактина по интернету",
            ]
        )
        + "\nИнформация носит справочный характер и не заменяет консультацию врача."
    )


def _amenorrhea_galactorrhea_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Есть ли беременность или кормление грудью?",
            "Какие лекарства вы принимаете постоянно (в т.ч. антидепрессанты/противорвотные)?",
            "Были ли сильные головные боли или ухудшение периферического зрения?",
            "Как давно нет менструации и как давно появились выделения из груди?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
        "library_topic": "amenorrhea_galactorrhea_guard",
    }


def _is_prolonged_appetite_loss_concern(message: str) -> bool:
    """Длительное снижение аппетита/мало ест — не сводить к шаблону «воспалительный процесс»."""
    if not message or not isinstance(message, str):
        return False
    t = message.strip().lower()
    eat_loss = any(
        k in t
        for k in (
            "аппетит",
            "не ем",
            "ничего не ем",
            "почти не ем",
            "есть не могу",
            "не могу есть",
        )
    )
    duration = any(
        k in t
        for k in (
            "месяц",
            "недел",
            "полгод",
            "пол года",
            "год",
            "два месяц",
            "2 месяц",
            "три месяц",
            "3 месяц",
            "давно",
        )
    )
    return eat_loss and duration


def _prolonged_appetite_loss_response() -> str:
    return (
        "Понял. Если аппетит выраженно снижен несколько недель и вы почти не едите, это повод для очной оценки: "
        "причины могут быть разными (включая тревогу/депрессию, ЖКТ, инфекции, эндокринные сдвиги), и важно не «пережить само» без контроля.\n\n"
        "Что сделать:\n"
        "- В ближайшие дни — очный приём (терапевт; детям — педиатр). При выраженной тревоге/настроении — обсудить поддержку у психиатра/психотерапевта по направлению.\n"
        "- Если есть обмороки, сильная слабость, рвота с кровью, чёрный стул, сильная боль в животе — срочно 103/112.\n\n"
        "Уточните коротко:\n"
        "- Менялся ли вес заметно за последние 2–3 месяца?\n"
        "- Есть ли тошнота, боль в животе, лихорадка, сильная слабость?\n"
        "- Были ли жёсткая диета, сильный стресс, новые лекарства?\n"
        + _medication_notice_block(
            [
                "не принимать «аппетитные» или жиросжигающие добавки без очного осмотра",
                "не пить большие комбинации БАДов, чтобы не маскировать симптомы",
            ]
        )
        + "\nИнформация носит справочный характер и не заменяет консультацию врача."
    )


def _prolonged_appetite_loss_structured() -> dict[str, Any]:
    return {
        "suggested_questions": [
            "Менялся ли вес заметно за последние 2–3 месяца?",
            "Есть ли тошнота, боль в животе, лихорадка, выраженная слабость?",
            "Были ли жёсткая диета, сильный стресс или новые лекарства?",
            "Были ли рвота, кровь в стуле или чёрный стул?",
        ],
        "action_sequence": [],
        "insufficient_data": False,
        "library_topic": "prolonged_appetite_loss_guard",
    }


def _is_hormone_mood_fatigue_request(message: str) -> bool:
    t = _norm_text_for_compare(message or "")
    if not t:
        return False
    has_hormone = any(x in t for x in ("гормон", "щитовид", "эндокрин", "ттг", "пролактин"))
    has_mood = any(x in t for x in ("настроен", "перепад", "скачет", "апат", "тревог", "раздраж"))
    has_fatigue = any(x in t for x in ("устал", "слабост", "нет сил", "энерг"))
    # Жесткий сценарий только для комбинации «гормоны + настроение + усталость»,
    # чтобы не перехватывать другие домены (пищевые/ЖКТ/прочее).
    return has_hormone and has_mood and has_fatigue


def _hormone_mood_fatigue_questions(message: str) -> list[str]:
    sex = _extract_sex_from_text(message or "")
    q = [
        "Когда начались перепады настроения и усталость, что усиливает и что облегчает симптомы?",
        "Как со сном: трудно уснуть, частые пробуждения, есть ли ощущение невосстановленного сна утром?",
        "Есть ли изменения веса, аппетита, потливости, сердцебиения или переносимости холода/жары?",
        "Сдавали ли ТТГ/св.Т4, ферритин, B12, витамин D, глюкозу и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца), были ли отклонения?",
    ]
    if sex == "female":
        q.insert(3, "Есть ли изменения цикла/ПМС (задержки, нерегулярность, усиление симптомов перед менструацией)?")
    return q[:5]


def _hormone_mood_fatigue_upload_tail() -> str:
    return "Если вы уже получили результаты анализов, загрузите полученные результаты в раздел «Анализы» — я помогу с интерпретацией."


def _hormone_mood_fatigue_response(message: str) -> str:
    sex = _extract_sex_from_text(message or "")
    cycle_tail = " или циклом" if sex == "female" else ""
    first_q = f"Когда начались симптомы? Есть ли связь со сном, стрессом{cycle_tail}?"
    return (
        "Здравствуйте, я ваш консультант Михаил.\n\n"
        "Понял. Жалобы: перепады настроения, усталость.\n\n"
        "Что проверить вероятнее всего:\n"
        "- гормональный фактор (щитовидная железа, стресс-ось; если актуально - половые гормоны)\n"
        "- дефициты (ферритин, B12, витамин D)\n"
        "- нарушение сна и хроническая перегрузка\n"
        "\nЧто проверить первым этапом:\n"
        "- ТТГ, свободный Т4\n"
        "- общий анализ крови + ферритин\n"
        "- витамин B12, витамин D\n"
        "- глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца)\n"
        "\nЧто делать сейчас:\n"
        "- не принимать гормоны без анализов\n"
        "- сон 7-8 часов\n"
        "- регулярное питание\n"
        "- умеренная нагрузка\n"
        "\nУточнение:\n"
        + first_q
        + "\n"
        + _hormone_mood_fatigue_upload_tail()
    )


def _hormone_mood_fatigue_thread_active(state: Optional[dict[str, Any]]) -> bool:
    if not isinstance(state, dict):
        return False
    block = state.get("hormone_mood_fatigue")
    return isinstance(block, dict) and bool(block.get("active"))


def _hormone_mood_fatigue_step(state: Optional[dict[str, Any]]) -> int:
    if not isinstance(state, dict):
        return 1
    block = state.get("hormone_mood_fatigue")
    if not isinstance(block, dict):
        return 1
    try:
        s = int(block.get("step") or 1)
        return max(1, min(5, s))
    except Exception:
        return 1


@lru_cache(maxsize=1)
def _load_endocrine_asthenic_policy() -> dict[str, Any]:
    policy_path = Path(__file__).resolve().parents[1] / "clinical_policies" / "endocrine_asthenic.json"
    fallback = {
        "required_slots_male": ["sleep_stress_link", "autonomic_signs", "labs_status"],
        "required_slots_female": ["sleep_stress_link", "autonomic_signs", "cycle_signs", "labs_status"],
        "blocked_topics_when_negated": ["respiratory"],
        "stop_conditions": {"finish_when_labs_status_filled": True},
    }
    try:
        raw = json.loads(policy_path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else fallback
    except Exception:
        return fallback


def _fsm_load_or_init(consultation_state: Optional[dict[str, Any]], message: str) -> dict[str, Any]:
    state = consultation_state if isinstance(consultation_state, dict) else {}
    fsm = state.get("clinical_fsm")
    if isinstance(fsm, dict) and str(fsm.get("scenario_id") or "") == "hormone_mood_fatigue":
        return {
            "scenario_id": "hormone_mood_fatigue",
            "active": bool(fsm.get("active", True)),
            "step_id": int(fsm.get("step_id") or 2),
            "domain_lock": "endocrine_asthenic",
            "asked_slots": list(fsm.get("asked_slots") or []),
            "filled_slots": dict(fsm.get("filled_slots") or {}),
            "forbidden_repeats": list(fsm.get("forbidden_repeats") or []),
            "expected_slot": str(fsm.get("expected_slot") or ""),
        }
    return {
        "scenario_id": "hormone_mood_fatigue",
        "active": bool(_hormone_mood_fatigue_thread_active(state) or _is_hormone_mood_fatigue_request(message)),
        "step_id": int(_hormone_mood_fatigue_step(state) or 2),
        "domain_lock": "endocrine_asthenic",
        "asked_slots": [],
        "filled_slots": {},
        "forbidden_repeats": [],
        "expected_slot": "sleep_stress_link",
    }


def _fsm_update_endocrine_slots(fsm: dict[str, Any], message: str) -> dict[str, Any]:
    t = _norm_text_for_compare(message or "")
    if not t:
        return fsm
    filled = dict(fsm.get("filled_slots") or {})
    forbidden = set(fsm.get("forbidden_repeats") or [])
    expected_slot = str(fsm.get("expected_slot") or "")
    yes_no = {"да", "нет", "неа", "ага", "угу", "не", "не связано", "связано"}
    if any(x in t for x in ("недел", "месяц", "дн", "дней", "нед", "уже говорил", "давно")):
        filled.setdefault("duration", t)
        forbidden.add("duration")
    if any(x in t for x in ("сон", "сплю", "засып", "просып", "стресс", "тревог", "выгор", "перегруз")):
        filled["sleep_stress_link"] = t
        forbidden.add("sleep_stress_link")
    if any(x in t for x in ("цикл", "пмс", "задерж", "менстру", "нерегуляр")):
        filled["cycle_signs"] = t
        forbidden.add("cycle_signs")
    if any(x in t for x in ("вес", "аппет", "потлив", "сердцеби", "холода", "жары")):
        filled["autonomic_signs"] = t
        forbidden.add("autonomic_signs")
    if any(
        x in t
        for x in (
            "результатов нет",
            "пока нет результатов",
            "еще нет результатов",
            "ещё нет результатов",
            "не готовы результаты",
            "жду результаты",
            "сдал но результатов нет",
        )
    ):
        filled["labs_status"] = "done_pending_results"
        forbidden.add("labs_status")
    elif any(x in t for x in ("сдавал", "сдал", "анализ")) and "результат" in t:
        filled["labs_status"] = "done_status_mentioned"
        forbidden.add("labs_status")
    elif expected_slot in {"autonomic_signs", "labs_status", "cycle_signs", "sleep_stress_link"} and t in yes_no:
        filled[expected_slot] = t
        forbidden.add(expected_slot)
    fsm["filled_slots"] = filled
    fsm["forbidden_repeats"] = list(forbidden)
    return fsm


def _policy_eval_endocrine(fsm: dict[str, Any], message: str) -> dict[str, Any]:
    sex = _extract_sex_from_text(message or "")
    policy = _load_endocrine_asthenic_policy()
    req_key = "required_slots_female" if sex == "female" else "required_slots_male"
    required_slots = [str(x) for x in (policy.get(req_key) or []) if str(x)]
    filled = dict(fsm.get("filled_slots") or {})
    blocked_topics: list[str] = []
    msg_norm = _norm_text_for_compare(message or "")
    if any(x in msg_norm for x in ("ни при чем", "не про кашель", "не про температуру", "температуры нет")):
        blocked_topics = [str(x) for x in (policy.get("blocked_topics_when_negated") or []) if str(x)]
    missing_slots = [slot for slot in required_slots if slot not in filled]
    stop_cfg = policy.get("stop_conditions") if isinstance(policy.get("stop_conditions"), dict) else {}
    force_plan = bool(stop_cfg.get("finish_when_labs_status_filled")) and ("labs_status" in filled)
    return {
        "required_slots": required_slots,
        "missing_slots": missing_slots,
        "next_slot": missing_slots[0] if missing_slots else "",
        "blocked_topics": blocked_topics,
        "force_plan": force_plan or not missing_slots,
    }


def _endocrine_slot_question(slot_id: str) -> str:
    mapping = {
        "sleep_stress_link": "Как со сном: трудно уснуть, частые пробуждения, есть ли ощущение невосстановленного сна утром?",
        "autonomic_signs": "Есть ли изменения веса, аппетита, потливости, сердцебиения или переносимости холода/жары?",
        "cycle_signs": "Есть ли изменения цикла/ПМС (задержки, нерегулярность, усиление симптомов перед менструацией)?",
        "labs_status": "Сдавали ли ТТГ/св.Т4, ферритин, B12, витамин D, глюкозу и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца), были ли отклонения?",
    }
    return mapping.get(slot_id, "")


def _endocrine_slot_signal_score(slot_id: str, msg_norm: str) -> int:
    if slot_id == "sleep_stress_link":
        return 45 if any(x in msg_norm for x in ("сон", "сплю", "засып", "просып", "стресс", "тревог", "выгор", "перегруз")) else 0
    if slot_id == "autonomic_signs":
        return 45 if any(x in msg_norm for x in ("вес", "аппет", "потлив", "сердцеби", "холода", "жары")) else 0
    if slot_id == "cycle_signs":
        return 50 if any(x in msg_norm for x in ("цикл", "пмс", "задерж", "менстру", "нерегуляр")) else 0
    if slot_id == "labs_status":
        return 50 if any(x in msg_norm for x in ("сдал", "сдавал", "анализ", "результат", "отклонен")) else 0
    return 0


def _endocrine_select_next_slot(fsm: dict[str, Any], policy: dict[str, Any], message: str) -> str:
    filled = dict(fsm.get("filled_slots") or {})
    asked = set(str(x) for x in (fsm.get("asked_slots") or []) if str(x))
    forbidden = set(str(x) for x in (fsm.get("forbidden_repeats") or []) if str(x))
    missing = [str(x) for x in (policy.get("missing_slots") or []) if str(x)]
    if not missing:
        return ""

    # Information gain prior: sleep/stress -> autonomic -> cycle -> labs; then adjust by message signals.
    base_gain = {
        "sleep_stress_link": 90,
        "autonomic_signs": 80,
        "cycle_signs": 70,
        "labs_status": 60,
    }
    msg_norm = _norm_text_for_compare(message or "")
    candidates = [slot for slot in missing if slot not in filled and slot not in asked and slot not in forbidden]
    if not candidates:
        return ""
    ranked = sorted(
        candidates,
        key=lambda s: (base_gain.get(s, 0) + _endocrine_slot_signal_score(s, msg_norm)),
        reverse=True,
    )
    return ranked[0] if ranked else ""


def _hormone_mood_fatigue_explainability(next_slot: str = "", stage: str = "followup") -> dict[str, str]:
    slot_why = {
        "sleep_stress_link": "Уточняю связь симптомов со сном и стрессом, чтобы отделить функциональную перегрузку от эндокринных причин.",
        "autonomic_signs": "Уточняю вегетативные признаки (вес, потливость, пульс, переносимость холода/жары), чтобы проверить вероятность тиреоидного контура.",
        "cycle_signs": "Уточняю связь с циклом, чтобы оценить гормональный профиль и приоритет обследований.",
        "labs_status": "Уточняю статус анализов, чтобы не повторять вопросы и сразу перейти к точному плану по результатам.",
    }
    plan_why = {
        "start": "План включает базовые анализы, которые чаще всего разделяют гормональные причины, дефициты и влияние сна/стресса.",
        "followup": "Следующий вопрос выбран по незаполненному клиническому слоту, чтобы не ходить по кругу.",
        "repair": "Переформулирую кратко по эндокринному сценарию, чтобы вернуть релевантность и убрать повтор.",
    }
    return {
        "why_this_question": slot_why.get(next_slot) or "Уточняю один ключевой пункт, чтобы не повторять уже пройденные шаги.",
        "why_this_plan": plan_why.get(stage) or plan_why["followup"],
    }


def _hormone_mood_fatigue_followup_response(message: str, step: int) -> tuple[str, int]:
    qs = _hormone_mood_fatigue_questions(message)
    if not qs:
        return ("Уточню коротко: когда начались симптомы и есть ли связь со сном или стрессом?", 2)
    idx = max(0, min(len(qs) - 1, step - 1))
    current_q = qs[idx]
    msg_norm = _norm_text_for_compare(message or "")

    # «что это?», «не понял», «что за вопрос?» — переформулируем текущий шаг и не двигаем счётчик.
    if _is_clarify_rephrase_request(message) or _norm_text_for_compare(message or "") in {
        "что это",
        "что это?",
        "что это значит",
        "что это за вопрос",
    }:
        resp = (
            "Извините, поясню проще. Этот вопрос нужен, чтобы отделить гормональный контур от дефицитного и стрессового.\n"
            + current_q
        )
        return resp, idx + 1

    # Явный сигнал, что ответ получился «флудом»/повтором — извиняемся и даём более собранный шаг.
    if any(
        x in msg_norm
        for x in (
            "зачем ты",
            "несколько раз",
            "каждый раз",
            "флуд",
            "не надо мне",
            "не предлагай",
            "ответ не тот",
            "не на квалифицированный ответ",
            "не квалифицированный ответ",
        )
    ):
        concise = (
            "Извините, вы правы — предыдущий ответ был перегружен повтором. Продолжаю кратко и по делу.\n"
            + current_q
        )
        return concise, idx + 1

    # Короткий/неинформативный ответ — мягко повторяем текущий вопрос.
    short_tokens = [x for x in msg_norm.split(" ") if x]
    yes_no_tokens = {
        "да",
        "нет",
        "неа",
        "ага",
        "угу",
        "не",
        "связано",
        "не связано",
    }
    # Короткий «да/нет» считаем валидным ответом и двигаем шаг дальше.
    if msg_norm in yes_no_tokens:
        if idx >= len(qs) - 1:
            resp = (
                "Спасибо, это уже полезно для маршрута. Следующий шаг: сдайте первый этап анализов "
                "(ТТГ, св.Т4, ОАК, ферритин, B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца)), после чего я разберу результаты и дам точный план."
                "\n"
                + _hormone_mood_fatigue_upload_tail()
            )
            return resp, len(qs)
        return qs[idx + 1], idx + 2
    if len(short_tokens) <= 2 and not any(ch.isdigit() for ch in msg_norm):
        return current_q, idx + 1

    # Если это последний шаг и пользователь дал содержательный ответ — закрываем шаги.
    if idx >= len(qs) - 1:
        resp = (
            "Спасибо, это уже полезно для маршрута. Следующий шаг: сдайте первый этап анализов "
            "(ТТГ, св.Т4, ОАК, ферритин, B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца)), после чего я разберу результаты и дам точный план."
            "\n"
            + _hormone_mood_fatigue_upload_tail()
        )
        return resp, len(qs)

    # Иначе идём к следующему уточнению.
    next_q = qs[idx + 1]
    return next_q, idx + 2


def _is_answer_quality_repair_request(message: str) -> bool:
    t = _norm_text_for_compare(message or "")
    if not t:
        return False
    explicit = (
        "не понял",
        "не поняла",
        "не понял вас",
        "что это",
        "что это значит",
        "что это за ответ",
        "ответ не тот",
        "нерелевант",
        "не по теме",
        "переформулируй",
        "сформулируй нормально",
        "зачем ты",
        "несколько раз",
        "каждый раз",
        "не надо мне каждый раз",
        "флуд",
        "не квалифицированный ответ",
        "тебя опять куда-то не туда понесло",
        "не туда понесло",
        "ни в какие ворота",
        "меня такой ответ не устраивает",
        "вообще не устраивает",
        "ты вообще не умный ассистент",
        "какой-то словесный",
    )
    return any(x in t for x in explicit)


def _last_substantive_user_message(chat_history: Optional[list[dict[str, Any]]], current_msg: str) -> str:
    now = _norm_text_for_compare(current_msg or "")
    for row in reversed(chat_history or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "").strip().lower() != "user":
            continue
        txt = str(row.get("content") or "").strip()
        if not txt:
            continue
        norm = _norm_text_for_compare(txt)
        if not norm or norm == now:
            continue
        if _is_answer_quality_repair_request(txt):
            continue
        return txt
    return ""


def _medical_repair_fallback_response(previous_user_message: str) -> str:
    return (
        "Давайте спокойно и по делу вернёмся к вашему медицинскому вопросу.\n"
        "Сначала отделяем гормональные причины от дефицитов и влияния сна/стресса.\n"
        "Проверьте первым этапом: ОАК, ферритин, B12, витамин D, ТТГ и свободный Т4, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца).\n"
        "Уточните: когда начались симптомы и что их усиливает/облегчает?\n"
        + _hormone_mood_fatigue_upload_tail()
    )


def _repair_domain_key(message: str) -> str:
    t = _norm_text_for_compare(message or "")
    if not t:
        return "general"
    if _is_hormone_mood_fatigue_request(message) or any(x in t for x in ("гормон", "щитовид", "ттг", "пролактин")):
        return "endocrine"
    if _is_trauma_context_message(message):
        return "trauma"
    if any(x in t for x in ("пульс", "давлен", "сердц", "тахикард", "аритм", "боль в груди", "одыш")):
        return "cardio"
    if any(x in t for x in ("живот", "тошн", "рвот", "диаре", "понос", "стул", "изжог", "кишеч", "желуд")):
        return "gastro"
    return "general"


def _domain_specific_repair_response(domain: str, previous_user_message: str) -> str:
    if domain == "endocrine":
        return (
            "Извините, предыдущий ответ был нерелевантным. Давайте корректно по эндокринному профилю.\n"
            + _hormone_mood_fatigue_response(previous_user_message)
        )
    if domain == "gastro":
        return (
            "Извините, предыдущий ответ был нерелевантным. Возвращаюсь к ЖКТ-контексту.\n"
            "Что важно сейчас: оценить связь симптомов с едой, исключить обезвоживание и красные флаги.\n"
            "Базово: ОАК, СРБ, биохимия (АЛТ/АСТ/билирубин), по показаниям копрограмма/кал на скрытую кровь.\n"
            "Уточните: есть ли рвота, кровь в стуле, высокая температура, нарастающая боль в животе?\n"
            "Если уже получили результаты анализов, загрузите полученные результаты в раздел «Анализы» — я помогу с интерпретацией."
        )
    if domain == "cardio":
        return (
            "Извините, предыдущий ответ был нерелевантным. Возвращаюсь к кардио-контексту.\n"
            "Сейчас приоритет: давление/пульс в динамике и исключение опасных симптомов.\n"
            "Уточните: боль в груди, одышка в покое, перебои, обморок, резкая слабость — есть сейчас?\n"
            "При ухудшении или боли в груди/одышке в покое — срочно 103.\n"
            "Если уже получили результаты анализов, загрузите полученные результаты в раздел «Анализы» — я помогу с интерпретацией."
        )
    if domain == "trauma":
        return (
            "Извините, предыдущий ответ был нерелевантным. Возвращаюсь к травматологическому контексту.\n"
            "Сейчас главное: оценить опору/объём движения, отёк, деформацию, неврологические симптомы.\n"
            "Уточните: можете наступать на конечность, есть ли нарастающий отёк/синяк, онемение или резкая боль?\n"
            "Если нет опоры, деформация, сильная нарастающая боль или кровотечение — срочно в травмпункт/103.\n"
            "Если уже получили результаты анализов, загрузите полученные результаты в раздел «Анализы» — я помогу с интерпретацией."
        )
    return (
        "Извините, предыдущий ответ был нерелевантным. Возвращаюсь к вашему медицинскому вопросу.\n"
        + _medical_repair_fallback_response(previous_user_message)
    )


def _build_answer_quality_repair_response(previous_user_message: str) -> str:
    return _domain_specific_repair_response(_repair_domain_key(previous_user_message), previous_user_message)


def _recent_repair_signal_count(chat_history: Optional[list[dict[str, Any]]], current_msg: str) -> int:
    """Сколько подряд последних user-реплик являются сигналом «ответ нерелевантен» (включая текущую)."""
    count = 1 if _is_answer_quality_repair_request(current_msg) else 0
    for row in reversed(chat_history or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "").strip().lower() != "user":
            continue
        txt = str(row.get("content") or "").strip()
        if not txt:
            continue
        if _is_answer_quality_repair_request(txt):
            count += 1
            continue
        break
    return count


def _domain_specific_concise_plan(domain: str, previous_user_message: str) -> str:
    if domain == "endocrine":
        return (
            "Извините. Перехожу к короткому и понятному плану.\n"
            "1) Вероятнее всего: гормональный фактор + дефициты + стресс/сон.\n"
            "2) Анализы 1-й линии: ТТГ, св.Т4, ОАК, ферритин, B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца).\n"
            "3) До результатов: сон 7-8 ч, регулярное питание, умеренная нагрузка, без самоназначения гормонов.\n"
            "4) После результатов — адресная коррекция плана с врачом.\n"
            + _hormone_mood_fatigue_upload_tail()
        )
    if domain == "gastro":
        return (
            "Извините. Перехожу к короткому итоговому плану.\n"
            "1) Проверить связь симптомов с едой/триггерами и исключить обезвоживание.\n"
            "2) База: ОАК, СРБ, биохимия (АЛТ/АСТ/билирубин), по показаниям копрограмма/кал на скрытую кровь.\n"
            "3) Если кровь в стуле, высокая температура, нарастающая боль — срочно очно/103.\n"
            "4) После анализов — точный разбор и следующий шаг.\n"
            "Если уже получили результаты анализов, загрузите полученные результаты в раздел «Анализы» — я помогу с интерпретацией."
        )
    if domain == "cardio":
        return (
            "Извините. Перехожу к короткому итоговому плану.\n"
            "1) Контроль давления и пульса в динамике (2-3 измерения).\n"
            "2) Если боль в груди/одышка в покое/обморок/нарастающая слабость — срочно 103.\n"
            "3) Базово: ЭКГ + очная оценка врача в ближайшие сутки при сохранении жалоб.\n"
            "4) После обследования вернёмся к точной тактике.\n"
            "Если уже получили результаты анализов, загрузите полученные результаты в раздел «Анализы» — я помогу с интерпретацией."
        )
    if domain == "trauma":
        return (
            "Извините. Перехожу к короткому итоговому плану.\n"
            "1) Оценить опору, объём движения, отёк, деформацию, онемение.\n"
            "2) Если нет опоры/деформация/сильная нарастающая боль/кровотечение — срочно травмпункт/103.\n"
            "3) До осмотра: покой, холод, щадящий режим.\n"
            "4) После очной оценки вернёмся к восстановлению по шагам.\n"
            "Если уже получили результаты анализов, загрузите полученные результаты в раздел «Анализы» — я помогу с интерпретацией."
        )
    return (
        "Извините. Перехожу к короткому итоговому плану.\n"
        + _medical_repair_fallback_response(previous_user_message)
    )


def _build_concise_plan_after_frustration(previous_user_message: str) -> str:
    return _domain_specific_concise_plan(_repair_domain_key(previous_user_message), previous_user_message)


def _normalize_suggested_questions_for_context(questions: list[str], known_symptoms_text: str) -> list[str]:
    known = _norm_text_for_compare(known_symptoms_text or "")
    out: list[str] = []
    seen: set[str] = set()
    for q in questions:
        s = str(q or "").strip()
        if not s:
            continue
        if known and _question_repeats_known_symptom(known, s):
            s = _rewrite_followup_for_known_symptom(known, s).strip()
            if not s:
                continue
        key = _norm_text_for_compare(s)
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _common_complaint_structured(
    item: dict[str, Any],
    user_message: str = "",
    chat_history: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    known_symptoms_text = _collect_known_symptoms_text(user_message, chat_history)
    cid = str(item.get("id") or "").strip()
    fh_struct = female_health_extra_structured(cid)
    fatigue_struct = fatigue_extra_structured(cid)
    gi_struct = gi_extra_structured(cid)
    primary_struct = fh_struct or fatigue_struct or gi_struct
    raw_follow = list(item.get("follow_up_questions", []))
    if primary_struct and primary_struct.get("followup_questions"):
        raw_follow = list(primary_struct["followup_questions"] or [])
    suggested_questions = _normalize_suggested_questions_for_context(
        [str(x).strip() for x in raw_follow if str(x).strip()][:6],
        known_symptoms_text,
    )
    suggested_questions = _enforce_domain_question_whitelist(item, user_message, suggested_questions)
    out: dict[str, Any] = {
        "suggested_questions": suggested_questions,
        "action_sequence": [],
        "insufficient_data": False,
        "library_topic": item.get("id"),
        "library_title": item.get("title"),
    }
    if fh_struct:
        out["female_health_scenario"] = fh_struct
    elif fatigue_struct:
        out["fatigue_scenario"] = fatigue_struct
    elif gi_struct:
        out["gi_scenario"] = gi_struct
    return out


def _complaint_from_medical_core_entry(entry: dict[str, Any]) -> dict[str, Any]:
    follow_up = entry.get("follow_up") or {}
    triage = entry.get("triage") or {}
    care = entry.get("care") or {}
    return {
        "id": str(entry.get("entry_id") or "").strip() or "medical_core_overlay",
        "complaint": str(entry.get("name") or "").strip(),
        "name": str(entry.get("name") or "").strip(),
        "category": str(entry.get("category") or "Общая медицина").strip(),
        "description": str(entry.get("description") or "").strip(),
        "anamnesis_questions": [str(x).strip() for x in (follow_up.get("must_ask") or []) if str(x).strip()],
        "must_ask_questions": [str(x).strip() for x in (follow_up.get("must_ask") or []) if str(x).strip()],
        "optional_questions": [str(x).strip() for x in (follow_up.get("optional") or []) if str(x).strip()],
        "red_flags": [str(x).strip() for x in (triage.get("red_flags") or []) if str(x).strip()],
        "red_flags_specific": [str(x).strip() for x in (triage.get("red_flags") or []) if str(x).strip()],
        "suggested_labs": [str(x).strip() for x in (care.get("tests") or []) if str(x).strip()],
        "nutrition_recommendations": [str(x).strip() for x in (care.get("nutrition") or []) if str(x).strip()],
        "physical_exercise_prevention_rehabilitation": [
            str(x).strip() for x in (care.get("activity") or []) if str(x).strip()
        ],
        "source": "medical_core_overlay",
        "urgency_level": str(triage.get("recommended_care_level") or "").strip(),
    }


def _search_complaint_candidates(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    hits = search_complaint_reference(query, top_k=top_k)
    if hits:
        return hits
    bridge_hit = build_bridge_complaint_protocol(query, top_k=top_k)
    if isinstance(bridge_hit, dict):
        return [bridge_hit]
    if MedicalCoreEngine is None:
        return []
    try:
        core_hits = MedicalCoreEngine().find_best_entries(query, limit=top_k)
        complaint_rows = [
            _complaint_from_medical_core_entry(x)
            for x in core_hits
            if isinstance(x, dict) and str(x.get("type") or "") == "complaint"
        ]
        return complaint_rows[:top_k]
    except Exception:
        return []


def _pick_list_text(item: dict[str, Any], keys: list[str], limit: int = 3) -> list[str]:
    out: list[str] = []
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            for v in value:
                s = str(v or "").strip()
                if s:
                    out.append(s)
        elif isinstance(value, str):
            s = value.strip()
            if s:
                out.append(s)
        if out:
            break
    dedup: list[str] = []
    seen: set[str] = set()
    for row in out:
        k = row.lower()
        if k in seen:
            continue
        seen.add(k)
        dedup.append(row)
        if len(dedup) >= max(1, limit):
            break
    return dedup


def _default_clarify_followup_questions() -> list[str]:
    return [
        "Когда начались симптомы и как они меняются?",
        "Что сейчас усиливает симптомы и что хотя бы немного облегчает?",
        "Есть ли сейчас признаки резкого ухудшения (сильная слабость, одышка, нарушение сознания)?",
    ]


def _is_trauma_context_message(message: str) -> bool:
    t = _norm_text_for_compare(message or "")
    if not t:
        return False
    trauma_markers = ("упал", "паден", "удар", "ушиб", "травм", "порез", "рана", "кров", "ссадин", "ожог")
    body_markers = ("колен", "нога", "голен", "ступн", "стоп", "плеч", "локт", "палец", "кисть", "рука", "спин", "шея")
    return any(m in t for m in trauma_markers) and any(b in t for b in body_markers)


def _lower_abdomen_pain_context(t: str) -> bool:
    """Боль/дискомфорт внизу живота или тазовой зоне — нужны пол и возраст для ветвления ЖКТ/гинекология."""
    if not t:
        return False
    if "низ" in t and "живот" in t:
        return True
    if ("внизу" in t or "низу" in t) and "живот" in t:
        return True
    if "поясн" in t and "бол" in t:
        return True
    if "живот" in t and "бол" in t and any(x in t for x in ("низ", "внизу", "низу", "пах", "лобк", "над лобк", "надлобк")):
        return True
    return False


def _extract_sex_from_text(text: str) -> Optional[str]:
    """'male' / 'female' из ответа пользователя; None если не указано."""
    t = _norm_text_for_compare(text or "")
    if not t:
        return None
    if any(
        x in t
        for x in (
            "мужчин",
            "мужик",
            "мужской",
            "я мужчина",
            "мужчина ",
            " мужчина",
        )
    ):
        return "male"
    if any(
        x in t
        for x in (
            "женщин",
            "девушк",
            "девочк",
            "женский",
            "я женщина",
            " женщина",
            "женского пола",
        )
    ):
        return "female"
    return None


def _extract_age_years_from_text(text: str) -> Optional[int]:
    t = _norm_text_for_compare(text or "")
    if not t:
        return None
    for pattern in (
        r"(?:мне|возраст)\s*(\d{1,2})\b",
        r"\b(\d{1,2})\s*лет",
        r"\b(\d{1,2})\s*год",
        r"\b(\d{1,2})\s*года",
    ):
        m = re.search(pattern, t)
        if m:
            try:
                age = int(m.group(1))
                if 1 <= age <= 120:
                    return age
            except ValueError:
                continue
    return None


def _explicit_menstrual_cycle_in_text(t: str) -> bool:
    """Явно указана менструация/цикл (без требования боли в животе)."""
    if not t:
        return False
    cycle_markers = (
        "менстру",
        "менст",
        "предменстру",
        "пмс",
        "месячн",
        "овуляц",
        "дисменор",
        "критическ",
    )
    if any(m in t for m in cycle_markers):
        return True
    if "скоро" in t and any(m in t for m in ("менст", "месяч")):
        return True
    if ("мен" in t and "стру" in t) and any(x in t for x in ("живот", "поясн", "низ")):
        return True
    return False


def _demographic_clarify_questions(known_symptoms_text: str, user_message: str) -> list[str]:
    """При боли внизу живота — уточнить пол и возраст до гинекологических вопросов."""
    combined = _norm_text_for_compare(f"{known_symptoms_text or ''} {user_message or ''}".strip())
    if not _lower_abdomen_pain_context(combined):
        return []
    out: list[str] = []
    if _extract_sex_from_text(combined) is None:
        out.append("Уточните, вы женщина или мужчина — так точнее оценить боль внизу живота.")
    if _extract_age_years_from_text(combined) is None:
        out.append(
            "Сколько вам полных лет? (у девочек до примерно 11–12 лет менструации обычно ещё нет — это важно для трактовки симптомов.)"
        )
    return out[:2]


def _is_menstrual_cycle_lower_abdomen_context(text: str) -> bool:
    """Боль внизу живота в контексте цикла/менструации — не смешивать с острой кишечной инфекцией и «связью с едой»."""
    t = _norm_text_for_compare(text or "")
    if not t:
        return False
    if _extract_sex_from_text(t) == "male":
        return False
    age = _extract_age_years_from_text(t)
    if age is not None and age < 11:
        return False
    has_cycle = _explicit_menstrual_cycle_in_text(t)
    if not has_cycle:
        return False
    belly = any(x in t for x in ("живот", "поясн", "низ", "бол", "тян", "спазм"))
    return belly


def _explicit_non_gyneco_domain_from_user_message(user_message: str) -> Optional[str]:
    """
    Явная смена домена по **тексту пользователя** (не по заголовку карточки библиотеки).
    «Головокружение», общая «боль в груди», размытая слабость без кардио/нейро-маркеров — не считаются.
    """
    text = _norm_text_for_compare(str(user_message or ""))
    if not text:
        return None
    if _is_trauma_context_message(text):
        return "trauma"
    if _is_strong_anorectal_symptom_context(text):
        return "anorectal"
    if _has_respiratory_cluster(str(user_message or "")):
        return "respiratory"
    if any(
        x in text
        for x in (
            "тошн",
            "рвот",
            "диаре",
            "понос",
            "жидкий стул",
            "жидк стул",
            "изжог",
            "жжет желуд",
            "жжет под лож",
            "кишечн инфекц",
            "гастроэнтерит",
            "острый гастрит",
            "острый гастроэнтерит",
        )
    ):
        return "gastro"
    cardio_markers = (
        "пульс",
        "аритм",
        "тахикард",
        "сердцеби",
        "перебои сердц",
        "перебои в сердц",
        "инфаркт",
        "стенокард",
        "за грудин",
        "за груди",
        "грудн клетк жмет",
        "ожог за грудин",
    )
    if any(x in text for x in cardio_markers):
        return "cardio"
    if "давлен" in text and any(
        x in text
        for x in (
            "мм рт",
            "ммрт",
            "артериальн",
            "тоном",
            "гипертон",
            "гипертенз",
            "гипотон",
            "гипотенз",
            "120",
            "130",
            "140",
            "150",
            "160",
            "170",
            "180",
            "190",
            "200",
        )
    ):
        return "cardio"
    if "груд" in text and any(
        x in text
        for x in (
            "давит",
            "жмет",
            "жмёт",
            "сжим",
            "жжет",
            "отдает в лев",
            "отдаёт в лев",
            "отдает в руку",
            "отдаёт в руку",
            "в лопатку",
            "в челюст",
            "простын",
        )
    ):
        return "cardio"
    if "одыш" in text or "не хватает воздух" in text.replace("ё", "е"):
        return "cardio"
    neuro_markers = (
        "мигрен",
        "инсульт",
        "судорог",
        "онемел",
        "онемен",
        "половина тела",
        "половину тела",
        "половина лица",
        "наруш реч",
        "спутан реч",
        "спутанная реч",
        "потерял созн",
        "потеря созн",
        "потеря зр",
        "двоен",
        "двоит",
        "эпилепс",
    )
    if any(x in text for x in neuro_markers):
        return "neuro"
    if any(x in text for x in ("болит голова", "головная боль", "боль в голове", "боль виск", "боль лба", "мигрен")):
        return "neuro"
    if any(x in text for x in ("сыпь", "крапивниц", "аллерг", "ангионеврот")):
        return "allergy_skin"
    if any(x in text for x in ("цистит", "мочеиспуск жжет", "жжет при моч", "кров в моче", "частое мочеиспуск")):
        return "uro"
    return None


def _libido_topic_overrides_respiratory_domain(text: str) -> bool:
    """Реплика явно про либидо — не классифицировать как respiratory из-за слова «кашель» в опровержении."""
    t = _norm_text_for_compare(text or "")
    if not t or "либид" not in t:
        return False
    if any(x in t for x in ("про либид", "либидо спрашива", "делать с либид", "что с либид", "вопрос про либид")):
        return True
    if "кашл" in t and any(x in t for x in ("какой кашель", "не про кашель", "не кашель", "не то кашель")):
        return True
    return False


def _detect_complaint_domain(item: dict[str, Any], user_message: str) -> str:
    text = _norm_text_for_compare((str(item.get("complaint") or item.get("name") or "") + " " + str(user_message or "")).strip())
    if _is_endocrine_asthenic_switch_request(user_message):
        return "general"
    if _is_trauma_context_message(text):
        return "trauma"
    if _is_strong_anorectal_symptom_context(text) or any(
        x in text
        for x in (
            "гемор",
            "геморро",
            "анус",
            "анальн",
            "прямой киш",
            "прямая киш",
            "задний проход",
            "кровь после стула",
            "кровит после стула",
            "боль при дефекац",
        )
    ):
        return "anorectal"
    if _is_menstrual_cycle_lower_abdomen_context(text):
        return "gyneco"
    # Риторическое «какой кашель» при уточнении про либидо не должно включать ОРВИ-шаблон.
    if _libido_topic_overrides_respiratory_domain(text):
        pass
    elif any(x in text for x in ("кашл", "горл", "температ", "насморк", "орви", "простуд", "лихорад", "озноб", "сопл")):
        return "respiratory"
    # Не использовать короткое «киш» — пересекается с «прямой кишки» (аноректальный контекст).
    if any(x in text for x in ("живот", "тошн", "рвот", "диаре", "понос", "стул", "изжог", "кишеч", "желуд")):
        return "gastro"
    if any(x in text for x in ("пульс", "давлен", "сердц", "тахикард", "аритм", "груд")):
        return "cardio"
    if any(x in text for x in ("голов", "головокруж", "мигрен", "онем", "реч", "невр")):
        return "neuro"
    if any(x in text for x in ("сып", "аллер", "зуд", "отек", "кожа")):
        return "allergy_skin"
    if any(x in text for x in ("цистит", "моч", "жжение", "поясниц")):
        return "uro"
    return "general"


def _is_reproductive_metabolic_cluster_user_message(t: str) -> bool:
    """
    Цикл/менструации + метаболические/кожные признаки (ПКО-подобный профиль).
    Не смешивать с «острой болью в животе» (gastro) только из-за слова «живот».
    """
    if not t:
        return False
    cycle = any(
        x in t
        for x in (
            "цикл",
            "месячн",
            "менстру",
            "овуляц",
            "пмс",
            "нерегулярн",
            "перед месячн",
            "задержк",
        )
    )
    metabolic = any(x in t for x in ("вес", "живот", "ожирен", "имт", "инсулин", "слад", "набор вес"))
    androg_skin = any(x in t for x in ("прыщ", "акне", "кож", "волос", "либид", "рост волос"))
    return bool(cycle and (metabolic or androg_skin))


def _is_stress_bloating_without_acute_gi(t: str) -> bool:
    """Стресс + рост/напряжение в животе без острой ЖКТ-картины — не уводить в gastro по одному «живот»."""
    if not t:
        return False
    if not any(x in t for x in ("стресс", "тревог", "нерв", "раздраж")):
        return False
    if not any(x in t for x in ("живот", "брюш", "живота")):
        return False
    if any(x in t for x in ("рвот", "понос", "диаре", "кров в стул", "температур", "лихорад", "остр боль", "нестерпим")):
        return False
    return True


def _coherence_adjust_complaint_score(msg: str, title_n: str) -> float:
    """
    Доп. баллы/штрафы за смысловое соответствие жалобы пользователя и заголовка карточки библиотеки.
    Снижает ложные попадания (анализ крови → цистит; волосы → ОРВИ и т.п.).
    """
    if not msg or not title_n:
        return 0.0
    adj = 0.0

    if any(k in msg for k in ("лимфоцит", "лейкоцит", "тромбоцит", "гемоглобин", "соэ", "анализ кров")):
        if any(k in title_n for k in ("цистит", "мочеиспуск", "пузыр", "почечн", "диабет", "жажд")) and not any(
            k in msg for k in ("моч", "жажд", "цистит", "диабет", "сахар")
        ):
            adj -= 14.0
        if any(k in title_n for k in ("рвот", "понос", "диаре", "кишечн инфекц", "гастроэнтерит")) and not any(
            k in msg for k in ("рвот", "понос", "диаре", "тошн", "жидк стул")
        ):
            adj -= 11.0

    if any(k in msg for k in ("волос", "выпадают", "выпаден", "алопец")):
        if any(k in title_n for k in ("кашл", "горл", "насморк", "орви", "ангин", "фарингит", "мокрот")):
            adj -= 16.0
        if any(k in title_n for k in ("онемен", "нарушен реч", "инсульт", "половин")) and not any(
            k in msg for k in ("онемен", "реч", "слабост", "половин")
        ):
            adj -= 10.0

    if any(k in msg for k in ("похуд", "сбросить вес", "не худею", "вес не уходит", "не могу сбросить", "не сбрасыва")):
        if any(k in title_n for k in ("онемен", "реч", "инсульт", "инфаркт", "сердечн приступ")):
            adj -= 16.0
        if any(k in title_n for k in ("рвот", "понос", "диаре")) and not any(k in msg for k in ("рвот", "понос", "диаре")):
            adj -= 10.0

    if ("плачу" in msg or "плач" in msg or "слез" in msg or "слёз" in msg) and any(
        k in msg for k in ("ребен", "ребён", "младенец", "роды", "родила", "новорожд", "послерод", "после род", "построд", "материн", "радоваться")
    ):
        if any(k in title_n for k in ("жажд", "диабет", "мочеиспуск", "полиур", "щитовид", "ттг", "гипотире", "гипертире", "инсулин", "сахарн")):
            if not any(k in msg for k in ("жажд", "диабет", "ттг", "щитовид", "сахар", "инсулин", "моч", "цистит")):
                adj -= 18.0

    if any(k in msg for k in ("родител", "мама", "папа", "мать", "отец")) and any(
        k in msg for k in ("давят", "требуют", "учись", "сдавай", "анализы", "контролиру", "оценк")
    ):
        if any(k in title_n for k in ("послерод", "новорожд", "младенец", "лимфоцит", "щитовид", "онколог")) and not any(
            k in msg for k in ("роды", "родила", "лимфоцит", "рак", "ребен", "ребён", "щитовид")
        ):
            adj -= 16.0
        if any(k in title_n for k in ("родител", "учеб", "школ", "подрост")):
            adj += 6.0

    if _has_health_anxiety_mortality_fear_query(msg):
        if any(k in title_n for k in ("тревог", "паник", "психолог", "ипохонд", "страх", "смерт")):
            adj += 5.0
        if any(k in title_n for k in ("лимфоцит", "лейкоформул", "цистит", "орви", "кашл")) and not any(
            k in msg for k in ("лимфоцит", "лейкоцит", "моч", "цистит", "кашл")
        ):
            adj -= 12.0

    if _has_prolonged_appetite_loss_query(msg):
        if any(k in title_n for k in ("аппетит", "питан", "жкт", "желуд", "истощен", "похуден")):
            adj += 4.0
        if any(k in title_n for k in ("лимфоцит", "орви", "кашл", "колен")) and not any(k in msg for k in ("лимфоцит", "кашл", "колен")):
            adj -= 10.0

    if _has_premenstrual_mood_sweet_craving_query(msg):
        if any(k in title_n for k in ("месячн", "менстру", "пмс", "цикл", "гинек", "овуляц", "дисменор")):
            adj += 5.0
        if any(k in title_n for k in ("лимфоцит", "орви", "колен", "послерод")) and not any(k in msg for k in ("лимфоцит", "кашл", "колен", "роды")):
            adj -= 10.0

    if _has_chronic_fatigue_months_no_recovery_query(msg):
        if any(k in title_n for k in ("усталост", "слабост", "энерг", "сон", "ферритин", "ттг", "желез", "анем")):
            adj += 4.0
        if any(k in title_n for k in ("цистит", "орви", "колен")) and not any(k in msg for k in ("моч", "цистит", "кашл", "колен")):
            adj -= 8.0

    if _has_adolescent_anhedonia_apathy_query(msg):
        if any(k in title_n for k in ("подросток", "школьн", "психолог", "депресс", "апати")):
            adj += 5.0
        if any(k in title_n for k in ("лимфоцит", "орви", "колен", "менопауз")) and not any(k in msg for k in ("лимфоцит", "кашл", "колен")):
            adj -= 8.0

    if _has_nutrition_supplements_where_to_start_query(msg):
        if any(k in title_n for k in ("пита", "рацион", "добавк", "витамин", "биодобавк", "бады", "диетолог")):
            adj += 5.0
        if any(k in title_n for k in ("лимфоцит", "цистит", "орви")) and not any(k in msg for k in ("лимфоцит", "кашл", "моч")):
            adj -= 8.0

    if _has_gas_bloating_digestion_query(msg):
        if any(k in title_n for k in ("вздут", "газ", "метеоризм", "живот", "кишечник", "пищевар", "жкт", "копрограм")):
            adj += 5.0
        if any(k in title_n for k in ("лимфоцит", "инсульт", "инфаркт")) and not any(k in msg for k in ("лимфоцит", "инсульт", "инфаркт")):
            adj -= 8.0

    if _has_heavy_menstrual_fatigue_hair_loss_query(msg):
        if any(k in title_n for k in ("месячн", "менстру", "обильн", "волос", "ферритин", "ттг", "гинек", "желез", "анем")):
            adj += 6.0
        if any(k in title_n for k in ("лимфоцит", "цистит", "орви")) and not any(k in msg for k in ("лимфоцит", "цистит", "кашл")):
            adj -= 8.0

    if (
        _has_irregular_cycle_women_query(msg)
        or _has_acne_skin_hormonal_women_query(msg)
        or _has_weight_plateau_women_query(msg)
        or _has_hair_loss_diffuse_women_query(msg)
        or _has_persistent_fatigue_women_query(msg)
        or _has_low_mood_apathy_women_query(msg)
        or _has_edema_swelling_women_query(msg)
        or _has_painful_periods_dysmenorrhea_women_query(msg)
        or _has_sweet_craving_standalone_women_query(msg)
    ):
        if any(
            k in title_n
            for k in (
                "гинек",
                "месячн",
                "менстру",
                "цикл",
                "акне",
                "прыщ",
                "высыпан",
                "волос",
                "вес",
                "усталост",
                "апати",
                "отёк",
                "отек",
                "дисменор",
                "сладк",
                "тяга",
            )
        ):
            adj += 4.0
        if any(k in title_n for k in ("лимфоцит", "орви", "ангин")) and not any(k in msg for k in ("лимфоцит", "кашл", "ангин")):
            adj -= 10.0

    if any(k in msg for k in ("счастлив", "плакать", "настроен", "бесит", "тоск", "бессмысл")):
        if any(k in title_n for k in ("онемен", "реч", "инсульт", "слабост в руке")) and not any(
            k in msg for k in ("онемен", "реч", "слабост в руке", "рук", "ног")
        ):
            adj -= 11.0

    if _is_reproductive_metabolic_cluster_user_message(msg):
        if any(k in title_n for k in ("гинек", "овуляц", "менстру", "цикл", "яичник", "андрог", "поликистоз", "пкос")):
            adj += 7.0
        if any(k in title_n for k in ("аппендиц", "кишечн инфекц", "гастроэнтерит", "остр живот")):
            adj -= 12.0

    if any(k in msg for k in ("гимнаст", "спорт", "трениров", "нагрузк")) and any(
        k in msg for k in ("месячн", "менстру", "цикл", "пропал", "нет месячн")
    ):
        if any(k in title_n for k in ("гинек", "менстру", "аменор", "цикл", "яичник", "кост", "энерг")):
            adj += 5.0

    if any(k in msg for k in ("колен", "мениск", "связк колен", "разрыв связок")) or (
        "травм" in msg and "колен" in msg
    ):
        if any(k in title_n for k in ("колен", "мениск", "связк", "сустав", "травм", "ушиб", "опор", "реабилит")):
            adj += 9.0

    if any(k in msg for k in ("правильн пит", "добавк", "омега", "витамин")) and "врач" not in title_n:
        if any(k in title_n for k in ("питан", "рацион", "диет", "витамин", "добавк", "омега")):
            adj += 4.0

    return adj


def _effective_complaint_domain(item: dict[str, Any], user_message: str) -> str:
    """Домен с учётом респираторного кластера и явной аноректальной симптоматики в тексте пользователя."""
    um_raw = _norm_text_for_compare(str(user_message or ""))
    item_id_early = str((item or {}).get("id") or "").strip()

    # Библиотека female_health (complaint ↔ scenario): не расширять домен по заголовку карточки и «мягким» симптомам реплики.
    # В другие справочники (кардио/нейро/ЖКТ и т.д.) — только при явных маркерах в тексте пользователя.
    if item_id_early in _FEMALE_HEALTH_LIBRARY_COMPLAINT_IDS and _extract_sex_from_text(um_raw) != "male":
        alt = _explicit_non_gyneco_domain_from_user_message(user_message)
        domain = alt if alt is not None else "gyneco"
    else:
        domain = _detect_complaint_domain(item, user_message)
        if _has_respiratory_cluster(user_message):
            domain = "respiratory"
        if _is_strong_anorectal_symptom_context(str(user_message or "")):
            domain = "anorectal"
        um = _norm_text_for_compare(str(user_message or ""))
        if _is_menstrual_cycle_lower_abdomen_context(um):
            domain = "gyneco"
        if _is_reproductive_metabolic_cluster_user_message(um) and _extract_sex_from_text(um) != "male":
            domain = "gyneco"
        if domain == "gastro" and _is_stress_bloating_without_acute_gi(um):
            domain = "general"
    # Мужчине не держим гинекологический домен даже при ложных срабатываниях по тексту жалобы.
    um = _norm_text_for_compare(str(user_message or ""))
    if domain == "gyneco" and _extract_sex_from_text(um) == "male":
        domain = _detect_complaint_domain(item, user_message)
        if _has_respiratory_cluster(user_message):
            domain = "respiratory"
        if _is_strong_anorectal_symptom_context(str(user_message or "")):
            domain = "anorectal"
    return domain


def _clarify_answers_section_present(text: str) -> bool:
    return "уточнения в диалоге" in str(text or "").lower()


def _clarify_log_supports_anorectal(text: str) -> bool:
    """Ответы в блоке уточнений подтверждают аноректальный источник крови/боли."""
    if not _clarify_answers_section_present(text):
        return False
    tn = _norm_text_for_compare(text)
    if any(x in tn for x in ("ярко", "красн", "алая")) and any(x in tn for x in ("бумаг", "унитаз", "стул", "дефекац", "туалет")):
        return True
    if any(x in tn for x in ("гемор", "трещин", "анальн", "задн проход", "анус", "узел")) and any(
        x in tn for x in ("да", "ест", "скорее", "именно", "похож", "вероятн")
    ):
        return True
    if "дефекац" in tn and ("кров" in tn or "бол" in tn) and any(x in tn for x in ("да", "сильн", "очень", "есть", "резк")):
        return True
    return False


def _clarify_log_supports_uro(text: str) -> bool:
    if not _clarify_answers_section_present(text):
        return False
    tn = _norm_text_for_compare(text)
    if not any(x in tn for x in ("моч", "мочеиспуск", "цистит", "уролог", "пузыр", "уретр")):
        return False
    return any(x in tn for x in ("кров в моче", "кровь в моче", "жжен при моч", "жжет при моч", "резь при моч", "частое мочеиспуск"))


def _blood_source_location_unclear(raw: str) -> bool:
    tn = _norm_text_for_compare(raw or "")
    # Avoid false positives like "с кровати": this is not bleeding context.
    tokens = re.findall(r"[a-zа-яё0-9\-]+", tn)
    has_blood_context = any(tok.startswith("кров") and not tok.startswith("кроват") for tok in tokens)
    if not has_blood_context:
        return False
    return not any(
        x in tn
        for x in (
            "носов",
            " из нос",
            "нос кров",
            "кашлем",
            "кашель",
            "моче",
            "мочи",
            "стул",
            "дефекац",
            "задн",
            "анус",
            "бумаг",
            "унитаз",
            "рвот",
            "во рту",
            "горл",
            "менстру",
            "месячн",
        )
    )


def _complaint_diagnostic_ambiguous(item: dict[str, Any], user_message: str) -> bool:
    """Недостаточно данных для уверенного домена — задаём наводящий вопрос до финала."""
    msg = _norm_text_for_compare(user_message or "")
    if not msg:
        return False
    domain = _effective_complaint_domain(item, user_message)
    if _blood_source_location_unclear(str(user_message or "")):
        return True
    vague_markers = ("что то", "что-то", "не понима", "непонят", "странно", "случилось", "не знаю", "непонятно", "не пойму")
    short = len(msg.split()) <= 16
    if domain == "general" and short and any(v in msg for v in vague_markers):
        return True
    if domain == "gastro" and "живот" in msg:
        if _is_menstrual_cycle_lower_abdomen_context(msg):
            return False
        localized = any(
            x in msg for x in ("справа", "слева", "пупк", "эпигастр", "подреб", "вверху", "внизу", "над пуп", "под лож", "лев подреб", "прав подреб")
        )
        return (not localized) and len(msg.split()) <= 20
    return False


def _diagnostic_fork_questions_for_ambiguity(item: dict[str, Any], user_message: str) -> list[str]:
    if not _complaint_diagnostic_ambiguous(item, user_message):
        return []
    raw = str(user_message or "")
    msg = _norm_text_for_compare(raw)
    forks: list[str] = []
    if _blood_source_location_unclear(raw):
        forks.append(
            "Чтобы отличить источник кровотечения, ответьте коротко: кровь видите при кашле/во рту, из носа, "
            "в моче или на туалетной бумаге/в воде унитаза после дефекации?"
        )
    domain = _effective_complaint_domain(item, user_message)
    if len(forks) < 2 and domain == "gastro" and "живот" in msg:
        forks.append(
            "Где боль в животе сильнее всего: вверху под ложечкой, вокруг пупка или внизу (справа/слева/по всему низу)?"
        )
    if not forks:
        forks.append(
            "Что из перечисленного есть сейчас (можно кратко «да/нет» по пунктам): температура, насморк или боль в горле, "
            "тошнота/рвота/жидкий стул, сыпь, боль или жжение при мочеиспускании, ярко-алая кровь на бумаге после стула?"
        )
    return forks[:2]


def _prepend_unique_fork_questions(queue: list[str], forks: list[str]) -> list[str]:
    seen = {_norm_text_for_compare(str(q)) for q in queue if str(q).strip()}
    merged: list[str] = []
    for f in forks:
        fs = str(f or "").strip()
        if not fs:
            continue
        fk = _norm_text_for_compare(fs)
        if fk in seen:
            continue
        merged.append(fs)
        seen.add(fk)
    return merged + [str(q).strip() for q in queue if str(q).strip()]


def _refine_domain_from_clarified_history(user_message: str, domain: str) -> str:
    """После ответов на уточнения — скорректировать домен (геморрой/цистит и т.д.)."""
    raw = str(user_message or "").strip()
    if not raw:
        return domain
    if _clarify_log_supports_anorectal(raw) or _is_strong_anorectal_symptom_context(raw):
        return "anorectal"
    if _clarify_log_supports_uro(raw):
        return "uro"
    if domain == "general" and _clarify_answers_section_present(raw) and _has_respiratory_cluster(raw):
        tn = _norm_text_for_compare(raw)
        if any(x in tn for x in ("насморк", "горл", "кашл", "сопл")) and any(x in tn for x in ("да", "ест", "именно", "появ")):
            return "respiratory"
    return domain


def _looks_like_high_fever(text: str) -> bool:
    t = _norm_text_for_compare(text or "")
    if not t:
        return False
    if any(x in t for x in ("высокая температура", "температура 40", "температура 39", "темп 40", "темп 39")):
        return True
    # Примеры: "температура 40", "t 39.5", "39,2"
    nums = re.findall(r"(?<!\d)(3[9]|4[0-2])([.,]\d)?(?!\d)", t)
    return bool(nums) and ("температ" in t or "t " in t or "жар" in t)


def _has_respiratory_cluster(text: str) -> bool:
    t = _norm_text_for_compare(text or "")
    if not t:
        return False
    # Отрицания симптомов не должны включать респираторный кластер:
    # «кашель/горло/одышка тут ни при чем», «не про кашель».
    if any(
        x in t
        for x in (
            "не про каш",
            "не про горл",
            "не про одыш",
            "кашел ни при чем",
            "кашель ни при чем",
            "кашель не при чем",
            "боль в горле ни при чем",
            "горло ни при чем",
            "одышка ни при чем",
            "одышка не при чем",
            "никаких температур",
            "температуры не было",
            "температуры нет",
        )
    ):
        return False
    has_cough = any(x in t for x in ("кашл", "кашел"))
    has_runny_nose = any(x in t for x in ("насморк", "сопл", "заложен нос"))
    has_fever = any(x in t for x in ("температ", "лихорад", "озноб", "жар")) or _looks_like_high_fever(t)
    # Достаточно двух из трёх признаков, чтобы не уходить в общий/невро fallback.
    score = int(has_cough) + int(has_runny_nose) + int(has_fever)
    return score >= 2


def _is_endocrine_asthenic_switch_request(text: str) -> bool:
    """Принудительный переход в эндокринно-астенический сценарий для гормоны+усталость+перепады настроения."""
    t = _norm_text_for_compare(text or "")
    if not t:
        return False
    has_hormonal = any(x in t for x in ("гормон", "щитовид", "эндокрин", "пролактин", "ттг"))
    has_fatigue_or_mood = any(
        x in t
        for x in (
            "устал",
            "слабост",
            "нет сил",
            "энерг",
            "настроен",
            "перепад",
            "скачет",
            "апат",
            "тревог",
            "раздраж",
        )
    )
    if not (has_hormonal and has_fatigue_or_mood):
        return False
    # Пользователь явно отрицает респираторный контекст.
    if any(
        x in t
        for x in (
            "не про каш",
            "не про температур",
            "кашель ни при чем",
            "кашель не при чем",
            "температуры нет",
            "температуры не было",
            "не было температуры",
        )
    ):
        return True
    return True


def _user_constitutional_fatigue_primary(user_message: str) -> bool:
    """
    Доминирующая жалоба на усталость/астению без явного респираторного кластера.
    Нужна, чтобы не отправлять такие реплики в офлайн-библиотеку ОРВИ (там нет LLM-промпта Михаила).
    """
    t = _norm_text_for_compare(user_message or "")
    if not t:
        return False
    # Обильные месячные + усталость/волосы — отдельный клинический маршрут (дефицит железа и др.), не «общая астения».
    if _has_heavy_menses_iron_priority_context(t):
        return False
    fatigue_markers = (
        "устал",
        "усталы",
        "устав",  # уставший / уставшими (часто без подстроки «устал»)
        "нет сил",
        "ничего не хочется",
        "не хочется",
        "неохота",
        "не охота",
        "лень встать",
        "лень вставать",
        "апат",
        "вял",
        "разбит",
        "сонлив",
        "встать тяжело",
        "вставать тяжело",
        "тяжело встать",
        "нет энерг",
        "выгорел",
    )
    if not any(m in t for m in fatigue_markers):
        return False
    if _has_respiratory_cluster(user_message):
        return False
    if any(
        w in t
        for w in (
            "кашл",
            "кашел",
            "насморк",
            "сопл",
            "ангин",
            "фаринг",
            "мокрот",
            "боль в горле",
            "горло бол",
            "озноб",
            "лихорад",
            "простуд",
            "орви",
            "грипп",
        )
    ):
        return False
    # «Температура / жар» без отрицания — скорее инфекционный контекст.
    if ("температ" in t or " жар" in t or "жар," in t or "жар." in t) and not any(
        x in t
        for x in (
            "нет температур",
            "не было температур",
            "температур нет",
            "температуры нет",
            "температуры не было",
            "без температур",
            "без жара",
            "температ не было",
        )
    ):
        return False
    return True


def _constitutional_fatigue_thread_probe(
    user_message: str,
    chat_history: Optional[list[Any]] = None,
    *,
    max_turns: int = 12,
) -> str:
    """Текущая реплика + последние user-тёрны — чтобы «несколько дней» не теряло якорь «усталость/апатия»."""
    parts: list[str] = [str(user_message or "").strip()]
    if isinstance(chat_history, list):
        collected: list[str] = []
        for entry in reversed(chat_history):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or "").lower() != "user":
                continue
            c = str(entry.get("content") or "").strip()
            if not c:
                continue
            collected.append(c)
            if len(collected) >= max_turns:
                break
        parts.extend(reversed(collected))
    return _norm_text_for_compare("\n".join(p for p in parts if p))


def _constitutional_fatigue_thread_active(user_message: str, chat_history: Optional[list[Any]] = None) -> bool:
    blob = _constitutional_fatigue_thread_probe(user_message, chat_history)
    return bool(blob) and _user_constitutional_fatigue_primary(blob)


def _user_text_blob_for_constitutional_probe(
    msg: str,
    chat_history: Any,
    *,
    max_user_turns: int = 5,
    max_chars: int = 1200,
) -> str:
    """Текущая реплика + последние сообщения пользователя — чтобы короткие ответы не теряли контекст усталости."""
    parts: list[str] = [str(msg or "").strip()]
    if isinstance(chat_history, list):
        collected: list[str] = []
        for entry in reversed(chat_history):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or "").lower() != "user":
                continue
            c = str(entry.get("content") or "").strip()
            if not c:
                continue
            collected.append(c)
            if len(collected) >= max_user_turns:
                break
        parts.extend(reversed(collected))
    blob = "\n".join(p for p in parts if p)
    if len(blob) > max_chars:
        return blob[:max_chars]
    return blob


def _complaint_library_hit_mismatch_constitutional_fatigue(user_message: str, item: dict[str, Any]) -> bool:
    """
    Любая справочная карточка при доминирующей жалобе на усталость/астению — пропускаем библиотеку (идём в LLM/RAG).
    Иначе «general»/нерелевантные хиты дают респираторные вопросы и шаблон ОРВИ без вызова модели.
    """
    return isinstance(item, dict) and _user_constitutional_fatigue_primary(user_message)


def _complaint_library_hit_mismatch_pleuritic_chest_dyspnea(user_blob: str, item: dict[str, Any]) -> bool:
    """
    Боль в груди при глубоком вдохе + нехватка воздуха — эталонный безопасный ответ из composer;
    справочник часто даёт нерелевантный первый шаг («давление/пульс»).
    """
    if not isinstance(item, dict):
        return False
    try:
        from app.services.clinical_extractor import extract_clinical_evidence
    except Exception:
        return False
    ext = extract_clinical_evidence(str(user_blob or "").strip())
    return str(ext.get("primary_scope") or "").strip() == "pleuritic_chest_dyspnea"


def _complaint_library_hit_mismatch_weight_loss_plateau(user_blob: str, item: dict[str, Any]) -> bool:
    """Длительное плато веса — эталон из composer; библиотека может дать нерелевантную карточку."""
    if not isinstance(item, dict):
        return False
    try:
        from app.services.clinical_extractor import extract_clinical_evidence
    except Exception:
        return False
    ext = extract_clinical_evidence(str(user_blob or "").strip())
    return str(ext.get("primary_scope") or "").strip() == "weight_loss_plateau"


def _looks_like_sputum_context(text: str) -> bool:
    t = _norm_text_for_compare(text or "")
    if not t:
        return False
    return any(x in t for x in ("мокрот", "кашель с мокрот", "желтоват", "желт", "густая мокрота"))


def _build_high_fever_respiratory_final_response(user_message: str) -> str:
    msg = _norm_text_for_compare(user_message or "")
    has_sputum = _looks_like_sputum_context(msg)
    bacterial_line = (
        "— возможно: присоединение бактериальной инфекции (учитывая мокроту)"
        if has_sputum
        else "— возможно: присоединение бактериальной инфекции"
    )
    lines = [
        "Похоже на выраженную инфекцию дыхательных путей с высокой температурой.",
        "",
        "Температура 40°C — это уже серьезная нагрузка на организм, даже если она временно снижается.",
        "",
        "Что вероятнее всего:",
        "— чаще всего: тяжелая вирусная инфекция (ОРВИ)",
        bacterial_line,
        "",
        "Риск сейчас: выше среднего",
        "",
        "Что делать сейчас:",
        "— продолжайте сбивать температуру, если она выше 38.5 и плохо переносится",
        "— пейте больше жидкости (это важно при высокой температуре)",
        "— отдых, не перегружаться",
        "— проветривайте помещение",
        "",
        _medication_block_intro_similar_cases(),
        "— жаропонижающие/обезболивающие (например, парацетамол или ибупрофен) при температуре выше 38.5",
        "— местные средства для горла (полоскания, пастилки/спреи) по инструкции",
        "— солевые растворы для носа при заложенности",
        _rx_only_medication_footer(),
        "",
        "Важно:",
        "если температура снова поднимается до 39-40 в течение нескольких часов — это повод для очного осмотра врача",
        "",
        "Обратиться к врачу нужно в ближайшее время, если:",
        "— температура держится выше 39 больше суток",
        "— становится хуже",
        "— усиливается кашель или появляется сильная слабость",
        "",
        "Срочно вызывайте помощь, если:",
        "— температура не сбивается или быстро возвращается",
        "— появляется одышка или трудно дышать",
        "— выраженная слабость, предобморочное состояние",
        "",
        "В вашем случае это уже не легкая простуда, лучше не затягивать с очным осмотром.",
    ]
    return "\n".join(lines)


def _detect_trauma_subdomain(text: str) -> str:
    t = _norm_text_for_compare(text or "")
    if any(x in t for x in ("колен",)):
        return "knee"
    if any(x in t for x in ("голеностоп", "лодыж", "стоп", "ступн")):
        return "ankle_foot"
    if any(x in t for x in ("плеч", "локт", "предплеч")):
        return "shoulder_elbow"
    if any(x in t for x in ("палец", "пальц", "кисть", "ладон", "запяст", "рука")):
        return "hand_finger"
    if any(x in t for x in ("глаз", "веко", "роговиц")):
        return "eye"
    if any(x in t for x in ("голов", "затыл", "висок", "череп", "сотряс")):
        return "head"
    if any(x in t for x in ("спин", "поясниц", "шея")):
        return "back_neck"
    return "general_trauma"


_TRAUMA_SUBDOMAIN_WHITELIST: dict[str, tuple[str, ...]] = {
    "knee": ("колен", "сгиб", "разгиб", "наступ", "опор", "отек", "синяк", "нестаб", "боль", "ссад", "кров"),
    "ankle_foot": ("голеностоп", "лодыж", "стоп", "ступн", "наступ", "опор", "отек", "синяк", "боль"),
    "shoulder_elbow": ("плеч", "локт", "поднят", "согн", "движен", "деформац", "отек", "боль"),
    "hand_finger": ("кисть", "палец", "пальц", "ладон", "запяст", "сгиб", "разгиб", "чувств", "онем", "рана", "кров"),
    "head": ("голов", "созн", "тошн", "рвот", "зрение", "сонлив", "спутан", "амнез"),
    "eye": ("глаз", "веко", "зрение", "боль", "светобоязн", "слез", "кров"),
    "back_neck": ("спин", "поясниц", "шея", "онем", "слабост", "прострел", "движен", "боль"),
    "general_trauma": ("травм", "рана", "кров", "ушиб", "отек", "боль", "опор", "движен"),
}


def _question_matches_domain(question: str, domain: str) -> bool:
    q = _norm_text_for_compare(question or "")
    if not q:
        return False
    if domain == "general":
        return True
    if domain == "trauma":
        return any(x in q for x in ("травм", "упал", "рана", "кров", "ссад", "отек", "сгиб", "наступ", "движен", "боль", "опор"))
    if domain == "respiratory":
        return any(x in q for x in ("кашл", "мокрот", "горл", "глот", "температ", "озноб", "одыш", "насморк", "сопл", "дыхан"))
    if domain == "gastro":
        return any(x in q for x in ("живот", "тошн", "рвот", "стул", "понос", "диаре", "изжог", "пищ", "обезвож"))
    if domain == "cardio":
        return any(x in q for x in ("давлен", "пульс", "сердц", "груд", "одыш", "обмор"))
    if domain == "neuro":
        return any(x in q for x in ("голов", "реч", "онем", "слабост", "головокруж", "зрение", "сознан"))
    if domain == "allergy_skin":
        return any(
            x in q
            for x in (
                "сып",
                "зуд",
                "отек",
                "аллер",
                "губ",
                "язык",
                "дыхан",
                "триггер",
                "гистамин",
                "неперенос",
                "после еды",
                "молоч",
                "сыр",
                "творог",
                "антигистамин",
            )
        )
    if domain == "uro":
        return any(x in q for x in ("моч", "жжен", "поясниц", "температ", "боль", "цистит"))
    if domain == "gyneco":
        return any(
            x in q
            for x in (
                "менстру",
                "цикл",
                "месячн",
                "овуляц",
                "беремен",
                "задерж",
                "выделен",
                "низ живот",
                "внизу живот",
                "спазм",
                "температ",
                "тошн",
                "рвот",
            )
        )
    if domain == "anorectal":
        qn = _norm_text_for_compare(question or "")
        # «Зуд» без проктологического контекста совпадает с аллерго-вопросами — отсекаем.
        peri = ("анус", "прям", "задн", "дефекац", "стул", "гемор", "узел", "трещин", "проктолог")
        if "зуд" in qn and not any(x in qn for x in peri):
            return False
        if any(x in qn for x in ("сып", "свистящ", "отек губ", "отек языка", "аллерг")) and not any(x in qn for x in peri):
            return False
        return any(
            x in qn
            for x in (
                "кров",
                "стул",
                "дефекац",
                "анус",
                "прямой киш",
                "узел",
                "зуд",
                "жжен",
                "боль",
                "запор",
            )
        )
    return True


def _enforce_domain_question_whitelist(item: dict[str, Any], user_message: str, questions: list[str]) -> list[str]:
    domain = _effective_complaint_domain(item, user_message)
    if domain == "trauma":
        subdomain = _detect_trauma_subdomain((str(item.get("complaint") or item.get("name") or "") + " " + str(user_message or "")).strip())
        tokens = _TRAUMA_SUBDOMAIN_WHITELIST.get(subdomain, _TRAUMA_SUBDOMAIN_WHITELIST["general_trauma"])
        filtered = [q for q in questions if any(tok in _norm_text_for_compare(q) for tok in tokens)]
    else:
        filtered = [q for q in questions if _question_matches_domain(q, domain)]
    if filtered:
        return filtered[:3]
    # Fallback: domain-safe defaults instead of leaking off-domain questions (e.g. cardio in respiratory flow).
    domain_defaults: dict[str, list[str]] = {
        "respiratory": [
            "Температура сбивается после жаропонижающего и на сколько часов хватает эффекта?",
            "Мокрота сейчас какого цвета и стала ли ее больше за сутки?",
            "Есть ли одышка в покое или становится труднее дышать?",
        ],
        "gastro": [
            "Боль в животе нарастает или держится на одном уровне?",
            "Есть ли повторная рвота, кровь в стуле или признаки обезвоживания?",
        ],
        "cardio": [
            "Какое сейчас давление и пульс (2 измерения с интервалом 5-10 минут)?",
            "Есть ли давящая боль в груди более 10 минут или одышка в покое?",
        ],
        "neuro": [
            "Головная боль нарастает или держится на одном уровне?",
            "Есть ли онемение, слабость в руке/ноге или нарушение речи?",
        ],
        "allergy_skin": [
            "Есть ли отек губ/языка или затруднение дыхания?",
            "Есть ли связь симптомов с новым продуктом/лекарством/средством ухода?",
        ],
        "uro": [
            "Есть ли температура, боль в пояснице или кровь в моче?",
            "Симптомы усиливаются при мочеиспускании или сохраняются весь день?",
        ],
        "gyneco": [
            "Боль связана с началом месячных или усиливается накануне/в первые дни цикла?",
            "Есть ли необычно обильные выделения, резкий запах, температура или подозрение на беременность/задержку?",
            "Боль симметричная или сильнее с одной стороны внизу живота?",
        ],
        "anorectal": [
            "Кровь ярко-красная и появляется после стула?",
            "Есть ли сильная боль при дефекации или выраженная слабость/головокружение?",
        ],
        "trauma": [
            "Кровотечение остановилось после прижатия 10-15 минут?",
            "Есть ли нарастающий отек, деформация или резкая боль при движении?",
        ],
        "general": _default_clarify_followup_questions(),
    }
    defaults = domain_defaults.get(domain, domain_defaults["general"])
    return defaults[:3]


def _collect_known_symptoms_text(user_message: str, chat_history: Optional[list[dict[str, Any]]] = None) -> str:
    parts: list[str] = [_norm_text_for_compare(user_message or "")]
    if isinstance(chat_history, list):
        # Read only recent user turns to avoid stale long-ago symptoms.
        for row in chat_history[-12:]:
            if not isinstance(row, dict):
                continue
            role = str(row.get("role") or row.get("sender") or "").strip().lower()
            if role != "user":
                continue
            text = str(row.get("message") or row.get("content") or row.get("text") or "").strip()
            if text:
                parts.append(_norm_text_for_compare(text))
    return " ".join(p for p in parts if p).strip()


def _get_clarify_followup_question_queue(
    item: dict[str, Any],
    user_message: str,
    chat_history: Optional[list[dict[str, Any]]] = None,
) -> list[str]:
    if _is_endocrine_asthenic_switch_request(user_message):
        sex = _extract_sex_from_text(user_message or "")
        endocrine_queue = [
            "Когда начались перепады настроения и усталость, что усиливает и что облегчает симптомы?",
            "Как со сном: трудно уснуть, частые пробуждения, есть ли ощущение «не восстановился» утром?",
            "Есть ли изменения веса, аппетита, потливости, сердцебиения или непереносимости холода/жары?",
            "Сдавали ли ТТГ/св.Т4, ферритин, B12, витамин D, глюкозу и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца), были ли отклонения?",
        ]
        if sex == "female":
            endocrine_queue.insert(
                3,
                "Есть ли изменения цикла/ПМС (задержки, нерегулярность, усиление симптомов перед менструацией)?",
            )
        return endocrine_queue[:6]
    known_symptoms_text = _collect_known_symptoms_text(user_message, chat_history)
    followups = _contextual_followup_questions(item, user_message, known_symptoms_text=known_symptoms_text)
    queue = followups if followups else _default_clarify_followup_questions()
    queue = _enforce_domain_question_whitelist(item, user_message, queue)
    forks = _diagnostic_fork_questions_for_ambiguity(item, user_message)
    if forks:
        queue = _prepend_unique_fork_questions(queue, forks)
    demo = _demographic_clarify_questions(known_symptoms_text, user_message)
    if demo:
        queue = _prepend_unique_fork_questions(queue, demo)
    return queue[:6]


def _food_trigger_reference_context(user_message: str) -> dict[str, Any]:
    """Легкое обогащение из food/histamine справочников для гипотез и follow-up."""
    text = str(user_message or "").strip()
    if not text:
        return {}
    tnorm = _norm_text_for_compare(text)
    if _is_menstrual_cycle_lower_abdomen_context(tnorm):
        return {}
    if _is_strong_anorectal_symptom_context(tnorm):
        return {}
    # Не использовать короткие «отек»/«зуд» — ложные совпадения с «протекла кровь» и др.
    markers = (
        "после еды",
        "поел",
        "творог",
        "сыр",
        "кефир",
        "молок",
        "семеч",
        "орех",
        "аллер",
        "сып",
        "отек губ",
        "отек язык",
        "гистамин",
    )
    if not any(m in tnorm for m in markers):
        return {}
    try:
        from app.services.food_triggers_lookup import build_food_trigger_context

        ctx = build_food_trigger_context(text)
        return ctx if isinstance(ctx, dict) else {}
    except Exception:
        return {}


def _is_food_trigger_context_message(message: str) -> bool:
    msg = _norm_text_for_compare(message or "")
    if not msg:
        return False
    markers = (
        "после еды",
        "поел",
        "съел",
        "семеч",
        "орех",
        "творог",
        "сыр",
        "кефир",
        "молок",
        "йогурт",
        "гистамин",
        "неперенос",
        "пищев",
    )
    return any(m in msg for m in markers)


def _should_inline_urgent_for_clarify(user_message: str, red_flags: list[str]) -> bool:
    msg = _norm_text_for_compare(user_message or "")
    return any(
        m in msg
        for m in (
            "одыш",
            "нехватк воздух",
            "боль в груди",
            "слабость в руке",
            "нарушение речи",
            "обмор",
            "кровотеч",
            "созн",
            "онем",
        )
    )


def _question_repeats_known_symptom(msg: str, question: str) -> bool:
    q = _norm_text_for_compare(question or "")
    if not q:
        return False
    # Отрицание в ответе пользователя: симптом упомянут, но явно отвергнут.
    negated_respiratory = any(
        x in msg
        for x in (
            "ни при чем",
            "не при чем",
            "не при чём",
            "не про каш",
            "не про горл",
            "не про одыш",
            "кашель не",
            "кашля нет",
            "горло не",
            "горло не бол",
            "одышки нет",
            "температуры нет",
            "температуры не было",
            "не было температуры",
        )
    )
    # Do not re-ask if the symptom is already explicitly present in user message.
    if ("кашл" in q or "кашел" in q) and ("кашл" in msg or "кашел" in msg) and not negated_respiratory:
        return True
    if ("мокрот" in q) and ("мокрот" in msg):
        return True
    if ("одыш" in q or "нехватк воздух" in q) and ("одыш" in msg or "нехватк воздух" in msg) and not negated_respiratory:
        return True
    if ("горл" in q or "глот" in q) and ("горл" in msg or "глот" in msg) and not negated_respiratory:
        return True
    if ("температур" in q or "лихорад" in q or "жар" in q) and (
        "температур" in msg or "лихорад" in msg or "жар" in msg
    ) and not negated_respiratory:
        return True
    if ("насморк" in q or "сопл" in q or "заложен" in q) and (
        "насморк" in msg or "сопл" in msg or "заложен" in msg
    ):
        return True
    if ("голов" in q) and ("голов" in msg):
        return True
    if "женщин" in q and "мужчин" in q and _extract_sex_from_text(msg):
        return True
    if ("полных лет" in q or "сколько вам" in q) and _extract_age_years_from_text(msg) is not None:
        return True
    if "лет" in q and "девоч" in q and _extract_age_years_from_text(msg) is not None:
        return True
    return False


def _rewrite_followup_for_known_symptom(msg: str, question: str) -> str:
    q = _norm_text_for_compare(question or "")
    if not q:
        return ""
    # If symptom is already known, ask about dynamics/severity/risks.
    if ("кашл" in q or "кашел" in q) and ("кашл" in msg or "кашел" in msg):
        if "мокрот" in msg:
            return "Мокрота сейчас какого цвета и стала ли ее больше за сутки?"
        return "Кашель усиливается ночью или примерно одинаковый в течение дня?"
    if ("температур" in q or "лихорад" in q or "жар" in q) and ("температур" in msg or "жар" in msg):
        return "Если использовали жаропонижающие, температура падает?\nНа сколько времени хватает эффекта?"
    if ("горл" in q or "глот" in q) and ("горл" in msg or "глот" in msg):
        return "По горлу сейчас больнее при глотании и не стало ли труднее пить?"
    if ("одыш" in q or "нехватк воздух" in q) and ("одыш" in msg or "нехватк воздух" in msg):
        return "Одышка появляется в покое или только при разговоре/ходьбе?"
    if ("насморк" in q or "сопл" in q or "заложен" in q) and ("насморк" in msg or "сопл" in msg or "заложен" in msg):
        return "По насморку: выделения прозрачные или стали густыми/желтыми?"
    if ("голов" in q) and ("голов" in msg):
        return "Головная боль сейчас нарастает или держится на одном уровне?"
    return ""


def _contextual_followup_questions(
    item: dict[str, Any],
    user_message: str,
    *,
    known_symptoms_text: str = "",
) -> list[str]:
    msg = _norm_text_for_compare(user_message or "")
    known = _norm_text_for_compare(known_symptoms_text or msg)
    is_trauma_context = _is_trauma_context_message(msg)
    base = [] if is_trauma_context else _pick_list_text(item, ["must_ask_questions", "anamnesis_questions", "optional_questions"], limit=6)
    questions: list[str] = []

    if is_trauma_context:
        if any(x in msg for x in ("колен", "нога", "голен", "ступн", "стоп")):
            questions.extend(
                [
                    "Сгибается ли колено полностью или есть блок/резкая боль при сгибании?",
                    "Можете ли наступать на ногу хотя бы несколько шагов без резкой боли?",
                    "Быстро ли нарастает отек, синяк или ощущение нестабильности в суставе?",
                    "Кровотечение из ссадины остановилось за 10-15 минут при прижатии?",
                ]
            )
        elif any(x in msg for x in ("плеч", "локт", "рука", "кисть", "палец")):
            questions.extend(
                [
                    "Получается ли двигать конечностью в полном объеме или движение резко ограничено?",
                    "Есть ли онемение, покалывание или слабость в пальцах?",
                    "Есть ли деформация, нарастающий отек или сильная боль при опоре/движении?",
                ]
            )
        elif any(x in msg for x in ("спин", "шея")):
            questions.extend(
                [
                    "Боль отдает в руку/ногу, есть онемение или слабость?",
                    "Усиливается ли боль при движении и мешает ли ходить/поворачиваться?",
                    "Есть ли нарушение мочеиспускания или выраженная слабость в конечностях?",
                ]
            )
        else:
            questions.extend(
                [
                    "Есть ли сейчас резкая боль при движении или опоре на травмированную область?",
                    "Быстро ли нарастает отек/синяк или ограничение движения?",
                    "Кровотечение остановилось при прижатии за 10-15 минут?",
                ]
            )

    # Case: headache + flushing/face heat + pulse/tachycardia
    if ("голов" in msg) and (("пульс" in msg) or ("сердц" in msg) or ("лицо гор" in msg) or ("жар" in msg)):
        questions.extend(
            [
                "Какое сейчас давление и пульс (желательно 2 измерения с интервалом 5-10 минут)?",
                "Были ли сегодня перегрев (солнце, баня/парилка), интенсивная нагрузка или сильный стресс?",
                "Была ли травма головы в последние дни?",
                "Есть ли тошнота, нарушение речи, онемение, слабость в руке/ноге или боль в груди?",
                "После отдыха и воды становится легче или без изменений?",
            ]
        )

    # Case: цикл/менструация и боль внизу живота — прицельные вопросы, не «связь с едой» (только не для мужчин).
    if _extract_sex_from_text(known) != "male" and _is_menstrual_cycle_lower_abdomen_context(known):
        questions.extend(
            [
                "Боль симметричная внизу живота или сильнее с одной стороны; есть ли задержка месячных или подозрение на беременность?",
                "Есть ли температура, выраженная слабость, обильные необычные выделения с запахом, тошнота/рвота или жидкий стул?",
                "Насколько боль мешает сну и активности; помогает ли тепло/обезболивающее по инструкции?",
            ]
        )

    # Женщина, боль внизу живота, цикл в тексте не назван явно — уточнить связь с менструацией (пол/возраст — в демографических вопросах clarify).
    age_y = _extract_age_years_from_text(known)
    if (
        _extract_sex_from_text(known) == "female"
        and _lower_abdomen_pain_context(known)
        and not _explicit_menstrual_cycle_in_text(known)
        and (age_y is None or age_y >= 11)
    ):
        questions.append(
            "Связана ли боль с менструацией или усиливается за 1–3 дня до неё (если нет — тоже ответьте явно)?"
        )

    # Case: suspected allergy/food-trigger (не пересекать с проктологией и гинекологическим циклом).
    if (
        not _is_strong_anorectal_symptom_context(msg)
        and not _is_menstrual_cycle_lower_abdomen_context(known)
        and any(
            x in msg
            for x in (
                "аллер",
                "сып",
                "после еды",
                "поел",
                "после молоч",
                "творог",
                "сыр",
                "кефир",
                "молок",
                "семеч",
                "орех",
                "отек губ",
                "отек язык",
            )
        )
    ):
        questions.extend(
            [
                "Есть ли четкая связь с продуктом/триггером (через сколько после еды начинается симптом)?",
                "Есть ли сыпь, зуд, отек губ/языка, свистящее дыхание или ощущение нехватки воздуха?",
                "Повторяется ли реакция на те же продукты (молочные, выдержанные сыры, добавки)?",
                "Помогают ли антигистаминные и проходит ли симптом после исключения триггера?",
            ]
        )

    # Case: possible hormonal / endocrine driver (у мужчин — без вопросов про менструальный цикл/фазу).
    if any(
        x in msg
        for x in ("гормон", "цикл", "месячн", "щитовид", "приливы", "потею ночью", "вес", "тахикард", "бессон", "тревог")
    ):
        if _extract_sex_from_text(known) == "male":
            questions.extend(
                [
                    "Есть ли изменения веса, сна, потливости, тревожности за последние 1-3 месяца?",
                    "Были ли ранее проблемы со щитовидной железой/гормонами и какие анализы сдавали?",
                    "Есть ли связь симптомов со стрессом или недосыпом?",
                    "Принимаете ли сейчас гормональные препараты/БАДы/стимуляторы?",
                ]
            )
        else:
            questions.extend(
                [
                    "Есть ли изменения цикла, веса, сна, потливости, тревожности за последние 1-3 месяца?",
                    "Были ли ранее проблемы со щитовидной железой/гормонами и какие анализы сдавали?",
                    "Есть ли связь симптомов с фазой цикла, стрессом или недосыпом?",
                    "Принимаете ли сейчас гормональные препараты/БАДы/стимуляторы?",
                ]
            )

    # Case: anorectal symptoms (hemorrhoids / fissure / proctology context).
    if _is_strong_anorectal_symptom_context(msg) or any(
        x in msg for x in ("гемор", "анус", "анальн", "прямой киш", "задний проход", "дефекац", "кровь после стула")
    ):
        questions.extend(
            [
                "Кровь появляется после стула на бумаге/в унитазе, и какого она цвета (ярко-красная или темная)?",
                "Есть ли выраженная боль при дефекации, зуд или ощущение узла в области ануса?",
                "Были ли запор, натуживание или длительное сидение в последние дни?",
                "Кровотечение усиливается, появляются сгустки, слабость или головокружение?",
            ]
        )

    # Knowledge-first enrichment from food/histamine references.
    ft_ctx = _food_trigger_reference_context(user_message)
    ref_followups = [
        str(x).strip().replace("\n", " ")
        for x in (ft_ctx.get("followup_questions") or [])
        if str(x).strip()
    ]
    if ref_followups:
        questions.extend(ref_followups[:5])

    # De-duplicate while preserving order.
    seen: set[str] = set()
    merged: list[str] = []
    for q in questions + base:
        s = str(q or "").strip()
        if not s:
            continue
        if _question_repeats_known_symptom(known, s):
            s = _rewrite_followup_for_known_symptom(known, s).strip()
            if not s:
                continue
        key = _norm_text_for_compare(s)
        if key in seen:
            continue
        seen.add(key)
        merged.append(s)
    # Не превращаем диалог в допрос: максимум 3 прицельных вопроса.
    return merged[:3]


def _diagnostic_hypotheses_for_message(user_message: str) -> list[str]:
    msg = _norm_text_for_compare(user_message or "")
    if _is_strong_anorectal_symptom_context(msg):
        core = [
            "геморрой (наружний/внутренний) и/или анальная трещина при типичной картине крови после стула и боли в области ануса",
            "другие аноректальные источники крови не исключены — при сильной боли, первом эпизоде или сомнениях важен очный осмотр проктолога",
        ]
        seen0: set[str] = set()
        out0: list[str] = []
        for h in core:
            k = _norm_text_for_compare(h)
            if k in seen0:
                continue
            seen0.add(k)
            out0.append(h)
        return out0[:4]
    if _is_menstrual_cycle_lower_abdomen_context(msg):
        core = [
            "дисменорея (болезненные менструации) и/или предменструальный синдром при связи боли с циклом без выраженной диареи/рвоты и температуры",
            "другие гинекологические причины боли внизу живота не исключены — при новой сильной боли, задержке цикла или подозрении на беременность нужна очная оценка гинеколога",
        ]
        seen_m: set[str] = set()
        out_m: list[str] = []
        for h in core:
            k = _norm_text_for_compare(h)
            if k in seen_m:
                continue
            seen_m.add(k)
            out_m.append(h)
        return out_m[:4]
    hyp: list[str] = []
    if _is_trauma_context_message(msg):
        hyp.append("посттравматическое повреждение мягких тканей (ушиб/ссадина/растяжение)")
        if any(x in msg for x in ("колен", "нога", "голен", "ступн", "стоп")):
            hyp.append("травма сустава/связок нижней конечности (нужна очная оценка при ограничении опоры)")
        hyp.append("при выраженной боли/отеке — исключить более серьезное повреждение (перелом/вывих)")
    if ("голов" in msg) and (("пульс" in msg) or ("сердц" in msg) or ("лицо гор" in msg) or ("жар" in msg)):
        hyp.append("вегетативная/сосудистая реакция на стресс, перегрев или нагрузку")
        hyp.append("колебания артериального давления (вверх или вниз)")
        hyp.append("реже — эндокринный фактор (щитовидная железа/гормональный дисбаланс)")
    if not _is_strong_anorectal_symptom_context(msg) and not _is_menstrual_cycle_lower_abdomen_context(msg):
        if any(x in msg for x in ("аллер", "сып", "зуд", "отек губ", "отек язык")):
            hyp.append("аллергическая реакция (пищевой или бытовой триггер)")
        if any(x in msg for x in ("творог", "сыр", "кефир", "молок", "после еды", "поел", "семеч", "орех")):
            hyp.append("пищевой триггер: непереносимость/чувствительность к продуктам")
            hyp.append("гистамин-опосредованная реакция на продукты (в том числе выдержанные/ферментированные)")
            hyp.append("не-IgE пищевая реакция (индивидуальная непереносимость компонентов продукта)")
    if (not _is_menstrual_cycle_lower_abdomen_context(msg)) and any(
        x in msg for x in ("гормон", "цикл", "месячн", "щитовид", "приливы", "потею ночью", "вес")
    ):
        hyp.append("гормональная причина (щитовидная железа/половые гормоны/стресс-ось)")
    if any(x in msg for x in ("травм", "удар", "упал")):
        hyp.append("посттравматическая причина (требует очной оценки)")
    if any(x in msg for x in ("бан", "парил", "перегрев", "солнц")):
        hyp.append("перегрев/дегидратация")

    # Add probable conditions from food/histamine libraries when relevant.
    ft_ctx = _food_trigger_reference_context(user_message)
    for cond in (ft_ctx.get("possible_conditions") or [])[:6]:
        c = str(cond or "").strip()
        if not c:
            continue
        cn = _norm_text_for_compare(c)
        if "гистамин" in cn:
            hyp.append("гистамин-опосредованная реакция (по данным справочников пищевых триггеров)")
        elif "mcas" in cn or "mast" in cn or "тучн" in cn:
            hyp.append("вариант маст-клеточной гиперреактивности (MCAS-подобный профиль)")
        elif "аллер" in cn:
            hyp.append("аллергическая реакция (вероятный триггер по справочникам)")
        elif "неперенос" in cn or "intoler" in cn:
            hyp.append("пищевая непереносимость/чувствительность (вероятный триггер)")
        else:
            hyp.append(c)

    dedup: list[str] = []
    seen: set[str] = set()
    for h in hyp:
        k = _norm_text_for_compare(h)
        if k in seen:
            continue
        seen.add(k)
        dedup.append(h)
    return dedup[:4]


def _rank_and_label_hypotheses(user_message: str, hypotheses: list[str]) -> list[str]:
    msg = _norm_text_for_compare(user_message or "")
    if not hypotheses:
        return []

    def _ends_with_terminal(s: str) -> bool:
        ss = str(s or "").strip()
        return bool(ss) and ss[-1] in ".!?"

    weighted: list[tuple[float, int, str]] = []
    for idx, h in enumerate(hypotheses):
        hs = str(h or "").strip()
        if not hs:
            continue
        hn = _norm_text_for_compare(hs)
        score = 0.0
        # Generic lexical overlap.
        overlap = sum(1 for tok in set(msg.split()) if len(tok) >= 4 and tok in hn)
        score += overlap * 1.2

        # Domain boosts.
        if any(x in msg for x in ("творог", "сыр", "кефир", "молок", "после еды", "гистамин")):
            if any(x in hn for x in ("гистамин", "неперенос", "чувств", "пищ", "аллер")):
                score += 4.5
        if any(x in msg for x in ("сып", "зуд", "отек", "отёк", "аллер")):
            if any(x in hn for x in ("аллер", "гистамин", "mast", "mcas", "тучн")):
                score += 3.0
        if _is_trauma_context_message(msg):
            if any(x in hn for x in ("травм", "ушиб", "перелом", "вывих", "связк", "сустав")):
                score += 3.5
        if any(x in msg for x in ("температур", "кашл", "горл", "сопл", "насморк")):
            if any(x in hn for x in ("вирус", "инфек", "воспал")):
                score += 2.5

        weighted.append((score, idx, hs))

    weighted.sort(key=lambda x: (-x[0], x[1]))
    ordered = [row[2] for row in weighted[:4]]
    if not ordered:
        return []

    labels = ("Наиболее вероятно", "Также возможно", "Реже")
    out: list[str] = []
    for i, h in enumerate(ordered):
        label = labels[i] if i < len(labels) else "Также возможно"
        body = h if _ends_with_terminal(h) else (h + ".")
        out.append(f"{label}: {body}")
    return out


def _diagnostic_resolution_steps(user_message: str) -> list[str]:
    msg = _norm_text_for_compare(user_message or "")
    steps = [
        "после ваших ответов фиксирую наиболее вероятную причину и даю план на сегодня",
    ]
    if _is_trauma_context_message(msg):
        steps.insert(0, "при признаках травмы сустава/невозможности опоры — направляю в травмпункт сегодня")
    if any(x in msg for x in ("творог", "сыр", "кефир", "молок", "после еды", "поел", "семеч", "орех")):
        steps.append("при подтверждении food-trigger — элиминация 10-14 дней + дневник реакции, затем персональные рекомендации")
    if any(x in msg for x in ("гормон", "цикл", "месячн", "щитовид", "приливы", "потею ночью", "вес")):
        steps.append("при признаках гормонального профиля — прицельные анализы (ТТГ/св.Т4 и по показаниям половые гормоны)")
    if any(x in msg for x in ("голов", "пульс", "давлен", "сердц")):
        steps.append("при нестабильных давлении/пульсе — маршрут к врачу в ближайшие сутки, при ухудшении — срочно 103")
    return steps[:2]


def _should_use_clarify_first_mode(user_message: str, item: dict[str, Any]) -> bool:
    item_id = str(item.get("id") or "").strip()
    if item_id in _COMPLAINT_IDS_CANNED_FIRST_RESPONSE:
        return False
    msg = _norm_text_for_compare(user_message or "")
    title = _norm_text_for_compare(str(item.get("complaint") or item.get("name") or ""))
    acute_markers = (
        "кашл",
        "температур",
        "лихорад",
        "жар",
        "озноб",
        "горл",
        "насморк",
        "сухост",
        "сухо",
        "голов",
        "тошн",
        "рвот",
        "одыш",
        "слабост",
    )
    if sum(1 for m in acute_markers if m in msg) >= 2:
        return True
    if _is_endocrine_asthenic_switch_request(user_message):
        return True
    # Ambiguous mixed symptoms -> ask targeted follow-ups first.
    if ("голов" in msg) and (("пульс" in msg) or ("сердц" in msg) or ("лицо гор" in msg) or ("жар" in msg)):
        return True
    if ("головокруж" in msg) and (("травм" in msg) or ("перегрев" in msg) or ("бан" in msg) or ("парил" in msg)):
        return True
    if any(x in msg for x in ("аллер", "сып", "зуд", "отек", "отёк", "после еды", "поел", "творог", "сыр", "кефир", "молок", "семеч", "орех")):
        return True
    if any(x in msg for x in ("гормон", "цикл", "месячн", "щитовид", "приливы", "потею ночью")):
        return True
    if any(
        x in msg
        for x in (
            "лишний вес",
            "набор вес",
            "набрать вес",
            "вес в животе",
            "ожирен",
            "имт",
            "сбросить вес",
            "похудеть",
            "не худею",
            "не могу похудеть",
            "вес не уходит",
            "вес стоит",
        )
    ):
        return True
    # If title looks like noisy phrase-level scenario, prefer clarification-first.
    if len(title.split()) >= 6:
        return True
    if _complaint_diagnostic_ambiguous(item, user_message):
        return True
    return False


def _womens_health_pack_title_matches(title_n: str) -> bool:
    """Ключевые слова заголовков сценариев женского здоровья (complaint_scenarios_short / womens_health_canned_texts)."""
    return any(
        x in title_n
        for x in (
            "месячн",
            "менстру",
            "цикл",
            "нерегуляр",
            "регуляр",
            "овуляц",
            "гинек",
            "пмс",
            "акне",
            "прыщ",
            "высыпан",
            "кож",
            "вес",
            "худ",
            "похуд",
            "имт",
            "инсулин",
            "волос",
            "выпаден",
            "усталост",
            "слабост",
            "энерг",
            "апати",
            "настроен",
            "депресс",
            "отёк",
            "отек",
            "отечн",
            "болезнен",
            "дисменор",
            "спазм",
            "сладк",
            "тяга",
            "гормон",
            "жидкост",
        )
    )


def _merged_user_blob_for_complaint_clustering(
    message: str, chat_history: Optional[list[dict[str, Any]]]
) -> str:
    """Несколько user-рернов для детекторов кластеров (обильные месячные + волосы + усталость)."""
    parts: list[str] = [str(message or "").strip()]
    if isinstance(chat_history, list):
        n = 0
        for entry in reversed(chat_history):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("role") or "").lower() != "user":
                continue
            c = str(entry.get("content") or "").strip()
            if c:
                parts.append(c)
                n += 1
            if n >= 5:
                break
    return _norm_text_for_compare("\n".join(p for p in parts if p))


def _select_best_complaint_hit(
    message: str,
    hits: list[dict[str, Any]],
    *,
    chat_history: Optional[list[dict[str, Any]]] = None,
) -> Optional[dict[str, Any]]:
    if not isinstance(hits, list) or not hits:
        return None
    msg = _norm_text_for_compare(message or "")
    cluster_blob = _merged_user_blob_for_complaint_clustering(message, chat_history)
    msg_tokens = {t for t in msg.split() if len(t) >= 4}
    food_markers = ("творог", "кефир", "молок", "йогурт", "сыр", "после еды", "пища", "еда")
    has_food_context = any(m in msg for m in food_markers)
    has_blood_context = any(m in msg for m in ("кров", "кровотеч", "идет кровь", "идёт кровь"))
    has_nose_context = any(m in msg for m in ("нос", "носа", "носов", "ноздр"))
    anorectal_markers = ("гемор", "анус", "анальн", "прямой киш", "задний проход", "дефекац", "стул")
    has_anorectal_context = any(m in msg for m in anorectal_markers)
    has_lab_panel_fear = any(m in msg for m in ("лимфоцит", "лейкоцит", "тромбоцит", "гемоглобин", "лейкоформул")) or (
        "боюсь" in msg and "рак" in msg and any(m in msg for m in ("анализ", "лимфо", "лейко", "оак", "кров"))
    )
    has_postpartum_context = ("плач" in msg or "слез" in msg or "слёз" in msg or "тоск" in msg or "депресс" in msg) and any(
        m in msg for m in ("ребен", "ребён", "новорожд", "роды", "родила", "послерод", "построд", "материн", "радоваться")
    )
    _pp_parents = any(m in msg for m in ("родител", "мама", "папа", "мать", "отец"))
    _pp_pressure = any(
        m in msg for m in ("давят", "требуют", "требует", "контролиру", "учись", "учиться", "сдавай", "сдавать", "анализы", "оценк")
    ) or ("давлен" in msg and "родител" in msg)
    _pp_school_or_distress = any(
        m in msg
        for m in (
            "ничего не хоч",
            "не хочу",
            "не хочется",
            "устал",
            "устала",
            "вымота",
            "школ",
            "учеб",
            "учись",
            "учиться",
            "институт",
            "универ",
            "экзамен",
            "дз",
            "урок",
            "анализы",
            "анализ ",
        )
    )
    has_parental_pressure_context = bool(_pp_parents and _pp_pressure and _pp_school_or_distress)
    has_knee_postinjury_training_context = _has_knee_postinjury_training_return_query(msg)
    has_health_anxiety_mortality_context = _has_health_anxiety_mortality_fear_query(msg)
    has_prolonged_appetite_loss_context = _has_prolonged_appetite_loss_query(msg)
    has_premenstrual_mood_sweet_context = _has_premenstrual_mood_sweet_craving_query(msg)
    has_chronic_fatigue_months_context = _has_chronic_fatigue_months_no_recovery_query(msg)
    has_adolescent_anhedonia_context = _has_adolescent_anhedonia_apathy_query(msg)
    has_nutrition_supplements_where_to_start_context = _has_nutrition_supplements_where_to_start_query(msg)
    has_gas_bloating_digestion_context = _has_gas_bloating_digestion_query(msg)
    has_heavy_menstrual_fatigue_hair_loss_context = _has_heavy_menstrual_fatigue_hair_loss_query(cluster_blob)
    has_irregular_cycle_women_context = _has_irregular_cycle_women_query(msg)
    has_acne_skin_hormonal_women_context = _has_acne_skin_hormonal_women_query(msg)
    has_weight_plateau_women_context = _has_weight_plateau_women_query(msg)
    has_hair_loss_diffuse_women_context = _has_hair_loss_diffuse_women_query(msg)
    has_persistent_fatigue_women_context = _has_persistent_fatigue_women_query(msg)
    has_low_mood_apathy_women_context = _has_low_mood_apathy_women_query(msg)
    has_edema_swelling_women_context = _has_edema_swelling_women_query(msg)
    has_painful_periods_dysmenorrhea_women_context = _has_painful_periods_dysmenorrhea_women_query(msg)
    has_sweet_craving_standalone_women_context = _has_sweet_craving_standalone_women_query(msg)
    has_womens_health_pack_context = (
        has_irregular_cycle_women_context
        or has_acne_skin_hormonal_women_context
        or has_weight_plateau_women_context
        or has_hair_loss_diffuse_women_context
        or has_persistent_fatigue_women_context
        or has_low_mood_apathy_women_context
        or has_edema_swelling_women_context
        or has_painful_periods_dysmenorrhea_women_context
        or has_sweet_craving_standalone_women_context
    )
    _womens_health_pack_score_rules = (
        (has_irregular_cycle_women_context, "complaint_irregular_menstrual_cycle_women", ("цикл", "месячн", "менстру", "нерегуляр", "овуляц", "гинек")),
        (has_acne_skin_hormonal_women_context, "complaint_acne_skin_hormonal_women", ("акне", "прыщ", "высыпан", "кож", "гормон")),
        (has_weight_plateau_women_context, "complaint_weight_plateau_women", ("вес", "худ", "похуд", "имт", "инсулин", "сахар")),
        (has_hair_loss_diffuse_women_context, "complaint_hair_loss_diffuse_women", ("волос", "выпаден", "ферритин", "ттг", "желез")),
        (has_persistent_fatigue_women_context, "complaint_persistent_fatigue_women", ("усталост", "слабост", "энерг", "сон", "ферритин", "ттг")),
        (has_low_mood_apathy_women_context, "complaint_low_mood_apathy_women", ("апати", "настроен", "депресс", "психолог", "стресс")),
        (has_edema_swelling_women_context, "complaint_edema_swelling_women", ("отёк", "отек", "отечн", "жидкост")),
        (has_painful_periods_dysmenorrhea_women_context, "complaint_painful_periods_dysmenorrhea_women", ("болезнен", "дисменор", "месячн", "менстру", "спазм")),
        (has_sweet_craving_standalone_women_context, "complaint_sweet_craving_standalone_women", ("сладк", "тяга", "сахар", "инсулин", "глюкоз")),
    )

    best_item: Optional[dict[str, Any]] = None
    best_score = -10_000.0
    for item in hits:
        if not isinstance(item, dict):
            continue
        title = str(item.get("complaint") or item.get("name") or "").strip()
        title_n = _norm_text_for_compare(title)
        if not title_n:
            continue
        title_tokens = {t for t in title_n.split() if len(t) >= 4}
        overlap = len(msg_tokens & title_tokens)
        score = float(overlap * 4.0)

        if title_n in msg or msg in title_n:
            score += 3.0

        # Penalize noisy, user-phrase-like synthetic titles for non-matching context.
        word_count = len([w for w in title_n.split() if w])
        if word_count >= 6:
            if not (
                (has_lab_panel_fear and any(x in title_n for x in ("анализ кров", "анализе кров", "страх", "лимфоцит", "онколог")))
                or (
                    has_postpartum_context
                    and any(x in title_n for x in ("послерод", "материн", "депресс", "тревог", "психолог", "эмоцион", "младенец", "слез"))
                )
                or (
                    has_parental_pressure_context
                    and any(x in title_n for x in ("родител", "учеб", "школ", "давлен", "апати", "стресс", "анализ", "подрост"))
                )
                or (
                    has_knee_postinjury_training_context
                    and any(x in title_n for x in ("колен", "мениск", "травм", "связок", "реабилит", "трениров", "восстанов"))
                )
                or (
                    has_health_anxiety_mortality_context
                    and any(x in title_n for x in ("тревог", "паник", "страх", "смерт", "ипохонд", "психолог", "серьезн"))
                )
                or (
                    has_prolonged_appetite_loss_context
                    and any(x in title_n for x in ("аппетит", "питан", "жкт", "желуд", "тошн", "похуден", "истощен"))
                )
                or (
                    has_premenstrual_mood_sweet_context
                    and any(x in title_n for x in ("месячн", "менстру", "пмс", "цикл", "гинек", "овуляц", "гормон", "настроен", "сладк"))
                )
                or (
                    has_chronic_fatigue_months_context
                    and any(x in title_n for x in ("усталост", "слабост", "энерг", "сон", "ферритин", "ттг", "желез", "витамин", "анем", "гипотире"))
                )
                or (
                    has_adolescent_anhedonia_context
                    and any(x in title_n for x in ("подросток", "школьн", "психолог", "депресс", "апати", "настроен", "бессмыслен", "суицид"))
                )
                or (
                    has_nutrition_supplements_where_to_start_context
                    and any(
                        x in title_n
                        for x in ("пита", "рацион", "добавк", "витамин", "биодобавк", "бады", "диетолог", "дефицит", "ферритин")
                    )
                )
                or (
                    has_gas_bloating_digestion_context
                    and any(x in title_n for x in ("вздут", "газ", "метеоризм", "живот", "кишечник", "пищевар", "фермент"))
                )
                or (
                    has_heavy_menstrual_fatigue_hair_loss_context
                    and any(
                        x in title_n
                        for x in (
                            "месячн",
                            "менстру",
                            "обильн",
                            "волос",
                            "выпаден",
                            "усталост",
                            "ферритин",
                            "желез",
                            "гинек",
                            "ттг",
                        )
                    )
                )
                or (has_womens_health_pack_context and _womens_health_pack_title_matches(title_n))
            ):
                score -= 2.0
        if title_n.startswith("после "):
            score -= 1.5

        if has_lab_panel_fear:
            if str(item.get("id") or "").strip() == "complaint_lab_indices_oncophobia" or any(
                x in title_n for x in ("анализ кров", "анализе кров", "лимфоцит", "лейкоформул", "страх серь", "онколог")
            ):
                score += 22.0
            if any(x in title_n for x in ("груд", "голов", "кашл", "насморк", "орви", "фарингит", "мочеиспуск", "цистит")) and not any(
                x in msg for x in ("груд", "голов", "кашл", "насморк", "горл", "моч", "цистит", "позыв", "жжение")
            ):
                score -= 16.0

        if has_postpartum_context:
            if str(item.get("id") or "").strip() == "complaint_postpartum_distress" or any(
                x in title_n for x in ("послерод", "материн", "депресс", "тревог", "психолог", "эмоцион", "младенец", "слез", "плач")
            ):
                score += 24.0
            if any(x in title_n for x in ("щитовид", "ттг", "диабет", "жажд", "мочеиспуск", "пятно на коже", "сыпь на коже")) and not any(
                x in msg for x in ("ттг", "щитовид", "диабет", "жажд", "моч", "пятн", "кож", "сыпь")
            ):
                score -= 22.0

        if has_parental_pressure_context:
            if str(item.get("id") or "").strip() == "complaint_parental_academic_pressure" or any(
                x in title_n for x in ("родител", "учеб", "школ", "апати", "стресс", "подрост", "требова", "контрол", "анализ")
            ):
                score += 24.0
            if any(x in title_n for x in ("послерод", "младенец", "новорожд", "лимфоцит", "онколог", "щитовид")) and not any(
                x in msg for x in ("роды", "родила", "лимфоцит", "рак", "ребен", "ребён", "щитовид")
            ):
                score -= 22.0

        if has_knee_postinjury_training_context:
            if str(item.get("id") or "").strip() == "complaint_knee_postinjury_training_return" or any(
                x in title_n for x in ("колен", "мениск", "травм", "связок", "реабилит", "трениров", "операц")
            ):
                score += 24.0
            if any(x in title_n for x in ("цистит", "мочеиспуск", "послерод", "орви", "насморк", "лимфоцит")) and not any(
                x in msg for x in ("моч", "цистит", "роды", "кашл", "насморк", "лимфоцит")
            ):
                score -= 22.0

        if has_health_anxiety_mortality_context:
            if str(item.get("id") or "").strip() == "complaint_health_anxiety_mortality_fear" or any(
                x in title_n for x in ("тревог", "паник", "страх", "смерт", "ипохонд", "психолог", "катастроф", "серьезн")
            ):
                score += 24.0
            if any(x in title_n for x in ("лимфоцит", "лейкоформул", "оак", "цистит", "орви", "колен", "мениск")) and not any(
                x in msg for x in ("лимфоцит", "лейкоцит", "оак", "моч", "цистит", "кашл", "колен", "мениск")
            ):
                score -= 22.0

        if has_prolonged_appetite_loss_context:
            if str(item.get("id") or "").strip() == "complaint_prolonged_loss_of_appetite" or any(
                x in title_n for x in ("аппетит", "питан", "жкт", "желуд", "тошн", "похуден", "истощен")
            ):
                score += 24.0
            if any(x in title_n for x in ("лимфоцит", "орви", "кашл", "колен", "цистит", "паник", "смерт")) and not any(
                x in msg for x in ("лимфоцит", "кашл", "колен", "моч", "цистит", "паник", "умру", "смерт")
            ):
                score -= 22.0

        if has_premenstrual_mood_sweet_context:
            if str(item.get("id") or "").strip() == "complaint_premenstrual_mood_sweet_craving" or any(
                x in title_n for x in ("месячн", "менстру", "пмс", "цикл", "гинек", "овуляц", "дисменор", "гормон", "настроен", "сладк")
            ):
                score += 24.0
            if any(x in title_n for x in ("лимфоцит", "орви", "колен", "послерод", "онколог")) and not any(
                x in msg for x in ("лимфоцит", "кашл", "колен", "роды", "рак")
            ):
                score -= 22.0

        if has_chronic_fatigue_months_context:
            if str(item.get("id") or "").strip() == "complaint_chronic_fatigue_months_no_recovery" or any(
                x in title_n for x in ("усталост", "слабост", "энерг", "сон", "ферритин", "ттг", "желез", "витамин", "анем", "гипотире")
            ):
                score += 24.0
            if any(x in title_n for x in ("цистит", "орви", "колен", "лимфоцит", "послерод")) and not any(
                x in msg for x in ("моч", "цистит", "кашл", "колен", "лимфоцит", "роды")
            ):
                score -= 22.0

        if has_adolescent_anhedonia_context:
            if str(item.get("id") or "").strip() == "complaint_adolescent_anhedonia_apathy" or any(
                x in title_n for x in ("подросток", "школьн", "психолог", "депресс", "апати", "настроен", "бессмыслен", "суицид")
            ):
                score += 24.0
            if any(x in title_n for x in ("лимфоцит", "орви", "колен", "менопауз", "беремен")) and not any(
                x in msg for x in ("лимфоцит", "кашл", "колен", "беремен")
            ):
                score -= 22.0

        if has_nutrition_supplements_where_to_start_context:
            if str(item.get("id") or "").strip() == "complaint_nutrition_supplements_where_to_start" or any(
                x in title_n for x in ("пита", "рацион", "добавк", "витамин", "биодобавк", "бады", "диетолог", "дефицит", "ферритин")
            ):
                score += 24.0
            if any(x in title_n for x in ("лимфоцит", "цистит", "орви", "колен", "менопауз")) and not any(
                x in msg for x in ("лимфоцит", "кашл", "колен", "моч", "цистит", "беремен")
            ):
                score -= 22.0

        if has_gas_bloating_digestion_context:
            if str(item.get("id") or "").strip() == "complaint_gas_bloating" or any(
                x in title_n for x in ("вздут", "газ", "метеоризм", "живот", "кишечник", "пищевар", "фермент", "копрограм")
            ):
                score += 24.0
            if any(x in title_n for x in ("лимфоцит", "онколог", "инсульт", "инфаркт")) and not any(
                x in msg for x in ("лимфоцит", "рак", "инсульт", "инфаркт")
            ):
                score -= 22.0

        if has_heavy_menstrual_fatigue_hair_loss_context:
            if str(item.get("id") or "").strip() == "complaint_heavy_menstrual_bleeding_fatigue_hair_loss" or any(
                x in title_n
                for x in (
                    "месячн",
                    "менстру",
                    "обильн",
                    "менорраг",
                    "волос",
                    "выпаден",
                    "ферритин",
                    "желез",
                    "анем",
                    "ттг",
                    "гинек",
                    "щитовид",
                )
            ):
                score += 24.0
            if any(x in title_n for x in ("лимфоцит", "цистит", "орви", "гастроэнтерит")) and not any(
                x in msg for x in ("лимфоцит", "цистит", "кашл", "понос", "рвот")
            ):
                score -= 22.0

        item_id = str(item.get("id") or "").strip()
        if any(
            flag and (item_id == sid or any(k in title_n for k in keys))
            for flag, sid, keys in _womens_health_pack_score_rules
        ):
            score += 24.0
        if has_womens_health_pack_context and any(x in title_n for x in ("лимфоцит", "орви", "ангин")) and not any(
            x in msg for x in ("лимфоцит", "кашл", "ангин", "горл")
        ):
            score -= 22.0

        title_has_food_context = any(m in title_n for m in food_markers)
        if title_has_food_context and not has_food_context:
            score -= 8.0

        if has_blood_context:
            if "кров" in title_n or "кровотеч" in title_n:
                score += 4.0
            else:
                score -= 3.5
        if has_nose_context:
            if "нос" in title_n or "носов" in title_n:
                score += 2.5

        if has_anorectal_context:
            if any(m in title_n for m in anorectal_markers):
                score += 5.0
            # Аноректальный контекст часто ошибочно прилипает к "порез/рана/кровотечение".
            if any(x in title_n for x in ("порез", "рана", "ссад", "ушиб", "травм")):
                score -= 6.0

        # Boost clinically relevant matches for headache/cardio-like messages.
        if (
            not has_heavy_menstrual_fatigue_hair_loss_context
            and any(x in msg for x in ("голов", "пульс", "давлен", "лицо горит"))
        ):
            if any(x in title_n for x in ("голов", "давлен", "сердц", "пульс")):
                score += 2.0

        score += _coherence_adjust_complaint_score(msg, title_n)

        if score > best_score:
            best_score = score
            best_item = item

    if best_item is None:
        return hits[0] if hits else None
    if best_score < -3.5:
        return None
    # Триада в объединённом тексте (текущая реплика + недавние user-сообщения) — приоритет над дисменореей/головокружением из одной фразы.
    if has_heavy_menstrual_fatigue_hair_loss_context:
        for hit in hits:
            if isinstance(hit, dict) and str(hit.get("id") or "").strip() == "complaint_heavy_menstrual_bleeding_fatigue_hair_loss":
                return hit
    return best_item


def _match_human_tone_profile(text: str) -> dict[str, str]:
    t = _norm_text_for_compare(text)
    profiles = [
        (("гемор", "анальн", "кровь из зад"), "Понимаю, это деликатная и неприятная ситуация, давайте спокойно разберем.", "Если кровотечение усиливается или появляется слабость, не тяните с очной помощью."),
        (("головн", "болит голова"), "По головной боли сейчас разберем все коротко и по делу.", "Если боль необычно сильная или новая по характеру, лучше очный осмотр сегодня."),
        (("мигрен", "пульсир"), "Похоже на мигренозный тип боли, давайте снизим нагрузку и симптомы по шагам.", "Если приступы участились или изменились, стоит скорректировать тактику с врачом."),
        (("температ", "жар", "озноб"), "Ты справишься, сейчас быстро стабилизируем состояние и разложим шаги.", "Если температура держится высокой и состояние ухудшается, нужна очная оценка."),
        (("кашл",), "Кашель правда выматывает, но это рабочая история — сейчас дам короткий понятный план.", "Если появляется одышка или кровь в мокроте, это повод для срочного осмотра."),
        (("горло", "ангин", "тонзилл"), "Понимаю, боль в горле неприятна и мешает есть/пить. Дам рабочие шаги.", "Если трудно глотать или дышать, нужна неотложная помощь."),
        (("насморк", "ринит", "синус", "гаймор"), "Похоже на проблему ЛОР-зоны, разложу по делу: что можно дома и когда к врачу.", "Если нарастает боль в лице или температура, лучше очный осмотр."),
        (("груд", "за грудин"), "С болью в груди всегда действуем осторожно. Дам безопасный приоритетный алгоритм.", "При давящей боли, одышке, холодном поте — сразу 103."),
        (("одыш", "тяжело дыш"), "Понимаю, когда не хватает воздуха — это тревожно. Действуем по приоритету безопасности.", "Если одышка в покое или усиливается — не откладывайте вызов 103."),
        (("давлен", "гипертон"), "С давлением разберемся спокойно и четко, сейчас дам приоритетные шаги.", "Если давление очень высокое и есть симптомы — лучше не рисковать и вызвать скорую."),
        (("сердцеби", "тахикард", "пульс"), "Понимаю, перебои и частый пульс могут пугать. Разберем пошагово.", "Если есть обморок, боль в груди или одышка — это срочный сценарий."),
        (("живот", "абдомин"), "Понимаю, боль в животе бывает очень разной. Дам аккуратный план без лишнего.", "При резком усилении боли, рвоте с кровью или черном стуле — срочно за помощью."),
        (("тошнот",), "Понимаю, тошнота сильно выбивает из ритма. Сначала стабилизируем состояние.", "Если не удается пить или есть признаки обезвоживания — нужен очный осмотр."),
        (("рвот",), "Понимаю, это неприятно и быстро истощает. Главное сейчас — не допустить обезвоживания.", "При повторной рвоте, крови или сильной боли вызывайте неотложку."),
        (("диаре", "понос", "жидкий стул"), "Здесь главное быстро восстановить жидкость — сейчас дам понятный план.", "Если слабость нарастает, мало мочи или есть кровь в стуле — срочно к врачу."),
        (("запор", "нет стул"), "Понимаю, это дискомфортно и выматывает. Сделаем мягкий и безопасный план.", "Если боль сильная или нет стула и газов с рвотой — нужна срочная помощь."),
        (("изжог", "рефлюкс", "гэрб"), "Понимаю, постоянная изжога сильно снижает качество жизни. Разберем практично.", "Если есть боль при глотании, рвота с кровью или черный стул — срочно к врачу."),
        (("цистит", "мочеиспуск", "жжение"), "Симптомы неприятные, но это хорошо контролируется при правильных шагах.", "Если есть температура и боль в пояснице, это может быть выше мочевого пузыря — нужен врач."),
        (("поясниц", "спин", "прострел"), "Понимаю, боль в спине ограничивает всё. Дам безопасный план на ближайшие дни.", "Если есть слабость в ногах или нарушения мочеиспускания — это срочно."),
        (("сустав", "артрит", "артроз"), "По суставам можно заметно облегчить состояние, если действовать аккуратно и по плану.", "Если сустав горячий, сильно отек и есть температура — срочно к врачу."),
        (("колен", "мениск"), "Понимаю, колено быстро ограничивает движение. Разберем план восстановления.", "Если колено 'заклинило' или после травмы не можете опереться — нужен травматолог."),
        (("отек ног", "варик", "вены", "голен"), "Давай спокойно проверим ключевые риски и сразу определим безопасные шаги.", "Односторонний отек с болью или одышкой — срочно 103."),
        (("головокруж", "вертит"), "Понимаю, головокружение пугает и мешает держать равновесие. Сначала безопасность.", "При нарушении речи, слабости в конечностях или двоении — срочно 103."),
        (("усталост", "слабост", "нет сил"), "Понимаю, постоянная слабость морально истощает. Дам реалистичный план.", "Если слабость резко усилилась или есть одышка/обморок — нужна срочная оценка."),
        (("бессон", "сон", "не могу уснуть"), "Понимаю, без сна тяжело держать ресурс. Сфокусируемся на работающих шагах.", "Если бессонница длительная и влияет на психоэмоциональное состояние — лучше очно обсудить лечение."),
        (("тревог", "паник"), "Понимаю, тревога ощущается очень телесно. Дам спокойный и понятный план.", "Если есть мысли о самоповреждении или выраженная дезориентация — срочно за помощью."),
        (("сып", "кожа", "аллерг"), "С этим можно разобраться: уберем триггеры и посмотрим динамику по делу.", "При отеке губ/горла или затрудненном дыхании — сразу 103."),
        (("ухо", "отит"), "Понимаю, боль в ухе может быть очень резкой. Дам практичные шаги до осмотра.", "Если есть гной, высокая температура или резкое ухудшение — нужен ЛОР."),
        (("глаз", "красный глаз", "зрение"), "По глазу действуем аккуратно и быстро — так безопаснее всего.", "Боль в глазу со снижением зрения — это повод для срочного осмотра."),
        (("зуб", "зубная"), "Понимаю, зубная боль может быть невыносимой. Дам временную тактику до стоматолога.", "Если отек лица/шеи или температура, нужна срочная очная помощь."),
    ]
    for tokens, _intro, outro in profiles:
        if any(tok in t for tok in tokens):
            # Без вводных «для объёма» — не повторяем жалобу и не тратим время на пустой текст.
            return {"intro": "", "outro": outro}
    return {
        "intro": "",
        "outro": "Если состояние ухудшается или появляются красные флаги, лучше очно обратиться за помощью.",
    }


def _is_sleep_stress_anxiety_muscle_cluster(norm_text: str) -> bool:
    """Кластер нарушения сна + тревожности + мышечных спазмов/судорог (нормализованный текст)."""
    t = str(norm_text or "").strip()
    if not t:
        return False
    sleep = any(
        p in t
        for p in (
            "плохо сплю",
            "плохой сон",
            "бессон",
            "бессониц",
            "не сплю",
            "не засып",
            "не могу спать",
            "просыпаюсь",
            "нарушен сон",
            "нарушение сна",
            "мало сплю",
            "инсомн",
            "плохо спит",
        )
    )
    anx = any(
        p in t
        for p in (
            "тревог",
            "тревож",
            "беспоко",
            "стресс",
            "паник",
            "нервнич",
            "взвиноч",
            "беспокойств",
        )
    )
    muscle = any(p in t for p in ("сводит", "судорог", "спазм", "икр", "мышц"))
    # Два из трёх типичных маркеров — чтобы не цеплять односложные жалобы.
    return int(sleep) + int(anx) + int(muscle) >= 2


def _cfb_amenorrhea_galactorrhea(t: str) -> bool:
    am = ("месячн" in t and any(x in t for x in ("пропал", "пропали", "нет", "аменоре", "задержк"))) or ("аменоре" in t)
    gal = ("молоко" in t and ("груд" in t or "соск" in t)) or ("галактор" in t) or ("груд" in t and "выдел" in t)
    return bool(am and gal)


def _cfb_athletic_amenorrhea(t: str) -> bool:
    sport = any(x in t for x in ("гимнастик", "спортсмен", "танц", "балет", "трениров", "фитнес", "кроссфит"))
    amen = "месячн" in t and any(x in t for x in ("пропал", "пропали", "нет", "аменоре"))
    long_dur = any(x in t for x in ("полгода", "6 месяц", "год", "долго", "месяцев"))
    return sport and amen and long_dur


def _cfb_panic_somatic(t: str) -> bool:
    anx = any(x in t for x in ("тревог", "паник", "страх"))
    heart = any(x in t for x in ("сердц колот", "колотится", "тахикард", "учащен сердц", "пульс бьет", "учащен пульс"))
    breath = any(x in t for x in ("воздух", "не хватает", "одышк", "задыха", "не могу вдох", "хват"))
    return anx and heart and breath


def _cfb_hypothyroid_pattern(t: str) -> bool:
    cold = any(x in t for x in ("мёрзн", "мерзн", "зябк", "холодн мне", "мерзну"))
    fat = any(x in t for x in ("усталост", "нет сил", "слабост"))
    w = any(x in t for x in ("набира вес", "набор вес", "лишн вес", "полн", "вес медлен"))
    thy = "щитовид" in t
    return (cold and fat and w) or (thy and cold and fat)


def _cfb_thyroid_and_infection(t: str) -> bool:
    if "щитовид" not in t:
        return False
    return any(x in t for x in ("болею", "простуд", "орви", "иммун", "инфекц", "часто бол"))


def _cfb_stress_abdominal_gain(t: str) -> bool:
    st = any(x in t for x in ("стресс", "стрессе", "нерв"))
    belly = any(x in t for x in ("живот раст", "живот увелич", "живот", "абдомин"))
    gain = any(x in t for x in ("растет", "растёт", "растут", "набира", "набор", "полн"))
    return st and belly and gain


def _cfb_pcos_like(t: str) -> bool:
    score = 0
    if ("живот" in t or "талия" in t) and any(x in t for x in ("вес", "лишн", "набира", "растет", "растёт")):
        score += 1
    if any(x in t for x in ("нерегулярн", "неровн", "месячн")) and any(x in t for x in ("цикл", "месячн")):
        score += 1
    if any(x in t for x in ("прыщ", "акне", "угр")):
        score += 1
    if any(x in t for x in ("сладк", "инсулин")):
        score += 1
    return score >= 2


def _cfb_recurrent_uri(t: str) -> bool:
    sick = any(x in t for x in ("болею", "простуж", "орви", "простуда", "насморк", "ангин"))
    freq = any(x in t for x in ("часто", "постоянн", "зимой", "повтор", "особенно"))
    return sick and freq and not _cfb_thyroid_and_infection(t)


def _cfb_scoliosis_teen(t: str) -> bool:
    sk = "сколиоз" in t or ("осанк" in t and "искривл" in t)
    pain = "спина" in t and "бол" in t
    teen = any(x in t for x in ("14 лет", "15 лет", "13 лет", "16 лет", "школ", "подрост"))
    return sk and (pain or teen)


def _cfb_severe_acne(t: str) -> bool:
    ac = any(x in t for x in ("прыщ", "акне", "угр"))
    sev = any(x in t for x in ("ужасн", "сильн", "лиц", "спин", "много"))
    return ac and sev


def _cfb_skin_aging_cosmetic(t: str) -> bool:
    return any(x in t for x in ("упругост", "морщин", "фото старен")) or ("кож" in t and "морщин" in t)


def _cfb_omega3_supplement(t: str) -> bool:
    return "омега" in t or "omega" in t or "рыбий жир" in t


def _cfb_stress_concentration_irritable(t: str) -> bool:
    s = any(x in t for x in ("нерв на предел", "нерв", "стресс"))
    c = any(x in t for x in ("концентрац", "вниман", "фокус"))
    i = "раздражит" in t
    return (s and c) or (s and i) or (c and i)


def _cfb_circadian_phone(t: str) -> bool:
    gadget = any(x in t for x in ("телефон", "гаджет", "экран", "смартфон"))
    late = any(x in t for x in ("ноч", "3 ночи", "до утра", "поздно", "ночи"))
    wake = any(x in t for x in ("утром", "встать", "просып", "не могу подняться"))
    return gadget and (late or wake)


def _cfb_early_menarche_peers(t: str) -> bool:
    young = any(x in t for x in ("11 лет", "10 лет", "12 лет"))
    return young and "месячн" in t and any(x in t for x in ("одноклассниц", "подруг", "других", "девочек"))


def _cfb_delayed_puberty_male(t: str) -> bool:
    teen = any(x in t for x in ("15 лет", "16 лет", "17 лет"))
    voice = any(x in t for x in ("голос", "мутац", "ломается"))
    mus = ("мышц" in t and "рост" in t) or any(x in t for x in ("мышечн масс", "полов созреван"))
    return teen and voice and mus


def _cfb_hair_loss_diffuse(t: str) -> bool:
    return ("волос" in t) and any(x in t for x in ("выпада", "выпаден", "алопец"))


def _cfb_oily_acne_chin(t: str) -> bool:
    return ("жирн" in t and "кож" in t) or ("подбородок" in t and any(x in t for x in ("прыщ", "акне")))


def _cfb_mood_lability(t: str) -> bool:
    return ("то " in t or "то вдруг" in t or "перепад" in t) or ("счастлив" in t and "плакать" in t) or ("бесит" in t and "плакать" in t)


def _cfb_fatigue_libido_training(t: str) -> bool:
    lib = any(x in t for x in ("либидо", "сексуальн", "влечен"))
    fat = any(x in t for x in ("нет сил", "усталост", "трениров", "спорт"))
    return lib and fat


def _cfb_libido_followup_only(t: str) -> bool:
    """Уточняющие вопросы только про либидо без связки «силы/тренировки» в этой же реплике."""
    if "либид" not in t:
        return False
    if _cfb_fatigue_libido_training(t):
        return False
    return any(
        x in t
        for x in (
            "делать с либид",
            "про либид",
            "либидо спрашива",
            "что с либид",
            "вопрос про либид",
            "данной ситуац",
            "в этой ситуац",
        )
    )


def _cluster_based_fallback_plan(msg_fb: str) -> Optional[dict[str, Any]]:
    """Кластеры по тексту пользователя — до доменных шаблонов (перекрывают неверный domain вроде cardio при панике)."""
    t = str(msg_fb or "").strip()
    if not t:
        return None

    if _cfb_amenorrhea_galactorrhea(t):
        return {
            "hypothesis": (
                "Сочетание отсутствия менструаций и выделений из грудей может соответствовать гормональному дисбалансу "
                "(в том числе повышению пролактина); точную причину определяют очно по анализам и осмотру."
            ),
            "actions": [
                "Запишитесь к гинекологу и эндокринологу без отлагательств; не начинайте самостоятельно гормональную терапию.",
                "Часто назначают ТТГ, свободный Т4, пролактин (иногда утром, натощак и с правильной подготовкой); при необходимости УЗИ малого таза и молочных желез по показаниям.",
                "Если есть головные боли или ухудшение зрения на фоне этих симптомов — сообщите об этом при приёме неотложно.",
                "Используйте надёжную контрацепцию до выяснения причины, если есть половая жизнь.",
            ],
            "urgent": [
                "очень сильная стойкая головная боль или быстрое ухудшение зрения",
                "выраженная слабость, обморок, спутанность сознания",
            ],
        }

    if _cfb_athletic_amenorrhea(t):
        return {
            "hypothesis": (
                "При высоких нагрузках отсутствие месячных длительное время относится к «красным флагам» женского здоровья "
                "(энергодефицит/избыточные тренировки и др.); нужна очная оценка гинеколога и спортивного врача."
            ),
            "actions": [
                "Не игнорируйте отсутствие цикла как «норму спортсменки»: обсудите нагрузку, питание и набор веса/жира по показаниям.",
                "Часто нужны ОАК, ферритин, обмен костного метаболизма по решению врача; коррекция нагрузки и питания — только под наблюдением.",
                "При болях в костях, частых переломах, выраженной усталости — сообщите врачу.",
            ],
            "urgent": [
                "частые переломы или острая сильная костная боль без травмы",
                "выраженная одышка в покое, обмороки или тяжёлая головная боль",
            ],
        }

    if _cfb_panic_somatic(t):
        return {
            "hypothesis": (
                "Сочетание сильной тревоги, учащённого сердцебиения и ощущения нехватки воздуха часто встречается при панических атаках "
                "и выраженном стрессе, но всегда нужно исключить сердечно-сосудистые и другие опасные причины очно."
            ),
            "actions": [
                "При первом тяжёлом эпизоде или сомнениях лучше сделать ЭКГ и базовый приём у терапева в ближайшее время.",
                "На фоне приступа: медленное дыхание (вдох на 4 счёта — пауза — выдох на 4–6), холодная вода на запястья, выход на свежий воздух; ограничить кофеин.",
                "При повторяющихся приступах обсудите терапию тревоги с врачом или психотерапевтом.",
            ],
            "urgent": [
                "давящая боль в груди более 15–20 минут, отдающая в руку/челюсть, с холодным потом",
                "выраженная одышка в покое независимо от тревоги, обморок или потеря сознания",
            ],
        }

    if _cfb_hypothyroid_pattern(t):
        return {
            "hypothesis": (
                "Холодная непереносимость, сильная усталость и набор веса могут соответствовать снижению функции щитовидной железы "
                "или другим эндокринным и общим причинам — это подтверждается анализами."
            ),
            "actions": [
                "Запишитесь к терапевту или эндокринологу; базово часто оценивают ТТГ и свободный Т4 (список уточнит врач).",
                "Не начинайте самостоятельно гормоны щитовидной железы и йод без назначения.",
                "До приёма врача соблюдайте режим сна и питания по переносимости, без жёстких диет.",
            ],
            "urgent": [
                "сильная сонливость и спутанность сознания, отёки лица/языка",
                "выраженная одышка в покое или боль в груди",
            ],
        }

    if _cfb_thyroid_and_infection(t):
        return {
            "hypothesis": (
                "При заболеваниях щитовидной железы иммунитет и переносимость инфекций могут меняться; частые простуды также бывают при других причинах "
                "(дефициты, аллергия бронхов, контакты) — нужна очная сбор анамнеза и прицельные анализы."
            ),
            "actions": [
                "Контроль функции щитовидной железы по назначению врача (ТТГ/гормоны); не менять дозы самостоятельно.",
                "При частых ОРВИ — обсудить календарь прививок, железо/витамин D и режим сна по результатам анализов.",
                "Гигиена, сон, питание с достаточным белком; не антибиотики «на всякий случай» без показаний.",
            ],
            "urgent": [
                "высокая температура несколько дней подряд с выраженной слабостью",
                "одышка в покое или боль в груди",
            ],
        }

    if _cfb_stress_abdominal_gain(t):
        return {
            "hypothesis": (
                "Хронический стресс сопровождается активацией симпатической системы и часто влияет на аппетит и распределение жира; "
                "рост живота также может быть связан с гормональными и метаболическими причинами — их различают очно."
            ),
            "actions": [
                "Регулярный сон, ограничение алкоголя и поздних перекусов; дневник стресса и триггеров.",
                "Умеренная активность без крайностей; при наборе веса — измерения талии и динамика веса 2–4 недели.",
                "Если живот растёт быстро, есть боли или нарушения цикла — гинеколог/эндокринолог по показаниям.",
            ],
            "urgent": [
                "очень быстрый рост живота за недели, сильная боль или рвота",
                "выраженная одышка или отёки ног",
            ],
        }

    if _cfb_pcos_like(t):
        return {
            "hypothesis": (
                "Сочетание абдоминального набора веса, нарушений цикла и акне нередко наводит на мысль о метаболическом/гормональном профиле "
                "(включая СПКЯ), но диагноз ставят только очно по критериям и анализам."
            ),
            "actions": [
                "Очная оценка гинеколога и эндокринолога; часто УЗИ и андрогены/глюкоза по назначению врача.",
                "Базовый фон движения и питание с контролем простых углеводов — по переносимости и без крайних диет.",
                "Не принимать самостоятельно гормональные препараты «для цикла» без обследования.",
            ],
            "urgent": [
                "сильные боли внизу живота или подозрение на беременность с кровотечением",
                "быстрый рост волос/акне на фоне быстрого ухудшения самочувствия",
            ],
        }

    if _cfb_scoliosis_teen(t):
        return {
            "hypothesis": (
                "Сколиоз II степени и боль в спине требуют очной оценки ортопеда и физической реабилитации; боль может быть связана с мышечным дисбалансом "
                "и нагрузками."
            ),
            "actions": [
                "Подтвердите степень и динамику у ортопеда; обсудите корсет, ЛФК и эргономику ранца/парты.",
                "Избегайте тяжёлых осевых нагрузок без рекомендаций; равномерная активность укрепляет мышечный корсет.",
                "Если боль усиливается ночью, есть лихорадка или неврологические симптомы — нужен срочный осмотр.",
            ],
            "urgent": [
                "слабость в ногах, нарушение мочеиспускания или онемение в промежности",
                "тяжёлая травма спины на фоне сильной боли",
            ],
        }

    if _cfb_severe_acne(t):
        return {
            "hypothesis": (
                "Выраженное акне на лице и спине часто требует очной дерматологической терапии (в т.ч. системной); самолечение может оставить рубцы и пятна."
            ),
            "actions": [
                "Запись к дерматологу; не выдавливать воспалительные элементы — риск рубцев и инфекции.",
                "Мягкое очищение 2 раза в день, некомедогенная косметика; солнцезащита по типу кожи.",
                "При подозрении на гормональный компонент у женщин — очная оценка по показаниям.",
            ],
            "urgent": [
                "быстро нарастающий отёк лица/губ с затруднением дыхания",
                "высокая температура на фоне выраженной сыпи",
            ],
        }

    if _cfb_skin_aging_cosmetic(t):
        return {
            "hypothesis": (
                "Потеря упругости и мелкие морщины связаны с возрастными и фотоиндуцированными изменениями кожи, а также с уходом и образом жизни; "
                "иногда добавляют дефициты и гормональный фон."
            ),
            "actions": [
                "Ежедневный SPF, гидратация, ретиноиды/пептиды только по назначению дерматолога для вашего типа кожи.",
                "Не курить; достаточный сон и белок в рационе поддерживают кожу.",
                "При быстром ухудшении тургора или сочетании с необъяснимой слабостью — общий осмотр и базовые анализы.",
            ],
            "urgent": [
                "быстрое распространение зуда/сыпи по всему телу с отёком",
                "выраженное ухудшение за короткий срок на фоне температуры",
            ],
        }

    if _cfb_omega3_supplement(t):
        return {
            "hypothesis": (
                "Омега-3 (EPA/DHA) могут поддерживать сердечно-сосудистое здоровье и воспалительный фон при дефиците жирной кислотной составляющей рациона; "
                "эффект «для мозга и настроения» индивидуален и не заменяет лечение депрессии или тревоги по назначению врача."
            ),
            "actions": [
                "Перед добавкой обсудите дозу с врачом, если принимаете антикоагулянты, беременность/лактация или есть аллергия на рыбу.",
                "Проверьте качество продукта (концентрация EPA/DHA на порцию), храните по инструкции.",
                "Базово полезно 2 порции жирной рыбы в неделю как альтернатива или дополнение к добавке.",
            ],
            "urgent": [
                "отёк губ/языка или затруднённое дыхание после приёма добавки",
                "кровотечение/синячность на фоне новых препаратов — обсудить с врачом срочно",
            ],
        }

    if _cfb_stress_concentration_irritable(t):
        return {
            "hypothesis": (
                "Раздражительность, снижение концентрации и ощущение «нервов на пределе» часто связаны с хроническим стрессом, недосыпом и перегрузкой; "
                "редко добавляются дефициты и щитовидная железа — это проверяют очно при стойкой симптоматике."
            ),
            "actions": [
                "Гигиена сна и фиксированное время без экранов перед сном; короткие перерывы в работе каждые 60–90 минут.",
                "Умеренная физическая активность и ограничение кофеина после полудня.",
                "Если симптомы мешают учёбе/работе более 2 недель — терапевт или психотерапевт.",
            ],
            "urgent": [
                "мысли о самоповреждении или ощущение потери контроля над поведением",
                "спутанность сознания, галлюцинации или резкая невозможность сосредоточиться",
            ],
        }

    if _cfb_recurrent_uri(t):
        return {
            "hypothesis": (
                "Частые простуды зимой часто связаны с контактами в закрытых помещениях, сухим воздухом, недосыпом и индивидуальными факторами иммунитета; "
                "реже нужно исключать аллергию, астму и дефициты."
            ),
            "actions": [
                "Проверьте календарь прививок с терапевтом; обсудите железо, витамин D и сон при повторяющихся эпизодах.",
                "Мойте руки, проветривайте, увлажняйте слизистую изотоническими спреями при сухости.",
                "Не принимайте антибиотики без назначения при «простуде» без признаков бактериальной инфекции.",
            ],
            "urgent": [
                "одышка в покое, синюшность губ или выраженная слабость",
                "высокая температура более 3 суток или возвращающаяся лихорадка",
            ],
        }

    if _cfb_circadian_phone(t):
        return {
            "hypothesis": (
                "Позднее использование экрана и эмиссивный свет сдвигают циркадный ритм и ухудшают глубину сна; утром это даёт инерцию отключения мелатонина."
            ),
            "actions": [
                "За 60–90 минут до сна — без телефона; при необходимости режим «ночь», тёплый свет, чтение бумаги.",
                "Фиксированный подъём даже в выходные ±30 минут; утренний свет 10–15 минут.",
                "Кофеин только до раннего послеобеда; лёгкий завтрак для запуска дня.",
            ],
            "urgent": [
                "выраженная дневная сонливость за рулём или при работе на высоте",
                "галлюцинации или спутанность после бессонницы",
            ],
        }

    if _cfb_early_menarche_peers(t):
        return {
            "hypothesis": (
                "Раннее менархе на фоне нормальных параметров роста чаще является вариантом индивидуального графика полового созревания; "
                "сравнение с одноклассницами не является медицинским критерием."
            ),
            "actions": [
                "Если цикл устанавливается в пределах года и нет сильной боли/обильного кровотечения — наблюдение у детского гинеколога по показаниям.",
                "Обсудите с родителями гигиену, боль и настроение; при стеснении можно начать с терапевта или школьного врача.",
                "При отсутствии других признаков полового созревания или очень раннем возрасте (<8 лет) нужна очная оценка без отлагательств.",
            ],
            "urgent": [
                "очень обильное кровотечение или сильные боли, вызывающие обморок",
                "отсутствие признаков полового созревания при уже начавшихся месячных — очно к врачу",
            ],
        }

    if _cfb_delayed_puberty_male(t):
        return {
            "hypothesis": (
                "Отсутствие мутации голоса и малая мышечная масса в 15–17 лет может быть вариантом позднего созревания, но нужно исключить эндокринные и другие причины очно."
            ),
            "actions": [
                "Запись к подростковому эндокринологу или терапевту; часто оценивают рост, половое развитие по шкале Tanner, гормоны по показаниям.",
                "Не использовать анаболики и добавки без контроля — это опасно для роста и гормональной оси.",
                "Питание с достаточным калорийным и белковым составом для возраста и активности.",
            ],
            "urgent": [
                "очень медленный рост или отсутствие полового развития при старше 16 лет — приоритетная очная оценка",
                "тяжёлая головная боль или ухудшение зрения на фоне других симптомов",
            ],
        }

    if _cfb_hair_loss_diffuse(t):
        return {
            "hypothesis": (
                "Диффузное выпадение волос за месяцы часто связано с телогенным выпадением после стресса, дефицита железа/витаминов, гормональными сдвигами или заболеваниями кожи головы — различают очно."
            ),
            "actions": [
                "Очный осмотр дерматолога и базовые анализы по назначению (часто ОАК, ферритин, ТТГ, витамин D).",
                "Бережный уход без агрессивной укладки; не начинать миноксидил без рекомендации врача при неясной причине.",
                "Учитывать причёсывание и стресс; дневник выпадения 2–4 недели помогает врачу.",
            ],
            "urgent": [
                "очаговые гладкие пятна на коже головы с полным облысением за дни",
                "выраженная слабость, переломы или другие признаки тяжёлой патологии",
            ],
        }

    if _cfb_oily_acne_chin(t):
        return {
            "hypothesis": (
                "Жирная кожа и воспалительные элементы на подбородке чаще связаны с себумом, гормональными колебаниями цикла и уходом; иногда — с пищевыми триггерами и косметикой."
            ),
            "actions": [
                "Некомедогенное очищение 2 раза в день; кислоты и ретиноиды только по рекомендации дерматолога для вашей кожи.",
                "Не трогать лица руками; менять наволочку 1–2 раза в неделю.",
                "При связи обострений с циклом — гинеколог/дерматолог по показаниям.",
            ],
            "urgent": [
                "быстрое распространение болезненной сыпи с температурой",
                "отёк губ/глаз с высыпаниями",
            ],
        }

    if _cfb_mood_lability(t):
        return {
            "hypothesis": (
                "Резкие перепады настроения могут быть связаны со стрессом, недосыпом, предменструальной фазой или другими состояниями настроения; "
                "при выраженной полярности нужна очная оценка специалиста."
            ),
            "actions": [
                "Дневник сна, настроения и триггеров 2 недели; стабильный режим и физическая активность умеренной интенсивности.",
                "Ограничить алкоголь и стимуляторы; при ухудшении — психотерапевт или психиатр по показаниям.",
                "Если есть мысли о самоповреждении — немедленно обратиться за помощью.",
            ],
            "urgent": [
                "мысли о суициде или план причинения себе вреда",
                "бессонница несколько суток и беспокойство с двигательным моторным беспокойством",
            ],
        }

    if _cfb_libido_followup_only(t):
        return {
            "hypothesis": (
                "Снижение либидо чаще связано со стрессом, депрессией/тревогой, недосыпом, конфликтами в паре, дефицитами "
                "(железо, витамин D), заболеваниями щитовидной железы и половых гормонов или приёмом некоторых препаратов; точную причину находят очно."
            ),
            "actions": [
                "Открыто обсудите с урологом/андрологом или терапевтом (для женщин также гинеколог/эндокринолог по показаниям); не стесняться темы — это обычный медицинский симптом.",
                "Часто назначают ОАК, ТТГ, половые гормоны по решению врача; самостоятельная гормональная «стимуляция либидо» опасна без контроля.",
                "Улучшить базу: сон, ограничение алкоголя, умеренная активность; при выгорании и тревоге может помочь психотерапия параллельно с телесной причиной.",
            ],
            "urgent": [
                "редкое половое возбуждение или приапизм при приёме новых препаратов — сразу сообщить врачу или в приёмную",
                "выраженная депрессия или мысли о самоповреждении",
            ],
        }

    if _cfb_fatigue_libido_training(t):
        return {
            "hypothesis": (
                "Снижение либидо и сил на тренировки может быть связано с перетренированностью, недосыпом, стрессом, дефицитами и гормональными причинами (включая тестостерон/щитовидную железу у мужчин) — выясняют очно."
            ),
            "actions": [
                "Сократить объём нагрузки на 20–30% на 2 недели при перегрузке; режим сна и белок в еде.",
                "Обсудить с терапевтом ОАК, ферритин, ТТГ и половые гормоны по показаниям.",
                "Не принимать тестостерон и стимуляторы без назначения.",
            ],
            "urgent": [
                "острая боль в яичках, отёк или травма промежности",
                "выраженная эректильная дисфункция на фоне боли в груди или одышки",
            ],
        }

    if _is_sleep_stress_anxiety_muscle_cluster(t):
        return {
            "hypothesis": (
                "Сочетание нарушенного сна, вечерней тревожности и мышечных спазмов чаще всего связано "
                "с перенапряжением нервной системы и хроническим стрессом; при судорогах возможны дефицит "
                "магния и других электролитов — это нужно отличать от других причин при очной оценке."
            ),
            "actions": [
                "Режим сна: подъём и отбой в одно время, без ярких экранов за час до сна; днём короткая прогулка.",
                "Ограничьте кофеин и энергетики после полудня; вечером лёгкий ужин без переедания и без алкоголя.",
                "При сведении мышц — мягкая растяжка и тепло на зону спазма; достаточно питья днём; при частых судорогах обсудите с врачом анализы (в т.ч. электролиты, магний).",
                "Если тревога нарастает, есть панические атаки или мысли о самоповреждении — к терапевту или психотерапевту без отлагательств.",
            ],
            "urgent": [
                "спутанность сознания, судорожный приступ с потерей сознания или очень высокая температура",
                "выраженная боль в груди с одышкой, онемение или внезапная слабость в конечности",
            ],
        }

    return None


def _cluster_fallback_medication_options(norm_msg: str) -> Optional[list[str]]:
    """Тексты для блока препаратов при срабатывании кластера (до доменных списков)."""
    t = norm_msg
    if not t:
        return None
    if _cfb_amenorrhea_galactorrhea(t) or _cfb_athletic_amenorrhea(t):
        return [
            "гормональная и симптоматическая терапия подбирается только врачом после анализов — самостоятельный приём препаратов противопоказан",
            "допаминовые агонисты или другие средства при гиперпролактинемии — строго по назначению эндокринолога",
            "обезболивающие при болях только по инструкции и после исключения острой патологии",
        ]
    if _cfb_panic_somatic(t):
        return [
            "при выраженной тревоге и панических атаках группы препаратов подбирает врач — не начинать самостоятельно бензодиазепины или антидепрессанты",
            "при наличии кардиологического диагноза — только ранее назначенные препараты по схеме врача",
            "растительные успокоительные по инструкции не заменяют очную оценку при сердечной симптоматике",
        ]
    if _cfb_hypothyroid_pattern(t) or _cfb_thyroid_and_infection(t):
        return [
            "левотироксин и другие гормоны щитовидной железы — только по назначению и с контролем анализов",
            "НПВП при простуде только при необходимости и без противопоказаний; антибиотики — только при подтверждении бактериальной инфекции врачом",
            "витамин D или железо — после подтверждения дефицита анализами",
        ]
    if _cfb_pcos_like(t) or _cfb_stress_abdominal_gain(t):
        return [
            "метформин или гормональная контрацепция при СПКЯ — только по назначению гинеколога/эндокринолога",
            "НПВП или спазмолитики при болях по инструкции при отсутствии противопоказаний",
            "БАД для похудения без очной оценки не использовать",
        ]
    if _cfb_severe_acne(t) or _cfb_oily_acne_chin(t):
        return [
            "ретиноиды системные и местные (в т.ч. изотретиноин) — только под контролем дерматолога из-за побочных эффектов и беременности",
            "местные ретиноиды/кислоты по инструкции для вашего типа кожи после очной консультации",
            "не комбинировать несколько агрессивных средств без рекомендации врача",
        ]
    if _cfb_skin_aging_cosmetic(t):
        return [
            "ретиноиды и кислотные продукты против старения кожи — только подбор дерматолога для вашего типа кожи",
            "SPF-препараты ежедневно — основная профилактика фото старения",
            "БАД с коллагеном не заменяют доказательную дерматологическую терапию",
        ]
    if _cfb_omega3_supplement(t):
        return [
            "рыбий жир/омега-3 как добавка — по инструкции и без замены антикоагулянтов без консультации при приёме разжижающих препаратов",
            "прием терапевтических доз решается с врачом при сердечно-сосудистых диагнозах",
            "не смешивать несколько добавок с омега-3 без учёта суммарной дозы",
        ]
    if _cfb_stress_concentration_irritable(t) or _cfb_mood_lability(t):
        return [
            "при стойкой тревоге или депрессии препараты назначает врач — самостоятельный подбор антидепрессантов опасен",
            "растительные успокоительные по инструкции при отсутствии противопоказаний",
            "мелатонин или снотворное — только по рекомендации врача при нарушении сна",
        ]
    if _cfb_recurrent_uri(t):
        return [
            "симптоматические средства для насморка/горла по инструкции при отсутствии противопоказаний",
            "иммуномодуляторы и антибиотики «профилактически» без назначения не использовать",
            "жаропонижающие при температуре выше 38.5 при плохой переносимости — по инструкции",
        ]
    if _cfb_circadian_phone(t):
        return [
            "мелатонин или снотворное для сдвига режима — только короткими курсами по назначению врача",
            "кофеин и энергетики после полудня ограничить без медикаментозной компенсации",
            "при необходимости назначения препаратов для СДВГ или тревоги — только очно при подростках",
        ]
    if _cfb_early_menarche_peers(t):
        return [
            "гормональная коррекция полового созревания только по строгим показаниям детского эндокринолога",
            "обезболивающие при дисменорее по инструкции после исключения патологии",
            "БАД «для роста» без очной оценки не использовать",
        ]
    if _cfb_delayed_puberty_male(t):
        return [
            "половые гормоны и аналоги ГнРГ — только по назначению эндокринолога с мониторингом роста и костного возраста",
            "спортивные добавки и анаболики без контроля запрещены в подростковом возрасте",
            "витамин D и железо — после анализов при дефиците",
        ]
    if _cfb_hair_loss_diffuse(t):
        return [
            "миноксидил и финастерид — только по показаниям дерматолога с учётом пола, возраста и планирования беременности",
            "витамины и биотин без подтверждения дефицита могут быть бесполезны",
            "специализированные шампуни от выпадения — как вспомогательное средство после очной причины",
        ]
    if _cfb_libido_followup_only(t):
        return [
            "гормоны и любые средства для либидо/эрекции — только после очной оценки уролога/андролога или эндокринолога и анализов",
            "ингибиторы ФДЭ-5 при эректильной дисфункции только по показаниям кардиолога при сердечных заболеваниях и приёме нитратов — не совмещать самостоятельно",
            "финастерид и аналоги без отмены по согласованию с назначившим врачом — возможны эффект на либидо",
        ]
    if _cfb_fatigue_libido_training(t):
        return [
            "тестостерон и другие гормональные препараты — только после очной оценки эндокринолога и анализов",
            "НПВП при болях после тренировки по инструкции при отсутствии противопоказаний",
            "стимуляторы и предтренировочные комплексы без контроля не комбинировать с сердечными симптомами",
        ]
    if _cfb_scoliosis_teen(t):
        return [
            "НПВП или парацетамол при боли по инструкции после еды при отсутствии противопоказаний",
            "миорелаксанты только по назначению врача при выраженном спазме",
            "корсет или фиксация — только по рекомендации ортопеда",
        ]
    if _is_sleep_stress_anxiety_muscle_cluster(t):
        return [
            "при стойкой тревоге или панических атаках препараты подбирает только врач — самостоятельный курс анксиолитиков или снотворного небезопасен",
            "магний или другие добавки при частых судорогах — только после консультации с учётом ваших заболеваний и текущих лекарств",
            "растительные успокоительные по инструкции не заменяют очную оценку при выраженных симптомах",
        ]
    return None


def _fallback_specific_plan(domain: str, user_message: str = "") -> dict[str, Any]:
    msg_fb = _norm_text_for_compare(user_message or "")
    cluster_plan = _cluster_based_fallback_plan(msg_fb)
    if cluster_plan is not None:
        return cluster_plan
    if domain == "respiratory":
        return {
            "hypothesis": "Похоже на инфекцию верхних дыхательных путей (ОРВИ/фарингит).",
            "actions": [
                "Пейте больше тёплой жидкости, проветривайте комнату, сохраняйте щадящий режим.",
                "Если температура выше 38.5 и переносится тяжело — жаропонижающее по инструкции.",
                "Для горла: полоскание тёплым солевым раствором 4-6 раз в день.",
                "Если за 24-48 часов не становится лучше — очно к терапевту или ЛОР-врачу.",
            ],
            "urgent": [
                "температура около 40 и не снижается или быстро снова растет после жаропонижающего",
                "одышка в покое или становится трудно дышать",
                "не можете пить из-за боли в горле или выраженная слабость/спутанность",
            ],
        }
    if domain == "gastro":
        return {
            "hypothesis": "Похоже на острое раздражение ЖКТ или кишечную инфекцию.",
            "actions": [
                "Пейте воду маленькими порциями, чтобы не допустить обезвоживания.",
                "На 12-24 часа щадящее питание: без жирного, острого и алкоголя.",
                "При повторной рвоте/диарее — раствор для регидратации по инструкции.",
                "Если боли или рвота сохраняются — очно к терапевту или гастроэнтерологу.",
            ],
            "urgent": [
                "рвота с кровью, чёрный стул или кровь в стуле",
                "сильная нарастающая боль в животе или признаки обезвоживания",
            ],
        }
    if domain == "cardio":
        return {
            "hypothesis": "Нужна очная проверка сердечно-сосудистых причин симптомов.",
            "actions": [
                "Ограничьте физнагрузку и контролируйте давление/пульс в покое.",
                "Не увеличивайте дозы сердечных препаратов без назначения врача.",
                "Избегайте кофеина, алкоголя и обезвоживания до стабилизации.",
                "В ближайшее время очно к терапевту или кардиологу.",
            ],
            "urgent": [
                "боль или давление в груди более 10 минут",
                "одышка в покое, обморок или выраженная слабость",
            ],
        }
    if domain == "neuro":
        return {
            "hypothesis": "Вероятна неврологическая причина симптомов, требуется очная оценка.",
            "actions": [
                "Покой, сон и снижение зрительной/шумовой нагрузки.",
                "Контроль давления и температуры каждые 4-6 часов.",
                "Не садитесь за руль и избегайте травмоопасных нагрузок.",
                "При сохранении симптомов очно к неврологу или терапевту.",
            ],
            "urgent": [
                "слабость в руке/ноге, перекос лица или нарушение речи",
                "внезапная очень сильная головная боль, спутанность или обморок",
            ],
        }
    if domain == "allergy_skin":
        return {
            "hypothesis": "Похоже на аллергическую реакцию или кожное воспаление.",
            "actions": [
                "Уберите возможный триггер и не используйте новые продукты/косметику.",
                "При зуде можно антигистаминный препарат по инструкции.",
                "Наблюдайте за дыханием и распространением отёка/сыпи.",
                "Если симптомы держатся — очно к терапевту, аллергологу или дерматологу.",
            ],
            "urgent": [
                "отёк губ/языка/горла или затруднённое дыхание",
                "быстрое распространение сыпи с головокружением и слабостью",
            ],
        }
    if domain == "gyneco":
        return {
            "hypothesis": "Похоже на боль, связанную с менструальным циклом: дисменорея и/или предменструальный синдром при типичной картине (без температуры, рвоты и жидкого стула).",
            "actions": [
                "Тепло на низ живота 15–20 минут, покой, сон; избегайте переохлаждения и интенсивных тренировок при сильной боли.",
                "При переносимости — обезболивающие из группы НПВП или парацетамол по инструкции после еды; не превышайте суточную дозу.",
                "Если боль новая для вас, очень сильная или с подозрением на беременность/задержку — очно к гинекологу или в женскую консультацию.",
                "Если появятся температура, выраженная слабость, рвота/понос или необычные выделения — очная оценка сегодня.",
            ],
            "urgent": [
                "сильная односторонняя боль внизу живота, обморок или выраженная слабость",
                "подозрение на беременность при задержке менструаций с болью или кровотечением",
            ],
        }
    if domain == "uro":
        return {
            "hypothesis": "Похоже на воспаление мочевыводящих путей.",
            "actions": [
                "Пейте больше воды, избегайте переохлаждения.",
                "Не откладывайте общий анализ мочи и очный осмотр.",
                "Не начинайте антибиотик без назначения врача.",
                "Очно к терапевту или урологу в ближайшее время.",
            ],
            "urgent": [
                "высокая температура с болью в пояснице",
                "кровь в моче, озноб или выраженная слабость",
            ],
        }
    if domain == "anorectal":
        return {
            "hypothesis": "Похоже на аноректальную причину: чаще всего геморрой (наружний/внутренний) и/или анальная трещина при крови после стула и боли в области заднего прохода.",
            "actions": [
                "Избегайте натуживания, пейте больше воды и нормализуйте мягкий ежедневный стул.",
                "Гигиена после стула: прохладная вода, без агрессивного трения и раздражающих средств.",
                "На 1-2 дня исключите острое и алкоголь, добавьте пищевые волокна и щадящий режим.",
                "В ближайшее время очно к проктологу/хирургу для подтверждения причины кровотечения.",
            ],
            "urgent": [
                "кровотечение усиливается, появляются сгустки, слабость, головокружение или предобморок",
                "сильная нарастающая боль, высокая температура или черный/темный стул",
            ],
        }
    if domain == "trauma":
        return {
            "hypothesis": "Вероятен ушиб или травматическое повреждение мягких тканей/сустава.",
            "actions": [
                "Покой, холод на 10-15 минут 3-4 раза в день первые сутки.",
                "Ограничьте нагрузку на травмированную область.",
                "При боли используйте обезболивание по инструкции.",
                "Очно к травматологу, если боль или отёк нарастают.",
            ],
            "urgent": [
                "деформация, невозможность опоры или нарастающий сильный отёк",
                "онемение, слабость конечности или выраженное кровотечение",
            ],
        }
    return {
        "hypothesis": "По текущим данным вероятен воспалительный процесс.",
        "actions": [
            "Покой, достаточное питьё и контроль самочувствия каждые 4-6 часов.",
            "Лекарства — только по инструкции и с учётом противопоказаний.",
            "При усилении симптомов не откладывайте очный осмотр.",
        ],
        "urgent": [
            "резкое ухудшение состояния или нарушение сознания",
            "сильная нарастающая боль или затруднение дыхания",
        ],
    }


def _fallback_medication_options(domain: str, user_message: str = "") -> list[str]:
    msg = _norm_text_for_compare(user_message or "")
    if domain == "respiratory":
        meds = [
            "жаропонижающие/обезболивающие (например, парацетамол или ибупрофен) при температуре выше 38.5 и плохой переносимости",
            "местные средства для горла (полоскания, пастилки/спреи с антисептическим эффектом)",
            "солевые растворы для носа при насморке и заложенности",
        ]
        if _looks_like_sputum_context(msg):
            meds.append("при подозрении на бактериальную инфекцию вопрос антибиотика решается только очно врачом")
        return meds
    if domain == "gastro":
        return [
            "оральные растворы для регидратации при рвоте/диарее",
            "симптоматические средства для ЖКТ по назначению врача",
            "спазмолитики по показаниям и только после очной оценки при выраженной боли",
        ]
    if domain == "cardio":
        return [
            "только ранее назначенные вам сердечно-сосудистые препараты по схеме врача",
            "самостоятельно не повышать дозировки и не добавлять новые препараты без очной консультации",
        ]
    if domain == "neuro":
        return [
            "обезболивающие по инструкции при переносимой головной боли",
            "при мигренозных приступах - только ранее назначенная врачом терапия",
        ]
    if domain == "allergy_skin":
        return [
            "антигистаминные препараты второго поколения по инструкции",
            "местные противозудные/смягчающие средства на кожу",
        ]
    if domain == "uro":
        return [
            "симптоматические обезболивающие/спазмолитики по инструкции",
            "вопрос антибиотиков решается только после анализа мочи и очного осмотра",
        ]
    if domain == "gyneco":
        return [
            "НПВП (например, ибупрофен/напроксен) или парацетамол по инструкции после еды при болезненных менструациях — при отсутствии противопоказаний",
            "спазмолитики по показаниям и только после очной оценки при неясной сильной боли",
            "комбинированные оральные контрацептивы или другая терапия дисменореи — только по назначению гинеколога",
        ]
    if domain == "anorectal":
        return [
            "ректальные свечи (в т.ч. с обезболивающим, противовоспалительным или венотоническим действием) — только по инструкции и при отсутствии противопоказаний",
            "наружные мази/гели для перианальной зоны по инструкции для боли и раздражения",
            "мягкий стул: клетчатка и при необходимости препараты для регуляции стула по инструкции (меньше натуживания — меньше травмы слизистой)",
        ]
    cm = _cluster_fallback_medication_options(msg)
    if cm is not None:
        return cm
    return [
        "симптоматические препараты по инструкции и только при отсутствии противопоказаний",
    ]


def _action_line_is_too_generic(line: str) -> bool:
    t = _norm_text_for_compare(line)
    generic_markers = (
        "по рецепту",
        "по инструкции",
        "динамик симптом",
        "контрол динамик",
        "очная консультац",
        "очная оценк",
        "в целом все понят",
    )
    return any(m in t for m in generic_markers)


def _filter_gyneco_incompatible_hypotheses(hypotheses: list[str]) -> list[str]:
    """Убрать ЖКТ/кишечную инфекцию из гипотез при циклическом контексте."""
    out: list[str] = []
    for h in hypotheses or []:
        hs = str(h or "").strip()
        if not hs:
            continue
        hn = _norm_text_for_compare(hs)
        if any(x in hn for x in ("кишечн инфекц", "кишечн", "гастроэнтерит", "острое раздражение", "жкт", "диаре", "понос", "рвот", "инфекц желуд")):
            continue
        out.append(hs)
    return out


# Сценарии с готовым безопасным ответом «с первого сообщения» (не clarify-first и не шаблон «Что вероятнее всего»).
_COMPLAINT_IDS_CANNED_FIRST_RESPONSE: frozenset[str] = frozenset(
    {
        "complaint_lab_indices_oncophobia",
        "complaint_postpartum_distress",
        "complaint_parental_academic_pressure",
        "complaint_knee_postinjury_training_return",
        "complaint_health_anxiety_mortality_fear",
        "complaint_prolonged_loss_of_appetite",
        "complaint_premenstrual_mood_sweet_craving",
        "complaint_chronic_fatigue_months_no_recovery",
        "complaint_adolescent_anhedonia_apathy",
        "complaint_nutrition_supplements_where_to_start",
        "complaint_gas_bloating",
        "complaint_heavy_menstrual_bleeding_fatigue_hair_loss",
        "complaint_irregular_menstrual_cycle_women",
        "complaint_acne_skin_hormonal_women",
        "complaint_weight_plateau_women",
        "complaint_hair_loss_diffuse_women",
        "complaint_persistent_fatigue_women",
        "complaint_low_mood_apathy_women",
        "complaint_edema_swelling_women",
        "complaint_painful_periods_dysmenorrhea_women",
        "complaint_sweet_craving_standalone_women",
    }
)


def _complaint_canned_patient_first_response(complaint_id: str) -> Optional[str]:
    cid = (complaint_id or "").strip()
    if cid in WOMENS_HEALTH_SCENARIO_CANNED:
        return WOMENS_HEALTH_SCENARIO_CANNED[cid]
    if cid == "complaint_lab_indices_oncophobia":
        return (
            "Понимаю, что это пугает.\n\n"
            "Повышенные лимфоциты чаще всего связаны не с раком, а с обычной реакцией организма — например, после инфекции.\n\n"
            "Важно:\n"
            "по одному анализу такие выводы не делают.\n\n"
            "Что делать:\n"
            "— посмотреть анализ в динамике\n"
            "— обсудить с врачом\n\n"
            "Если нет других серьёзных симптомов, это в большинстве случаев не опасно.\n\n"
            "Давайте при необходимости разберём ваш анализ подробнее — так будет спокойнее."
        )
    if cid == "complaint_postpartum_distress":
        return (
            "Слышу вас.\n\n"
            "То, что вы описываете — не редкость после рождения ребёнка. Это не про «плохую маму», а про состояние организма и психики.\n\n"
            "Что это может быть:\n"
            "— послеродовое истощение\n"
            "— гормональные изменения\n"
            "— эмоциональная перегрузка\n\n"
            "Важно:\n"
            "это состояние требует внимания, а не игнорирования.\n\n"
            "Что можно сделать:\n"
            "— не оставаться одной с этим\n"
            "— по возможности обсудить с врачом или психологом\n"
            "— дать себе отдых, насколько это возможно\n\n"
            "Если состояние держится или усиливается — лучше обратиться за помощью очно.\n\n"
            "Вы не обязаны справляться с этим в одиночку."
        )
    if cid == "complaint_parental_academic_pressure":
        return (
            "Слышу тебя.\n\n"
            "Когда постоянно давят и требуют, это может сильно выматывать и вызывать ощущение, что «ничего не хочется».\n\n"
            "Это не значит, что с тобой что-то не так — это реакция на стресс.\n\n"
            "Что можно сделать:\n"
            "— постараться немного снизить нагрузку, если есть возможность\n"
            "— поговорить с кем-то, кому доверяешь\n"
            "— хотя бы немного времени оставлять для себя\n\n"
            "Если состояние становится сильнее — важно не замыкаться и попросить помощи.\n\n"
            "Ты не обязан справляться со всем один."
        )
    if cid == "complaint_knee_postinjury_training_return":
        return (
            "Понимаю, как это тяжело.\n\n"
            "Когда после травмы долго не получается вернуться к тренировкам — это выбивает из привычного ритма.\n\n"
            "Что важно:\n"
            "восстановление занимает время, и это нормально.\n\n"
            "Что можно делать:\n"
            "— не сравнивать себя с прежним уровнем\n"
            "— постепенно возвращаться к нагрузке\n"
            "— при необходимости проверить состояние колена у врача\n\n"
            "Это временный этап, а не «конец формы»."
        )
    if cid == "complaint_health_anxiety_mortality_fear":
        return (
            "Слышу вас.\n\n"
            "Такие мысли могут появляться, когда есть тревога или непонятные симптомы.\n\n"
            "Важно:\n"
            "ощущение «вдруг я умру» чаще связано с тревогой, а не с реальной угрозой.\n\n"
            "Что можно сделать:\n"
            "— постараться успокоить дыхание\n"
            "— не накручивать себя поиском в интернете\n"
            "— при необходимости обсудить состояние с врачом\n\n"
            "Если такие мысли повторяются — лучше не оставаться с этим одному.\n\n"
            "С этим можно справиться."
        )
    if cid == "complaint_prolonged_loss_of_appetite":
        return (
            "Понимаю.\n\n"
            "Если аппетита нет уже долго — это важно не игнорировать.\n\n"
            "Что это может быть:\n"
            "— стресс или эмоциональное состояние\n"
            "— проблемы с ЖКТ\n"
            "— общее истощение\n\n"
            "Что делать:\n"
            "— не пропускать питание полностью\n"
            "— стараться есть небольшими порциями\n"
            "— обратиться к врачу, если это длится больше нескольких недель\n\n"
            "Организм даёт сигнал — важно его не игнорировать."
        )
    if cid == "complaint_chronic_fatigue_months_no_recovery":
        return (
            "Слышу вас.\n\n"
            "Если усталость держится месяцами и не проходит даже после сна — это уже не обычная усталость.\n\n"
            "Что это может быть:\n"
            "— дефициты (железо, B12, витамин D)\n"
            "— гормоны\n"
            "— стресс и перегрузка\n\n"
            "Что стоит проверить:\n"
            "— общий анализ крови\n"
            "— ферритин\n"
            "— ТТГ\n\n"
            "С этим состоянием можно разобраться, важно найти причину."
        )
    if cid == "complaint_adolescent_anhedonia_apathy":
        return (
            "Слышу тебя.\n\n"
            "Когда ничего не радует и нет сил — это не «характер» и не «лень».\n\n"
            "Это может быть связано с:\n"
            "— перегрузкой\n"
            "— стрессом\n"
            "— эмоциональным состоянием\n\n"
            "Важно:\n"
            "если такие ощущения держатся — лучше поговорить с кем-то взрослым или врачом.\n\n"
            "Ты не один с этим состоянием, и с ним можно справиться."
        )
    if cid == "complaint_gas_bloating":
        return (
            "Слышу вас.\n\n"
            "Постоянное вздутие, газы и дискомфорт в животе — это не норма, а сигнал от пищеварения, что что-то работает не так.\n\n"
            "Что это может быть:\n"
            "— часто: особенности питания (перекусы, сладкое, избыток быстрых углеводов)\n"
            "— также: чувствительность к отдельным продуктам (молочные, бобовые, хлеб)\n"
            "— возможно: дисбаланс кишечной микрофлоры\n"
            "— иногда: ферментная недостаточность или раздражённый кишечник\n\n"
            "Важно: обычно это не одна причина, а сочетание факторов.\n\n"
            "Что можно сделать уже сейчас:\n"
            "— попробовать есть более регулярно (2–3 раза в день без постоянных перекусов)\n"
            "— уменьшить сладкое, мучное и продукты, которые усиливают газообразование\n"
            "— есть спокойнее, не на ходу, хорошо пережёвывать\n"
            "— понаблюдать, после каких продуктов становится хуже\n\n"
            "Что стоит проверить, если это повторяется:\n"
            "— общий анализ крови\n"
            "— базовая биохимия\n"
            "— при необходимости — обследование ЖКТ по рекомендации врача\n\n"
            "Обратиться к врачу стоит, если:\n"
            "— вздутие держится постоянно и усиливается\n"
            "— есть боль, снижение веса или нестабильный стул\n"
            "— симптомы мешают повседневной жизни"
        )
    if cid == "complaint_heavy_menstrual_bleeding_fatigue_hair_loss":
        return (
            "Слышу вас.\n\n"
            "Обильные месячные + сильная усталость + выпадение волос — это не просто «особенность организма». Такая комбинация часто указывает на состояние, которое можно и нужно проверить.\n\n"
            "Что это может быть:\n"
            "— часто: дефицит железа (даже без выраженной анемии)\n"
            "— также: гормональный дисбаланс\n"
            "— возможно: проблемы со щитовидной железой\n"
            "— иногда: общий дефицит витаминов и микроэлементов\n\n"
            "Важно: при обильных месячных организм может терять железо быстрее, чем успевает его восполнять — отсюда усталость и выпадение волос.\n\n"
            "Что можно сделать уже сейчас:\n"
            "— не игнорировать это состояние\n"
            "— стараться поддерживать регулярное питание и отдых\n"
            "— по возможности снизить перегрузки\n\n"
            "С чего начать обследование:\n"
            "— общий анализ крови\n"
            "— ферритин (ключевой показатель запасов железа)\n"
            "— ТТГ\n"
            "— витамин B12\n"
            "— витамин D\n\n"
            "Эти анализы часто позволяют быстро понять причину.\n\n"
            "Обратиться к врачу стоит, если:\n"
            "— месячные очень обильные или становятся сильнее\n"
            "— выраженная слабость, головокружение\n"
            "— усиливается выпадение волос\n\n"
            "Важно:\n"
            "такие симптомы обычно имеют объяснимую причину, и при правильном подходе состояние можно значительно улучшить.\n\n"
            "Если хотите, можем уточнить:\n"
            "— как долго это длится?\n"
            "— менялась ли обильность со временем?\n\n"
            "Это поможет точнее понять причину и следующий шаг."
        )
    if cid == "complaint_nutrition_supplements_where_to_start":
        return (
            "Слышу вас — это частый и нормальный вопрос.\n\n"
            "Сейчас действительно очень много информации про питание и добавки, и она часто противоречивая — поэтому легко запутаться.\n\n"
            "Важно:\n"
            "начинать лучше не с добавок, а с базы — с питания и состояния организма.\n\n"
            "Почему это важно:\n"
            "если питание и режим не настроены, добавки почти не дают эффекта.\n\n"
            "Что это значит на практике:\n"
            "— сначала навести порядок в режиме питания (регулярность, без постоянных перекусов)\n"
            "— добавить нормальный белок и простую, понятную еду\n"
            "— не пытаться сразу сделать «идеально»\n\n"
            "Добавки имеет смысл подбирать не «на всякий случай», а по факту:\n"
            "— после оценки самочувствия\n"
            "— и, по возможности, базовых анализов\n\n"
            "С чего начать:\n"
            "— выровнять режим питания (2–3 приёма пищи в день)\n"
            "— пить достаточно воды\n"
            "— убрать явный «мусор» (сладкие напитки, мучное и частые перекусы)\n\n"
            "Что можно проверить, если есть усталость или вопросы по самочувствию:\n"
            "— общий анализ крови\n"
            "— ферритин\n"
            "— витамин D\n"
            "— витамин B12\n\n"
            "После этого уже можно понять, нужны ли добавки и какие именно.\n\n"
            "Важно:\n"
            "универсального набора добавок «для всех» не существует — всё зависит от состояния организма.\n\n"
            "Когда будут результаты, мы сможем объяснить вам его либо можем разобрать ваш текущий рацион, после чего я помогу собрать для вас простой и понятный план без перегруза."
        )
    return None


def _prior_user_turns_in_chat(chat_history: Optional[list[dict[str, Any]]]) -> int:
    """Число предыдущих реплик пользователя в истории (текущее сообщение в append ещё не включён)."""
    if not isinstance(chat_history, list):
        return 0
    return sum(
        1
        for entry in chat_history
        if isinstance(entry, dict) and str(entry.get("role") or "").lower() == "user"
    )


_HEAVY_MENSES_LIBRARY_ITEM_ID = "complaint_heavy_menstrual_bleeding_fatigue_hair_loss"


def _heavy_menses_iron_priority_fallback_plan() -> dict[str, Any]:
    return {
        "hypothesis": (
            "При обильных менструациях слабость, головокружение и выпадение волос часто сочетаются с кровопотерей "
            "и возможным дефицитом железа или снижением гемоглобина; также учитывают гормональные причины тяжёлого цикла "
            "и состояние щитовидной железы. Это повод обсудить очно с гинекологом или терапевтом и сдать ОАК с ферритином "
            "(ТТГ — по решению врача)."
        ),
        "actions": [
            "Очная оценка объёма кровопотери и при необходимости осмотр/УЗИ по назначению; лабораторно в ближайшие дни — ОАК и ферритин (ТТГ — если назначит врач).",
            "Режим: достаточно жидкости; при головокружении избегать интенсивных нагрузок; препараты железа и НПВП — только по схеме врача.",
            "Если кровотечение очень обильное или быстро нарастает слабость — не откладывать очную помощь.",
        ],
        "urgent": [
            "обморок или предобморок, быстро нарастающая слабость, выраженное сердцебиение или одышка в покое на фоне сильного кровотечения",
            "острая сильная боль внизу живота с интенсивным кровотечением",
            "головокружение с нарушением речи, слабостью в конечности или асимметрией лица",
        ],
    }


def _acute_non_gyneco_topic_shift(message: str) -> bool:
    """Явный сдвиг к острой неакушерской теме (инфаркт/инсульт), без гинекологического контекста в сообщении."""
    msg = _norm_text_for_compare(str(message or ""))
    if not msg:
        return False
    neuro_cardio = (
        "инфаркт",
        "инсульт",
        "за грудин",
        "боль в груди",
        "давит в груди",
        "спутан",
        "онемение лица",
        "онемение рук",
        "асимметрия лица",
        "половина тела",
        "половину тела",
    )
    if not any(k in msg for k in neuro_cardio):
        return False
    gyn = (
        "месячн",
        "менстру",
        "кровотеч",
        "маточн",
        "менорраг",
        "гинек",
        "обильн",
        "менструац",
    )
    return not any(k in msg for k in gyn)


def _followup_keeps_heavy_menses_anchor(
    message: str, chat_history: Optional[list[dict[str, Any]]]
) -> bool:
    if _acute_non_gyneco_topic_shift(message):
        return False
    blob = _merged_user_blob_for_complaint_clustering(message, chat_history)
    if _has_heavy_menstrual_fatigue_hair_loss_query(blob):
        return True
    if _prior_user_turns_in_chat(chat_history) == 0:
        return False
    hist_only = _merged_user_blob_for_complaint_clustering("", chat_history)
    if not _has_heavy_menstrual_fatigue_hair_loss_query(hist_only):
        return False
    msg_n = _norm_text_for_compare(str(message or ""))
    if len(msg_n) <= 64:
        return True
    short_follow_markers = (
        "месячн",
        "менстру",
        "кров",
        "обильн",
        "головокруж",
        "слабост",
        "устал",
        "волос",
        "день",
        "недел",
        "месяц",
        "ферритин",
        "гемоглобин",
        "анем",
        "желез",
        "гинек",
        "ттг",
        "щитовид",
    )
    return any(m in msg_n for m in short_follow_markers)


def _maybe_restore_heavy_menses_complaint_item(
    message: str,
    *,
    chat_history: Optional[list[dict[str, Any]]],
    selected: Optional[dict[str, Any]],
    consultation_state: dict[str, Any],
) -> Optional[dict[str, Any]]:
    if not _followup_keeps_heavy_menses_anchor(message, chat_history):
        return selected
    anchor = (
        consultation_state.get("complaint_library_anchor")
        if isinstance(consultation_state.get("complaint_library_anchor"), dict)
        else {}
    )
    anchor_id = str(anchor.get("item_id") or "").strip()
    blob = _merged_user_blob_for_complaint_clustering(message, chat_history)
    cluster_ok = _has_heavy_menstrual_fatigue_hair_loss_query(blob)
    if anchor_id != _HEAVY_MENSES_LIBRARY_ITEM_ID and not cluster_ok:
        return selected
    forced = get_complaint_reference_item_by_id(_HEAVY_MENSES_LIBRARY_ITEM_ID)
    if not isinstance(forced, dict) or not forced:
        return selected
    sid = str((selected or {}).get("id") or "").strip()
    if selected is None or sid != _HEAVY_MENSES_LIBRARY_ITEM_ID:
        return forced
    return selected


def _persist_complaint_library_anchor(uid: str, subject_id: Optional[str], item: Optional[dict[str, Any]]) -> None:
    if not item:
        return
    cid = str(item.get("id") or "").strip()
    if cid == _HEAVY_MENSES_LIBRARY_ITEM_ID:
        save_consultation_state(uid, {"complaint_library_anchor": {"item_id": cid}}, subject_id=subject_id)
    elif cid:
        save_consultation_state(uid, {"complaint_library_anchor": {"item_id": ""}}, subject_id=subject_id)


def _build_complaint_reference_response(
    item: dict[str, Any],
    user_message: str = "",
    style_hint: str = "A",
    *,
    chat_history: Optional[list[dict[str, Any]]] = None,
    skip_clarify_first: bool = False,
) -> str:
    if _is_endocrine_asthenic_switch_request(user_message):
        q = _get_clarify_followup_question_queue(item, user_message, chat_history=chat_history)
        first_q = q[0] if q else "Когда начались перепады настроения и усталость, и что сейчас усиливает симптомы?"
        lines = [
            "Понял вас. По описанию это похоже на эндокринно-астенический профиль (гормональная причина возможна, но не единственная).",
            "Что вероятнее всего:",
            "- гормональный фактор (щитовидная железа/стресс-ось, по показаниям половые гормоны)",
            "- дефицитные состояния (железо/ферритин, B12, витамин D)",
            "- влияние сна и хронического стресса",
            "Что проверить в первую очередь:",
            "- ТТГ и свободный Т4",
            "- общий анализ крови + ферритин",
            "- витамин B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца)",
            "Что делать сейчас:",
            "- не начинать гормональные препараты самостоятельно",
            "- стабилизировать сон (7-8 часов), питание и нагрузку на 5-7 дней",
            "- после анализов скорректировать план вместе с врачом",
            "Чтобы сузить причину, уточню один вопрос:",
            first_q,
        ]
        return "\n".join(lines)

    clarify_intro = "Понял."
    title = str(item.get("complaint") or item.get("name") or "жалоба").strip()
    tone = _match_human_tone_profile((title + " " + str(user_message or "")).strip())
    _ = str(tone.get("intro") or "").strip()
    domain = _effective_complaint_domain(item, user_message)
    domain = _refine_domain_from_clarified_history(user_message, domain)
    fallback_plan = _fallback_specific_plan(domain, user_message)
    if str(item.get("id") or "").strip() == _HEAVY_MENSES_LIBRARY_ITEM_ID and domain == "gyneco":
        fallback_plan = _heavy_menses_iron_priority_fallback_plan()
    hypotheses = _pick_list_text(item, ["top_hypotheses", "likely_causes", "diagnosis_hints"], limit=4)
    contextual_hyp = _diagnostic_hypotheses_for_message(user_message)
    if contextual_hyp:
        merged_h: list[str] = []
        seen_h: set[str] = set()
        for h in hypotheses + contextual_hyp:
            hs = str(h or "").strip()
            if not hs:
                continue
            hk = _norm_text_for_compare(hs)
            if hk in seen_h:
                continue
            seen_h.add(hk)
            merged_h.append(hs)
        hypotheses = merged_h[:6]
    hypotheses = _rank_and_label_hypotheses(user_message, hypotheses)
    if domain == "gyneco":
        hypotheses = _filter_gyneco_incompatible_hypotheses(hypotheses)
    if (
        str(item.get("id") or "").strip() == _HEAVY_MENSES_LIBRARY_ITEM_ID
        and domain == "gyneco"
        and _prior_user_turns_in_chat(chat_history) > 0
    ):
        iron_line = str(fallback_plan.get("hypothesis") or "").strip()
        if iron_line:
            hypotheses = [iron_line]
    # treatment_methods часто содержит режим/диету — не смешивать с блоком «препараты».
    medication = _pick_list_text(item, ["medication_options_safe_general"], limit=3)
    alternative = _pick_list_text(item, ["first_line_non_drug_steps", "first_aid", "treatment_basic"], limit=3)
    nutrition = _pick_list_text(item, ["nutrition_recommendations", "nutrition_advice"], limit=3)
    activity = _pick_list_text(item, ["physical_exercise_prevention_rehabilitation", "physical_activity_advice"], limit=3)
    red_flags = _pick_list_text(item, ["red_flags", "red_flags_specific"], limit=3)
    followups = _get_clarify_followup_question_queue(item, user_message, chat_history=chat_history)
    core_for_food = _user_complaint_without_clarification_log(user_message)
    is_food_trigger_context = _is_food_trigger_context_message(core_for_food)
    if domain == "anorectal" or _is_strong_anorectal_symptom_context(str(user_message or "")):
        is_food_trigger_context = False
    if domain == "gyneco" or _is_menstrual_cycle_lower_abdomen_context(str(user_message or "")):
        is_food_trigger_context = False

    lib_hyp_ok = bool(hypotheses)
    lib_med_ok = bool(medication)
    # Доменные fallback-формулировки, чтобы не было пустой канцелярщины.
    _def_hyp_line = str(fallback_plan.get("hypothesis") or "По текущим данным вероятен воспалительный процесс.")
    fallback_actions = [str(x).strip() for x in (fallback_plan.get("actions") or []) if str(x).strip()]
    fb_med_opts = _fallback_medication_options(domain, user_message)
    _def_med_line = (
        fb_med_opts[0]
        if fb_med_opts
        else "Симптоматические группы препаратов подбираются только очно; конкретное средство и доза — по рецепту или назначению врача."
    )
    use_merged_plain_summary = (not lib_hyp_ok) and (not lib_med_ok)
    if not lib_hyp_ok and lib_med_ok:
        hypotheses = [_def_hyp_line]
    elif lib_hyp_ok and not lib_med_ok:
        medication = fb_med_opts if fb_med_opts else [_def_med_line]
    elif use_merged_plain_summary:
        hypotheses = []
        medication = []
    if domain == "anorectal":
        medication = _fallback_medication_options(domain, user_message)
    if domain == "gyneco":
        medication = _fallback_medication_options(domain, user_message)
    if (
        domain == "gyneco"
        and str(item.get("id") or "").strip() == _HEAVY_MENSES_LIBRARY_ITEM_ID
        and _prior_user_turns_in_chat(chat_history) > 0
    ):
        medication = [
            "препараты железа — только по схеме врача после ОАК и ферритина; длительный курс без контроля не начинать самостоятельно",
            "НПВП или парацетамол по инструкции после еды при боли/спазме — если нет противопоказаний; при обильном кровотечении приём обсудить с врачом",
            "гормональная коррекция тяжёлого цикла или другие методы уменьшения кровопотери — только по назначению гинеколога",
        ]
    if not alternative:
        alternative = ["щадящий режим, сон и контроль динамики в ближайшие 24–48 часов."]
    if not nutrition:
        nutrition = ["лёгкая сбалансированная еда и достаточное питьё по самочувствию."]
    if not activity:
        activity = ["умеренная активность без перегрузки, с паузами на отдых."]

    food_tests: list[str] = []
    if is_food_trigger_context:
        medication = [
            "На этом этапе лекарства не подбираем вслепую: сначала исключите подозрительный продукт и подтвердите причину анализами.",
        ]
        alternative = [
            "Исключите подозрительный продукт минимум на 72 часа и отслеживайте динамику тошноты/головной боли.",
            "Пейте воду небольшими порциями, отдыхайте, не перегружайтесь.",
            "Ведите дневник питания и симптомов (что съели, через сколько началась реакция, как долго держалась).",
        ]
        nutrition = [
            "Щадящий рацион малыми порциями; временно убрать триггерные продукты (семечки/орехи, выдержанные сыры, ферментированное — по переносимости).",
            "Не пробуйте сразу несколько новых продуктов, чтобы не смазать картину.",
        ]
        activity = ["В день реакции — спокойный режим; к обычной нагрузке возвращаться после стабилизации."]
        food_tests = [
            "Общий IgE и специфические IgE к подозрительным продуктам (по согласованию с врачом).",
            "Гистамин/DAO (где доступно) и базовая биохимия крови (АЛТ, АСТ, билирубин, амилаза/липаза).",
            "После результатов — загрузите их на страницу «Анализы», разберу интерпретацию и следующий шаг.",
        ]

    use_clarify = (not skip_clarify_first) and _should_use_clarify_first_mode(user_message, item)
    item_id = str(item.get("id") or "").strip()
    if item_id in _COMPLAINT_IDS_CANNED_FIRST_RESPONSE:
        use_clarify = False
    canned_first = _complaint_canned_patient_first_response(item_id)
    # Длинный канонический «первый ответ» только на первой реплике пользователя в цепочке; иначе повтор всего блока на каждый ход.
    allow_canned_first_wall = (
        canned_first
        and not use_clarify
        and _prior_user_turns_in_chat(chat_history) == 0
        and not skip_clarify_first
    )
    if allow_canned_first_wall:
        appendix = format_female_health_appendix_for_complaint(item_id)
        if not appendix:
            appendix = format_fatigue_appendix_for_complaint(item_id)
        if not appendix:
            appendix = format_gi_appendix_for_complaint(item_id)
        return (canned_first + appendix) if appendix else canned_first

    if use_clarify:
        q_lines = followups
        first_question = q_lines[0] if q_lines else "Когда начались симптомы и как они меняются?"
        clarify_parts: list[str] = []
        clarify_parts.append(clarify_intro)
        clarify_parts.append(first_question)
        if red_flags and _should_inline_urgent_for_clarify(user_message, red_flags):
            urgent = red_flags[:2]
            clarify_parts.append("Если резко станет хуже — сразу 103:\n- " + "\n- ".join(urgent))
        return "\n".join(clarify_parts)

    # Для сценария "высокая температура + респираторный кластер" используем усиленный клинический шаблон.
    if domain == "respiratory" and _looks_like_high_fever(user_message):
        return _build_high_fever_respiratory_final_response(user_message)

    lines: list[str] = []
    # Жесткий короткий шаблон финала: 1 причина + 3 шага + 2 красных флага.
    lines.append("Что вероятнее всего:\n- " + _def_hyp_line)
    strict_actions = fallback_actions[:3]
    if len(strict_actions) < 3:
        strict_actions = (fallback_actions + [
            "Контролируйте температуру и самочувствие каждые 4-6 часов.",
            "Избегайте перегрузки и соблюдайте питьевой режим.",
            "Если за 24-48 часов не лучше — очно к врачу.",
        ])[:3]
    lines.append("Что делать сейчас:\n- " + "\n- ".join(strict_actions))
    med_items = [str(x).strip() for x in medication if str(x).strip()]
    if not med_items:
        med_items = _fallback_medication_options(domain, user_message)
    # Если из справочника попали строки из «что делать», заменить доменным списком.
    act_norm = {_norm_text_for_compare(x) for x in fallback_actions}
    if med_items and all(_norm_text_for_compare(m) in act_norm for m in med_items[:2]):
        med_items = _fallback_medication_options(domain, user_message)
    if med_items:
        lines.append(
            _medication_block_intro_similar_cases()
            + "\n- "
            + "\n- ".join(med_items[:3])
            + "\n"
            + _rx_only_medication_footer()
        )
    urgent_items = [str(x).strip() for x in red_flags if str(x).strip()]
    generic_urgent = {"резкое ухудшение состояния", "сильная нарастающая боль", "нарушение сознания"}
    if not urgent_items or all(_norm_text_for_compare(x) in generic_urgent for x in urgent_items[:2]):
        urgent_items = [str(x).strip() for x in (fallback_plan.get("urgent") or []) if str(x).strip()]
    if urgent_items:
        if _looks_like_high_fever(user_message) and domain == "respiratory":
            respiratory_urgent = [str(x).strip() for x in (fallback_plan.get("urgent") or []) if str(x).strip()]
            fever_urgent = "температура около 40 и не снижается или быстро снова растет после жаропонижающего"
            merged_urgent: list[str] = []
            seen_urgent: set[str] = set()
            for item_text in [fever_urgent] + respiratory_urgent + urgent_items:
                key = _norm_text_for_compare(item_text)
                if not key or key in seen_urgent:
                    continue
                seen_urgent.add(key)
                merged_urgent.append(item_text)
            urgent_items = merged_urgent
        lines.append("Срочно 103/неотложка, если:\n- " + "\n- ".join(urgent_items[:2]))
    return "\n".join(lines)


def _clear_clarify_followup_state(user_id: str, subject_id: str) -> None:
    save_consultation_state(user_id, {"clarify_followup": {"active": False}}, subject_id=subject_id)


def _merge_clarify_answers_for_finalize(original_message: str, answers: list[dict[str, Any]]) -> str:
    lines = [str(original_message or "").strip()]
    if answers:
        lines.append("")
        lines.append("Уточнения в диалоге:")
        for row in answers:
            q = str((row or {}).get("question") or "").strip()
            a = str((row or {}).get("answer") or "").strip()
            if q and a:
                lines.append(f"- {q} → {a}")
    return "\n".join(lines).strip()


def _user_complaint_without_clarification_log(text: str) -> str:
    """Отрезает блок «Уточнения в диалоге» — там могут быть фразы вроде «после еды» из вопросов ассистента и ложно включать food-trigger."""
    t = str(text or "").strip()
    low = t.lower()
    needle = "уточнения в диалоге"
    i = low.find(needle)
    if i == -1:
        return t
    return t[:i].strip()


def _is_strong_anorectal_symptom_context(msg: str) -> bool:
    """Явный проктологический контекст — не смешивать с аллерго/пищевым follow-up и ЖКТ."""
    t = _norm_text_for_compare(msg or "")
    if not t:
        return False
    markers = (
        "гемор",
        "геморро",
        "анус",
        "анальн",
        "прямой киш",
        "прямая киш",
        "задний проход",
        "задниц",
        "жоп",
        "дефекац",
        "кровь после стула",
        "протекла кров",
        "потекла кров",
        "туалет по большому",
        "по большому",
        "ректальн",
        "проктолог",
    )
    if any(x in t for x in markers):
        return True
    # Бытовая формулировка: туалет «по-большому» + кровь (в т.ч. «потекла», не только «протекла»).
    if ("туалет" in t and "по большому" in t) and any(x in t for x in ("кров", "потек", "протек", "кровотеч")):
        return True
    if ("жоп" in t or "задниц" in t) and any(x in t for x in ("бол", "кров", "трещ", "кровотеч", "узел")):
        return True
    return False


def _try_clarify_followup_reply(
    *,
    uid: str,
    sid: str,
    msg: str,
    channel: str,
) -> Optional[dict[str, Any]]:
    """Пошаговое уточнение: один вопрос за раз, состояние в consultation_state."""
    st = get_consultation_state(uid, subject_id=sid) or {}
    cf = st.get("clarify_followup")
    if not isinstance(cf, dict) or not cf.get("active"):
        return None
    original_message = str(cf.get("original_message") or "").strip()
    if _user_constitutional_fatigue_primary(original_message):
        _clear_clarify_followup_state(uid, sid)
        return None
    item = cf.get("item")
    if not isinstance(item, dict):
        _clear_clarify_followup_state(uid, sid)
        return None
    questions = [str(q).strip() for q in (cf.get("questions") or []) if str(q).strip()]
    if not questions:
        _clear_clarify_followup_state(uid, sid)
        return None
    awaiting = int(cf.get("awaiting_question_index") or 0)
    answers = [dict(x) for x in (cf.get("answers") or []) if isinstance(x, dict)]
    ab_style = str(cf.get("ab_style") or "A").strip().upper()
    if awaiting < 0 or awaiting >= len(questions):
        _clear_clarify_followup_state(uid, sid)
        return None

    msg_clean = str(msg or "").strip()
    if _is_clarify_rephrase_request(msg_clean):
        current_q = questions[awaiting] if 0 <= awaiting < len(questions) else ""
        structured = _common_complaint_structured(item, user_message=str(original_message or "").strip())
        structured["ab_style"] = ab_style
        structured["clarify_followup"] = {"phase": "question", "step": awaiting + 1, "total": len(questions)}
        if "suggested_questions" not in structured:
            structured["suggested_questions"] = []
            structured["action_sequence"] = []
            structured["insufficient_data"] = False
        return {
            "response": _clarify_rephrase_response(current_q),
            "structured": structured,
            "response_source": f"clarify_rephrase_{channel}",
            "has_red_flags": bool(item.get("red_flags") or item.get("red_flags_specific")),
            "knowledge_topic": str(original_message or "").strip()[:300],
        }
    if _is_dialog_reset_request(msg_clean):
        _clear_clarify_followup_state(uid, sid)
        return {
            "response": _dialog_reset_response(),
            "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
            "response_source": f"clarify_flow_reset_{channel}",
            "has_red_flags": False,
            "knowledge_topic": "",
        }
    if _is_audio_clarity_request(msg_clean):
        _clear_clarify_followup_state(uid, sid)
        return {
            "response": _audio_clarity_response(),
            "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
            "response_source": f"clarify_audio_check_{channel}",
            "has_red_flags": False,
            "knowledge_topic": "",
        }
    if _looks_like_full_complaint_message(msg_clean):
        current_domain = _effective_complaint_domain(item, msg_clean)
        original_domain = _effective_complaint_domain(item, original_message)
        word_count = len([w for w in re.split(r"\s+", msg_clean) if w])
        # Пользователь сформулировал новую жалобу: прерываем старую цепочку уточнений.
        if word_count >= 10 or (current_domain != "general" and (original_domain == "general" or current_domain != original_domain)):
            _clear_clarify_followup_state(uid, sid)
            return None

    answers.append({"question": questions[awaiting], "answer": msg_clean})
    next_idx = awaiting + 1
    has_red_flags = bool(item.get("red_flags") or item.get("red_flags_specific"))

    if next_idx < len(questions):
        save_consultation_state(
            uid,
            {
                "clarify_followup": {
                    "active": True,
                    "ab_style": ab_style,
                    "item": item,
                    "questions": questions,
                    "awaiting_question_index": next_idx,
                    "original_message": original_message,
                    "answers": answers,
                }
            },
            subject_id=sid,
        )
        n_total = len(questions)
        response = questions[next_idx]
        known_for_struct = (str(original_message or "").strip() + "\n" + str(msg or "").strip()).strip()
        structured = _common_complaint_structured(item, user_message=known_for_struct)
        structured["ab_style"] = ab_style
        structured["clarify_followup"] = {"phase": "question", "step": next_idx + 1, "total": n_total}
        if "suggested_questions" not in structured:
            structured["suggested_questions"] = []
            structured["action_sequence"] = []
            structured["insufficient_data"] = False
        return {
            "response": response,
            "structured": structured,
            "response_source": f"complaint_clarify_step_{channel}",
            "has_red_flags": has_red_flags,
            "knowledge_topic": str(msg or "").strip()[:300],
        }

    _clear_clarify_followup_state(uid, sid)
    enriched = _merge_clarify_answers_for_finalize(original_message, answers)
    response = _build_complaint_reference_response(item, enriched, style_hint=ab_style, skip_clarify_first=True)
    structured = _common_complaint_structured(item, user_message=enriched)
    structured["ab_style"] = ab_style
    structured["clarify_followup"] = {"phase": "completed", "answered": len(answers)}
    if "suggested_questions" not in structured:
        structured["suggested_questions"] = []
        structured["action_sequence"] = []
        structured["insufficient_data"] = False
    return {
        "response": response,
        "structured": structured,
        "response_source": f"complaint_reference_library_ab_{ab_style}_clarify_done_{channel}",
        "has_red_flags": has_red_flags,
        "knowledge_topic": enriched[:300],
    }


def _record_voice_quality_event(
    *,
    source: str,
    complaint: Optional[str] = None,
    severity: Optional[str] = None,
) -> None:
    """Лёгкий журнал voice-качества в runtime analytics (без LLM-затрат)."""
    try:
        record_runtime_event(
            source=source,
            llm_used=False,
            model_used=None,
            protocol_source="voice_quality",
            complaint=(complaint or "")[:300],
            cluster="voice_quality",
            severity=severity or "",
            prompt_chars=0,
            response_chars=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0,
        )
    except Exception:
        pass


def _save_default_voice_state(user_id: str, subject_id: Optional[str] = None) -> None:
    try:
        save_consultation_state(
            user_id,
            {"voice_concierge": default_voice_state()},
            subject_id=subject_id,
        )
    except Exception:
        pass


def _run_knowledge_enrichment_followup_api(
    *,
    uid: str,
    sid: str,
    topic: str,
    red_flags_present: bool,
    llm_used: bool,
    response_source: str,
) -> dict[str, Any]:
    """Постановка фонового обогащения по теме (без блокировки ответа пользователю)."""
    try:
        from app.services.knowledge_enrichment_queue import enqueue_knowledge_enrichment_followup

        if red_flags_present:
            return {"queued": False, "reason": "skipped_red_flags"}
        topic_clean = (topic or "").strip()
        if len(topic_clean) < 8:
            return {"queued": False, "reason": "topic_too_short"}
        return enqueue_knowledge_enrichment_followup(
            user_id=uid,
            subject_id=sid,
            topic=topic_clean[:500],
            llm_used=llm_used,
            response_source=response_source,
        )
    except Exception:
        return {"queued": False, "reason": "error"}


def _get_last_assistant_message(messages: list) -> Optional[str]:
    """Последнее сообщение ассистента в истории чата (рекомендации для «Повтори»)."""
    if not messages:
        return None
    for i in range(len(messages) - 1, -1, -1):
        m = messages[i] if isinstance(messages[i], dict) else {}
        if str(m.get("role") or "").strip().lower() == "assistant":
            content = (m.get("content") or "").strip()
            if content:
                return content
    return None


def _norm_text_for_compare(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\wа-яёА-ЯЁ ]+", " ", str(text or "").lower())).strip()


def _strip_appended_assistant_blob_after_user_paragraph(tail: str) -> str:
    """Если после абзаца пользователя UI вставил ответ ассистента (типичный текст про ОАК), не тащим его в complaint-поиск."""
    s = str(tail or "").strip()
    if "\n\n" not in s:
        return s
    head, rest = s.split("\n\n", 1)
    head = head.strip()
    rest = (rest or "").strip()
    if not head or not rest:
        return s
    r = rest.lower().replace("ё", "е")

    def _looks_like_assistant_reply_blob() -> bool:
        if r.startswith("повышенные лимфоцит") or r.startswith("повышенные лейкоцит"):
            return True
        if r.startswith("понимаю,") and ("это пугает" in r[:160] or "это страшно" in r[:160]):
            return True
        if r.startswith("если нет других серьезных"):
            return True
        if r.startswith("важно:") and "что делать" in r[:400]:
            return True
        if r.startswith("что делать:") and ("анализ" in r[:500] or "лимфоцит" in r[:500] or "оак" in r[:500]):
            return True
        return False

    return head if _looks_like_assistant_reply_blob() else s


def _strip_dialog_question_prefix(text: str) -> str:
    """Снимает служебный префикс «Вопрос: …» из UI, чтобы complaint-first не цеплялся к «вопрос» в мусорных карточках.

    В многострочном вводе «Вопрос:» часто идёт после подсказок — берём хвост после последнего «Вопрос:» по строке.
    """
    t = str(text or "").strip()
    if not t:
        return t
    parts = re.split(r"(?is)(?:^|\n)\s*вопрос\s*[:.;,]?\s*", t)
    if len(parts) > 1:
        tail = parts[-1].strip()
        if tail:
            t = tail
    low = t.lstrip().lower()
    if low.startswith("вопрос"):
        t2 = re.sub(r"(?is)^вопрос\s*[:.;,]?\s*", "", t).strip()
        if t2:
            t = t2
    return _strip_appended_assistant_blob_after_user_paragraph(t)


def _token_overlap_ratio(a: str, b: str) -> float:
    ta = [x for x in _norm_text_for_compare(a).split(" ") if len(x) >= 3]
    tb = [x for x in _norm_text_for_compare(b).split(" ") if len(x) >= 3]
    if not ta or not tb:
        return 0.0
    bset = set(tb)
    hit = sum(1 for t in ta if t in bset)
    return hit / max(1, len(ta))


def _is_near_duplicate_answer(current: str, previous: str) -> bool:
    cur = str(current or "").strip()
    prev = str(previous or "").strip()
    if not cur or not prev:
        return False
    if _norm_text_for_compare(cur) == _norm_text_for_compare(prev):
        return True
    if len(cur) < 80 or len(prev) < 80:
        return False
    return _token_overlap_ratio(cur, prev) >= 0.82


def _first_text(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            if isinstance(item, dict):
                for k in ("text", "name", "label", "title", "description"):
                    v = str(item.get(k) or "").strip()
                    if v:
                        return v
    if isinstance(value, dict):
        for k in ("text", "name", "label", "title", "description"):
            v = str(value.get(k) or "").strip()
            if v:
                return v
    return ""


def _structured_pick(structured: dict, keys: list[str]) -> str:
    for k in keys:
        if k in structured:
            txt = _first_text(structured.get(k))
            if txt:
                return txt
    return ""


def _fallback_plan_blocks(user_message: str) -> tuple[str, str, str, str]:
    um = _norm_text_for_compare(user_message or "")
    food_trigger_markers = ("после еды", "поел", "семеч", "орех", "творог", "сыр", "кефир", "молок")
    treatment = (
        "Контроль симптомов и щадящий режим 24–48 часов с оценкой динамики. "
        "Витамины и добавки не подменяют очный осмотр: при стойких жалобах — обсудить с врачом анализы и целесообразность препаратов."
    )
    alternative = (
        "Немедикаментозно: сон, вода, короткие прогулки на свежем воздухе при силах, снижение стресса и перегруза без «догонки» самочувствия."
    )
    nutrition = (
        "Регулярные приёмы пищи: белок, крупы, овощи/фрукты, вода; меньше сахара, алкоголя и ультрапереработки; ориентир по овощам/фруктам — около 400 г/сутки (ВОЗ), если нет противопоказаний."
    )
    activity = (
        "По возможности 15–30 минут умеренной ходьбы или лёгкой гимнастики в день; при температуре и выраженной слабости — отдых вместо нагрузки. "
        "После выздоровления ориентир по ВОЗ — наращивать до ~150 мин умеренной активности в неделю."
    )
    if any(w in um for w in food_trigger_markers):
        treatment = "Вероятна реакция на пищевой триггер: пауза в еде 2–3 часа, небольшие порции воды, контроль тошноты и головной боли."
        alternative = (
            "Без лекарств: исключить предполагаемый триггер на 48–72 часа, вести дневник реакции. "
            "Ферменты/сорбенты — только по согласованию с врачом и инструкции, не «наугад»."
        )
        nutrition = "Щадящее питание малыми порциями: вода, сухари/рис/банан; без жирного, острого, алкоголя и потенциальных триггеров; при длительной диарее — обсудить регидратацию и электролиты с врачом."
        activity = "Покой сегодня; завтра — лёгкая ходьба 10–15 минут, если лучше; без силовых тренировок до нормализации ЖКТ."
    elif any(w in um for w in ("горл", "кашл", "насморк", "температ", "простуд")):
        treatment = "Тёплое питьё, контроль температуры, местная симптоматическая терапия по инструкции и наблюдение."
        alternative = (
            "Без лекарств: увлажнение воздуха, отдых голоса, промывание носа изотоником. "
            "Витамин C/D «для профилактики ОРВИ» не заменяют режим и очную оценку при высокой температуре или ухудшении."
        )
        nutrition = "Тёплая мягкая пища (супы, каши), вода небольшими порциями; без ледяного и острого; достаточно белка и овощей по переносимости."
        activity = "Дома — лёгкая разминка; на улице — короткая прогулка без переохлаждения, если нет высокой температуры и одышки; спортзал отложить до выздоровления."
    elif any(w in um for w in ("живот", "тошн", "стул", "диаре", "запор")):
        treatment = "Щадящий ЖКТ-режим, контроль боли/тошноты, регидратация и оценка динамики симптомов."
        alternative = (
            "Немедикаментозно: дробное питание, временно убрать раздражающие продукты, тёплое питьё. "
            "Пробиотики/ферменты — только по рекомендации врача при показаниях."
        )
        nutrition = "Лёгкая еда малыми порциями (рис, банан, сухари, нежирный бульон по переносимости); без жареного, алкоголя и избытка сахара; вода равномерно в течение дня."
        activity = "Спокойная ходьба 10–20 минут при отсутствии сильной боли; без пресса и тяжёлых весов до стабилизации стула и боли."
    elif any(w in um for w in ("давлен", "голов", "сердц", "пульс")):
        treatment = "Контроль давления/пульса, снижение стресса, соблюдение режима сна и плановая очная оценка."
        alternative = (
            "Немедикаментозно: дыхательные практики, ограничение соли и кофеина, регулярные замеры. "
            "Магний/омега-3/коэнзим Q10 и др. — только после согласования с врачом (учитывая лекарства от давления)."
        )
        nutrition = "Меньше соли и ультрапереработанных продуктов; больше овощей, клетчатки и воды; умеренный кофеин; регулярный завтрак и обед."
        activity = "Ежедневная умеренная ходьба 20–40 минут в комфортном темпе; без рывковых силовых нагрузок и соревнований при плохом самочувствии."
    elif any(w in um for w in ("устал", "усталы", "нет сил", "не хочется", "неохота", "апат", "встать тяжело", "вставать тяжело", "тяжело встать", "слабост", "вял")) and not any(
        w in um for w in ("горл", "кашл", "насморк", "температ", "простуд", "орви", "грипп", "одыш", "груд", "сердц", "давлен")
    ):
        treatment = (
            "Похоже на выраженную усталость с сильной слабостью: когда даже подняться с кровати даётся с трудом, это уже не «просто переработал» и не вопрос силы воли. "
            "Такое состояние стоит воспринимать серьёзно. Часто сочетаются факторы: перегрузка и стресс (в т.ч. выгорание), нарушение сна, дефициты (железо, B12, витамин D), "
            "щитовидная железа, хроническое воспаление или недавно перенесённая инфекция; одна причина без остального встречается реже."
        )
        alternative = (
            "Сейчас: не «загонять» себя на полную мощность; сон, вода, еда по графилу небольшими порциями. "
            "Движение — только по самочувствию: даже несколько минут у окна или короткий шаг по квартире могут быть достаточной нагрузкой на сегодня. "
            "К терапевту имеет смысл пойти, если так дольше 1–2 недель, быстро хуже, или появляются головокружение, одышка в покое, обмороки, сильнее боль в груди."
        )
        nutrition = (
            "Что проверить с врачом по анализам (по показаниям): ОАК, ферритин, витамин B12, витамин D, ТТГ. "
            "Питание: важнее регулярность и переносимость, чем «супердиеты»; белок и тёплая еда; витаминные комплексы не заменяют поиск причины и очный осмотр."
        )
        activity = (
            "Про нормы «много ходить в неделю» и спортзал — не с первого дня при такой слабости: сначала отдых и очная оценка. "
            "К умеренной активности на свежем воздухе можно возвращаться постепенно, когда станет заметно легче, без сравнения себя с чужими «нормами из интернета»."
        )
    return treatment, alternative, nutrition, activity


def _rotate_followup_if_repeated(structured: dict, previous_voice_state: dict, user_message: str) -> None:
    questions = structured.get("suggested_questions")
    if not isinstance(questions, list) or not questions:
        return
    prev_q = str(previous_voice_state.get("last_question") or "").strip()
    cur_q = str(questions[0] or "").strip()
    if not prev_q or not cur_q:
        return
    if _norm_text_for_compare(prev_q) != _norm_text_for_compare(cur_q):
        return
    um = _norm_text_for_compare(user_message or "")
    if any(w in um for w in ("горл", "кашл", "насморк", "температ", "простуд")):
        alt = "Что изменилось за последние сутки: температура, боль в горле или общее самочувствие?"
    elif any(w in um for w in ("живот", "тошн", "стул", "диаре", "запор")):
        alt = "Что сейчас выражено сильнее: боль, тошнота или нарушение стула?"
    else:
        alt = "Какой симптом сейчас мешает больше всего и что уже пробовали сделать?"
    questions[0] = alt
    structured["suggested_questions"] = questions


def _voice_response_is_clarification_only(text: str) -> bool:
    """Не навешивать «Клинический план» на короткие уточняющие реплики до выводов."""
    t = _norm_text_for_compare(text or "")
    if len(t) < 28:
        return True
    hints = (
        "пока мало данных",
        "пока данных недостаточно",
        "уточню один ключевой момент",
        "уточню один момент",
        "хочу уточнить одно",
        "оценим дыхательные симптомы",
        "оценим мочевые симптомы",
        "разберём по шагам",
        "разберем по шагам",
        "усталость и тяжесть",
        "слышу вас",
        "не норма с которой надо смириться",
        "такие жалобы",
        "важно уточнить",
        "уточнить аккуратно",
    )
    if not any(h in t for h in hints):
        return False
    heavy = (
        "что вероятнее всего",
        "похожа на острую",
        "похоже на ",
        "клинический план",
        "срочно 103",
        "срочно вызывайте",
        "103/112",
        "терапевт",
        "обратитесь к врачу",
        "вес не снижается",
        "что стоит проверить",
        "глюкоза и инсулин",
        "ферритин",
    )
    if any(h in t for h in heavy):
        return False
    return True


def _strip_trailing_clinical_plan_after_canonical_template(base: str) -> str:
    """Срезаем хвост «Клинический план: …», если тело — один из эталонных ответов без плана."""
    from app.services.response_composer import response_has_canonical_no_clinical_plan_lead

    blob = str(base or "").strip().replace("\r\n", "\n")
    if not response_has_canonical_no_clinical_plan_lead(blob):
        return str(base or "").strip()
    for marker in ("\n\nКлинический план:", "\nКлинический план:"):
        i = blob.find(marker)
        if i > 0:
            return blob[:i].strip()
    return str(base or "").strip()


def _voice_fatigue_first_reply_without_plan(text: str) -> bool:
    """Первый ответ по выраженной усталости: интро + один вопрос — без клинического плана."""
    raw = str(text or "")
    low = raw.lower()
    if "клинический план" in low:
        return False
    if "\n- " not in raw and "\n-" not in raw.replace(" ", ""):
        return False
    if len(low) > 900:
        return False
    if not any(x in low for x in ("усталост", "слабост", "кроват", "встать", "вставать", "нет сил", "не хочется")):
        return False
    return any(x in low for x in ("разберём по шагам", "разберем по шагам", "по шагам", "слышу вас", "не норма"))


def _enrich_medical_response(
    response: str,
    structured: dict,
    previous_answer: str,
    user_message: str,
    chat_history: Optional[list[Any]] = None,
) -> str:
    from app.services.response_composer import response_has_canonical_no_clinical_plan_lead

    base = str(response or "").strip()
    base = _strip_trailing_clinical_plan_after_canonical_template(base)
    if not base or not isinstance(structured, dict):
        return base
    if structured.get("insufficient_data"):
        return base
    thread_fatigue = _constitutional_fatigue_thread_active(user_message, chat_history)
    if thread_fatigue and _voice_fatigue_first_reply_without_plan(base):
        return base
    if _voice_response_is_clarification_only(base):
        return base
    base_n = _norm_text_for_compare(base)
    if re.search(r"(до свидания|до встречи|увидимся|пока\.)", base_n) and "вероятнее" not in base_n and "жалоб" not in base_n:
        return base
    # Не добавляем клинический блок к сервисным/бытовым ответам (например: "Ладно спасибо").
    if not _is_clearly_medical_request(user_message):
        medical_output_markers = (
            "что вероятнее всего",
            "что делать сейчас",
            "срочно 103",
            "жалоб",
            "симптом",
            "температ",
            "кашл",
            "горл",
            "боль",
            "одыш",
            "лечение",
        )
        if not any(m in base_n for m in medical_output_markers):
            return base
        small_talk_markers = (
            "рад помочь",
            "я на связи",
            "что вас беспокоит",
            "до свидания",
            "до встречи",
            "пока",
        )
        if any(m in base_n for m in small_talk_markers) and "что вероятнее всего" not in base_n:
            return base
    probe_for_plan = _constitutional_fatigue_thread_probe(user_message, chat_history)
    fb_treatment, fb_alternative, fb_nutrition, fb_activity = _fallback_plan_blocks(
        probe_for_plan if thread_fatigue else user_message
    )
    if thread_fatigue or _user_constitutional_fatigue_primary(user_message):
        treatment, alternative, nutrition, activity = fb_treatment, fb_alternative, fb_nutrition, fb_activity
    else:
        treatment = _structured_pick(structured, ["care_plan_today", "treatment_advice", "what_to_do", "recommendations", "safe_actions_now"])
        alternative = _structured_pick(structured, ["alternative_treatment", "alternatives", "backup_plan"])
        nutrition = _structured_pick(structured, ["nutrition_advice", "nutrition", "diet_advice"])
        activity = _structured_pick(structured, ["activity_advice", "physical_activity", "physicalExercise", "exercise"])
        treatment = treatment or fb_treatment
        alternative = alternative or fb_alternative
        nutrition = nutrition or fb_nutrition
        activity = activity or fb_activity

    # Стабильный клинический формат из 4 блоков для каждого медицинского ответа.
    plan_block = (
        "\n\nКлинический план:\n"
        "Лечение: " + treatment + "\n"
        "Альтернативный вариант: " + alternative + "\n"
        "Питание: " + nutrition + "\n"
        "Физическая активность: " + activity
    )
    _blob = base.replace("\r\n", "\n")
    if response_has_canonical_no_clinical_plan_lead(_blob) and "клинический план" not in _blob.lower():
        pass
    elif "Клинический план:" not in base:
        base = base.rstrip() + plan_block
    if _is_near_duplicate_answer(base, previous_answer):
        # Один и тот же эталон при похожих жалобах — не дописывать «не повторяться».
        if response_has_canonical_no_clinical_plan_lead(_blob):
            return base
        q = _structured_pick(structured, ["suggested_questions"])
        if q:
            base = base.rstrip() + "\n\nЧтобы продвинуться дальше по сути, уточню: " + q
        else:
            base = base.rstrip() + "\n\nЧтобы не повторяться, уточните, что изменилось с прошлого ответа: стало лучше, хуже или без динамики?"
    return base


def _inject_unified_engine_snapshot(
    payload: dict[str, Any],
    *,
    subject_id: Optional[str] = None,
    documents_count: int = 0,
    symptom_entries_count: int = 0,
) -> dict[str, Any]:
    data = dict(payload or {})
    structured = data.get("structured")
    structured_dict = structured if isinstance(structured, dict) else {}
    snapshot = data.get("unified_engine_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = structured_dict.get("unified_engine_snapshot")
    if not isinstance(snapshot, dict):
        snapshot = {
            "version": "v1_compact",
            "pattern_scores": {},
            "confidence": "low",
            "symptom": {},
            "causal": {},
            "non_drug": {},
            "nutraceutical": {},
            "amino": {},
            "thyroid": {},
            "a1at": {},
            "indexes": {},
        }
    snapshot = tag_unified_snapshot(snapshot)
    data["unified_engine_snapshot"] = snapshot
    if isinstance(structured, dict):
        structured.setdefault("unified_engine_snapshot", snapshot)
    data["clinical_core"] = clinical_core_envelope(
        subject_id=subject_id,
        documents_count=int(documents_count or 0),
        symptom_entries_count=int(symptom_entries_count or 0),
    )
    if "knowledge_enrichment" not in data:
        data["knowledge_enrichment"] = {"queued": False, "reason": "not_applicable"}
    return data
from app.services.knowledge_base_resolver import resolve_medical_context
from app.services.knowledge_flywheel import (
    capture_learning_candidate,
    get_learning_candidate,
    get_learning_queue_stats,
    list_learning_candidates,
    update_learning_candidate_review,
)
from app.services.improvement_backlog import add_backlog_item, backlog_stats, list_backlog, update_backlog_item
from app.services.enrichment_suggestions import (
    cluster_sprint_plan,
    cluster_workspace,
    complaint_enrichment_suggestion,
)
from app.services.help_store import (
    FAQ_CATEGORIES,
    list_faq,
    get_faq_item,
    create_faq,
    update_faq,
    delete_faq,
    list_user_questions,
    create_user_question,
    answer_user_question,
    delete_user_question,
)
from app.services.complaint_draft_workflow import (
    apply_draft_candidate,
    create_draft_candidate,
    draft_stats,
    get_draft_diff,
    list_draft_candidates,
    update_draft_candidate,
)
from app.services.medical_question_engine import suggest_clarifying_questions
from app.services.quality_autolearn import record_turn_for_autolearn
from app.services.release_gate_policy import get_release_gate_policy, update_release_gate_policy
from app.services.routing_control import get_routing_control_config
from app.services.runtime_analytics import get_runtime_overview, get_runtime_events, record_runtime_event
from app.services.search_service import suggest as search_suggest
from app.services.symptom_extractor import extract_symptom_payload
from app.services.threshold_presets import apply_threshold_preset, list_threshold_presets
from app.services.report import build_lab_report_from_doc, build_lab_report_from_docs
from app.services.clinical_engine.unified_contract import serialize_aggregate_report_to_unified_payload
from app.services.clinical_engine.report_api_service import build_api_payload_from_current_result
from app.services.voice_structured_report import build_structured_response
from app.services.concierge_action_sequence import build_concierge_action_sequence
from app.services.gut_muscle_axis_engine import evaluate_gut_muscle_axis
from app.services.microbiome_engine import run_microbiome_engine
from app.services.microbiome_axes_engine import (
    calc_microbiome_axes,
    build_microbiome_payload_from_message,
)
from app.services.microbiome_guardrails import enrich_with_microbiome
from app.services.pdf_export import build_pdf_report, build_pdf_report_like_user_tab, build_pdf_document
from app.services.pdf_report_generator import (
    build_personal_report_pdf_bytes,
    build_premium_pdf_bytes,
    report_to_pdf_data,
    report_to_premium_pdf_data,
)
from app.services.tts_provider import get_tts_client_provider_label, get_tts_voices, synthesize_tts, TTSProviderError
from app.services.speech_to_text import transcribe_audio, get_stt_runtime_status
from app.services.forum_store import (
    create_comment as forum_create_comment,
    create_thread as forum_create_thread,
    delete_comment as forum_delete_comment,
    delete_thread as forum_delete_thread,
    get_comment as forum_get_comment,
    get_thread as forum_get_thread,
    list_comments as forum_list_comments,
    list_comments_for_moderation as forum_list_comments_for_moderation,
    list_threads as forum_list_threads,
    moderate_comment as forum_moderate_comment,
    update_comment as forum_update_comment,
    update_thread as forum_update_thread,
)
from app.services.news_store import (
    delete_news_item as news_delete_item,
    list_news_items as news_list_items,
    upsert_news_item as news_upsert_item,
)
from app.services.audit_logger import log_audit_event
from app.services.auth_store import (
    ADMIN_ONLY_FEATURES,
    ALL_FEATURE_KEYS,
    USER_DEFAULT_FEATURES,
    authenticate_user,
    begin_passkey_login,
    begin_passkey_registration,
    change_password,
    create_session,
    disable_passkeys,
    finish_passkey_login,
    finish_passkey_registration,
    get_enabled_features,
    get_user_by_session,
    list_accounts,
    register_user,
    revoke_session,
    set_user_disabled_features,
)

router = APIRouter(prefix="/api", tags=["user"])
_consultation_orchestrator_adapter = ConsultationOrchestratorAdapter()
logger = logging.getLogger(__name__)


def _bearer_token(authorization: Optional[str]) -> str:
    val = (authorization or "").strip()
    if val.lower().startswith("bearer "):
        return val[7:].strip()
    return ""


def _user_id(
    x_user_id: Optional[str] = None,
    authorization: Optional[str] = None,
) -> str:
    """Папка данных: при валидном Bearer — user_id из сессии, иначе X-User-Id или default."""
    token = _bearer_token(authorization or "")
    if token:
        user = get_user_by_session(token)
        sid = (user or {}).get("user_id") or ""
        if str(sid).strip():
            return str(sid).strip()
    return get_or_create_user_id(x_user_id or "")


def resolve_user_storage_id(
    x_user_id_header: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
) -> str:
    return _user_id(x_user_id_header, authorization)


def _subject_id(x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id")) -> str:
    return normalize_subject_id(x_subject_id or "")


def _get_current_user(authorization: Optional[str] = Header(None, alias="Authorization")):
    """Зависимость: текущий пользователь по Bearer токену. Иначе 401."""
    token = _bearer_token(authorization)
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _require_admin(authorization: Optional[str] = Header(None, alias="Authorization")):
    """Зависимость: текущий пользователь с ролью admin. Иначе 403."""
    user = _get_current_user(authorization)
    if (user.get("role") or "").strip().lower() != "admin":
        raise HTTPException(status_code=403, detail="Доступ только для администратора.")
    return user


class SettingsUpdate(BaseModel):
    mode: Optional[str] = None
    subscription: Optional[str] = None
    billing_period: Optional[str] = None  # month | year (для одной подписки с двумя периодами оплаты)
    free_features: Optional[dict] = None
    dashboard_widgets: Optional[dict] = None
    dashboard_layout_mode: Optional[str] = None
    sprint_focus: Optional[dict] = None


class ProfileUpdate(BaseModel):
    name: Optional[str] = None
    address: Optional[str] = None
    chronic_conditions: Optional[List[str]] = None
    low_activity: Optional[bool] = None
    allergies: Optional[List[str]] = None
    family_history: Optional[str] = None
    family_access: Optional[List[dict]] = None
    privacy_consent: Optional[bool] = None
    date_of_birth: Optional[str] = None
    sex: Optional[str] = None


class VitalsUpdate(BaseModel):
    systolic: Optional[int] = None
    diastolic: Optional[int] = None
    pulse: Optional[int] = None
    weight_kg: Optional[float] = None
    height_cm: Optional[int] = None
    hrv_rmssd: Optional[int] = None  # вариабельность пульса, мс
    sleep_hours: Optional[float] = None
    sleep_quality: Optional[str] = None  # poor, normal, good
    body_temp_c: Optional[float] = None  # температура тела, °C (носимые / ручной ввод)
    steps: Optional[int] = None  # шаги за день (носимые / ручной ввод)
    source: Optional[str] = None  # "device" — пульс/температура/шаги с устройства (приоритет на экране); иначе ручной ввод


class SeverityUpdate(BaseModel):
    severity: str
    source: Optional[str] = "dashboard"


class ChatMessage(BaseModel):
    message: str
    lookup_mode: Optional[str] = None


class SubscriptionUpgradePayload(BaseModel):
    plan_type: str
    billing_period: Optional[str] = "month"
    status: Optional[str] = "active"
    expires_at: Optional[str] = None


class VoiceQualityEventPayload(BaseModel):
    event: str
    detail: Optional[str] = None
    severity: Optional[str] = None


class EmergencyAuditPayload(BaseModel):
    source: str
    channel: Optional[str] = "ui"
    trigger_text: Optional[str] = None
    status: Optional[str] = "requested"
    meta: Optional[dict] = None


class MikhailConsultationPayload(BaseModel):
    """Диалог с консьержем Михаилом после анализа: сообщение пользователя и состояние этапа."""
    message: Optional[str] = None
    state: Optional[dict] = None
    analysis_result: Optional[dict] = None


class SymptomAdd(BaseModel):
    text: str


class StructuredConsultationPayload(BaseModel):
    """Структурированный ввод консультации: области тела, симптомы, ответы Михаила."""
    body_areas: Optional[List[str]] = None
    symptoms: Optional[List[str]] = None
    mikhail_answers: Optional[dict] = None  # duration, severity, medications, red_flags


class ConsultationRunRequest(BaseModel):
    user_text: str
    debug: Optional[bool] = False
    extra_context: Optional[dict] = None


class ConsultationRunResponse(BaseModel):
    branch: str
    matched: bool
    relevance_score: float
    patient_response: str
    doctor_payload: dict[str, Any]
    care_level: str
    followup_questions: List[str]
    machine_payload: dict[str, Any]
    errors: List[str]


class SymptomDeletePayload(BaseModel):
    entry_indices: Optional[List[Any]] = None  # индексы (0-based), примут int/float/str
    clear_all: Optional[bool] = None  # True — очистить всю историю


class LabReportRequest(BaseModel):
    document_id: Optional[str] = None
    task_query: Optional[str] = None
    compact_for_doctor: Optional[bool] = False
    save_generated_report: Optional[bool] = False


class LabCaseCreate(BaseModel):
    name: Optional[str] = None


class LabCaseUpdate(BaseModel):
    name: str


class LabCaseReportRequest(BaseModel):
    case_id: Optional[str] = None
    task_query: Optional[str] = None
    compact_for_doctor: Optional[bool] = False
    save_generated_report: Optional[bool] = False


class NotificationsReadRequest(BaseModel):
    ids: Optional[List[str]] = None  # None или пустой = отметить все как прочитанные


class ConversationReportMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ConversationReportRequest(BaseModel):
    messages: List[ConversationReportMessage]
    title: Optional[str] = None  # по умолчанию: жалоба + дата


class SearchSuggestRequest(BaseModel):
    query: str
    limit: Optional[int] = 8


class MicrobiomeReportRequest(BaseModel):
    """Запрос отчёта Microbiome Engine v1."""
    symptoms_text: Optional[str] = None
    age: Optional[int] = None
    low_activity: Optional[bool] = None
    poor_diet: Optional[bool] = None


class DocumentUpdate(BaseModel):
    summary: Optional[str] = None
    extracted_text: Optional[str] = None
    case_id: Optional[str] = None


class ShareAccessCreate(BaseModel):
    label: Optional[str] = None
    doctor_name: Optional[str] = None
    days_valid: Optional[int] = 30
    one_time: Optional[bool] = False
    session_minutes: Optional[int] = 30


class FamilyAccessCreate(BaseModel):
    member_name: Optional[str] = None
    relation: Optional[str] = None
    role: Optional[str] = "family_viewer"
    permissions: Optional[dict] = None
    days_valid: Optional[int] = 30
    one_time: Optional[bool] = False
    session_minutes: Optional[int] = 30


class TtsSpeakRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    rate: Optional[str] = None


class LearningReviewUpdate(BaseModel):
    review_status: str
    review_notes: Optional[str] = None
    reviewer: Optional[str] = None


class KnowledgeEnrichmentStatusPatch(BaseModel):
    promotion_status: str
    notes: Optional[str] = None


class KnowledgeIndexMergeRequest(BaseModel):
    max_items: int = 25


class DailyClusterEnrichmentRequest(BaseModel):
    max_topics: int = 8


class BacklogCreateRequest(BaseModel):
    complaint: str
    cluster: Optional[str] = None
    reason: Optional[str] = None
    source: Optional[str] = "analytics"


class BacklogUpdateRequest(BaseModel):
    status: str
    notes: Optional[str] = None


class DraftCreateRequest(BaseModel):
    complaint: str
    cluster: Optional[str] = None
    source: Optional[str] = "analytics"
    notes: Optional[str] = None
    draft_entry: Optional[dict] = None


class DraftUpdateRequest(BaseModel):
    status: str
    notes: Optional[str] = None


class ReleaseGatePolicyUpdate(BaseModel):
    core_targets: Optional[list[str]] = None
    weak_core_quality_threshold: Optional[int] = None
    min_total_events_warn: Optional[int] = None
    llm_share_warn_threshold: Optional[float] = None


class AuthCredentials(BaseModel):
    login: str
    password: str
    name: Optional[str] = None


class AuthChangePassword(BaseModel):
    old_password: str
    new_password: str


class PasskeyStartRequest(BaseModel):
    login: str
    password: Optional[str] = None
    origin: Optional[str] = None
    rp_id: Optional[str] = None


class PasskeyFinishRequest(BaseModel):
    flow_id: str
    credential: dict


@router.post("/export-pdf")
def export_pdf(
    payload: dict,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Генерация PDF на бэкенде: отчёт или документ. Тело: { type, ... }."""
    _user_id(x_user_id, authorization)
    if payload.get("type") == "document":
        title = payload.get("title") or "Документ"
        body = payload.get("body") or ""
        date_str = payload.get("date_str") or ""
        pdf_bytes = build_pdf_document(title, body, date_str)
        filename = "Dokument_" + (date_str or "export") + ".pdf"
    elif payload.get("type") == "personal_report":
        report = payload.get("report") or {}
        data = report_to_pdf_data(report)
        pdf_bytes = build_personal_report_pdf_bytes(data)
        date_str = payload.get("date_str") or ""
        filename = "Personal_report_" + (date_str or "export") + ".pdf"
    elif payload.get("type") == "premium_report":
        report = payload.get("report") or {}
        date_str = payload.get("date_str") or ""
        report_id = payload.get("report_id") or ""
        data = report_to_premium_pdf_data(report, report_id=report_id, date_str=date_str)
        pdf_bytes = build_premium_pdf_bytes(data)
        filename = "Metabolic_report_" + (date_str or "export") + ".pdf"
    else:
        date_str = payload.get("date_str") or ""
        sections = payload.get("sections")
        user_html = payload.get("user_html") or ""
        doctor_html = payload.get("doctor_html") or ""
        doc_name = payload.get("doc_name") or ""
        for_doctor = payload.get("for_doctor") is True
        pdf_bytes = b""
        if for_doctor and doctor_html:
            pdf_bytes = build_pdf_report(user_html, doctor_html, doc_name, date_str, for_doctor=True)
        elif isinstance(sections, list) and len(sections) > 0:
            pdf_bytes = build_pdf_report_like_user_tab(sections, date_str)
        if not pdf_bytes:
            pdf_bytes = build_pdf_report(user_html, doctor_html, doc_name, date_str)
        filename = "Otchet_" + (date_str or "export") + ".pdf"
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Не удалось сформировать PDF. Установите reportlab: pip install reportlab")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="' + filename + '"'},
    )


@router.get("/user/settings")
def user_get_settings(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    out = get_settings(uid)
    out["user_id"] = uid
    return out


@router.post("/user/settings")
def user_save_settings(
    payload: SettingsUpdate,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    out = save_settings(uid, payload.model_dump(exclude_none=True))
    out["user_id"] = uid
    return out


@router.get("/subscription/status")
def subscription_status(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    settings = get_settings(uid)
    plan = _normalize_subscription_plan(str(settings.get("subscription") or "free"))
    active = _is_subscription_active(settings)
    limits = _plan_limits(plan)
    return {
        "user_id": uid,
        "plan_type": plan,
        "status": "active" if active else "expired",
        "billing_period": str(settings.get("billing_period") or "month"),
        "expires_at": str(settings.get("subscription_expires_at") or ""),
        "limits": limits,
    }


@router.post("/subscription/upgrade")
def subscription_upgrade(
    payload: SubscriptionUpgradePayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    plan = _normalize_subscription_plan(payload.plan_type)
    status = str(payload.status or "active").strip().lower() or "active"
    billing_period = str(payload.billing_period or "month").strip().lower() or "month"
    save_payload = {
        "subscription": plan,
        "subscription_status": status,
        "billing_period": billing_period,
    }
    if payload.expires_at:
        save_payload["subscription_expires_at"] = str(payload.expires_at).strip()
    out = save_settings(uid, save_payload)
    try:
        record_runtime_event(
            source="subscription_upgrade",
            llm_used=False,
            model_used="plan:" + _normalize_subscription_plan(str(out.get("subscription") or "free")),
            protocol_source="paywall",
            complaint="upgrade_request",
            cluster="paywall",
            severity=str(out.get("subscription_status") or "active")[:32],
            prompt_chars=0,
            response_chars=0,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0,
        )
    except Exception:
        pass
    return {
        "ok": True,
        "user_id": uid,
        "plan_type": _normalize_subscription_plan(str(out.get("subscription") or "free")),
        "status": str(out.get("subscription_status") or "active"),
        "billing_period": str(out.get("billing_period") or "month"),
        "expires_at": str(out.get("subscription_expires_at") or ""),
    }


@router.post("/subscription/webhook")
def subscription_webhook(payload: dict = Body(default={})):
    # Заглушка для интеграции ЮKassa / Tinkoff / in-app billing.
    # В следующем шаге сюда добавляется верификация подписи провайдера и маппинг user_id.
    return {"received": True, "event_type": str((payload or {}).get("event") or "")}


@router.get("/user/profile")
def user_get_profile(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    out = get_profile(uid)
    out["user_id"] = uid
    return out


@router.post("/user/profile")
def user_save_profile(
    payload: ProfileUpdate,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    out = save_profile(uid, payload.model_dump(exclude_none=True))
    out["user_id"] = uid
    return out


_VITALS_CACHE_HEADERS = {"Cache-Control": "no-store, max-age=0, must-revalidate", "Pragma": "no-cache"}


@router.get("/user/vitals")
def user_get_vitals(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    out = get_vitals(uid)
    out["user_id"] = uid
    return JSONResponse(content=out, headers=_VITALS_CACHE_HEADERS)


@router.post("/user/vitals")
def user_save_vitals(
    payload: VitalsUpdate,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    out = save_vitals(uid, payload.model_dump(exclude_none=True))
    out["user_id"] = uid
    return JSONResponse(content=out, headers=_VITALS_CACHE_HEADERS)


@router.get("/user/notifications")
def user_get_notifications(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    enforce_chat_retention_policy(uid)
    items = get_notifications(uid)
    unread_count = sum(1 for i in items if not i.get("read"))
    return {"user_id": uid, "items": items, "unread_count": unread_count}


@router.post("/user/notifications/read")
def user_mark_notifications_read(
    payload: NotificationsReadRequest = Body(default=NotificationsReadRequest()),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    ids = payload.ids if payload.ids else None
    count = mark_notifications_read(uid, ids=ids)
    return {"user_id": uid, "marked_read": count}


@router.post("/user/notifications/clear")
def user_clear_notifications(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    uid = _user_id(x_user_id, authorization)
    removed = clear_notifications(uid)
    return {"user_id": uid, "removed": removed}


@router.get("/user/knowledge-enrichment/{result_id}")
def user_get_knowledge_enrichment_snapshot(
    result_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Снимок обогащения по теме консультации (уведомление «Обновление по вашей теме»)."""
    from app.services.knowledge_enrichment_queue import get_enrichment_snapshot_for_user

    uid = _user_id(x_user_id, authorization)
    sid = normalize_subject_id(x_subject_id or "")
    payload, err = get_enrichment_snapshot_for_user(result_id, user_id=uid, subject_id=sid)
    if err == "not_found":
        raise HTTPException(status_code=404, detail="Материал не найден.")
    if err == "forbidden":
        raise HTTPException(
            status_code=403,
            detail="Нет доступа к этому материалу. Выберите тот же профиль (X-Subject-Id), что при запросе консультации.",
        )
    return payload


@router.get("/user/documents")
def user_get_documents(
    include_generated: bool = False,
    include_voice_concierge: bool = False,
    include_deleted: bool = False,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    items = get_documents(uid, include_deleted=include_deleted, subject_id=sid)
    if not include_generated:
        items = [d for d in items if (d.get("type") or "") not in ("lab_report_single", "lab_report_summary")]
    if not include_voice_concierge:
        items = [d for d in items if (d.get("type") or "") != "voice_concierge"]
    return {"user_id": uid, "items": items}


@router.get("/user/lab-cases")
def user_get_lab_cases(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    items = get_lab_cases(uid, subject_id=sid)
    return {"user_id": uid, "items": items}


@router.post("/user/lab-cases")
def user_create_lab_case(
    payload: LabCaseCreate,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    name = (payload.name or "").strip()
    item = create_lab_case(uid, name, subject_id=sid)
    return {"user_id": uid, "item": item}


@router.patch("/user/lab-cases/{case_id}")
def user_update_lab_case(
    case_id: str,
    payload: LabCaseUpdate,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    item = update_lab_case(uid, case_id, {"name": payload.name}, subject_id=sid)
    if not item:
        raise HTTPException(status_code=404, detail="Папка не найдена.")
    return {"user_id": uid, "item": item}


@router.delete("/user/lab-cases/{case_id}")
def user_delete_lab_case(
    case_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    ok = delete_lab_case(uid, case_id, subject_id=sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Папка не найдена.")
    return {"user_id": uid, "deleted_id": case_id}


def _ensure_doc_extracted_text(uid: str, doc: dict) -> dict:
    """Если у документа нет извлечённого текста — пробуем извлечь из файла и обновить запись."""
    if (doc.get("extracted_text") or "").strip():
        return doc
    path = get_upload_file_path(uid, doc)
    if not path:
        return doc
    ext = Path(doc.get("filename") or "").suffix.lower().lstrip(".") or "pdf"
    extracted = extract_text_from_file(path, ext)
    if not (extracted or "").strip():
        return doc
    store_update_document(uid, doc["id"], {"extracted_text": extracted[:50000]})
    updated = get_document_by_id(uid, doc["id"])
    return updated if updated else doc


def _build_concierge_dialog_context(uid: str, max_chars: int = 1800) -> str:
    """
    Separate source for report context: recent concierge dialog.
    Keeps only compact user/assistant pairs.
    """
    msgs = get_chat_history(uid)
    if not msgs:
        return ""
    lines: list[str] = []
    medical_keys = (
        "боль",
        "каш",
        "одыш",
        "температ",
        "симптом",
        "жалоб",
        "анализ",
        "показат",
        "лечение",
        "диагноз",
        "витамин",
        "кислот",
        "моч",
        "креатинин",
    )
    off_topic_keys = ("автомоб", "машин", "погод", "фильм", "музык", "анекдот", "шутк")
    keep_assistant = False
    for m in msgs[-18:]:
        role = (m.get("role") or "").strip().lower()
        content = str(m.get("content") or "").strip()
        if not content:
            continue
        low = content.lower()
        if role == "user":
            is_med = any(k in low for k in medical_keys)
            is_off = any(k in low for k in off_topic_keys)
            if is_med and not is_off:
                lines.append("Пользователь: " + content)
                keep_assistant = True
            else:
                keep_assistant = False
        elif role == "assistant":
            if not keep_assistant:
                continue
            if "можем вернуться к здоровью" in low:
                continue
            if any(k in low for k in medical_keys):
                lines.append("Консьерж: " + content)
            keep_assistant = False
    return "\n".join(lines)[:max_chars]


@router.post("/user/lab-report")
def user_lab_report(
    payload: LabReportRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Сформировать отчёт по загруженному документу. При отсутствии текста — повторное извлечение из файла."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    items = [
        d for d in get_documents(uid, subject_id=sid)
        if (d.get("type") or "") not in ("lab_report_single", "lab_report_summary", "voice_concierge")
    ]
    if not items:
        raise HTTPException(status_code=400, detail="Нет загруженных документов. Сначала загрузите PDF или фото анализа.")
    if payload.document_id:
        doc = get_document_by_id(uid, payload.document_id, subject_id=sid)
        if not doc:
            raise HTTPException(status_code=404, detail="Документ не найден.")
    else:
        doc = items[-1]
    doc = _ensure_doc_extracted_text(uid, doc)
    task_query = str(payload.task_query or "").strip()
    # Отчёт только по этому документу — не подмешивать весь диалог и другие жалобы
    dialog_context = ""
    try:
        report = build_lab_report_from_doc(
            doc,
            profile=get_profile(uid),
            task_query=task_query,
            dialog_context=dialog_context,
            compact_for_doctor=bool(payload.compact_for_doctor),
        )
    except Exception:
        logger.exception("lab_report_build_failed")
        report = {
            "display_summary": "Не удалось полноценно собрать AI-отчёт. Показана базовая версия.",
            "user_summary": "Произошла внутренняя ошибка интерпретации. Рекомендуется повторить запрос и показать исходный бланк врачу.",
            "safe_next_steps": "Повторите попытку позже. Если есть симптомы, обратитесь к врачу с исходным анализом.",
            "when_urgent": "",
            "document_name": doc.get("filename") or "document",
            "document_type": str(doc.get("type") or "generic_lab_document"),
            "findings": [],
            "hypotheses": [],
            "diagnostics": [],
            "professional_summary": "",
            "user_report_structured": {"severity": "normal", "headline": "Базовая версия отчёта", "blocks": []},
        }
    if bool(payload.save_generated_report):
        try:
            source_name = (doc.get("filename") or "document").strip()
            source_name = source_name.replace(" ", "_")
            _save_generated_lab_report(
                uid,
                report,
                report_kind="lab_report_single",
                base_filename=f"report_{source_name}",
                case_id=doc.get("case_id"),
                compact_for_doctor=bool(payload.compact_for_doctor),
                subject_id=sid,
            )
        except Exception:
            logger.exception("save_generated_single_lab_report_failed")
    out = {"user_id": uid, "document_id": doc.get("id"), "report": report}
    try:
        patient_profile = get_profile(uid) or {}
        unified_single = build_api_payload_from_current_result(
            current_result=report,
            patient_info={
                "display_name": patient_profile.get("display_name") or patient_profile.get("name"),
                "sex": patient_profile.get("sex"),
                "age": patient_profile.get("age"),
            },
        )
        out.update(unified_single.model_dump(mode="json"))
    except Exception:
        logger.exception("unified_payload_single_lab_report_failed")
    return out


@router.post("/user/lab-case-report")
def user_lab_case_report(
    payload: LabCaseReportRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """
    Сводный отчёт по папке (нескольким документам).
    Если case_id не передан — берём все документы пользователя.
    """
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    docs = [
        d for d in get_documents(uid, subject_id=sid)
        if (d.get("type") or "") not in ("lab_report_single", "lab_report_summary", "voice_concierge")
    ]
    if not docs:
        raise HTTPException(status_code=400, detail="Нет загруженных документов.")
    case_id = (payload.case_id or "").strip()
    if case_id:
        docs = [d for d in docs if (d.get("case_id") or "") == case_id]
    if not docs:
        raise HTTPException(status_code=400, detail="В выбранной папке пока нет документов.")
    # Сводный анализ: не больше 10 последних по дате загрузки
    try:
        docs = sorted(
            docs,
            key=lambda d: float(d.get("created_at") or 0),
            reverse=True,
        )[:10]
    except (TypeError, ValueError):
        docs = docs[:10]
    case_name = ""
    if case_id:
        for c in get_lab_cases(uid, subject_id=sid):
            if c.get("id") == case_id:
                case_name = c.get("name") or ""
                break
    task_query = str(payload.task_query or "").strip()
    # Сводный отчёт только по документам выбранной папки — без общего диалога по разным темам
    dialog_context = ""
    try:
        report = build_lab_report_from_docs(
            docs,
            case_name=case_name or "Сводный отчёт",
            profile=get_profile(uid),
            task_query=task_query,
            dialog_context=dialog_context,
            compact_for_doctor=bool(payload.compact_for_doctor),
        )
    except Exception:
        logger.exception("lab_case_report_build_failed")
        report = {
            "display_summary": "Не удалось собрать сводный AI-отчёт. Показана базовая версия.",
            "user_summary": "Произошла внутренняя ошибка при сводном анализе. Попробуйте позже или сформируйте отчёты по отдельным документам.",
            "safe_next_steps": "Сверьте ключевые отклонения в каждом документе и покажите врачу.",
            "when_urgent": "",
            "document_name": case_name or "Сводный отчёт",
            "document_type": "aggregate_clinical_report",
            "findings": [],
            "hypotheses": [],
            "diagnostics": [],
            "professional_summary": "",
            "aggregate_clinical": {
                "title": "Сводный клинический отчёт",
                "main_conclusion": {"main_priority": "Базовая версия сводного отчёта", "secondary_findings": []},
                "document_matrix": [],
                "attention_zones": [],
                "not_supported": [],
                "derived_indices": [],
                "next_checks": [],
                "next_checks_grouped": {"high": [], "medium": [], "optional": []},
                "working_hypotheses": [],
                "limitations": [],
                "urgent": "",
            },
        }
    if bool(payload.save_generated_report):
        try:
            base = (case_name or "all_documents").strip().replace(" ", "_")
            _save_generated_lab_report(
                uid,
                report,
                report_kind="lab_report_summary",
                base_filename=f"summary_{base}",
                case_id=case_id or None,
                compact_for_doctor=bool(payload.compact_for_doctor),
                subject_id=sid,
            )
        except Exception:
            logger.exception("save_generated_summary_lab_report_failed")
    patient_profile = get_profile(uid) or {}
    out: dict = {}
    try:
        unified_payload = build_api_payload_from_current_result(
            current_result=report,
            patient_info={
                "display_name": patient_profile.get("display_name") or patient_profile.get("name"),
                "sex": patient_profile.get("sex"),
                "age": patient_profile.get("age"),
            },
        )
        out = unified_payload.model_dump(mode="json")
    except Exception:
        logger.exception("unified_payload_build_failed")
    # Совместимость с nav.js: всегда отдаём legacy `report` (полный сводный dict) + unified поля сверху.
    out["report"] = report
    return out


def _summary_priority_to_api(priority: str) -> str:
    p = str(priority or "").lower()
    if "выс" in p or "high" in p:
        return "high"
    if "низ" in p or "low" in p:
        return "low"
    return "medium"


@router.get("/reports/summary")
def reports_summary(
    case_id: str = Query(default=""),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """
    Живой endpoint для summary dashboard (web шаблон / модал).
    Возвращает компактный JSON под UI-макет.
    """
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    docs = [
        d for d in get_documents(uid, subject_id=sid)
        if (d.get("type") or "") not in ("lab_report_single", "lab_report_summary", "voice_concierge")
    ]
    if not docs:
        return {
            "title": "🧾 Сводный отчёт",
            "main": {"headline": "Нет загруженных документов", "subtext": "Загрузите анализы для построения сводной картины.", "risk_level": "low"},
            "analyses": [],
            "attention": [],
            "actions": [],
            "not_found": [],
            "indices": [],
            "physician_note": "После загрузки анализов будут доступны клинические детали.",
        }
    cid = (case_id or "").strip()
    if cid:
        docs = [d for d in docs if (d.get("case_id") or "") == cid]
    if not docs:
        raise HTTPException(status_code=400, detail="В выбранной папке нет документов.")
    try:
        docs = sorted(docs, key=lambda d: float(d.get("created_at") or 0), reverse=True)[:10]
    except (TypeError, ValueError):
        docs = docs[:10]

    case_name = "Сводный отчёт"
    if cid:
        for c in get_lab_cases(uid, subject_id=sid):
            if c.get("id") == cid:
                case_name = c.get("name") or case_name
                break
    report = build_lab_report_from_docs(
        docs,
        case_name=case_name,
        profile=get_profile(uid),
        compact_for_doctor=False,
    )
    agg = report.get("aggregate_clinical") if isinstance(report.get("aggregate_clinical"), dict) else {}
    main = agg.get("main_conclusion") if isinstance(agg.get("main_conclusion"), dict) else {}
    analyses = []
    for row in (agg.get("document_matrix") or []):
        if not isinstance(row, dict):
            continue
        analyses.append(
            {
                "name": str(row.get("document") or "Анализ"),
                "priority": _summary_priority_to_api(str(row.get("priority") or "")),
            }
        )
    risk_level = "low"
    if any(x.get("priority") == "high" for x in analyses):
        risk_level = "high"
    elif any(x.get("priority") == "medium" for x in analyses):
        risk_level = "medium"

    grouped = agg.get("next_checks_grouped") if isinstance(agg.get("next_checks_grouped"), dict) else {}
    actions = []
    actions.extend([str(x).strip() for x in (grouped.get("high") or []) if str(x).strip()])
    actions.extend([str(x).strip() for x in (grouped.get("medium") or []) if str(x).strip()])
    actions.extend([str(x).strip() for x in (grouped.get("optional") or []) if str(x).strip()])
    if not actions:
        actions = [str(x).strip() for x in (agg.get("next_checks") or []) if str(x).strip()]

    indices = []
    for idx in (agg.get("derived_indices") or []):
        if not isinstance(idx, dict):
            continue
        indices.append(
            {
                "label": str(idx.get("name") or "Индекс"),
                "value": str(idx.get("value") or "—"),
                "comment": str(idx.get("interpretation") or ""),
            }
        )

    secondary = [str(x).strip() for x in (main.get("secondary_findings") or []) if str(x).strip()]
    return {
        "title": str(agg.get("title") or "🧾 Сводный отчёт"),
        "main": {
            "headline": str(main.get("main_priority") or report.get("display_summary") or ""),
            "subtext": "; ".join(secondary[:2]) if secondary else "Остальные находки вторичны по приоритету.",
            "risk_level": risk_level,
        },
        "analyses": analyses,
        "attention": [str(x).strip() for x in (agg.get("attention_zones") or []) if str(x).strip()][:10],
        "actions": actions[:12],
        "not_found": [str(x).strip() for x in (agg.get("not_supported") or []) if str(x).strip()][:10],
        "indices": indices[:10],
        "physician_note": "Полная клиническая интерпретация, гипотезы и расчёты доступны во врачебной версии отчёта.",
    }


@router.get("/reports/unified")
def reports_unified(
    case_id: str = Query(default=""),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """
    Единый JSON-контракт для frontend: patient + core + ui + documents.
    Frontend не вычисляет медицинскую логику, только рендерит.
    """
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    docs = [
        d for d in get_documents(uid, subject_id=sid)
        if (d.get("type") or "") not in ("lab_report_single", "lab_report_summary", "voice_concierge")
    ]
    if not docs:
        return serialize_aggregate_report_to_unified_payload(
            {
                "document_type": "aggregate_clinical_report",
                "aggregate_clinical": {
                    "title": "🧾 Сводный отчёт",
                    "main_conclusion": {
                        "main_priority": "Нет загруженных документов",
                        "secondary_findings": ["Загрузите анализы для построения сводной клинической картины."],
                    },
                    "document_matrix": [],
                    "attention_zones": [],
                    "not_supported": [],
                    "derived_indices": [],
                    "next_checks": [],
                    "next_checks_grouped": {"high": [], "medium": [], "optional": []},
                    "working_hypotheses": [],
                    "limitations": [],
                    "urgent": "",
                },
            },
            report_id="agg_empty",
        ).model_dump()

    cid = (case_id or "").strip()
    if cid:
        docs = [d for d in docs if (d.get("case_id") or "") == cid]
    if not docs:
        raise HTTPException(status_code=400, detail="В выбранной папке нет документов.")
    try:
        docs = sorted(docs, key=lambda d: float(d.get("created_at") or 0), reverse=True)[:10]
    except (TypeError, ValueError):
        docs = docs[:10]

    case_name = "Сводный отчёт"
    if cid:
        for c in get_lab_cases(uid, subject_id=sid):
            if c.get("id") == cid:
                case_name = c.get("name") or case_name
                break

    report = build_lab_report_from_docs(
        docs,
        case_name=case_name,
        profile=get_profile(uid),
        compact_for_doctor=False,
    )
    payload = serialize_aggregate_report_to_unified_payload(report)
    return payload.model_dump()


@router.post("/user/documents/clear-all")
def user_clear_all_documents(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Очистить все загруженные документы (необратимо)."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    count = clear_all_documents(uid, subject_id=sid)
    return {"user_id": uid, "cleared_count": count}


@router.delete("/user/documents/{document_id}")
def user_delete_document(
    document_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Мягкое удаление: документ помечается удалённым, файл сохраняется. Можно вернуть через restore."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    removed = store_delete_document(uid, document_id, subject_id=sid)
    if not removed:
        raise HTTPException(status_code=404, detail="Документ не найден.")
    return {"user_id": uid, "deleted_id": document_id}


@router.post("/user/documents/{document_id}/restore")
def user_restore_document(
    document_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Вернуть документ из корзины."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    restored = store_restore_document(uid, document_id, subject_id=sid)
    if not restored:
        raise HTTPException(status_code=404, detail="Документ не найден или не в корзине.")
    return {"user_id": uid, "document": restored}


@router.post("/user/documents/{document_id}/permanent-delete")
def user_permanent_delete_document(
    document_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Окончательно удалить документ из корзины (файл удаляется с диска). Необратимо."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    removed = store_permanent_delete_document(uid, document_id, subject_id=sid)
    if not removed:
        raise HTTPException(status_code=404, detail="Документ не найден.")
    path = get_upload_file_path(uid, removed)
    if path and path.exists():
        try:
            path.unlink(missing_ok=True)
        except Exception as e:
            logger.warning("permanent_delete_document file unlink failed doc_id=%s: %s", document_id, e)
    return {"user_id": uid, "permanent_deleted_id": document_id}


@router.patch("/user/documents/{document_id}")
def user_update_document(
    document_id: str,
    payload: DocumentUpdate,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Изменить документ: название/описание (summary) или извлечённый текст (extracted_text)."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    current = get_document_by_id(uid, document_id, subject_id=sid)
    if not current:
        raise HTTPException(status_code=404, detail="Документ не найден.")
    updates = {}
    if payload.summary is not None:
        updates["summary"] = payload.summary
    if payload.extracted_text is not None:
        updates["extracted_text"] = payload.extracted_text[:50000]
    if payload.case_id is not None:
        updates["case_id"] = payload.case_id or None
    if not updates:
        raise HTTPException(status_code=400, detail="Укажите summary, extracted_text или case_id для обновления.")
    updated = store_update_document(uid, document_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Документ не найден.")
    return {"user_id": uid, "document": updated}


@router.get("/user/severity")
def user_get_severity(x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    return {"user_id": uid, **get_severity(uid)}


@router.post("/user/severity")
def user_set_severity(payload: SeverityUpdate, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    out = save_severity(uid, payload.severity, payload.source or "dashboard")
    return {"user_id": uid, **out}


@router.get("/user/chat_history")
def user_get_chat_history(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    return {"user_id": uid, "messages": get_chat_history(uid, subject_id=sid)}


@router.post("/user/conversation-report")
def user_save_conversation_report(
    payload: ConversationReportRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Сохраняет диалог (голосовой или чат) как отчёт. Название — по жалобе и дате."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    messages = [{"role": m.role, "content": m.content or ""} for m in (payload.messages or [])]
    if not messages:
        raise HTTPException(status_code=400, detail="messages is required and must not be empty")
    report_id = save_conversation_as_report(uid, messages, title=payload.title, subject_id=sid)
    return {"user_id": uid, "report_id": report_id}


@router.post("/user/search-suggest")
def user_search_suggest(payload: SearchSuggestRequest):
    q = (payload.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query is required")
    limit = payload.limit if isinstance(payload.limit, int) else 8
    limit = max(1, min(limit, 20))
    suggestions = search_suggest(q, limit=limit)
    qn = q.lower()

    forum_hits: list[dict[str, Any]] = []
    for row in _forum_branch_items():
        if not isinstance(row, dict):
            continue
        hay = " ".join(
            [
                str(row.get("title") or ""),
                str(row.get("description") or ""),
                " ".join([str(x) for x in (row.get("tags") or [])]),
            ]
        ).lower()
        if qn in hay:
            forum_hits.append(
                {
                    "kind": "forum_branch",
                    "id": str(row.get("id") or ""),
                    "title": str(row.get("title") or ""),
                    "url": f"/forum?branch={quote(str(row.get('id') or ''))}",
                }
            )
        if len(forum_hits) >= limit:
            break

    faq_hits: list[dict[str, Any]] = []
    for it in list_faq():
        if not isinstance(it, dict):
            continue
        qq = str(it.get("question") or "")
        aa = str(it.get("answer") or "")
        if qn in qq.lower() or qn in aa.lower():
            faq_hits.append(
                {
                    "kind": "faq",
                    "id": str(it.get("id") or ""),
                    "title": qq[:140],
                    "url": "/help#faq",
                }
            )
        if len(faq_hits) >= limit:
            break

    complaint_hits = _search_complaint_candidates(q, top_k=min(6, limit))
    complaint_links = [
        {
            "kind": "complaint",
            "id": str(x.get("id") or ""),
            "title": str(x.get("title") or x.get("complaint") or "Жалоба"),
            "url": f"/dashboard?q={quote(str(x.get('title') or x.get('complaint') or q))}",
        }
        for x in complaint_hits
        if isinstance(x, dict)
    ]

    news_hits: list[dict[str, Any]] = []
    for it in _merged_news_items():
        if not isinstance(it, dict):
            continue
        hay = " ".join(
            [str(it.get("title") or ""), str(it.get("summary") or ""), " ".join([str(x) for x in (it.get("tags") or [])])]
        ).lower()
        if qn in hay:
            news_hits.append(
                {
                    "kind": "news",
                    "id": str(it.get("id") or ""),
                    "title": str(it.get("title") or ""),
                    "url": "/news",
                }
            )
        if len(news_hits) >= max(3, limit // 2):
            break

    cross_links = forum_hits + faq_hits + complaint_links + news_hits
    return {
        "query": q,
        "suggestions": suggestions,
        "cross_links": cross_links[: max(8, limit * 2)],
        "hints": suggestions[: min(6, len(suggestions))],
    }


@router.get("/user/lab-panel-preview")
def user_lab_panel_preview(
    profile: str = Query("", description="Название профиля из UI, например: Гистамин/MCAS-check"),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    uid = _user_id(x_user_id)
    result = get_lab_panel_preview(profile)
    return {"user_id": uid, **result}


@router.post("/user/microbiome-report")
def user_microbiome_report(
    payload: MicrobiomeReportRequest = Body(default_factory=MicrobiomeReportRequest),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """
    Microbiome Engine v1: отчёт по осям кишечник–организм (gut_muscle, gut_brain, gut_immune, gut_skin).
    Тело опционально; при отсутствии symptoms_text используется профиль пользователя (age).
    """
    uid = _user_id(x_user_id)
    profile = get_profile(uid) if uid else {}
    if isinstance(profile, dict) and payload.age is None and profile.get("age") is not None:
        try:
            age = int(profile["age"])
        except (TypeError, ValueError):
            age = None
    else:
        age = payload.age
    result = run_microbiome_engine(
        symptoms_text=payload.symptoms_text or "",
        age=age,
        low_activity=payload.low_activity,
        poor_diet=payload.poor_diet,
    )
    return {"user_id": uid, "microbiome_report": result}


@router.get("/user/trash")
def user_get_trash(x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    """Корзина: удалённые документы и отчёты. Сначала выполняется автоочистка старше 30 дней."""
    uid = _user_id(x_user_id)
    purge_deleted_older_than_30_days(uid)
    docs = get_documents(uid, include_deleted=True)
    doc_items = [d for d in docs if d.get("deleted_at")]
    recs = get_consultation_reports_list(uid, include_deleted=True)
    rec_items = [r for r in recs if r.get("deleted_at")]
    return {
        "user_id": uid,
        "documents": doc_items,
        "recommendations": rec_items,
    }


@router.get("/user/recommendations")
def user_get_recommendations(
    include_deleted: bool = False,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    enforce_chat_retention_policy(uid)
    items = get_consultation_reports_list(uid, include_deleted=include_deleted, subject_id=sid)
    return {"user_id": uid, "items": items}


@router.post("/user/recommendations/clear-all")
def user_clear_all_recommendations(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Очистить всю историю рекомендаций (необратимо)."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    count = clear_all_consultation_reports(uid, subject_id=sid)
    return {"user_id": uid, "cleared_count": count}


@router.get("/admin/feature-keys")
def admin_feature_keys(_: dict = Depends(_require_admin)):
    """Список всех ключей функций для настройки доступа (только админ)."""
    return {"user_default": USER_DEFAULT_FEATURES, "admin_only": ADMIN_ONLY_FEATURES, "all": ALL_FEATURE_KEYS}


@router.get("/admin/users")
def admin_list_users(_: dict = Depends(_require_admin)):
    """Список пользователей и их отключённых функций (только админ)."""
    return {"items": list_accounts()}


class AdminUserFeaturesUpdate(BaseModel):
    disabled_features: List[str]


@router.patch("/admin/users/{target_user_id}")
def admin_update_user_features(
    target_user_id: str,
    payload: AdminUserFeaturesUpdate,
    _: dict = Depends(_require_admin),
):
    """Задать отключённые функции для пользователя (только админ)."""
    try:
        out = set_user_disabled_features(target_user_id, payload.disabled_features or [])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, **out}


# ─── Помощь: FAQ и пользовательские вопросы ─────────────────────────────────
@router.get("/help/faq")
def help_faq_list(q: Optional[str] = Query(default=None)):
    """Публичный список FAQ (без авторизации)."""
    items = list_faq()
    query = (q or "").strip().lower()
    if query:
        filtered: list[dict[str, Any]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            hay = " ".join([str(it.get("question") or ""), str(it.get("answer") or ""), str(it.get("category") or "")]).lower()
            if query in hay:
                filtered.append(it)
        items = filtered
    return {"items": items, "categories": list(FAQ_CATEGORIES), "query": q or ""}


class HelpUserQuestionCreate(BaseModel):
    question: str


@router.get("/help/user-questions")
def help_user_questions_list(uid: str = Depends(_user_id)):
    """Список вопросов текущего пользователя."""
    return {"items": list_user_questions(uid, admin=False)}


@router.post("/help/user-questions")
def help_user_question_create(payload: HelpUserQuestionCreate, uid: str = Depends(_user_id)):
    """Задать вопрос (сохраняется за текущим пользователем)."""
    q = (payload.question or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Введите текст вопроса.")
    return {"item": create_user_question(uid, q)}


class HelpFaqCreate(BaseModel):
    question: str
    answer: str
    category: Optional[str] = "общее"


class HelpFaqUpdate(BaseModel):
    question: Optional[str] = None
    answer: Optional[str] = None
    category: Optional[str] = None
    order: Optional[int] = None


@router.get("/admin/help/faq")
def admin_help_faq_list(_: dict = Depends(_require_admin)):
    return {"items": list_faq(), "categories": list(FAQ_CATEGORIES)}


@router.post("/admin/help/faq")
def admin_help_faq_create(payload: HelpFaqCreate, _: dict = Depends(_require_admin)):
    item = create_faq(
        question=payload.question or "",
        answer=payload.answer or "",
        category=payload.category or "общее",
    )
    return {"item": item}


@router.patch("/admin/help/faq/{item_id}")
def admin_help_faq_update(item_id: str, payload: HelpFaqUpdate, _: dict = Depends(_require_admin)):
    item = update_faq(
        item_id,
        question=payload.question,
        answer=payload.answer,
        category=payload.category,
        order=payload.order,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Вопрос не найден.")
    return {"item": item}


@router.delete("/admin/help/faq/{item_id}")
def admin_help_faq_delete(item_id: str, _: dict = Depends(_require_admin)):
    if not delete_faq(item_id):
        raise HTTPException(status_code=404, detail="Вопрос не найден.")
    return {"ok": True}


@router.get("/admin/help/user-questions")
def admin_help_user_questions_list(_: dict = Depends(_require_admin)):
    return {"items": list_user_questions(None, admin=True)}


class HelpUserQuestionAnswer(BaseModel):
    answer: str
    answered_by_type: Optional[str] = "admin"


@router.patch("/admin/help/user-questions/{item_id}")
def admin_help_user_question_answer(item_id: str, payload: HelpUserQuestionAnswer, _: dict = Depends(_require_admin)):
    item = answer_user_question(item_id, payload.answer or "", payload.answered_by_type or "admin")
    if not item:
        raise HTTPException(status_code=404, detail="Вопрос не найден.")
    return {"item": item}


@router.delete("/admin/help/user-questions/{item_id}")
def admin_help_user_question_delete(item_id: str, _: dict = Depends(_require_admin)):
    if not delete_user_question(item_id):
        raise HTTPException(status_code=404, detail="Вопрос не найден.")
    return {"ok": True}


@router.get("/review/learning-candidates")
def review_learning_candidates(limit: int = 100, _: dict = Depends(_require_admin)):
    items = list_learning_candidates(limit=limit)
    stats = get_learning_queue_stats()
    return {"items": items, "stats": stats}


@router.get("/review/learning-candidates/{candidate_id}")
def review_learning_candidate_get(candidate_id: str, _: dict = Depends(_require_admin)):
    item = get_learning_candidate(candidate_id)
    if not item:
        raise HTTPException(status_code=404, detail="Кандидат не найден.")
    return {"item": item}


@router.patch("/review/learning-candidates/{candidate_id}")
def review_learning_candidate_patch(candidate_id: str, payload: LearningReviewUpdate, _: dict = Depends(_require_admin)):
    try:
        item = update_learning_candidate_review(
            candidate_id,
            review_status=payload.review_status,
            review_notes=payload.review_notes or "",
            reviewer=payload.reviewer or "",
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый review_status. Используйте pending, approved или rejected.")
    if not item:
        raise HTTPException(status_code=404, detail="Кандидат не найден.")
    if str(payload.review_status or "").strip().lower() == "approved":
        import os

        if os.environ.get("DISABLE_AUTO_MERGE_ON_FLYWHEEL_APPROVE", "").strip().lower() not in ("1", "true", "yes"):
            try:
                from app.services.task_queue import enqueue_task

                enqueue_task("knowledge_index_merge_flywheel", {"max_items": 12})
            except Exception as e:
                logger.debug("auto_merge_after_approve_failed", extra={"error": str(e)[:200]})
    return {"item": item, "stats": get_learning_queue_stats()}


@router.get("/review/knowledge-enrichment-results")
def review_knowledge_enrichment_results_list(limit: int = 100, _: dict = Depends(_require_admin)):
    from app.services.knowledge_enrichment_queue import list_enrichment_results

    return {"items": list_enrichment_results(limit=limit)}


@router.get("/review/knowledge-enrichment-jobs")
def review_knowledge_enrichment_jobs_list(limit: int = 100, _: dict = Depends(_require_admin)):
    from app.services.knowledge_enrichment_queue import list_enrichment_jobs

    return {"items": list_enrichment_jobs(limit=limit)}


@router.get("/review/knowledge-enrichment-results/{result_id}")
def review_knowledge_enrichment_result_get(result_id: str, _: dict = Depends(_require_admin)):
    from app.services.knowledge_enrichment_queue import get_enrichment_result

    item = get_enrichment_result(result_id)
    if not item:
        raise HTTPException(status_code=404, detail="Снимок не найден.")
    return {"item": item}


@router.patch("/review/knowledge-enrichment-results/{result_id}")
def review_knowledge_enrichment_result_patch(
    result_id: str,
    payload: KnowledgeEnrichmentStatusPatch,
    _: dict = Depends(_require_admin),
):
    from app.services.knowledge_enrichment_queue import update_enrichment_result_status

    item = update_enrichment_result_status(
        result_id,
        promotion_status=payload.promotion_status,
        notes=payload.notes or "",
    )
    if not item:
        raise HTTPException(status_code=404, detail="Снимок не найден.")
    return {"item": item}


@router.post("/review/knowledge-enrichment-results/{result_id}/promote")
def review_knowledge_enrichment_result_promote(
    result_id: str,
    reviewer: Optional[str] = Query(None, description="Подпись ревьюера для audit trail"),
    _: dict = Depends(_require_admin),
):
    from app.services.knowledge_enrichment_queue import promote_enrichment_result_to_flywheel

    try:
        out = promote_enrichment_result_to_flywheel(result_id, reviewer=reviewer or "")
    except ValueError as e:
        code = str(e)
        if code == "result_not_found":
            raise HTTPException(status_code=404, detail="Снимок не найден.")
        if code == "topic_too_short":
            raise HTTPException(status_code=400, detail="Тема слишком короткая для промоушена.")
        raise HTTPException(status_code=400, detail=code)
    return out


@router.post("/review/knowledge-index/merge-flywheel-approved")
def review_knowledge_index_merge_flywheel(
    payload: KnowledgeIndexMergeRequest,
    _: dict = Depends(_require_admin),
):
    """Слить одобренные кейсы flywheel в knowledge_cache/chunks.json (keyword-поиск)."""
    from app.services.knowledge_index_merge import merge_approved_flywheel_into_chunks

    return merge_approved_flywheel_into_chunks(max_new=max(1, min(int(payload.max_items or 25), 200)))


@router.post("/review/knowledge-enrichment/run-daily-clusters")
def review_knowledge_enrichment_run_daily_clusters(
    payload: DailyClusterEnrichmentRequest,
    _: dict = Depends(_require_admin),
):
    """Поставить в очередь обогащение по weak_complaints и слабым кластерам (системный пользователь)."""
    from app.services.knowledge_enrichment_queue import run_daily_cluster_enrichment_from_analytics

    return run_daily_cluster_enrichment_from_analytics(max_topics=max(1, min(int(payload.max_topics or 8), 40)))


@router.get("/review/knowledge-pipeline-overview")
def review_knowledge_pipeline_overview(_: dict = Depends(_require_admin)):
    """Сводка очередей enrichment / flywheel / индекса и подсказок по env (для операторов)."""
    from app.services.knowledge_pipeline_overview import build_knowledge_pipeline_overview

    return build_knowledge_pipeline_overview()


@router.get("/analytics/overview")
def analytics_overview(limit: int = 1000, _: dict = Depends(_require_admin)):
    return get_runtime_overview(limit=limit)


@router.get("/analytics/paywall")
def analytics_paywall(limit: int = 2000, _: dict = Depends(_require_admin)):
    events = get_runtime_events(limit=max(100, min(int(limit or 2000), 5000)), protocol_source="paywall")
    paywall_events = [e for e in events if str(e.get("source") or "").startswith("paywall_")]
    upgrades = [e for e in events if str(e.get("source") or "") == "subscription_upgrade"]

    source_counts: dict[str, int] = {}
    reason_counts: dict[str, int] = {}
    plan_counts: dict[str, int] = {}
    for e in paywall_events:
        src = str(e.get("source") or "unknown")
        source_counts[src] = int(source_counts.get(src) or 0) + 1
        reason = str(e.get("severity") or "unknown")
        reason_counts[reason] = int(reason_counts.get(reason) or 0) + 1
        model_used = str(e.get("model_used") or "")
        plan = model_used.replace("plan:", "").strip() if model_used.startswith("plan:") else "unknown"
        plan_counts[plan] = int(plan_counts.get(plan) or 0) + 1

    conversion_rate = 0.0
    if paywall_events:
        conversion_rate = round(len(upgrades) / len(paywall_events), 4)

    latest_events = sorted(paywall_events, key=lambda x: float(x.get("created_at") or 0), reverse=True)[:30]
    latest_upgrades = sorted(upgrades, key=lambda x: float(x.get("created_at") or 0), reverse=True)[:20]

    return {
        "summary": {
            "paywall_events_total": len(paywall_events),
            "upgrades_total": len(upgrades),
            "upgrade_conversion_rate": conversion_rate,
        },
        "source_counts": source_counts,
        "reason_counts": reason_counts,
        "plan_counts": plan_counts,
        "latest_events": latest_events,
        "latest_upgrades": latest_upgrades,
    }


@router.get("/analytics/release-gate")
def analytics_release_gate(limit: int = 1000, _: dict = Depends(_require_admin)):
    overview = get_runtime_overview(limit=limit)
    return overview.get("release_quality_gate") or {}


@router.get("/analytics/release-gate-policy")
def analytics_release_gate_policy_get(_: dict = Depends(_require_admin)):
    return get_release_gate_policy()


@router.patch("/analytics/release-gate-policy")
def analytics_release_gate_policy_patch(payload: ReleaseGatePolicyUpdate, _: dict = Depends(_require_admin)):
    return update_release_gate_policy(payload.model_dump(exclude_none=True))


@router.get("/analytics/threshold-presets")
def analytics_threshold_presets(_: dict = Depends(_require_admin)):
    return list_threshold_presets()


@router.post("/analytics/threshold-presets/{preset_id}/apply")
def analytics_threshold_preset_apply(preset_id: str, _: dict = Depends(_require_admin)):
    try:
        return apply_threshold_preset(preset_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Preset не найден.")


@router.get("/analytics/release-checklist")
def analytics_release_checklist(limit: int = 1000, _: dict = Depends(_require_admin)):
    overview = get_runtime_overview(limit=limit)
    gate = overview.get("release_quality_gate") or {}
    return {
        "gate": gate,
        "draft_stats": draft_stats(),
        "review_queue_stats": get_learning_queue_stats(),
        "backlog_stats": backlog_stats(),
        "weak_complaints": overview.get("weak_complaints") or [],
        "top_quality_complaints": overview.get("top_quality_complaints") or [],
    }


@router.get("/analytics/release-decision-bundle")
def analytics_release_decision_bundle(limit: int = 1000, _: dict = Depends(_require_admin)):
    overview = get_runtime_overview(limit=limit)
    bundle = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gate": overview.get("release_quality_gate") or {},
        "routing_control": get_routing_control_config(),
        "release_gate_policy": get_release_gate_policy(),
        "checklist": {
            "draft_stats": draft_stats(),
            "review_queue_stats": get_learning_queue_stats(),
            "backlog_stats": backlog_stats(),
        },
        "weak_complaints": overview.get("weak_complaints") or [],
        "top_quality_complaints": overview.get("top_quality_complaints") or [],
        "cluster_roadmap": overview.get("cluster_roadmap") or [],
        "rollups": {
            "weekly": overview.get("weekly_rollup") or {},
            "monthly": overview.get("monthly_rollup") or {},
        },
        "cost": {
            "llm_calls": overview.get("llm_calls"),
            "offline_saved_calls": overview.get("offline_saved_calls"),
            "estimated_cost_usd_total": overview.get("estimated_cost_usd_total"),
            "avg_estimated_cost_usd_per_llm_call": overview.get("avg_estimated_cost_usd_per_llm_call"),
        },
    }
    bundle["release_recommendation"] = _build_release_recommendation(bundle)
    return bundle


def _build_priority_cluster(bundle: dict) -> dict:
    roadmap = list(bundle.get("cluster_roadmap") or [])
    weak = list(bundle.get("weak_complaints") or [])
    if not roadmap and not weak:
        return {}

    if roadmap:
        top = roadmap[0] or {}
        cluster_name = str(top.get("cluster") or "")
        weakest = list(top.get("weakest_complaints") or [])
        return {
            "cluster": cluster_name,
            "reason": "Минимальный средний quality score в cluster roadmap.",
            "avg_quality_score": top.get("avg_quality_score"),
            "offline_share": top.get("offline_share"),
            "weakest_complaints": weakest[:3],
        }

    first_weak = weak[0] or {}
    return {
        "cluster": str(first_weak.get("cluster") or ""),
        "reason": "Кластер определён по самой слабой жалобе.",
        "avg_quality_score": None,
        "offline_share": first_weak.get("offline_share"),
        "weakest_complaints": [str(first_weak.get("complaint") or "")] if first_weak.get("complaint") else [],
    }


def _build_staged_rollout_plan(decision: str, gate: dict, bundle: dict) -> list[str]:
    llm_share = float(gate.get("llm_share") or 0.0)
    total_events = int(gate.get("total_events") or 0)
    weak = list(bundle.get("weak_complaints") or [])

    if decision == "go_with_caution":
        plan = [
            "Stage 1: internal beta или ограниченный pilot на контролируемой аудитории.",
            "Stage 2: ежедневно проверять release cockpit, weak complaints и review queue.",
            "Stage 3: расширять трафик только если quality gate остаётся не хуже warn и не растёт доля weak complaints.",
        ]
        if llm_share > 0.8:
            plan.append("Во время rollout держать под контролем LLM share и cost spike.")
        if weak:
            plan.append(
                "До расширения rollout усилить жалобы: "
                + ", ".join(str(x.get("complaint") or "") for x in weak[:3] if x.get("complaint"))
            )
        return plan[:5]

    if decision == "go":
        plan = [
            "Можно запускать staged rollout с базовым ежедневным мониторингом quality gate.",
            "Отслеживать weak complaints, review queue и стоимость на weekly rollup.",
        ]
        if total_events < 20:
            plan.append("При низком объёме данных сохранить ручной контроль первых дней после релиза.")
        return plan[:4]

    return []


def _build_priority_cluster_sprint_plan(priority_cluster: dict, checklist: dict) -> list[dict]:
    cluster_name = str(priority_cluster.get("cluster") or "")
    weakest = list(priority_cluster.get("weakest_complaints") or [])
    if not cluster_name:
        return []

    draft_stats = checklist.get("draft_stats") or {}
    review_stats = checklist.get("review_queue_stats") or {}
    backlog_stats = checklist.get("backlog_stats") or {}
    weakest_text = ", ".join(str(x) for x in weakest if x) or "ключевые слабые жалобы"

    return [
        {
            "step": "review",
            "title": "Разобрать реальные кейсы и сигналы",
            "goal": "Понять, почему кластер проседает по quality score.",
            "ui_target": "review-queue",
            "action_label": "Open review queue",
            "actions": [
                "Проверить review queue и approved/pending кейсы по жалобам кластера.",
                "Сверить weak complaints с cluster roadmap и backlog.",
            ],
            "done_when": "Есть список главных причин деградации по кластеру " + cluster_name + ".",
        },
        {
            "step": "draft",
            "title": "Подготовить обновления знаний",
            "goal": "Собрать draft-изменения для слабых complaint flows.",
            "ui_target": "analytics-drafts",
            "action_label": "Open draft candidates",
            "actions": [
                "Создать или обновить draft candidates для: " + weakest_text + ".",
                "Заполнить недостающие anamnesis, red flags, labs и offline recommendations.",
            ],
            "done_when": "Есть готовые draft-кандидаты для ключевых слабых жалоб.",
        },
        {
            "step": "apply",
            "title": "Применить и закрепить изменения",
            "goal": "Перенести согласованные улучшения в offline knowledge.",
            "ui_target": "cluster-workspace",
            "action_label": "Open cluster workspace",
            "actions": [
                "Approve/apply согласованные draft candidates.",
                "Закрыть связанные backlog items после внесения изменений.",
            ],
            "done_when": "Изменения применены, backlog по кластеру уменьшен.",
        },
        {
            "step": "validate",
            "title": "Проверить эффект после изменений",
            "goal": "Подтвердить, что quality gate и cluster metrics улучшаются.",
            "ui_target": "analytics",
            "action_label": "Open analytics validation",
            "actions": [
                "Обновить analytics overview и release cockpit.",
                "Проверить quality score, weak complaints и долю LLM для кластера.",
            ],
            "done_when": "Кластер " + cluster_name + " больше не выглядит главным риском релиза.",
        },
        {
            "step": "ops",
            "title": "Закрепить операционный режим",
            "goal": "Встроить улучшенный кластер в регулярный цикл управления качеством.",
            "ui_target": "analytics",
            "action_label": "Open operations analytics",
            "actions": [
                "Продолжать weekly review по кластеру и approved cases.",
                "Следить за draft/review/backlog метриками: drafts={0}, pending_reviews={1}, open_backlog={2}.".format(
                    int(draft_stats.get("pending") or 0),
                    int(review_stats.get("pending") or 0),
                    int(backlog_stats.get("open") or 0),
                ),
            ],
            "done_when": "У кластера есть устойчивый operational контроль после исправлений.",
        },
    ]


def _build_release_recommendation(bundle: dict) -> dict:
    gate = bundle.get("gate") or {}
    issues = list(gate.get("issues") or [])
    weak = list(bundle.get("weak_complaints") or [])
    cost = bundle.get("cost") or {}
    checklist = bundle.get("checklist") or {}
    total_events = int(gate.get("total_events") or 0)
    llm_share = float(gate.get("llm_share") or 0.0)
    status = str(gate.get("status") or "unknown")
    draft_stats = checklist.get("draft_stats") or {}
    review_stats = checklist.get("review_queue_stats") or {}
    backlog_stats = checklist.get("backlog_stats") or {}
    priority_cluster = _build_priority_cluster(bundle)

    if status == "fail":
        decision = "no_go"
        summary = "Релиз не рекомендован: quality gate не пройден."
    elif status == "warn":
        decision = "go_with_caution"
        summary = "Релиз возможен с ограничениями: есть warning-сигналы, требующие контроля."
    elif status == "pass":
        decision = "go"
        summary = "Релиз рекомендован: ключевые quality-сигналы в допустимой зоне."
    else:
        decision = "needs_review"
        summary = "Решение требует ручной проверки: статус quality gate не определён."

    reasons: list[str] = []
    if issues:
        reasons.extend([str(x) for x in issues[:5]])
    if not issues and status == "pass":
        reasons.append("Критические проблемы по quality gate не обнаружены.")
    if weak:
        top_weak = weak[:3]
        reasons.append(
            "Слабые жалобы для ближайшего улучшения: "
            + ", ".join(str(x.get("complaint") or "") for x in top_weak if x.get("complaint"))
        )
    if total_events < 10:
        reasons.append("Низкий объём событий может делать вывод по релизу менее устойчивым.")
    if llm_share > 0.8:
        reasons.append("Высокая зависимость от LLM повышает cost/risk profile.")
    if float(cost.get("estimated_cost_usd_total") or 0) == 0 and total_events > 0:
        reasons.append("Стоимость пока выглядит нулевой: проверьте полноту cost telemetry.")
    if decision == "no_go" and priority_cluster.get("cluster"):
        reasons.append(
            "Приоритетный кластер для доработки: " + str(priority_cluster.get("cluster") or "")
        )

    blockers: list[str] = []
    next_actions: list[str] = []
    ready_now: list[str] = []

    if status == "fail":
        blockers.append("Закрыть проблемы quality gate до выпуска.")
    if total_events < 10:
        blockers.append("Набрать больше runtime-событий для устойчивого решения по релизу.")
    if weak:
        blockers.append(
            "Усилить слабые жалобы: "
            + ", ".join(str(x.get("complaint") or "") for x in weak[:3] if x.get("complaint"))
        )
    if int(review_stats.get("pending") or 0) > 0:
        next_actions.append("Разобрать pending кейсы в review queue.")
    if int(draft_stats.get("pending") or 0) > 0:
        next_actions.append("Проверить и применить pending draft candidates.")
    if int(backlog_stats.get("open") or 0) > 0:
        next_actions.append("Запланировать sprint по открытому improvement backlog.")
    if llm_share > 0.8:
        next_actions.append("Снизить долю LLM за счёт offline-first coverage и complaint enrichment.")
    if float(cost.get("estimated_cost_usd_total") or 0) == 0 and total_events > 0:
        next_actions.append("Проверить pipeline cost telemetry и корректность записи estimated cost.")

    if status == "pass":
        ready_now.append("Можно выпускать релиз на текущую аудиторию.")
    elif status == "warn":
        ready_now.append("Можно выпускать ограниченно: pilot, internal beta или staged rollout.")
    if llm_share <= 0.8:
        ready_now.append("LLM share находится в контролируемой зоне.")
    if not weak:
        ready_now.append("Слабые complaint flows не выявлены текущей аналитикой.")
    if int(review_stats.get("approved") or 0) > 0:
        ready_now.append("Есть approved cases для переноса в offline knowledge flywheel.")

    if decision == "no_go" and priority_cluster.get("cluster"):
        next_actions.insert(
            0,
            "Сфокусировать ближайший sprint на кластере "
            + str(priority_cluster.get("cluster") or "")
            + ".",
        )

    staged_rollout_plan = _build_staged_rollout_plan(decision, gate, bundle)
    priority_cluster_sprint_plan = _build_priority_cluster_sprint_plan(priority_cluster, checklist)

    return {
        "decision": decision,
        "summary": summary,
        "gate_status": status,
        "reasons": reasons[:6],
        "blockers": blockers[:5],
        "next_actions": next_actions[:6],
        "ready_now": ready_now[:5],
        "priority_cluster": priority_cluster,
        "staged_rollout_plan": staged_rollout_plan,
        "priority_cluster_sprint_plan": priority_cluster_sprint_plan,
    }


@router.get("/analytics/release-decision-report")
def analytics_release_decision_report(limit: int = 1000, _: dict = Depends(_require_admin)):
    bundle = analytics_release_decision_bundle(limit=limit)
    gate = bundle.get("gate") or {}
    checklist = bundle.get("checklist") or {}
    weak = bundle.get("weak_complaints") or []
    strong = bundle.get("top_quality_complaints") or []
    roadmap = bundle.get("cluster_roadmap") or []
    cost = bundle.get("cost") or {}
    recommendation = bundle.get("release_recommendation") or {}

    lines = [
        "Release Decision Report",
        "",
        "Generated at: " + str(bundle.get("generated_at") or ""),
        "Final verdict: " + str(recommendation.get("decision") or "needs_review"),
        "Verdict summary: " + str(recommendation.get("summary") or ""),
        "Gate status: " + str(gate.get("status") or "unknown"),
        "",
        "Recommendation reasons:",
    ]
    reasons = list(recommendation.get("reasons") or [])
    if reasons:
        lines.extend(["- " + str(x) for x in reasons])
    else:
        lines.extend(
            [
                "- No explicit recommendation reasons available.",
            ]
        )
    lines.extend(
        [
            "",
            "Blockers before release:",
        ]
    )
    blockers = list(recommendation.get("blockers") or [])
    if blockers:
        lines.extend(["- " + str(x) for x in blockers])
    else:
        lines.append("- Blocking items not detected.")
    lines.extend(
        [
            "",
            "Next actions:",
        ]
    )
    next_actions = list(recommendation.get("next_actions") or [])
    if next_actions:
        lines.extend(["- " + str(x) for x in next_actions])
    else:
        lines.append("- No immediate actions suggested.")
    lines.extend(
        [
            "",
            "Ready now:",
        ]
    )
    ready_now = list(recommendation.get("ready_now") or [])
    if ready_now:
        lines.extend(["- " + str(x) for x in ready_now])
    else:
        lines.append("- No explicit ready-now items.")
    priority_cluster = recommendation.get("priority_cluster") or {}
    lines.extend(
        [
            "",
            "Priority cluster:",
        ]
    )
    if priority_cluster.get("cluster"):
        lines.append("- Cluster: " + str(priority_cluster.get("cluster") or ""))
        lines.append("- Reason: " + str(priority_cluster.get("reason") or ""))
        weakest_complaints = list(priority_cluster.get("weakest_complaints") or [])
        if weakest_complaints:
            lines.append("- Weakest complaints: " + ", ".join(str(x) for x in weakest_complaints))
    else:
        lines.append("- No priority cluster suggested.")
    lines.extend(
        [
            "",
            "Staged rollout plan:",
        ]
    )
    rollout_plan = list(recommendation.get("staged_rollout_plan") or [])
    if rollout_plan:
        lines.extend(["- " + str(x) for x in rollout_plan])
    else:
        lines.append("- No staged rollout plan suggested.")
    lines.extend(
        [
            "",
            "Priority cluster sprint plan:",
        ]
    )
    sprint_plan = list(recommendation.get("priority_cluster_sprint_plan") or [])
    if sprint_plan:
        for row in sprint_plan:
            lines.append("- Step: " + str(row.get("step") or ""))
            lines.append("  Title: " + str(row.get("title") or ""))
            lines.append("  Goal: " + str(row.get("goal") or ""))
            for action in list(row.get("actions") or []):
                lines.append("  Action: " + str(action))
            lines.append("  Done when: " + str(row.get("done_when") or ""))
    else:
        lines.append("- No sprint plan suggested.")
    lines.extend(
        [
        "",
        "Issues:",
        ]
    )
    issues = list(gate.get("issues") or [])
    if issues:
        lines.extend(["- " + str(x) for x in issues[:10]])
    else:
        lines.append("- Critical issues not detected.")
    lines.extend(
        [
            "",
            "Cost and routing:",
            "- LLM calls: " + str(cost.get("llm_calls") or 0),
            "- Offline saved: " + str(cost.get("offline_saved_calls") or 0),
            "- Estimated cost USD: " + str(cost.get("estimated_cost_usd_total") or 0),
            "- Avg cost / LLM call: " + str(cost.get("avg_estimated_cost_usd_per_llm_call") or 0),
            "",
            "Checklist:",
            "- Draft stats: " + str(checklist.get("draft_stats") or {}),
            "- Review queue stats: " + str(checklist.get("review_queue_stats") or {}),
            "- Backlog stats: " + str(checklist.get("backlog_stats") or {}),
            "",
            "Weak complaints:",
        ]
    )
    if weak:
        lines.extend(
            [
                "- {0}: quality={1}, offline_share={2}, approved={3}".format(
                    str(x.get("complaint") or ""),
                    str(x.get("quality_score") or 0),
                    str(x.get("offline_share") or 0),
                    str(x.get("approved_cases") or 0),
                )
                for x in weak[:10]
            ]
        )
    else:
        lines.append("- No weak complaints flagged.")
    lines.append("")
    lines.append("Top quality complaints:")
    if strong:
        lines.extend(
            [
                "- {0}: quality={1}, maturity={2}".format(
                    str(x.get("complaint") or ""),
                    str(x.get("quality_score") or 0),
                    str(x.get("maturity") or ""),
                )
                for x in strong[:10]
            ]
        )
    else:
        lines.append("- No high-quality complaint flows yet.")
    lines.append("")
    lines.append("Cluster roadmap:")
    if roadmap:
        lines.extend(
            [
                "- {0}: quality={1}, maturity={2}, weakest={3}".format(
                    str(x.get("cluster") or ""),
                    str(x.get("avg_quality_score") or 0),
                    str(x.get("maturity") or ""),
                    ", ".join(x.get("weakest_complaints") or []),
                )
                for x in roadmap[:12]
            ]
        )
    else:
        lines.append("- No cluster roadmap available.")

    return {
        "title": "Release Decision Report",
        "body": "\n".join(lines).strip(),
        "bundle": bundle,
        "release_recommendation": recommendation,
    }


@router.get("/analytics/improvement-backlog")
def analytics_improvement_backlog(limit: int = 200, _: dict = Depends(_require_admin)):
    return {"items": list_backlog(limit=limit), "stats": backlog_stats()}


@router.get("/analytics/draft-candidates")
def analytics_draft_candidates(limit: int = 200, _: dict = Depends(_require_admin)):
    return {"items": list_draft_candidates(limit=limit), "stats": draft_stats()}


@router.post("/analytics/draft-candidates")
def analytics_draft_candidates_create(payload: DraftCreateRequest, _: dict = Depends(_require_admin)):
    item = create_draft_candidate(
        complaint=payload.complaint,
        cluster=payload.cluster or "",
        source=payload.source or "analytics",
        notes=payload.notes or "",
        draft_entry=payload.draft_entry or {},
    )
    return {"item": item, "stats": draft_stats()}


@router.patch("/analytics/draft-candidates/{draft_id}")
def analytics_draft_candidates_update(draft_id: str, payload: DraftUpdateRequest, _: dict = Depends(_require_admin)):
    try:
        item = update_draft_candidate(draft_id, status=payload.status, notes=payload.notes or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый status. Используйте pending, approved, applied или rejected.")
    if not item:
        raise HTTPException(status_code=404, detail="Draft candidate не найден.")
    return {"item": item, "stats": draft_stats()}


@router.get("/analytics/draft-candidates/{draft_id}/diff")
def analytics_draft_candidates_diff(draft_id: str, _: dict = Depends(_require_admin)):
    diff = get_draft_diff(draft_id)
    if not diff:
        raise HTTPException(status_code=404, detail="Draft candidate не найден.")
    return diff


@router.post("/analytics/draft-candidates/{draft_id}/apply")
def analytics_draft_candidates_apply(draft_id: str, _: dict = Depends(_require_admin)):
    item = apply_draft_candidate(draft_id)
    if not item:
        raise HTTPException(status_code=404, detail="Draft candidate не найден или не может быть применён.")
    return {"applied_item": item, "stats": draft_stats()}


@router.post("/analytics/improvement-backlog")
def analytics_improvement_backlog_create(payload: BacklogCreateRequest, _: dict = Depends(_require_admin)):
    item = add_backlog_item(
        complaint=payload.complaint,
        cluster=payload.cluster or "",
        reason=payload.reason or "",
        source=payload.source or "analytics",
    )
    return {"item": item, "stats": backlog_stats()}


@router.patch("/analytics/improvement-backlog/{item_id}")
def analytics_improvement_backlog_update(item_id: str, payload: BacklogUpdateRequest, _: dict = Depends(_require_admin)):
    try:
        item = update_backlog_item(item_id, status=payload.status, notes=payload.notes or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="Недопустимый status. Используйте open, in_progress, done или cancelled.")
    if not item:
        raise HTTPException(status_code=404, detail="Элемент backlog не найден.")
    return {"item": item, "stats": backlog_stats()}


@router.get("/analytics/enrichment-suggestion")
def analytics_enrichment_suggestion(complaint: str, _: dict = Depends(_require_admin)):
    return complaint_enrichment_suggestion(complaint)


@router.get("/analytics/cluster-sprint")
def analytics_cluster_sprint(cluster: str, _: dict = Depends(_require_admin)):
    return cluster_sprint_plan(cluster)


@router.get("/analytics/cluster-workspace")
def analytics_cluster_workspace(cluster: str, _: dict = Depends(_require_admin)):
    return cluster_workspace(cluster)


@router.get("/user/recommendations/{report_id}")
def user_get_recommendation_item(
    report_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    item = get_consultation_report_item(uid, report_id, subject_id=sid)
    if not item:
        raise HTTPException(status_code=404, detail="Отчёт не найден.")
    return {"user_id": uid, "item": item}


@router.delete("/user/recommendations/{report_id}")
def user_delete_recommendation_item(
    report_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    ok = delete_consultation_report(uid, report_id, subject_id=sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Отчёт не найден.")
    return {"user_id": uid, "deleted_id": report_id}


@router.post("/user/recommendations/{report_id}/restore")
def user_restore_recommendation_item(
    report_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    ok = restore_consultation_report(uid, report_id, subject_id=sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Отчёт не найден или не в корзине.")
    return {"user_id": uid, "restored_id": report_id}


@router.post("/user/recommendations/{report_id}/permanent-delete")
def user_permanent_delete_recommendation_item(
    report_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Окончательно удалить отчёт из корзины. Необратимо."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    ok = store_permanent_delete_consultation_report(uid, report_id, subject_id=sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Отчёт не найден.")
    return {"user_id": uid, "permanent_deleted_id": report_id}


@router.post("/user/chat/resume-today")
def user_chat_resume_today(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    out = resume_chat_from_today_voice_diary(uid, subject_id=sid)
    return {"user_id": uid, **out}


@router.get("/user/share-access")
def user_get_share_access(x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    items = get_share_accesses(uid, access_kind="doctor")
    return {"user_id": uid, "items": items}


@router.post("/user/share-access")
def user_create_share_access_link(payload: ShareAccessCreate, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    item = create_share_access(
        uid,
        label=(payload.label or "").strip(),
        doctor_name=(payload.doctor_name or "").strip(),
        days_valid=int(payload.days_valid or 30),
        one_time=bool(payload.one_time),
        session_minutes=int(payload.session_minutes or 30),
    )
    return {"user_id": uid, "item": item}


@router.delete("/user/share-access/{share_id}")
def user_revoke_share_access_link(share_id: str, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    ok = revoke_share_access(uid, share_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Ссылка доступа не найдена.")
    return {"user_id": uid, "revoked_id": share_id}


@router.get("/user/family-access")
def user_get_family_access(x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    items = get_share_accesses(uid, access_kind="family")
    return {"user_id": uid, "items": items}


@router.post("/user/family-access")
def user_create_family_access_link(payload: FamilyAccessCreate, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    try:
        item = create_family_access(
            uid,
            member_name=(payload.member_name or "").strip(),
            relation=(payload.relation or "").strip(),
            role=(payload.role or "family_viewer").strip(),
            permissions=payload.permissions or {},
            days_valid=int(payload.days_valid or 30),
            one_time=bool(payload.one_time),
            session_minutes=int(payload.session_minutes or 30),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"user_id": uid, "item": item}


@router.delete("/user/family-access/{share_id}")
def user_revoke_family_access_link(share_id: str, x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    ok = revoke_share_access(uid, share_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Семейная ссылка доступа не найдена.")
    return {"user_id": uid, "revoked_id": share_id}


@router.get("/share/{token}/folder")
def public_shared_folder(token: str):
    data = get_shared_snapshot_by_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Ссылка недействительна или срок действия истёк.")
    perms = ((data.get("share") or {}).get("permissions") or {})
    uid = data.get("user_id") or ""
    docs = get_documents(uid) if perms.get("documents") else []
    recs = get_consultation_reports_list(uid) if perms.get("recommendations") else []
    items = []
    for d in docs:
        doc_id = str(d.get("id") or "").strip()
        if not doc_id:
            continue
        created = d.get("created_at")
        name = str(d.get("filename") or d.get("summary") or ("document_" + doc_id + ".txt"))
        items.append(
            {
                "id": "doc:" + doc_id,
                "kind": "document",
                "name": name,
                "type": d.get("type") or "report",
                "created_at": created,
                "open_url": "/api/share/" + quote(token, safe="") + "/documents/" + quote(doc_id, safe=""),
            }
        )
    for r in recs:
        rid = str(r.get("id") or "").strip()
        if not rid:
            continue
        base = str(r.get("title") or "Рекомендация").strip() or "Рекомендация"
        filename = base + ".txt"
        items.append(
            {
                "id": "rec:" + rid,
                "kind": "recommendation",
                "name": filename,
                "type": "consultation_report",
                "created_at": r.get("created_at"),
                "open_url": "/api/share/" + quote(token, safe="") + "/recommendations/" + quote(rid, safe=""),
            }
        )
    items.sort(key=lambda x: float(x.get("created_at") or 0.0))
    return {
        "share": data.get("share"),
        "items": items,
        "disclaimer": "Данные предоставлены владельцем кабинета по приватной ссылке.",
    }


@router.get("/share/{token}/documents/{document_id}")
def public_shared_document_open(token: str, document_id: str):
    data = get_shared_snapshot_by_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Ссылка недействительна или срок действия истёк.")
    perms = ((data.get("share") or {}).get("permissions") or {})
    if not perms.get("documents"):
        raise HTTPException(status_code=403, detail="По этой ссылке доступ к документам отключён.")
    uid = str(data.get("user_id") or "").strip()
    if not uid:
        raise HTTPException(status_code=404, detail="Ссылка недействительна.")
    doc = get_document_by_id(uid, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Документ не найден.")
    path = get_upload_file_path(uid, doc)
    filename = str(doc.get("filename") or ("document_" + str(document_id) + ".txt"))
    filename = filename.replace('"', "").replace("\r", " ").replace("\n", " ").strip() or "document.txt"
    if path and path.exists():
        media_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=filename)
    text = (doc.get("extracted_text") or doc.get("summary") or "").strip()
    if not text:
        text = "Документ доступен по ссылке, но исходный файл не найден в хранилище."
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/share/{token}/recommendations/{report_id}")
def public_shared_recommendation_open(token: str, report_id: str):
    data = get_shared_snapshot_by_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Ссылка недействительна или срок действия истёк.")
    perms = ((data.get("share") or {}).get("permissions") or {})
    if not perms.get("recommendations"):
        raise HTTPException(status_code=403, detail="По этой ссылке доступ к рекомендациям отключён.")
    uid = str(data.get("user_id") or "").strip()
    if not uid:
        raise HTTPException(status_code=404, detail="Ссылка недействительна.")
    item = get_consultation_report_item(uid, report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Отчёт не найден.")
    text = _build_shared_report_text(item)
    filename = ((item.get("title") or "recommendation") + ".txt").replace('"', "").replace("\r", " ").replace("\n", " ").strip()
    if not filename:
        filename = "recommendation.txt"
    return Response(
        content=text,
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/share/{token}")
def public_shared_snapshot(token: str):
    data = get_shared_snapshot_by_token(token)
    if not data:
        raise HTTPException(status_code=404, detail="Ссылка недействительна или срок действия истёк.")
    return {
        "share": data.get("share"),
        "snapshot": data.get("snapshot"),
        "disclaimer": "Данные предоставлены владельцем кабинета по приватной ссылке.",
    }


@router.get("/user/action-sequence/latest")
def user_get_latest_action_sequence(x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    uid = _user_id(x_user_id)
    item = get_latest_action_sequence(uid)
    return {"user_id": uid, "item": item or None}


def _strip_html_for_export(text: str) -> str:
    """Убирает HTML из строк для шаринга/экспорта (plain text)."""
    s = str(text or "")
    s = re.sub(r"(?is)<script.*?>.*?</script>", " ", s)
    s = re.sub(r"(?is)<style.*?>.*?</style>", " ", s)
    s = re.sub(r"(?is)<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _build_shared_report_text(item: dict) -> str:
    title = str(item.get("title") or "Отчёт консультации").strip()
    created = item.get("created_at")
    dt = ""
    try:
        if created:
            from datetime import datetime

            dt = datetime.fromtimestamp(float(created)).strftime("%d.%m.%Y %H:%M")
    except Exception:
        dt = ""
    parts = [
        title,
        ("Дата: " + dt) if dt else "",
        "",
        "Кратко:",
        _strip_html_for_export(item.get("summary") or ""),
        "",
        "Сводка случая:",
        _strip_html_for_export(item.get("case_summary") or ""),
        "",
        "Профессиональная сводка:",
        _strip_html_for_export(item.get("professional_summary") or ""),
        "",
        "Рекомендованные шаги:",
        _strip_html_for_export(item.get("safe_next_steps") or ""),
        "",
        "Когда срочно:",
        _strip_html_for_export(item.get("when_urgent") or ""),
        "",
    ]
    return "\n".join([p for p in parts if p is not None]).strip() + "\n"


def _build_lab_report_text(title: str, report: dict) -> str:
    def _dedup_keep_order(items: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for x in items or []:
            s = str(x or "").strip()
            if not s:
                continue
            low = s.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(s)
        return out

    def _is_metabolic_report(rep: dict) -> bool:
        probe = " ".join(
            [
                str(rep.get("input_data") or ""),
                str(rep.get("findings") or ""),
                str(rep.get("hypotheses") or ""),
                str(rep.get("diagnosis") or ""),
                str(rep.get("treatment_plan") or ""),
                str(rep.get("diagnostics") or ""),
            ]
        ).lower()
        keys = (
            "органическ",
            "аминокис",
            "жирн",
            "метабол",
            "митохонд",
            "цикл кребс",
            "ацидеми",
            "ацидур",
            "масс-спектр",
            "масс спектр",
            "gc-ms",
            "гх-мс",
            "лактат",
            "пируват",
            "сукцинат",
            "фумарат",
            "малат",
            "цитрат",
            "метилмалон",
            "оксалат",
            "креатинин",
            "ммоль/моль",
            "ацетоацет",
            "3-гидроксибутират",
            "гиппур",
            "метилгиппур",
            "квинолинов",
            "ксантурен",
            "оротов",
        )
        return any(k in probe for k in keys)

    def _take_human_items(items: list[str], max_items: int = 6) -> list[str]:
        cleaned = [_humanize(x) for x in (items or [])]
        cleaned = [x for x in cleaned if x]
        return _dedup_keep_order(cleaned)[:max_items]

    def _metabolic_addon_block(rep: dict) -> list[str]:
        prebuilt = rep.get("metabolic_sections")
        if isinstance(prebuilt, dict) and prebuilt:
            out = ["Метаболический контекст (структурированный блок 1-7):"]
            map_blocks = [
                ("1. Краткое резюме находок", prebuilt.get("summary_of_findings") or []),
                ("2. Интерпретация метаболических путей", prebuilt.get("pathway_interpretation") or []),
                ("3. Оценка кофакторов", prebuilt.get("cofactor_assessment") or []),
                ("4. Дифференциальные метаболические гипотезы", prebuilt.get("differential_hypotheses") or []),
                ("5. Поддержка питанием и образом жизни", prebuilt.get("nutritional_support") or []),
                ("6. Рекомендации по дообследованию", prebuilt.get("further_diagnostics") or []),
            ]
            for title, items in map_blocks:
                out.append(title + ":")
                clean_items = [str(x).strip() for x in (items or []) if str(x).strip()]
                if not clean_items:
                    clean_items = ["Недостаточно метаболических данных для уверенной интерпретации."]
                out.extend(["- " + x for x in clean_items[:8]])
                out.append("")
            out.append("7. Медицинский дисклеймер:")
            out.append("- Это метаболическая интерпретация и она не заменяет очную диагностику у врача.")
            md = str(
                prebuilt.get("medical_disclaimer")
                or "Информация носит образовательный характер и не заменяет консультацию врача."
            ).strip()
            if md:
                out.append("- " + md)
            out.append("")
            return out

        findings = _take_human_items(rep.get("findings") or [], max_items=8)
        hypotheses = _take_human_items(rep.get("hypotheses") or [], max_items=8)
        diagnosis = _take_human_items(rep.get("diagnosis") or [], max_items=6)
        treatment_plan = _take_human_items(rep.get("treatment_plan") or [], max_items=8)
        alt = _take_human_items(rep.get("alternative_treatment") or [], max_items=8)
        diagnostics = _take_human_items(rep.get("diagnostics") or [], max_items=8)

        cofactor_keys = (
            "b2",
            "b3",
            "b6",
            "b12",
            "витамин",
            "кофактор",
            "nad",
            "fad",
            "coq10",
            "селен",
            "цинк",
        )
        pathway_keys = (
            "цикл",
            "кребс",
            "путь",
            "митохонд",
            "триптофан",
            "кинурен",
            "метабол",
            "ацид",
            "лактат",
            "пируват",
            "сукцинат",
            "фумарат",
            "малат",
            "цитрат",
            "глутатион",
        )
        nutr_keys = (
            "питани",
            "диет",
            "рацион",
            "белк",
            "жир",
            "углевод",
            "оксалат",
            "вода",
            "гидрат",
            "пробиот",
            "клетчат",
            "anti-inflammatory",
            "воспал",
            "витамин d",
        )

        combined = findings + hypotheses + diagnosis + treatment_plan + alt
        pathway = [x for x in combined if any(k in x.lower() for k in pathway_keys)]
        cofactors = [x for x in combined if any(k in x.lower() for k in cofactor_keys)]
        nutrition = [x for x in (alt + treatment_plan) if any(k in x.lower() for k in nutr_keys)]

        # Ensure sections stay informative even on sparse data.
        if not pathway and hypotheses:
            pathway = hypotheses[:4]
        if not cofactors:
            cofactors = [x for x in (hypotheses + findings) if "дефицит" in x.lower() or "витамин" in x.lower()][:4]
        if not nutrition:
            nutrition = alt[:4]

        disclaimer = str(rep.get("disclaimer") or "Информация носит справочный характер.").strip()
        out = ["Метаболический контекст (структурированный блок 1-7):", "1. Краткое резюме находок:"]
        out.extend(["- " + x for x in (findings[:6] or ["Недостаточно метаболических данных для уверенной интерпретации."])])
        out.append("")
        out.append("2. Интерпретация метаболических путей:")
        out.extend(["- " + x for x in (pathway[:6] or ["Недостаточно метаболических данных для уверенной интерпретации."])])
        out.append("")
        out.append("3. Оценка кофакторов:")
        out.extend(["- " + x for x in (cofactors[:6] or ["Недостаточно метаболических данных для уверенной интерпретации."])])
        out.append("")
        out.append("4. Дифференциальные метаболические гипотезы:")
        out.extend(["- " + x for x in ((hypotheses[:4] + diagnosis[:2]) or ["Недостаточно метаболических данных для уверенной интерпретации."])])
        out.append("")
        out.append("5. Поддержка питанием и образом жизни:")
        out.extend(["- " + x for x in (nutrition[:6] or ["Недостаточно метаболических данных для уверенной интерпретации."])])
        out.append("")
        out.append("6. Рекомендации по дообследованию:")
        out.extend(["- " + x for x in (diagnostics[:6] or ["Недостаточно метаболических данных для уверенной интерпретации."])])
        out.append("")
        out.append("7. Медицинский дисклеймер:")
        out.append("- Это метаболическая интерпретация и она не заменяет очную диагностику у врача.")
        out.append("- Информация носит образовательный характер и не заменяет консультацию врача.")
        if disclaimer:
            out.append("- " + disclaimer)
        out.append("")
        return out

    def _is_noise_line(text: str) -> bool:
        low = str(text or "").lower()
        canon = re.sub(r"[^a-zа-яё0-9]+", "", low)
        if not low.strip():
            return True
        if low.strip() in {"дефицит витамина d", "дефицит витамина d.", "дефицит витамина d:"}:
            return True
        # Hide cohort/methodology snippets in patient report text.
        if " детей " in low and "у " in low:
            return True
        research_noise = (
            "в плане дальнейших исследований",
            "в целях уточнения диагноза намечены",
            "повторное исследование органи",
            "во многих случаях также использовалось определение",
            "определение ацилкарнитинов",
            "анализ ацилкарнитинов крови",
            "молекулярно-генетическ",
            "биоматериалом служили пятна крови",
            "маркерными метаболитами этого заболевания являются",
            "маркерными ме- таболитами этого заболевания являются",
            "субериновая и себациновая кислоты",
            "предположен дефицит короткоце",
            "установлен диагноз дефицита длинноце",
            "дефицит одной из них",
            "выше 2,7 +другие метаболиты фенилаланина",
            "маркер недостаточности глицина и в5",
        )
        if any(f in low for f in research_noise):
            return True
        research_noise_canon = (
            "впланедальнейшихисследований",
            "вцеляхуточнениядиагнозанамечены",
            "повторноеисследованиеорганическихкислотвмочеианализацилкарнитиновкрови",
            "вомногихслучаяхтакжеиспользовалосьопределение",
            "определениеацилкарнитинов",
            "анализацилкарнитиновкрови",
            "молекулярногенетическ",
            "биоматериаломслужилипятнакрови",
            "маркернымиметаболитамиэтогозаболеванияявляются",
            "субериноваяисебациноваякислоты",
            "предположендефициткороткоце",
            "установлендиагноздефицитадлинноце",
            "дефицитоднойизних",
            "выше27другиеметаболитыфенилаланина",
        )
        if any(f in canon for f in research_noise_canon):
            return True
        if "у 14 детей ре-" in low:
            return True
        if "у 14 детей результаты хроматографического анализа органических кислот" in low:
            return True
        if "topic: drugs" in low:
            return True
        if "do not rely on openfda" in low:
            return True
        if "<!doctype html" in low or "<html" in low:
            return True
        if "\"meta\"" in low and "\"results\"" in low:
            return True
        if "openfda" in low and ((low.count("{") + low.count("}")) >= 2):
            return True
        braces = low.count("{") + low.count("}")
        if braces >= 12:
            return True
        return False

    def _humanize(line: str) -> str:
        s = str(line or "").strip()
        if not s:
            return ""
        if _is_noise_line(s):
            return ""
        replacements = (
            ("Справочная гипотеза (база знаний): ", ""),
            ("Гипотеза по документному маркеру: ", ""),
            ("Рабочая гипотеза (strict 350+/50+): ", "Рабочая гипотеза: "),
            ("Рекомендованные препараты (strict): ", "Рекомендованные препараты: "),
            ("Аналоги (strict): ", "Аналоги препаратов: "),
            ("Дополнительная справка: ", ""),
        )
        for old, new in replacements:
            s = s.replace(old, new)
        if _is_noise_line(s):
            return ""
        return s

    lines: list[str] = [str(title or "Отчёт по анализам").strip(), ""]
    has_thematic = bool(report.get("thematic_metabolite_sections"))
    compact_for_doctor = bool(report.get("compact_for_doctor"))
    overview = [str(x).strip() for x in (report.get("metabolic_overview") or []) if str(x).strip()]
    findings_items = report.get("findings") or []
    if has_thematic and overview:
        # Keep overview inside "Выводы" instead of a separate duplicate block.
        findings_items = overview
    blocks = []
    if not compact_for_doctor:
        blocks.append(("Вводные данные", report.get("input_data") or []))
    if not compact_for_doctor:
        blocks.extend(
            [
                ("Выводы", findings_items),
                ("Гипотезы", report.get("hypotheses") or []),
                ("Рабочий диагноз", report.get("diagnosis") or []),
                ("Лечение", report.get("treatment_plan") or []),
                ("Препараты", report.get("medications") or []),
                ("Альтернативное лечение", report.get("alternative_treatment") or []),
                ("Физические упражнения", report.get("physical_exercises") or []),
                ("Диагностика/контроль", report.get("diagnostics") or []),
            ]
        )
    # User-facing report should not include article/library citation blocks.
    for section, items in blocks:
        items = [_humanize(x) for x in (items or [])]
        items = [x for x in items if x]
        if not items:
            continue
        lines.append(section + ":")
        lines.extend(["- " + x for x in items[:40]])
        lines.append("")
        lines.append("")
    if has_thematic:
        block_intro = {
            "Метаболиты цикла Кребса": "Оценивает эффективность клеточного энергообмена и признаки митохондриального напряжения.",
            "Кетоновые тела и углеводный обмен": "Показывает баланс углеводного обмена, кетогенеза и бета-окисления жирных кислот.",
            "Аминокислотный обмен": "Помогает выявить нарушения путей фенилаланина/тирозина/триптофана и BCAA.",
            "Витамин-зависимые маркеры": "Указывает на вероятные дефициты витаминных кофакторов и нутритивных факторов.",
            "Маркеры детоксикации и токсического воздействия": "Отражает возможную токсическую нагрузку и состояние детоксикационных путей.",
        }

        tables = report.get("metabolite_tables") or {}
        if tables:
            lines.append("Тематические разделы по метаболитам:")
            header = "| Метаболит | Категория | Референсный диапазон | Результат | Оценка | Пояснение |"
            sep = "|---|---|---:|---:|---|---|"
            for sec in (
                "Метаболиты цикла Кребса",
                "Кетоновые тела и углеводный обмен",
                "Аминокислотный обмен",
                "Витамин-зависимые маркеры",
                "Маркеры детоксикации и токсического воздействия",
            ):
                rows = tables.get(sec) or []
                if not rows:
                    continue
                lines.append(sec + ":")
                lines.append("- " + block_intro.get(sec, ""))
                lines.append(header)
                lines.append(sep)
                for r in rows[:80]:
                    line = (
                        f"| {r.get('metabolite','')} | {r.get('category','')} | {r.get('reference','')} | "
                        f"{r.get('result','')} | {r.get('assessment','')} | {r.get('explanation','')} |"
                    )
                    lines.append(line)
                lines.append("")

        themed = report.get("thematic_metabolite_sections") or {}
        if not tables and themed:
            lines.append("Тематические разделы по метаболитам:")
            for sec in (
                "Метаболиты цикла Кребса",
                "Кетоновые тела и углеводный обмен",
                "Аминокислотный обмен",
                "Витамин-зависимые маркеры",
                "Маркеры детоксикации и токсического воздействия",
            ):
                rows = [str(x).strip() for x in (themed.get(sec) or []) if str(x).strip()]
                if not rows:
                    continue
                lines.append(sec + ":")
                lines.extend(["- " + _humanize(x) for x in rows[:40] if _humanize(x)])
                lines.append("")

        grouped = report.get("grouped_hypotheses") or {}
        if grouped:
            lines.append("Гипотезы (по темам):")
            for theme, rows in grouped.items():
                clean_rows = [str(x).strip() for x in (rows or []) if str(x).strip()]
                if not clean_rows:
                    continue
                lines.append(theme + ":")
                lines.extend(["- " + _humanize(x) for x in clean_rows[:20] if _humanize(x)])
                lines.append("")

        unified = report.get("unified_recommendations") or {}
        if unified:
            lines.append("Единый раздел рекомендаций:")
            for theme in ("Основные дефициты и питание", "Исследования для контроля", "Экология и образ жизни"):
                rows = [str(x).strip() for x in (unified.get(theme) or []) if str(x).strip()]
                if not rows:
                    continue
                lines.append(theme + ":")
                lines.extend(["- " + _humanize(x) for x in rows[:25] if _humanize(x)])
                lines.append("")

        glossary = [str(x).strip() for x in (report.get("glossary_terms") or []) if str(x).strip()]
        if glossary:
            lines.append("Пояснения простым языком:")
            lines.extend(["- " + _humanize(x) for x in glossary[:20] if _humanize(x)])
            lines.append("")

    if (not compact_for_doctor) and (not any(len(str((report.get(k) or []))) > 2 for k in ("input_data", "findings", "hypotheses", "diagnosis", "treatment_plan"))):
        lines.append("Ключевые структурные блоки не заполнены полностью. Нужны дополнительные данные.")
        lines.append("")
    if (report.get("safe_next_steps") or "").strip():
        lines.append("Что делать дальше:")
        lines.append("- " + str(report.get("safe_next_steps")).strip())
        lines.append("")
    if _is_metabolic_report(report) and not has_thematic:
        lines.extend(_metabolic_addon_block(report))
    lines.append(
        "Важно: "
        + str(
            report.get("educational_disclaimer")
            or report.get("disclaimer")
            or "Информация носит справочный характер."
        )
    )
    return "\n".join(lines).strip() + "\n"


def _save_generated_lab_report(
    uid: str,
    report: dict,
    *,
    report_kind: str,
    base_filename: str,
    case_id: Optional[str] = None,
    compact_for_doctor: bool = False,
    subject_id: Optional[str] = None,
) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"{base_filename}_{stamp}.txt"
    report_for_store = dict(report or {})
    report_for_store["compact_for_doctor"] = bool(compact_for_doctor)
    text = _build_lab_report_text(base_filename.replace("_", " "), report_for_store)[:50000]
    store_add_document(
        uid,
        {
            "type": report_kind,
            "summary": "Сформированный отчёт по анализам",
            "filename": filename,
            "extracted_text": text,
            "case_id": case_id or None,
            "subject_id": _subject_id(subject_id),
        },
    )


@router.post("/auth/register")
def auth_register(payload: AuthCredentials):
    try:
        user = register_user(payload.login, payload.password, name=(payload.name or ""))
        sess = create_session(user["user_id"], role="user")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    u = get_user_by_session(sess["token"])
    features = get_enabled_features("user", list(u.get("disabled_features") or [])) if u else []
    return {
        "ok": True,
        "user_id": user["user_id"],
        "login_kind": user["login_kind"],
        "login": user["login"],
        "role": "user",
        "features": features,
        "token": sess["token"],
        "expires_at": sess["expires_at"],
    }


@router.post("/auth/login")
def auth_login(payload: AuthCredentials):
    try:
        user = authenticate_user(payload.login, payload.password)
        role = user.get("role") or "user"
        sess = create_session(user["user_id"], role=role)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=str(e))
    u = get_user_by_session(sess["token"])
    disabled = list(u.get("disabled_features") or []) if u else []
    features = get_enabled_features(role, disabled)
    return {
        "ok": True,
        "user_id": user["user_id"],
        "login_kind": user["login_kind"],
        "login": user["login"],
        "name": user.get("name") or "",
        "role": role,
        "features": features,
        "token": sess["token"],
        "expires_at": sess["expires_at"],
    }


@router.get("/auth/me")
def auth_me(authorization: Optional[str] = Header(None, alias="Authorization")):
    token = _bearer_token(authorization)
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    role = user.get("role") or "user"
    disabled = list(user.get("disabled_features") or [])
    features = get_enabled_features(role, disabled)
    out = {k: v for k, v in user.items() if k != "disabled_features"}
    out["ok"] = True
    out["features"] = features
    return out


@router.post("/auth/change-password")
def auth_change_password(
    payload: AuthChangePassword,
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    token = _bearer_token(authorization)
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    try:
        change_password(user["user_id"], payload.old_password, payload.new_password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/auth/logout")
def auth_logout(authorization: Optional[str] = Header(None, alias="Authorization")):
    token = _bearer_token(authorization)
    if token:
        revoke_session(token)
    return {"ok": True}


@router.post("/auth/passkey/register/start")
def auth_passkey_register_start(payload: PasskeyStartRequest):
    login = (payload.login or "").strip()
    password = (payload.password or "").strip()
    if not login or not password:
        raise HTTPException(status_code=400, detail="login и password обязательны для подключения отпечатка.")
    origin = (payload.origin or "").strip() or "http://localhost:8000"
    rp_id = (payload.rp_id or "").strip() or "localhost"
    try:
        out = begin_passkey_registration(login, password, origin=origin, rp_id=rp_id)
    except ValueError as e:
        msg = str(e)
        code = 503 if "webauthn" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)
    return {"ok": True, **out}


@router.post("/auth/passkey/register/finish")
def auth_passkey_register_finish(payload: PasskeyFinishRequest):
    try:
        out = finish_passkey_registration(payload.flow_id, payload.credential or {})
    except ValueError as e:
        msg = str(e)
        code = 503 if "webauthn" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)
    return out


@router.post("/auth/passkey/login/start")
def auth_passkey_login_start(payload: PasskeyStartRequest):
    login = (payload.login or "").strip()
    if not login:
        raise HTTPException(status_code=400, detail="login обязателен.")
    origin = (payload.origin or "").strip() or "http://localhost:8000"
    rp_id = (payload.rp_id or "").strip() or "localhost"
    try:
        out = begin_passkey_login(login, origin=origin, rp_id=rp_id)
    except ValueError as e:
        msg = str(e)
        code = 503 if "webauthn" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)
    return {"ok": True, **out}


@router.post("/auth/passkey/login/finish")
def auth_passkey_login_finish(payload: PasskeyFinishRequest):
    try:
        out = finish_passkey_login(payload.flow_id, payload.credential or {})
    except ValueError as e:
        msg = str(e)
        code = 503 if "webauthn" in msg.lower() else 400
        raise HTTPException(status_code=code, detail=msg)
    return out


@router.post("/auth/passkey/disable")
def auth_passkey_disable(authorization: Optional[str] = Header(None, alias="Authorization")):
    token = _bearer_token(authorization)
    user = get_user_by_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    try:
        disabled = disable_passkeys(user.get("user_id") or "")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "disabled_count": disabled}


@router.get("/user/tts/voices")
async def user_get_tts_voices():
    try:
        voices = await get_tts_voices()
    except TTSProviderError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"provider": get_tts_client_provider_label(), "items": voices}


@router.post("/user/tts/speak")
async def user_tts_speak(
    payload: TtsSpeakRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    _user_id(x_user_id, authorization)  # keep user context parity with other /user endpoints
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    try:
        audio_bytes, voice_used, provider = await synthesize_tts(text=text, voice=payload.voice, rate=payload.rate)
    except TTSProviderError as e:
        raise HTTPException(status_code=503, detail=str(e))
    media_type = "audio/ogg" if provider == "yandex" else ("audio/wav" if provider in ("local_tts", "local_xtts") else "audio/mpeg")
    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={"X-TTS-Provider": provider, "X-TTS-Voice": voice_used},
    )


@router.post("/user/voice/transcribe")
async def user_voice_transcribe(
    file: UploadFile = File(..., description="Аудио: webm, mp3, wav, m4a и др."),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Транскрипция голоса в текст (Whisper). Для надёжной записи жалоб без ограничений браузера."""
    _user_id(x_user_id, authorization)
    content_type = file.content_type or ""
    try:
        audio_bytes = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать файл: {e}")
    if not audio_bytes or len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Файл пустой или больше 25 МБ")
    try:
        text = await transcribe_audio(audio_bytes, content_type=content_type)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    return {"text": text}


@router.post("/user/voice/quality-event")
def user_voice_quality_event_post(
    payload: VoiceQualityEventPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """Лог клиентских voice-событий (ошибки STT/TTS/permissions) для контроля качества перед релизом."""
    uid = _user_id(x_user_id)
    event = str(payload.event or "").strip().lower()
    if not event:
        raise HTTPException(status_code=400, detail="event is required")
    severity = str(payload.severity or "info").strip().lower() or "info"
    detail = (payload.detail or "").strip()
    source = "voice_client_" + event[:60]
    _record_voice_quality_event(source=source, complaint=detail, severity=severity)
    return {"user_id": uid, "ok": True, "source": source}


@router.post("/user/emergency/audit")
def user_emergency_audit_post(
    payload: EmergencyAuditPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = normalize_subject_id(x_subject_id)
    source = str(payload.source or "").strip().lower()
    if not source:
        raise HTTPException(status_code=400, detail="source is required")
    event = append_emergency_audit_event(
        uid,
        {
            "source": source,
            "channel": str(payload.channel or "ui"),
            "trigger_text": str(payload.trigger_text or ""),
            "status": str(payload.status or "requested"),
            "meta": payload.meta if isinstance(payload.meta, dict) else {},
        },
    )
    log_audit_event(
        uid,
        "emergency_action_requested",
        {
            "subject_id": sid,
            "source": source,
            "channel": str(payload.channel or "ui"),
            "status": str(payload.status or "requested"),
            "trigger_text": str(payload.trigger_text or "")[:180],
        },
    )
    return {"user_id": uid, "ok": True, "event": event}


@router.get("/analytics/emergency-events")
def analytics_emergency_events_get(
    source: Optional[str] = Query(None, description="Фильтр по source: footer_button, chat_button, voice_command"),
    limit: int = Query(300, ge=1, le=2000),
):
    return get_emergency_analytics_snapshot(limit=limit, source=source or "")


@router.get("/user/voice/stt-status")
def user_voice_stt_status(x_user_id: Optional[str] = Header(None, alias="X-User-Id")):
    """Технический статус server-side STT (ключи/ffmpeg/активный провайдер)."""
    uid = _user_id(x_user_id)
    status = get_stt_runtime_status()
    return {"user_id": uid, **status}


def _do_delete_symptoms(uid: str, payload: SymptomDeletePayload, subject_id: Optional[str] = None):
    """Общая логика удаления записей симптомов."""
    if payload.clear_all:
        store_clear_symptom_entries(uid, subject_id=subject_id)
        return {"user_id": uid, "entries": []}
    raw = payload.entry_indices or []
    indices = []
    for x in raw:
        try:
            indices.append(int(x) if isinstance(x, int) else int(float(x)))
        except (TypeError, ValueError):
            pass
    if not indices:
        raise HTTPException(status_code=400, detail="Укажите entry_indices или clear_all: true")
    entries = store_delete_symptom_entries(uid, indices, subject_id=subject_id)
    return {"user_id": uid, "entries": entries}


# Маршруты удаления — объявляем выше /user/symptoms, чтобы /user/symptoms/delete матчился первым
@router.post("/user/symptoms/delete")
def user_delete_symptoms_post(
    payload: SymptomDeletePayload = Body(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Удалить выбранные записи по индексам или очистить всю историю (clear_all: true)."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    return _do_delete_symptoms(uid, payload, subject_id=sid)


@router.delete("/user/symptoms")
def user_delete_symptoms_delete(
    payload: SymptomDeletePayload = Body(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """То же удаление по DELETE (если клиент отправляет body)."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    return _do_delete_symptoms(uid, payload, subject_id=sid)


@router.get("/user/symptoms")
def user_get_symptoms(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    return {"user_id": uid, "entries": get_symptom_entries(uid, subject_id=sid)}


@router.post("/user/symptoms")
def user_add_symptom(
    payload: SymptomAdd,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    sid = _subject_id(x_subject_id)
    entries = add_symptom_entry(uid, text, source="form", subject_id=sid)
    return {"user_id": uid, "entries": entries}


@router.post("/consultation/structured")
async def consultation_structured_post(
    payload: StructuredConsultationPayload,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Структурированная консультация: области тела + симптомы + ответы Михаила → результат от бэкенда."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    body_areas = list(payload.body_areas or [])
    symptoms = list(payload.symptoms or [])
    answers = payload.mikhail_answers or {}
    parts = []
    if body_areas:
        parts.append("Области тела: " + ", ".join(str(a).strip() for a in body_areas if str(a).strip()))
    if symptoms:
        parts.append("Симптомы: " + ", ".join(str(s).strip() for s in symptoms if str(s).strip()))
    duration = answers.get("duration") or answers.get("duration_label") or ""
    if duration:
        parts.append("Длительность: " + str(duration))
    severity = answers.get("severity") or answers.get("severity_label") or ""
    if severity:
        parts.append("Выраженность: " + str(severity))
    meds = answers.get("medications") or answers.get("medications_label") or ""
    if meds:
        parts.append("Медикаменты: " + str(meds))
    red_flags = answers.get("red_flags") or answers.get("red_flags_label") or ""
    if red_flags:
        parts.append("Тревожные признаки: " + str(red_flags))
    user_message = ". ".join(parts) if parts else "Консультация по жалобам."
    store_clear_symptom_entries(uid, subject_id=sid)
    for s in symptoms:
        if str(s).strip():
            add_symptom_entry(uid, str(s).strip(), source="structured_consultation", subject_id=sid)
    profile = get_profile(uid)
    documents = get_documents(uid, subject_id=sid)
    symptom_entries = get_symptom_entries(uid, subject_id=sid)
    chat_history = []
    document_context = get_last_consultation_report_context(uid, subject_id=sid)
    settings = get_settings(uid)
    app_mode = (settings.get("mode") or "BASIC").strip() or None
    vitals = get_vitals(uid)
    result = await run_consultation_turn(
        user_id=uid,
        user_message=user_message,
        profile=profile,
        documents_count=len(documents),
        symptom_entries=symptom_entries,
        chat_history=chat_history,
        app_mode=app_mode,
        vitals=vitals,
        document_context=document_context or None,
        subject_id=sid,
        consultation_mode_hint=None,
    )
    report = result.get("report") or {}
    severity = str(result.get("severity") or "YELLOW").upper()
    care_level = "low" if severity == "GREEN" else ("high" if severity == "RED" else "medium")
    care_labels = {
        "GREEN": "Планово — наблюдайте за симптомами",
        "YELLOW": "Обратиться к врачу",
        "RED": "Срочно"
    }
    hypotheses = report.get("hypotheses") or []
    top_hyp = (report.get("structured_consultation") or {}).get("top_hypotheses") or []
    causes = [str(h) for h in hypotheses] if hypotheses else []
    if not causes and top_hyp:
        causes = [str(h.get("name") or h.get("label_ru") or h) for h in top_hyp if isinstance(h, dict)]
    if not causes:
        causes = ["См. выводы в отчёте"]
    treatment = report.get("treatment") or []
    what_to_do = report.get("safe_next_steps") or ("; ".join(treatment) if treatment else "Наблюдение и обращение к врачу при сохранении симптомов.")
    nutrition = report.get("nutrition") or []
    nutrition_text = "; ".join(nutrition) if nutrition else ""
    activity = report.get("activity") or report.get("prevention") or []
    activity_text = "; ".join(activity) if activity else ""
    # Fallback для ОРЗ/ОРВИ: если API вернул нерелевантный контент (сыр, дневник питания) — подставляем ОРВИ-рекомендации
    user_msg_lower = (user_message or "").lower()
    is_respiratory = any(
        k in user_msg_lower
        for k in ("орз", "орви", "простуда", "кашель", "насморк", "горло", "температура", "боль в горле", "заложенность")
    )
    api_text_lower = (nutrition_text + " " + what_to_do + " " + activity_text).lower()
    wrong_for_respiratory = bool(
        is_respiratory
        and any(k in api_text_lower for k in ("сыр", "дневник питания", "пищевые триггеры", "подозрительн"))
    )
    if wrong_for_respiratory:
        nutrition_text = "Тёплые напитки (чай, компот, бульон). Лёгкая пища. Избегайте холодного и раздражающего. Достаточно витамина C (цитрусовые, шиповник)."
        activity_text = "Покой в острый период. После улучшения — лёгкая ходьба 15–20 минут. Избегайте интенсивных нагрузок до полного выздоровления."
        what_to_do = _append_rx_footer_if_missing(
            "Отдых и обильное питьё. Следите за изменениями симптомов. "
            "При необходимости — парацетамол или ибупрофен по инструкции. "
            "Альтернатива: тёплое питьё, полоскание горла."
        )
        if not causes or causes == ["См. выводы в отчёте"]:
            causes = ["ОРВИ, простуда", "Вирусная инфекция верхних дыхательных путей"]
    treatment_str = "; ".join(treatment) if treatment else what_to_do
    doctor_report = {
        "anamnesis": _strip_html_for_export(str(report.get("case_summary") or user_message)),
        "conclusions": _strip_html_for_export(
            str(report.get("display_summary") or report.get("case_summary") or "Клиническая картина по собранным данным.")
        ),
        "hypotheses": ", ".join(str(h) for h in hypotheses) if hypotheses else "",
        "diagnosis": ", ".join(str(h) for h in hypotheses[:3]) if hypotheses else "",
        "treatment": treatment_str,
        "alternatives": "; ".join(report.get("alternative_treatment") or []) if not wrong_for_respiratory else "Тёплое питьё, полоскание горла (соль, сода, ромашка). Ингаляции при отсутствии противопоказаний.",
        "nutrition": nutrition_text or "Питание по назначению врача.",
        "supplements": "Витамин C 500–1000 мг/сут. Цинк 15–30 мг/сут при первых симптомах. По назначению врача." if wrong_for_respiratory else "Добавки и витамины по назначению врача.",
        "labTests": "; ".join(report.get("diagnostics") or []),
        "exercise": activity_text or "Режим активности по назначению врача.",
    }
    _ue_snap = (
        ((result.get("structured") or {}).get("unified_engine_snapshot"))
        if isinstance(result.get("structured"), dict)
        else None
    )
    if isinstance(_ue_snap, dict):
        _ue_snap = tag_unified_snapshot(dict(_ue_snap))
    return {
        "title": report.get("title") or "Результаты оценки",
        "subtitle": "По итогам консультации",
        "careLevel": care_level,
        "careLevelLabel": care_labels.get(severity, "Обратиться к врачу"),
        "careLevelDescription": report.get("safe_next_steps") or "Рекомендуется наблюдение. При ухудшении — обратитесь к врачу.",
        "timeframe": "В течение 1–2 недель" if severity != "RED" else "В срочном порядке",
        "causes": causes if isinstance(causes, list) else [causes],
        "whatToDo": what_to_do,
        "nutrition": nutrition_text or report.get("user_summary", ""),
        "physicalExercise": activity_text,
        "whenToSeeDoctor": report.get("when_urgent") or "При усилении симптомов или если не станет лучше через 2–3 дня.",
        "doctorReport": doctor_report,
        "report_id": result.get("report_id"),
        "unified_engine_snapshot": _ue_snap,
        "clinical_core": clinical_core_envelope(
            subject_id=sid,
            documents_count=len(documents),
            symptom_entries_count=len(symptom_entries),
        ),
    }


@router.post("/consultation/run", response_model=ConsultationRunResponse)
def consultation_run_post(
    payload: ConsultationRunRequest,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    """Smoke endpoint for class-style orchestrator adapter."""
    uid = _user_id(x_user_id, authorization)
    user_text = (payload.user_text or "").strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="user_text is required")

    result = _consultation_orchestrator_adapter.run_consultation(
        user_id=uid,
        user_text=user_text,
        debug=bool(payload.debug),
        extra_context=dict(payload.extra_context or {}),
    )
    return result


@router.post("/user/chat")
async def user_chat_post(
    payload: ChatMessage,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    msg = _strip_dialog_question_prefix((payload.message or "").strip())
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")
    recent_chat_history = get_chat_history(uid, subject_id=sid)
    consultation_state = get_consultation_state(uid, subject_id=sid) or {}
    dc_active = _dialog_companion_active(consultation_state)
    if dc_active and _should_force_exit_companion(msg):
        save_consultation_state(uid, {"dialog_companion": {"active": False}}, subject_id=sid)
        consultation_state = get_consultation_state(uid, subject_id=sid) or {}
        dc_active = False
    route_state = consultation_state.get("dialogue_route") if isinstance(consultation_state.get("dialogue_route"), dict) else {}
    pending_route_mode = str(route_state.get("pending_mode") or "").strip().lower()
    pending_route_message = str(route_state.get("pending_message") or "").strip()

    def _finalize_chat_payload(out_payload: dict[str, Any]) -> dict[str, Any]:
        base_payload = dict(out_payload or {})
        if "knowledge_enrichment" not in base_payload:
            base_payload["knowledge_enrichment"] = {"queued": False, "reason": "not_applicable"}
        docs_count = len(get_documents(uid, subject_id=sid))
        sym_count = len(get_symptom_entries(uid, subject_id=sid))
        inject_kw = dict(
            subject_id=sid,
            documents_count=docs_count,
            symptom_entries_count=sym_count,
        )
        normalized_payload = _inject_unified_engine_snapshot(base_payload, **inject_kw)
        try:
            gated = apply_final_relevance_gate(msg, normalized_payload, channel="chat")
            return _inject_unified_engine_snapshot(
                gated if isinstance(gated, dict) else normalized_payload,
                **inject_kw,
            )
        except Exception:
            return normalized_payload

    user_settings = get_settings(uid)
    plan = _normalize_subscription_plan(str(user_settings.get("subscription") or "free"))
    limits = _plan_limits(plan)
    is_active = _is_subscription_active(user_settings)
    daily_limit = limits.get("messages_per_day")
    used_today = _count_user_messages_today(recent_chat_history)

    if not is_active:
        paywall_payload = _build_paywall_payload(
            uid=uid,
            plan_type=plan,
            limit=daily_limit,
            used=used_today,
            response_source="paywall_subscription_expired",
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", paywall_payload["response"], subject_id=sid)
        _record_paywall_event(source="paywall_subscription_expired_chat", plan_type=plan, reason="expired", message=msg)
        return _finalize_chat_payload(paywall_payload)

    if isinstance(daily_limit, int) and daily_limit > 0 and used_today >= daily_limit:
        paywall_payload = _build_paywall_payload(
            uid=uid,
            plan_type=plan,
            limit=daily_limit,
            used=used_today,
            response_source="paywall_daily_limit_chat",
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", paywall_payload["response"], subject_id=sid)
        _record_paywall_event(source="paywall_daily_limit_chat", plan_type=plan, reason="daily_limit", message=msg)
        return _finalize_chat_payload(paywall_payload)

    if _is_answer_quality_repair_request(msg):
        prev_user_msg = _last_substantive_user_message(recent_chat_history, msg)
        repair_burst = _recent_repair_signal_count(recent_chat_history, msg)
        if prev_user_msg:
            response = (
                _build_concise_plan_after_frustration(prev_user_msg)
                if repair_burst >= 2
                else _build_answer_quality_repair_response(prev_user_msg)
            )
        else:
            response = (
                "Извините, ответ действительно получился нерелевантным. "
                "Опишите жалобу одним предложением, и я дам структурированный медицинский ответ по шагам."
            )
        # При серии негативного фидбэка закрываем узкие followup-потоки, чтобы не зациклиться.
        if repair_burst >= 2:
            save_consultation_state(uid, {"hormone_mood_fatigue": {"active": False}}, subject_id=sid)
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "answer_quality_repair_chat",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": {
                "suggested_questions": _hormone_mood_fatigue_questions(prev_user_msg) if prev_user_msg else [],
                "action_sequence": [],
                "insufficient_data": False,
                **_hormone_mood_fatigue_explainability(stage="repair"),
            },
            "symptom_payload": extract_symptom_payload(prev_user_msg or msg),
            "knowledge_context": resolve_medical_context(prev_user_msg or msg, language="ru"),
            "action_sequence": [],
        })

    if _hormone_mood_fatigue_thread_active(consultation_state) and not _is_hormone_mood_fatigue_request(msg):
        fsm = _fsm_load_or_init(consultation_state, msg)
        fsm = _fsm_update_endocrine_slots(fsm, msg)
        policy = _policy_eval_endocrine(fsm, msg)
        next_slot = _endocrine_select_next_slot(fsm, policy, msg)
        if not next_slot and not policy.get("force_plan"):
            policy = dict(policy)
            policy["force_plan"] = True
        if policy.get("force_plan"):
            response = (
                "Спасибо, это уже полезно для маршрута. Следующий шаг: сдайте первый этап анализов "
                "(ТТГ, св.Т4, ОАК, ферритин, B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца)), после чего я разберу результаты и дам точный план."
                "\n"
                + _hormone_mood_fatigue_upload_tail()
            )
            next_step = len(_hormone_mood_fatigue_questions(msg))
            still_active = False
            fsm["active"] = False
            fsm["expected_slot"] = ""
        else:
            next_q = _endocrine_slot_question(next_slot)
            if next_q:
                response = next_q
                asked_slots = list(fsm.get("asked_slots") or [])
                if next_slot not in asked_slots:
                    asked_slots.append(next_slot)
                fsm["asked_slots"] = asked_slots
                fsm["expected_slot"] = next_slot
                next_step = max(2, int(fsm.get("step_id") or 2) + 1)
                still_active = True
            else:
                cur_step = _hormone_mood_fatigue_step(consultation_state)
                response, next_step = _hormone_mood_fatigue_followup_response(msg, cur_step)
                total_q = len(_hormone_mood_fatigue_questions(msg))
                still_active = bool(total_q and next_step < total_q)
                fsm["expected_slot"] = ""
        fsm["step_id"] = next_step
        save_consultation_state(
            uid,
            {
                "hormone_mood_fatigue": {"active": still_active, "step": next_step},
                "clinical_fsm": fsm,
            },
            subject_id=sid,
        )
        structured = {
            "suggested_questions": _hormone_mood_fatigue_questions(msg),
            "action_sequence": [],
            "insufficient_data": False,
            "library_topic": "hormone_mood_fatigue_template",
            **_hormone_mood_fatigue_explainability(next_slot=next_slot, stage="followup"),
        }
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "hormone_mood_fatigue_template_followup",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_hormone_mood_fatigue_request(msg):
        response = _hormone_mood_fatigue_response(msg)
        seed_fsm = {
            "scenario_id": "hormone_mood_fatigue",
            "active": True,
            "step_id": 2,
            "domain_lock": "endocrine_asthenic",
            "asked_slots": ["duration"],
            "filled_slots": {},
            "forbidden_repeats": ["duration"],
            "expected_slot": "sleep_stress_link",
        }
        structured = {
            "suggested_questions": _hormone_mood_fatigue_questions(msg),
            "action_sequence": [],
            "insufficient_data": False,
            "library_topic": "hormone_mood_fatigue_template",
            **_hormone_mood_fatigue_explainability(next_slot="sleep_stress_link", stage="start"),
        }
        save_consultation_state(
            uid,
            {
                "hormone_mood_fatigue": {"active": True, "step": 2},
                "clinical_fsm": seed_fsm,
            },
            subject_id=sid,
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "hormone_mood_fatigue_template",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    consultation_state_for_priority = get_consultation_state(uid, subject_id=sid) or {}
    has_active_clarify = bool(
        isinstance(consultation_state_for_priority.get("clarify_followup"), dict)
        and consultation_state_for_priority.get("clarify_followup", {}).get("active")
    )
    priority_intent = _classify_priority_intent(msg)
    if has_active_clarify and priority_intent in {"small_talk", "presence", "reset", "new_complaint"}:
        priority_intent = ""
    if priority_intent:
        if priority_intent == "new_complaint":
            _clear_clarify_followup_state(uid, sid)
            save_consultation_state(
                uid,
                {
                    "dialogue_route": {"pending_mode": "", "pending_message": ""},
                    "dialog_companion": {"active": False},
                },
                subject_id=sid,
            )
            dc_active = False
        else:
            _clear_clarify_followup_state(uid, sid)
            response_map = {
                "small_talk": _small_talk_response(msg),
                "presence": _presence_check_response(),
                "hear_me": _audio_clarity_response(),
                "reset": _dialog_reset_response(),
                "stop": _conversation_stop_response(msg),
            }
            response = response_map.get(priority_intent, "")
            if response:
                if priority_intent == "stop":
                    save_consultation_state(uid, {"dialogue_route": {"pending_mode": "", "pending_message": ""}}, subject_id=sid)
                append_chat_message(uid, "user", msg, subject_id=sid)
                append_chat_message(uid, "assistant", response, subject_id=sid)
                if priority_intent == "small_talk":
                    _record_voice_quality_event(source="small_talk_chat_turn", complaint=msg, severity="info")
                return _finalize_chat_payload({
                    "user_id": uid,
                    "response": response,
                    "response_simple": response,
                    "conclusion": priority_intent == "stop",
                    "report_id": None,
                    "report": None,
                    "suggest_pdf": False,
                    "severity": None,
                    "red_flags_present": False,
                    "red_flag_matches": [],
                    "llm_used": False,
                    "response_source": (
                        "small_talk" if priority_intent == "small_talk"
                        else "presence_check" if priority_intent == "presence"
                        else "audio_clarity_request" if priority_intent == "hear_me"
                        else "dialog_reset_request" if priority_intent == "reset"
                        else "conversation_stop_request"
                    ),
                    "medical_core_bypassed": True,
                    "model_used": None,
                    "worker_used": False,
                    "request_id": None,
                    "orchestrator_state": None,
                    "consultation_case": None,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
                    "symptom_payload": None,
                    "knowledge_context": None,
                    "action_sequence": [],
                })

    if pending_route_mode == "awaiting_choice":
        route_choice = _parse_route_choice(msg)
        if route_choice == "unknown":
            response = _clarify_route_question()
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", response, subject_id=sid)
            return _finalize_chat_payload({
                "user_id": uid,
                "response": response,
                "response_simple": response,
                "conclusion": False,
                "report_id": None,
                "report": None,
                "suggest_pdf": False,
                "severity": None,
                "red_flags_present": False,
                "red_flag_matches": [],
                "llm_used": False,
                "response_source": "route_clarification_repeat",
                "medical_core_bypassed": True,
                "model_used": None,
                "worker_used": False,
                "request_id": None,
                "orchestrator_state": None,
                "consultation_case": None,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "structured": None,
                "symptom_payload": None,
                "knowledge_context": None,
                "action_sequence": [],
            })
        save_consultation_state(uid, {"dialogue_route": {"pending_mode": "", "pending_message": ""}}, subject_id=sid)
        if route_choice == "talk":
            tone_hint = _resolve_non_medical_tone(msg)
            tone = tone_hint or _load_non_medical_tone(uid)
            if tone_hint:
                _save_non_medical_tone(uid, tone_hint)
            source_message = pending_route_message or msg
            save_consultation_state(uid, {"dialog_companion": {"active": True}}, subject_id=sid)
            dc_active = True
            cr_talk = await run_dialog_companion_turn(source_message, recent_chat_history)
            llm_talk = str(cr_talk.get("response") or "").strip()
            if llm_talk and not cr_talk.get("error"):
                response = llm_talk
                rsp_src_talk = "dialog_companion_llm_route_talk"
                pt_talk = int(cr_talk.get("prompt_tokens") or 0)
                ct_talk = int(cr_talk.get("completion_tokens") or 0)
                tt_talk = int(cr_talk.get("total_tokens") or 0)
                cost_talk = float(cr_talk.get("estimated_cost_usd") or 0.0)
                llm_used_talk = bool(cr_talk.get("llm_used"))
                model_talk = cr_talk.get("model_used")
            else:
                response = _non_medical_chat_response(source_message, tone=tone)
                rsp_src_talk = "non_medical_chat_bypass_clarified"
                pt_talk = ct_talk = tt_talk = 0
                cost_talk = 0.0
                llm_used_talk = False
                model_talk = None
            response = _augment_non_medical_with_web_search(source_message, response)
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", response, subject_id=sid)
            return _finalize_chat_payload({
                "user_id": uid,
                "response": response,
                "response_simple": response,
                "conclusion": False,
                "report_id": None,
                "report": None,
                "suggest_pdf": False,
                "severity": None,
                "red_flags_present": False,
                "red_flag_matches": [],
                "llm_used": llm_used_talk,
                "response_source": rsp_src_talk,
                "medical_core_bypassed": True,
                "model_used": model_talk,
                "worker_used": False,
                "request_id": None,
                "orchestrator_state": None,
                "consultation_case": None,
                "prompt_tokens": pt_talk,
                "completion_tokens": ct_talk,
                "total_tokens": tt_talk,
                "estimated_cost_usd": cost_talk,
                "structured": None,
                "symptom_payload": None,
                "knowledge_context": None,
                "action_sequence": [],
            })
        # Если пользователь прислал уже явный медицинский контекст, обрабатываем его текущий текст,
        # а не старый "двусмысленный" pending message.
        if pending_route_message and route_choice == "health" and not _is_clearly_medical_request(msg):
            msg = pending_route_message

    clarify_reply = _try_clarify_followup_reply(uid=uid, sid=sid, msg=msg, channel="chat")
    if clarify_reply is not None:
        response = str(clarify_reply.get("response") or "").strip()
        structured = clarify_reply.get("structured") if isinstance(clarify_reply.get("structured"), dict) else {}
        rs = str(clarify_reply.get("response_source") or "complaint_clarify_step_chat")
        has_red_flags = bool(clarify_reply.get("has_red_flags"))
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="complaint_clarify_chat_turn", complaint=msg, severity="info")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": has_red_flags,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": rs,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
            "knowledge_enrichment": _run_knowledge_enrichment_followup_api(
                uid=uid,
                sid=sid,
                topic=str(clarify_reply.get("knowledge_topic") or msg),
                red_flags_present=has_red_flags,
                llm_used=False,
                response_source=rs,
            ),
        })

    if dc_active and _should_force_exit_companion(msg):
        save_consultation_state(uid, {"dialog_companion": {"active": False}}, subject_id=sid)
        dc_active = False

    if _is_non_medical_turn(msg, recent_chat_history, dc_active):
        # Safety-guard: если пользователь явно возвращает медконтекст, не даём шаблон «поболтаем».
        lower_msg = str(msg or "").lower()
        if _contains_medical_markers(msg) or "вернуться к вопросам здоровья" in lower_msg:
            save_consultation_state(uid, {"dialog_companion": {"active": False}}, subject_id=sid)
            dc_active = False
        else:
            _clear_clarify_followup_state(uid, sid)
            tone_hint = _resolve_non_medical_tone(msg)
            tone = tone_hint or _load_non_medical_tone(uid)
            if tone_hint:
                _save_non_medical_tone(uid, tone_hint)
            companion_out = await run_dialog_companion_turn(msg, recent_chat_history)
            llm_body = str(companion_out.get("response") or "").strip()
            if llm_body and companion_out.get("error") is None:
                response = llm_body
                rsp_src_nm = "dialog_companion_llm"
                pt_nm = int(companion_out.get("prompt_tokens") or 0)
                ct_nm = int(companion_out.get("completion_tokens") or 0)
                tt_nm = int(companion_out.get("total_tokens") or 0)
                cost_nm = float(companion_out.get("estimated_cost_usd") or 0.0)
                llm_nm = bool(companion_out.get("llm_used"))
                model_nm = companion_out.get("model_used")
            else:
                response = _non_medical_chat_response(msg, tone=tone)
                rsp_src_nm = "non_medical_chat_bypass"
                pt_nm = ct_nm = tt_nm = 0
                cost_nm = 0.0
                llm_nm = False
                model_nm = None
            response = _augment_non_medical_with_web_search(msg, response)
            save_consultation_state(uid, {"dialog_companion": {"active": True}}, subject_id=sid)
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", response, subject_id=sid)
            _record_voice_quality_event(source="non_medical_chat_turn", complaint=msg, severity="info")
            return _finalize_chat_payload({
                "user_id": uid,
                "response": response,
                "response_simple": response,
                "conclusion": False,
                "report_id": None,
                "report": None,
                "suggest_pdf": False,
                "severity": None,
                "red_flags_present": False,
                "red_flag_matches": [],
                "llm_used": llm_nm,
                "response_source": rsp_src_nm,
                "medical_core_bypassed": True,
                "model_used": model_nm,
                "worker_used": False,
                "request_id": None,
                "orchestrator_state": None,
                "consultation_case": None,
                "prompt_tokens": pt_nm,
                "completion_tokens": ct_nm,
                "total_tokens": tt_nm,
                "estimated_cost_usd": cost_nm,
                "structured": None,
                "symptom_payload": None,
                "knowledge_context": None,
                "action_sequence": [],
            })

    deep_level = str(limits.get("deep_coaching") or "none")
    if _is_deep_coaching_request(msg, recent_chat_history) and deep_level == "none":
        gate_payload = _build_deep_coaching_gate_payload(
            uid=uid,
            plan_type=plan,
            response_source="paywall_deep_coaching_chat",
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", gate_payload["response"], subject_id=sid)
        _record_paywall_event(source="paywall_deep_coaching_chat", plan_type=plan, reason="deep_coaching_locked", message=msg)
        return _finalize_chat_payload(gate_payload)

    if _is_ambiguous_route_request(msg) and not dc_active:
        response = _clarify_route_question()
        save_consultation_state(
            uid,
            {"dialogue_route": {"pending_mode": "awaiting_choice", "pending_message": msg}},
            subject_id=sid,
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": None,
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "route_clarification_prompt",
            "medical_core_bypassed": True,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": None,
            "symptom_payload": None,
            "knowledge_context": None,
            "action_sequence": [],
        })

    if _is_acute_injury_bleeding_request(msg):
        response = _acute_injury_bleeding_response(msg)
        structured = _acute_injury_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="acute_injury_chat_turn", complaint=msg, severity="warn")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "acute_injury_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_food_symptom_super_request(msg):
        super_payload = _food_symptom_super_response(msg)
        response = str(super_payload.get("response") or "")
        structured = dict(super_payload.get("structured") or {})
        red_matches = list(super_payload.get("red_flag_matches") or [])
        urgent = bool(super_payload.get("red_flags_present"))
        source = str(super_payload.get("response_source") or "food_symptom_super_guard")
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="food_symptom_super_chat_turn", complaint=msg, severity="warn" if urgent else "info")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": source,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_upper_abdominal_request(msg):
        response, red_matches, urgent = _upper_abdominal_response(msg)
        structured = _upper_abdominal_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="upper_abdominal_chat_turn", complaint=msg, severity="warn" if urgent else "info")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": "upper_abdominal_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_postmeal_systemic_request(msg):
        response, red_matches, urgent = _postmeal_systemic_response(msg)
        structured = _postmeal_systemic_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="postmeal_systemic_chat_turn", complaint=msg, severity="warn" if urgent else "info")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": "postmeal_systemic_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_postmeal_bloating_request(msg):
        response, red_matches, urgent = _postmeal_bloating_response(msg)
        structured = _postmeal_bloating_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="postmeal_bloating_chat_turn", complaint=msg, severity="warn" if urgent else "info")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": "postmeal_bloating_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_food_overload_reaction_request(msg):
        response = _food_overload_reaction_response(msg)
        structured = _food_overload_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="food_overload_chat_turn", complaint=msg, severity="info")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "food_overload_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_anorectal_bleeding_request(msg):
        response = _anorectal_bleeding_response()
        structured = _anorectal_bleeding_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="anorectal_bleeding_chat_turn", complaint=msg, severity="warn")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "anorectal_bleeding_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_headache_autonomic_request(msg):
        response = _headache_autonomic_response()
        structured = _headache_autonomic_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="headache_autonomic_chat_turn", complaint=msg, severity="warn")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "headache_autonomic_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_nosebleed_request(msg):
        response = _nosebleed_response()
        structured = _nosebleed_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="nosebleed_chat_turn", complaint=msg, severity="warn")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "nosebleed_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_amenorrhea_galactorrhea_concern(msg):
        response = _amenorrhea_galactorrhea_response()
        structured = _amenorrhea_galactorrhea_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="amenorrhea_galactorrhea_chat_turn", complaint=msg, severity="warn")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "amenorrhea_galactorrhea_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    if _is_prolonged_appetite_loss_concern(msg):
        response = _prolonged_appetite_loss_response()
        structured = _prolonged_appetite_loss_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="prolonged_appetite_loss_chat_turn", complaint=msg, severity="warn")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "prolonged_appetite_loss_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        })

    msg_cq = _strip_dialog_question_prefix(msg)
    phrase_preset = match_user_phrase_preset(msg_cq)
    lookup_query = str(phrase_preset.get("canonical_query") or "").strip() if phrase_preset else msg_cq
    lookup_query = _strip_dialog_question_prefix(lookup_query)
    ab_style = str(phrase_preset.get("ab_style") or "A").strip().upper() if phrase_preset else "A"
    recent_chat_history = get_chat_history(uid, subject_id=sid)
    fatigue_probe = _user_text_blob_for_constitutional_probe(msg, recent_chat_history)
    consultation_state_for_anchor = get_consultation_state(uid, subject_id=sid) or {}
    complaint_hits = _search_complaint_candidates(lookup_query, top_k=10)
    if not complaint_hits and lookup_query != msg_cq:
        complaint_hits = _search_complaint_candidates(msg_cq, top_k=10)
    rank_query = lookup_query if phrase_preset and lookup_query else msg_cq
    common_item = _select_best_complaint_hit(rank_query, complaint_hits, chat_history=recent_chat_history)
    if common_item and _complaint_library_hit_mismatch_constitutional_fatigue(fatigue_probe, common_item):
        common_item = None
    if common_item and _complaint_library_hit_mismatch_pleuritic_chest_dyspnea(fatigue_probe, common_item):
        common_item = None
    if common_item and _complaint_library_hit_mismatch_weight_loss_plateau(fatigue_probe, common_item):
        common_item = None
    common_item = _maybe_restore_heavy_menses_complaint_item(
        msg_cq,
        chat_history=recent_chat_history,
        selected=common_item,
        consultation_state=consultation_state_for_anchor,
    )
    if common_item:
        _persist_complaint_library_anchor(uid, sid, common_item)
        use_clarify = _should_use_clarify_first_mode(msg, common_item)
        if use_clarify:
            q_queue = _get_clarify_followup_question_queue(common_item, msg, chat_history=recent_chat_history)
            save_consultation_state(
                uid,
                {
                    "clarify_followup": {
                        "active": True,
                        "ab_style": ab_style,
                        "item": common_item,
                        "questions": q_queue,
                        "awaiting_question_index": 0,
                        "original_message": msg,
                        "answers": [],
                    }
                },
                subject_id=sid,
            )
        else:
            _clear_clarify_followup_state(uid, sid)
        response = _build_complaint_reference_response(
            common_item,
            msg,
            style_hint=ab_style,
            chat_history=recent_chat_history,
        )
        structured = _common_complaint_structured(common_item, user_message=msg, chat_history=recent_chat_history)
        structured["ab_style"] = ab_style
        if use_clarify:
            structured["clarify_followup"] = {"phase": "question", "step": 1, "total": len(q_queue)}
        has_red_flags = bool(common_item.get("red_flags") or common_item.get("red_flags_specific"))
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="common_complaint_chat_turn", complaint=msg, severity="info")
        return _finalize_chat_payload({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": has_red_flags,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "complaint_reference_library_ab_" + ab_style,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
            "knowledge_enrichment": _run_knowledge_enrichment_followup_api(
                uid=uid,
                sid=sid,
                topic=msg,
                red_flags_present=has_red_flags,
                llm_used=False,
                response_source="complaint_reference_library_ab_" + ab_style,
            ),
        })

    intent = detect_intent(msg)
    distribution = {}
    if intent == "symptom" and msg:
        add_symptom_entry(uid, msg, source="chat", subject_id=sid)
        distribution["add_to_symptoms"] = msg[:200]

    chat_history = get_chat_history(uid, subject_id=sid)
    last_assistant_before = _get_last_assistant_message(chat_history)
    if _is_repeat_request(msg):
        last_assistant = _get_last_assistant_message(chat_history)
        if last_assistant:
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", last_assistant, subject_id=sid)
            return _finalize_chat_payload({
                "user_id": uid,
                "response": last_assistant,
                "response_simple": last_assistant[:_RESPONSE_SIMPLE_MAX_CHARS] if len(last_assistant) > _RESPONSE_SIMPLE_MAX_CHARS else None,
                "intent": intent,
                "distribution": distribution,
                "conclusion": False,
                "report_id": None,
                "report": None,
                "suggest_pdf": False,
                "severity": None,
                "red_flags_present": False,
                "red_flag_matches": [],
                "structured": None,
                "llm_used": False,
                "response_source": "repeat",
                "model_used": None,
                "worker_used": False,
                "request_id": None,
                "orchestrator_state": None,
                "consultation_case": None,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
            })

    if _is_red_flags_faq_request(msg):
        faq_response = get_red_flags_faq_response()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", faq_response, subject_id=sid)
        return _finalize_chat_payload({
            "user_id": uid,
            "response": faq_response,
            "response_simple": faq_response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(faq_response) > _RESPONSE_SIMPLE_MAX_CHARS else None,
            "intent": intent,
            "distribution": distribution,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": None,
            "red_flags_present": False,
            "red_flag_matches": [],
            "structured": None,
            "llm_used": False,
            "response_source": "red_flags_faq",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "response_chars": 0,
            "prompt_chars": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
        })

    append_chat_message(uid, "user", msg, subject_id=sid)
    profile = get_profile(uid)
    documents = get_documents(uid, subject_id=sid)
    symptom_entries = get_symptom_entries(uid, subject_id=sid)
    chat_history = get_chat_history(uid, subject_id=sid)
    last_assistant_before = _get_last_assistant_message(chat_history)
    settings = get_settings(uid)
    app_mode = (settings.get("mode") or "BASIC").strip() or None
    vitals = get_vitals(uid)

    document_context = get_last_consultation_report_context(uid, subject_id=sid)
    result = await run_consultation_turn(
        user_id=uid,
        user_message=msg,
        profile=profile,
        documents_count=len(documents),
        symptom_entries=symptom_entries,
        chat_history=chat_history,
        app_mode=app_mode,
        vitals=vitals,
        document_context=document_context or None,
        subject_id=sid,
        consultation_mode_hint=str(payload.lookup_mode or "").strip() or None,
    )

    append_chat_message(uid, "assistant", result["response"], subject_id=sid)
    try:
        record_runtime_event(
            source=str(result.get("response_source") or ""),
            llm_used=bool(result.get("llm_used")),
            model_used=result.get("model_used"),
            protocol_source=str((result.get("orchestrator_state") or {}).get("protocol_source") or ""),
            complaint=str((result.get("orchestrator_state") or {}).get("complaint") or ""),
            cluster=str((result.get("orchestrator_state") or {}).get("market_signal_cluster") or ""),
            severity=str(result.get("severity") or ""),
            prompt_chars=int(result.get("prompt_chars") or 0),
            response_chars=int(result.get("response_chars") or 0),
            prompt_tokens=int(result.get("prompt_tokens") or 0),
            completion_tokens=int(result.get("completion_tokens") or 0),
            total_tokens=int(result.get("total_tokens") or 0),
            estimated_cost_usd=float(result.get("estimated_cost_usd") or 0.0),
        )
    except Exception:
        pass
    try:
        record_turn_for_autolearn(msg, result.get("response") or "")
    except Exception:
        pass
    save_voice_concierge_turn_to_labs(uid, msg, result.get("response") or "", subject_id=sid)
    if result.get("conclusion") and result.get("response"):
        try:
            capture_learning_candidate(
                user_id=uid,
                question=msg,
                response=result.get("response") or "",
                structured=result.get("structured"),
                orchestrator_state=result.get("orchestrator_state"),
                report=result.get("report"),
                response_source=str(result.get("response_source") or ""),
                llm_used=bool(result.get("llm_used")),
            )
        except Exception:
            pass
    if result.get("conclusion") and result.get("response"):
        add_notification(
            uid,
            "Новая рекомендация по консультации",
            (result.get("response") or "")[:500],
            unread=True,
        )

    # Microbiome Engine v1 + v1.1: microbiome_report и оси (microbiome_axes_v11), обогащение ответа
    structured_out = result.get("structured")
    response_final = result["response"]
    if isinstance(structured_out, dict):
        try:
            # При выраженной астении/апатии без запроса про микробиом — не смешиваем тяжёлый модуль с первым контактом.
            if not _constitutional_fatigue_thread_active(msg or "", chat_history):
                profile_for_me = get_profile(uid) if uid else {}
                if not isinstance(profile_for_me, dict):
                    profile_for_me = {}
                user_age = profile_for_me.get("age")
                if user_age is not None and not isinstance(user_age, int):
                    try:
                        user_age = int(user_age)
                    except (TypeError, ValueError):
                        user_age = None
                low_activity = profile_for_me.get("low_activity") if isinstance(profile_for_me.get("low_activity"), bool) else None
                microbiome_result = run_microbiome_engine(
                    symptoms_text=msg or "",
                    age=user_age,
                    low_activity=low_activity,
                    poor_diet=None,
                )
                if microbiome_result.get("active"):
                    structured_out = {**structured_out, "microbiome_report": microbiome_result}
                gut_muscle = evaluate_gut_muscle_axis(msg, age=user_age, low_activity=low_activity, protein_deficit_hint=False)
                if gut_muscle.get("active"):
                    structured_out.setdefault("insights", [])
                    if gut_muscle.get("insight_block") and gut_muscle["insight_block"] not in structured_out["insights"]:
                        structured_out["insights"].append(gut_muscle["insight_block"])
                    structured_out["strength_metabolism_block"] = gut_muscle.get("strength_metabolism_block")
                    structured_out["axis"] = "gut_muscle"
                    structured_out["gut_muscle_risk_score"] = gut_muscle.get("risk_score", 0)
                    structured_out["gut_muscle_risk_level"] = gut_muscle.get("risk_level", "low")
                # v1.1: оси и обогащение текста ответа блоком «Микробиомный модуль»
                payload = build_microbiome_payload_from_message(msg or "", profile_for_me)
                axes = calc_microbiome_axes(payload)
                if axes:
                    structured_out["microbiome_axes_v11"] = [
                        {
                            "axis": a.axis,
                            "score": a.score,
                            "level": a.level,
                            "triggered_by": getattr(a, "triggered_by", []),
                            "insights": getattr(a, "insights", []),
                            "recommendations": getattr(a, "recommendations", []),
                            "cta": getattr(a, "cta", None),
                        }
                        for a in axes
                    ]
                    enriched = enrich_with_microbiome(payload, [result["response"]])
                    if enriched:
                        response_final = enriched[0]
        except Exception:
            pass

    try:
        from app.services.upsell_engine import build_response, user_data_from_result
        user_data = user_data_from_result(result)
        response_final = build_response(response_final, user_data)
    except Exception:
        pass

    orch_for_topic = result.get("orchestrator_state") or {}
    topic_for_enrich = str(orch_for_topic.get("complaint") or msg or "").strip()
    knowledge_enrichment_meta = _run_knowledge_enrichment_followup_api(
        uid=uid,
        sid=sid,
        topic=topic_for_enrich,
        red_flags_present=bool(result.get("red_flags_present")),
        llm_used=bool(result.get("llm_used")),
        response_source=str(result.get("response_source") or ""),
    )

    out = {
        "user_id": uid,
        "ok": result.get("ok", True),
        "response": response_final,
        "response_simple": result.get("response_simple") or (response_final[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response_final or "") > _RESPONSE_SIMPLE_MAX_CHARS else None),
        "intent": intent,
        "distribution": distribution,
        "conclusion": result.get("conclusion", False),
        "report_id": result.get("report_id"),
        "report": result.get("report"),
        "suggest_pdf": result.get("suggest_pdf", False),
        "severity": result.get("severity"),
        "red_flags_present": result.get("red_flags_present", False),
        "red_flag_matches": result.get("red_flag_matches") or [],
        "structured": structured_out,
        "unified_engine_snapshot": (
            structured_out.get("unified_engine_snapshot")
            if isinstance(structured_out, dict)
            else None
        ),
        "llm_used": result.get("llm_used", False),
        "response_source": result.get("response_source"),
        "model_used": result.get("model_used"),
        "worker_used": result.get("worker_used", False),
        "request_id": result.get("request_id"),
        "orchestrator_state": result.get("orchestrator_state"),
        "consultation_case": result.get("consultation_case"),
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "total_tokens": result.get("total_tokens", 0),
        "estimated_cost_usd": result.get("estimated_cost_usd", 0.0),
        "knowledge_enrichment": knowledge_enrichment_meta,
    }
    if result.get("state") is not None:
        out["state"] = result["state"]
    if result.get("urgency") is not None:
        out["urgency"] = result["urgency"]
    if result.get("questions") is not None:
        out["questions"] = result["questions"]
    if result.get("user_report_structured") is not None:
        out["user_report_structured"] = result["user_report_structured"]
    if result.get("final_user_message") is not None:
        out["final_user_message"] = result["final_user_message"]
    if result.get("user_hypotheses") is not None:
        out["user_hypotheses"] = result["user_hypotheses"]
    if result.get("recommended_labs") is not None:
        out["recommended_labs"] = result["recommended_labs"]
    if result.get("continuity_summary") is not None:
        out["continuity_summary"] = result["continuity_summary"]
    if result.get("care_plan") is not None:
        out["care_plan"] = result["care_plan"]
    if result.get("care_plan_message") is not None:
        out["care_plan_message"] = result["care_plan_message"]
    if result.get("physician_report") is not None:
        out["physician_report"] = result["physician_report"]
    if result.get("physician_report_text") is not None:
        out["physician_report_text"] = result["physician_report_text"]
    if result.get("product") is not None:
        out["product"] = result["product"]
    if result.get("onboarding") is not None:
        out["onboarding"] = result["onboarding"]
    if result.get("conversion") is not None:
        out["conversion"] = result["conversion"]
    if result.get("debug") is not None:
        out["debug"] = result["debug"]
    return _finalize_chat_payload(out)


@router.post("/user/mikhail-consultation")
def user_mikhail_consultation(
    payload: MikhailConsultationPayload = Body(default=MikhailConsultationPayload()),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    db: Session = Depends(get_db),
):
    """
    Живой диалог с консьержем Михаилом после загрузки анализа.
    С памятью (при авторизованном пользователе): сравнивает с предыдущими анализами, динамика.
    Этапы: старт → контекст → анализ → продажа (Включить наблюдение).
    Передайте analysis_result (результат multi-lab), при следующих вызовах — message и state.
    """
    uid = _user_id(x_user_id)
    result = payload.analysis_result or {}
    user_input = (payload.message or "").strip()
    state = dict(payload.state or {})
    user = _get_db_user_optional(db, uid)
    if user:
        out = run_mikhail_with_memory(db, user.id, result, user_input, state)
    else:
        out = run_mikhail_consultation(result, user_input, state)
    return {
        "user_id": uid,
        "text": out.get("text", ""),
        "state": out.get("state", state),
    }


@router.post("/user/chat/reset")
def user_chat_reset(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    clear_chat_history(uid, subject_id=sid)
    clear_consultation_state(uid, subject_id=sid)
    _save_default_voice_state(uid, subject_id=sid)
    return {"user_id": uid, "ok": True}


class ChatRestorePayload(BaseModel):
    messages: List[dict]  # [{"role": "user"|"assistant", "content": "..."}]


@router.post("/user/chat/restore")
def user_chat_restore(
    payload: ChatRestorePayload = Body(...),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Восстановить чат из архива (например после «Новый чат»)."""
    uid = _user_id(x_user_id)
    messages = list(payload.messages or [])
    if not messages:
        raise HTTPException(status_code=400, detail="messages is required and must not be empty")
    sid = _subject_id(x_subject_id)
    set_chat_history(uid, messages, subject_id=sid)
    return {"user_id": uid, "ok": True, "messages_count": len(messages)}


@router.post("/user/voice/archive")
def user_voice_archive(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Перенести текущий диалог в историю (симптомы). После 5 мин неактивности голоса."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    entry = archive_voice_dialog(uid, subject_id=sid)
    if not entry:
        return {"user_id": uid, "archived": False, "reason": "empty"}
    _save_default_voice_state(uid, subject_id=sid)
    return {"user_id": uid, "archived": True, "dialog_id": entry.get("id"), "created_at": entry.get("created_at")}


@router.get("/user/voice/archived-dialogs")
def user_voice_archived_dialogs(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Список архивных диалогов для истории симптомов."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    dialogs = get_archived_voice_dialogs(uid, subject_id=sid)
    items = [{"id": d.get("id"), "created_at": d.get("created_at"), "preview": d.get("preview") or "Диалог"} for d in dialogs]
    return {"user_id": uid, "items": items}


@router.delete("/user/voice/archived-dialog/{dialog_id}")
def user_voice_delete_archived_dialog(
    dialog_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Удалить один архивный диалог консьержа из истории симптомов."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    ok = delete_archived_voice_dialog(uid, dialog_id, subject_id=sid)
    if not ok:
        raise HTTPException(status_code=404, detail="Диалог не найден.")
    return {"user_id": uid, "deleted_id": dialog_id}


@router.post("/user/voice/archived-dialogs/clear-all")
def user_voice_clear_archived_dialogs(
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Очистить весь архив диалогов консьержа."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    count = clear_archived_voice_dialogs(uid, subject_id=sid)
    return {"user_id": uid, "cleared_count": count}


@router.post("/user/voice/restore-dialog/{dialog_id}")
def user_voice_restore_dialog(
    dialog_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """Восстановить чат из архивного диалога (для продолжения в окне консьержа)."""
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    result = restore_voice_dialog(uid, dialog_id, subject_id=sid)
    if not result:
        raise HTTPException(status_code=404, detail="Диалог не найден.")
    _save_default_voice_state(uid, subject_id=sid)
    return {"user_id": uid, "ok": True, "messages": result.get("messages") or []}


@router.post("/user/voice-structured")
async def user_voice_structured_post(
    payload: ChatMessage,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    x_subject_id: Optional[str] = Header(None, alias="X-Subject-Id"),
):
    """
    Голосовой консьерж: тот же поток, что и чат, плюс структурированный отчёт
    (описание, гипотезы, обследования, питание, активность, красные флаги, дисклеймер)
    и при необходимости — уточняющие вопросы. Не меняет логику MVP чата.
    """
    uid = _user_id(x_user_id)
    sid = _subject_id(x_subject_id)
    msg = _strip_dialog_question_prefix((payload.message or "").strip())
    if not msg:
        raise HTTPException(status_code=400, detail="message is required")
    recent_chat_history = get_chat_history(uid, subject_id=sid)
    consultation_state = get_consultation_state(uid, subject_id=sid) or {}
    dc_active = _dialog_companion_active(consultation_state)
    if dc_active and _should_force_exit_companion(msg):
        save_consultation_state(uid, {"dialog_companion": {"active": False}}, subject_id=sid)
        consultation_state = get_consultation_state(uid, subject_id=sid) or {}
        dc_active = False
    route_state = consultation_state.get("dialogue_route") if isinstance(consultation_state.get("dialogue_route"), dict) else {}
    pending_route_mode = str(route_state.get("pending_mode") or "").strip().lower()
    pending_route_message = str(route_state.get("pending_message") or "").strip()
    previous_voice_state = normalize_voice_state(
        get_consultation_state(uid, subject_id=sid).get("voice_concierge")
    )
    previous_voice_state["last_user_message"] = msg

    def _attach_voice_meta(payload_out: dict, meta_result: dict[str, Any]) -> dict:
        voice_meta = build_voice_meta(meta_result, previous_voice_state)
        payload_with_voice = _inject_unified_engine_snapshot(
            dict(payload_out or {}),
            subject_id=sid,
            documents_count=len(get_documents(uid, subject_id=sid)),
            symptom_entries_count=len(get_symptom_entries(uid, subject_id=sid)),
        )
        payload_with_voice["voice_meta"] = voice_meta

        orchestrator_state = payload_with_voice.get("orchestrator_state") or {}
        structured = payload_with_voice.get("structured") or {}
        followup_state = (orchestrator_state or {}).get("medical_core_followup") if isinstance(orchestrator_state, dict) else {}
        followup_struct = (structured or {}).get("medical_core_followup") if isinstance(structured, dict) else {}
        followup_action = str((followup_struct or {}).get("action") or "").strip().lower() if isinstance(followup_struct, dict) else ""
        followup_finished = bool(
            (isinstance(followup_state, dict) and followup_state.get("final_ready"))
            or followup_action in {"finalize", "urgent"}
        )
        urgent = bool(payload_with_voice.get("red_flags_present")) or str(payload_with_voice.get("severity") or "").upper() == "RED" or followup_action == "urgent"

        user_answer_matches_pending = None
        if isinstance(followup_struct, dict):
            ans = followup_struct.get("answer_assessment") or {}
            if isinstance(ans, dict) and "answered" in ans:
                user_answer_matches_pending = bool(ans.get("answered"))

        payload_with_voice = merge_voice_turn_into_payload(
            payload_with_voice,
            orchestrator_state=orchestrator_state if isinstance(orchestrator_state, dict) else {},
            urgent=urgent,
            followup_finished=followup_finished,
            user_answer_matches_pending=user_answer_matches_pending,
        )
        try:
            payload_with_voice = apply_final_relevance_gate(msg, payload_with_voice, channel="voice")
        except Exception:
            pass

        save_consultation_state(
            uid,
            {"voice_concierge": payload_with_voice.get("voice_meta") or voice_meta},
            subject_id=sid,
        )
        return payload_with_voice

    user_settings = get_settings(uid)
    plan = _normalize_subscription_plan(str(user_settings.get("subscription") or "free"))
    limits = _plan_limits(plan)
    is_active = _is_subscription_active(user_settings)
    daily_limit = limits.get("messages_per_day")
    used_today = _count_user_messages_today(recent_chat_history)

    if not is_active:
        paywall_payload = _build_paywall_payload(
            uid=uid,
            plan_type=plan,
            limit=daily_limit,
            used=used_today,
            response_source="paywall_subscription_expired",
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", paywall_payload["response"], subject_id=sid)
        _record_paywall_event(source="paywall_subscription_expired_voice", plan_type=plan, reason="expired", message=msg)
        return _attach_voice_meta(paywall_payload, {
            "response": paywall_payload["response"],
            "conclusion": False,
            "structured": {"suggested_questions": []},
            "response_source": "paywall_subscription_expired",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    if isinstance(daily_limit, int) and daily_limit > 0 and used_today >= daily_limit:
        paywall_payload = _build_paywall_payload(
            uid=uid,
            plan_type=plan,
            limit=daily_limit,
            used=used_today,
            response_source="paywall_daily_limit_voice",
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", paywall_payload["response"], subject_id=sid)
        _record_paywall_event(source="paywall_daily_limit_voice", plan_type=plan, reason="daily_limit", message=msg)
        return _attach_voice_meta(paywall_payload, {
            "response": paywall_payload["response"],
            "conclusion": False,
            "structured": {"suggested_questions": []},
            "response_source": "paywall_daily_limit_voice",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    if _is_answer_quality_repair_request(msg):
        prev_user_msg = _last_substantive_user_message(recent_chat_history, msg)
        repair_burst = _recent_repair_signal_count(recent_chat_history, msg)
        if prev_user_msg:
            response = (
                _build_concise_plan_after_frustration(prev_user_msg)
                if repair_burst >= 2
                else _build_answer_quality_repair_response(prev_user_msg)
            )
        else:
            response = (
                "Извините, ответ действительно получился нерелевантным. "
                "Опишите жалобу одним предложением, и я дам структурированный медицинский ответ по шагам."
            )
        if repair_burst >= 2:
            save_consultation_state(uid, {"hormone_mood_fatigue": {"active": False}}, subject_id=sid)
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "answer_quality_repair_voice",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": {
                "suggested_questions": _hormone_mood_fatigue_questions(prev_user_msg) if prev_user_msg else [],
                "action_sequence": [],
                "insufficient_data": False,
                **_hormone_mood_fatigue_explainability(stage="repair"),
            },
            "symptom_payload": extract_symptom_payload(prev_user_msg or msg),
            "knowledge_context": resolve_medical_context(prev_user_msg or msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": {
                "suggested_questions": _hormone_mood_fatigue_questions(prev_user_msg) if prev_user_msg else [],
                **_hormone_mood_fatigue_explainability(stage="repair"),
            },
            "response_source": "answer_quality_repair_voice",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    if _hormone_mood_fatigue_thread_active(consultation_state) and not _is_hormone_mood_fatigue_request(msg):
        fsm = _fsm_load_or_init(consultation_state, msg)
        fsm = _fsm_update_endocrine_slots(fsm, msg)
        policy = _policy_eval_endocrine(fsm, msg)
        next_slot = _endocrine_select_next_slot(fsm, policy, msg)
        if not next_slot and not policy.get("force_plan"):
            policy = dict(policy)
            policy["force_plan"] = True
        if policy.get("force_plan"):
            response = (
                "Спасибо, это уже полезно для маршрута. Следующий шаг: сдайте первый этап анализов "
                "(ТТГ, св.Т4, ОАК, ферритин, B12, витамин D, глюкоза и HbA1c (гликированный гемоглобин, средний сахар за 3 месяца)), после чего я разберу результаты и дам точный план."
                "\n"
                + _hormone_mood_fatigue_upload_tail()
            )
            next_step = len(_hormone_mood_fatigue_questions(msg))
            still_active = False
            fsm["active"] = False
            fsm["expected_slot"] = ""
        else:
            next_q = _endocrine_slot_question(next_slot)
            if next_q:
                response = next_q
                asked_slots = list(fsm.get("asked_slots") or [])
                if next_slot not in asked_slots:
                    asked_slots.append(next_slot)
                fsm["asked_slots"] = asked_slots
                fsm["expected_slot"] = next_slot
                next_step = max(2, int(fsm.get("step_id") or 2) + 1)
                still_active = True
            else:
                cur_step = _hormone_mood_fatigue_step(consultation_state)
                response, next_step = _hormone_mood_fatigue_followup_response(msg, cur_step)
                total_q = len(_hormone_mood_fatigue_questions(msg))
                still_active = bool(total_q and next_step < total_q)
                fsm["expected_slot"] = ""
        fsm["step_id"] = next_step
        save_consultation_state(
            uid,
            {
                "hormone_mood_fatigue": {"active": still_active, "step": next_step},
                "clinical_fsm": fsm,
            },
            subject_id=sid,
        )
        structured = {
            "suggested_questions": _hormone_mood_fatigue_questions(msg),
            "action_sequence": [],
            "insufficient_data": False,
            "library_topic": "hormone_mood_fatigue_template",
            **_hormone_mood_fatigue_explainability(next_slot=next_slot, stage="followup"),
        }
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "hormone_mood_fatigue_template_followup",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": {
                "suggested_questions": structured["suggested_questions"],
                **_hormone_mood_fatigue_explainability(next_slot=next_slot, stage="followup"),
            },
            "response_source": "hormone_mood_fatigue_template_followup",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    if _is_hormone_mood_fatigue_request(msg):
        response = _hormone_mood_fatigue_response(msg)
        seed_fsm = {
            "scenario_id": "hormone_mood_fatigue",
            "active": True,
            "step_id": 2,
            "domain_lock": "endocrine_asthenic",
            "asked_slots": ["duration"],
            "filled_slots": {},
            "forbidden_repeats": ["duration"],
            "expected_slot": "sleep_stress_link",
        }
        structured = {
            "suggested_questions": _hormone_mood_fatigue_questions(msg),
            "action_sequence": [],
            "insufficient_data": False,
            "library_topic": "hormone_mood_fatigue_template",
            **_hormone_mood_fatigue_explainability(next_slot="sleep_stress_link", stage="start"),
        }
        save_consultation_state(
            uid,
            {
                "hormone_mood_fatigue": {"active": True, "step": 2},
                "clinical_fsm": seed_fsm,
            },
            subject_id=sid,
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "hormone_mood_fatigue_template",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": {
                "suggested_questions": structured["suggested_questions"],
                **_hormone_mood_fatigue_explainability(next_slot="sleep_stress_link", stage="start"),
            },
            "response_source": "hormone_mood_fatigue_template",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    consultation_state_for_priority = get_consultation_state(uid, subject_id=sid) or {}
    has_active_clarify = bool(
        isinstance(consultation_state_for_priority.get("clarify_followup"), dict)
        and consultation_state_for_priority.get("clarify_followup", {}).get("active")
    )
    priority_intent = _classify_priority_intent(msg)
    if has_active_clarify and priority_intent in {"small_talk", "presence", "reset", "new_complaint"}:
        priority_intent = ""
    if priority_intent:
        if priority_intent == "new_complaint":
            _clear_clarify_followup_state(uid, sid)
            save_consultation_state(
                uid,
                {
                    "dialogue_route": {"pending_mode": "", "pending_message": ""},
                    "dialog_companion": {"active": False},
                },
                subject_id=sid,
            )
            dc_active = False
        else:
            _clear_clarify_followup_state(uid, sid)
            response_map = {
                "small_talk": _small_talk_response(msg),
                "presence": _presence_check_response(),
                "hear_me": _audio_clarity_response(),
                "reset": _dialog_reset_response(),
                "stop": _conversation_stop_response(msg),
            }
            response = response_map.get(priority_intent, "")
            if response:
                if priority_intent == "stop":
                    save_consultation_state(uid, {"dialogue_route": {"pending_mode": "", "pending_message": ""}}, subject_id=sid)
                append_chat_message(uid, "user", msg, subject_id=sid)
                append_chat_message(uid, "assistant", response, subject_id=sid)
                if priority_intent == "small_talk":
                    _record_voice_quality_event(source="small_talk_voice_turn", complaint=msg, severity="info")
                source_name = (
                    "small_talk" if priority_intent == "small_talk"
                    else "presence_check" if priority_intent == "presence"
                    else "audio_clarity_request" if priority_intent == "hear_me"
                    else "dialog_reset_request" if priority_intent == "reset"
                    else "conversation_stop_request"
                )
                return _attach_voice_meta({
                    "user_id": uid,
                    "response": response,
                    "response_simple": response,
                    "conclusion": priority_intent == "stop",
                    "report_id": None,
                    "report": None,
                    "suggest_pdf": False,
                    "severity": None,
                    "red_flags_present": False,
                    "red_flag_matches": [],
                    "llm_used": False,
                    "response_source": source_name,
                    "medical_core_bypassed": True,
                    "model_used": None,
                    "worker_used": False,
                    "request_id": None,
                    "orchestrator_state": None,
                    "consultation_case": None,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": 0.0,
                    "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
                    "symptom_payload": None,
                    "knowledge_context": None,
                    "action_sequence": [],
                }, {
                    "response": response,
                    "conclusion": priority_intent == "stop",
                    "structured": {"suggested_questions": []},
                    "response_source": source_name,
                    "severity": "GREEN",
                    "red_flags_present": False,
                })

    if pending_route_mode == "awaiting_choice":
        route_choice = _parse_route_choice(msg)
        if route_choice == "unknown":
            response = _clarify_route_question()
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", response, subject_id=sid)
            return _attach_voice_meta({
                "user_id": uid,
                "response": response,
                "response_simple": response,
                "conclusion": False,
                "report_id": None,
                "report": None,
                "suggest_pdf": False,
                "severity": None,
                "red_flags_present": False,
                "red_flag_matches": [],
                "llm_used": False,
                "response_source": "route_clarification_repeat",
                "medical_core_bypassed": True,
                "model_used": None,
                "worker_used": False,
                "request_id": None,
                "orchestrator_state": None,
                "consultation_case": None,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost_usd": 0.0,
                "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
                "symptom_payload": None,
                "knowledge_context": None,
                "action_sequence": [],
            }, {
                "response": response,
                "conclusion": False,
                "structured": {"suggested_questions": []},
                "response_source": "route_clarification_repeat",
                "severity": "GREEN",
                "red_flags_present": False,
            })
        save_consultation_state(uid, {"dialogue_route": {"pending_mode": "", "pending_message": ""}}, subject_id=sid)
        if route_choice == "talk":
            tone_hint = _resolve_non_medical_tone(msg)
            tone = tone_hint or _load_non_medical_tone(uid)
            if tone_hint:
                _save_non_medical_tone(uid, tone_hint)
            source_message = pending_route_message or msg
            save_consultation_state(uid, {"dialog_companion": {"active": True}}, subject_id=sid)
            dc_active = True
            cr_talk_v = await run_dialog_companion_turn(source_message, recent_chat_history)
            llm_talk_v = str(cr_talk_v.get("response") or "").strip()
            if llm_talk_v and not cr_talk_v.get("error"):
                response = llm_talk_v
                rsp_src_talk_v = "dialog_companion_llm_route_talk"
                pt_talk_v = int(cr_talk_v.get("prompt_tokens") or 0)
                ct_talk_v = int(cr_talk_v.get("completion_tokens") or 0)
                tt_talk_v = int(cr_talk_v.get("total_tokens") or 0)
                cost_talk_v = float(cr_talk_v.get("estimated_cost_usd") or 0.0)
                llm_used_talk_v = bool(cr_talk_v.get("llm_used"))
                model_talk_v = cr_talk_v.get("model_used")
            else:
                response = _non_medical_chat_response(source_message, tone=tone)
                rsp_src_talk_v = "non_medical_chat_bypass_clarified"
                pt_talk_v = ct_talk_v = tt_talk_v = 0
                cost_talk_v = 0.0
                llm_used_talk_v = False
                model_talk_v = None
            response = _augment_non_medical_with_web_search(source_message, response)
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", response, subject_id=sid)
            return _attach_voice_meta({
                "user_id": uid,
                "response": response,
                "response_simple": response,
                "conclusion": False,
                "report_id": None,
                "report": None,
                "suggest_pdf": False,
                "severity": None,
                "red_flags_present": False,
                "red_flag_matches": [],
                "llm_used": llm_used_talk_v,
                "response_source": rsp_src_talk_v,
                "medical_core_bypassed": True,
                "model_used": model_talk_v,
                "worker_used": False,
                "request_id": None,
                "orchestrator_state": None,
                "consultation_case": None,
                "prompt_tokens": pt_talk_v,
                "completion_tokens": ct_talk_v,
                "total_tokens": tt_talk_v,
                "estimated_cost_usd": cost_talk_v,
                "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
                "symptom_payload": None,
                "knowledge_context": None,
                "action_sequence": [],
            }, {
                "response": response,
                "conclusion": False,
                "structured": {"suggested_questions": []},
                "response_source": rsp_src_talk_v,
                "severity": "GREEN",
                "red_flags_present": False,
            })
        # Voice-path: та же логика, не перетирать явный мед-запрос старым pending message.
        if pending_route_message and route_choice == "health" and not _is_clearly_medical_request(msg):
            msg = pending_route_message

    clarify_reply_voice = _try_clarify_followup_reply(uid=uid, sid=sid, msg=msg, channel="voice")
    if clarify_reply_voice is not None:
        response = str(clarify_reply_voice.get("response") or "").strip()
        structured_v = clarify_reply_voice.get("structured") if isinstance(clarify_reply_voice.get("structured"), dict) else {}
        if "suggested_questions" not in structured_v:
            structured_v = {
                **structured_v,
                "suggested_questions": [],
                "action_sequence": [],
                "insufficient_data": False,
            }
        rs_v = str(clarify_reply_voice.get("response_source") or "complaint_clarify_step_voice")
        has_red_flags_v = bool(clarify_reply_voice.get("has_red_flags"))
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="complaint_clarify_voice_turn", complaint=msg, severity="info")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": has_red_flags_v,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": rs_v,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured_v,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": {"suggested_questions": structured_v.get("suggested_questions") or []},
            "response_source": rs_v,
            "severity": "GREEN",
            "red_flags_present": has_red_flags_v,
        })

    if dc_active and _should_force_exit_companion(msg):
        save_consultation_state(uid, {"dialog_companion": {"active": False}}, subject_id=sid)
        dc_active = False

    if _is_non_medical_turn(msg, recent_chat_history, dc_active):
        # Safety-guard для voice: «вернуться к вопросам здоровья» и медмаркеры должны ломать non-medical ветку.
        lower_msg = str(msg or "").lower()
        if _contains_medical_markers(msg) or "вернуться к вопросам здоровья" in lower_msg:
            save_consultation_state(uid, {"dialog_companion": {"active": False}}, subject_id=sid)
            dc_active = False
        else:
            _clear_clarify_followup_state(uid, sid)
            tone_hint = _resolve_non_medical_tone(msg)
            tone = tone_hint or _load_non_medical_tone(uid)
            if tone_hint:
                _save_non_medical_tone(uid, tone_hint)
            companion_out_v = await run_dialog_companion_turn(msg, recent_chat_history)
            llm_body_v = str(companion_out_v.get("response") or "").strip()
            if llm_body_v and companion_out_v.get("error") is None:
                response = llm_body_v
                rsp_src_vnm = "dialog_companion_llm"
                pt_v = int(companion_out_v.get("prompt_tokens") or 0)
                ct_v = int(companion_out_v.get("completion_tokens") or 0)
                tt_v = int(companion_out_v.get("total_tokens") or 0)
                cost_v = float(companion_out_v.get("estimated_cost_usd") or 0.0)
                llm_v = bool(companion_out_v.get("llm_used"))
                model_v = companion_out_v.get("model_used")
            else:
                response = _non_medical_chat_response(msg, tone=tone)
                rsp_src_vnm = "non_medical_chat_bypass"
                pt_v = ct_v = tt_v = 0
                cost_v = 0.0
                llm_v = False
                model_v = None
            response = _augment_non_medical_with_web_search(msg, response)
            save_consultation_state(uid, {"dialog_companion": {"active": True}}, subject_id=sid)
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", response, subject_id=sid)
            _record_voice_quality_event(source="non_medical_voice_turn", complaint=msg, severity="info")
            return _attach_voice_meta({
                "user_id": uid,
                "response": response,
                "response_simple": response,
                "conclusion": False,
                "report_id": None,
                "report": None,
                "suggest_pdf": False,
                "severity": None,
                "red_flags_present": False,
                "red_flag_matches": [],
                "llm_used": llm_v,
                "response_source": rsp_src_vnm,
                "medical_core_bypassed": True,
                "model_used": model_v,
                "worker_used": False,
                "request_id": None,
                "orchestrator_state": None,
                "consultation_case": None,
                "prompt_tokens": pt_v,
                "completion_tokens": ct_v,
                "total_tokens": tt_v,
                "estimated_cost_usd": cost_v,
                "structured": {
                    "suggested_questions": [],
                    "action_sequence": [],
                    "insufficient_data": False,
                },
                "symptom_payload": None,
                "knowledge_context": None,
                "action_sequence": [],
            }, {
                "response": response,
                "conclusion": False,
                "structured": {"suggested_questions": []},
                "response_source": rsp_src_vnm,
                "severity": "GREEN",
                "red_flags_present": False,
            })

    deep_level = str(limits.get("deep_coaching") or "none")
    if _is_deep_coaching_request(msg, recent_chat_history) and deep_level == "none":
        gate_payload = _build_deep_coaching_gate_payload(
            uid=uid,
            plan_type=plan,
            response_source="paywall_deep_coaching_voice",
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", gate_payload["response"], subject_id=sid)
        _record_paywall_event(source="paywall_deep_coaching_voice", plan_type=plan, reason="deep_coaching_locked", message=msg)
        return _attach_voice_meta(gate_payload, {
            "response": gate_payload["response"],
            "conclusion": False,
            "structured": {"suggested_questions": []},
            "response_source": "paywall_deep_coaching_voice",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    if _is_ambiguous_route_request(msg) and not dc_active:
        response = _clarify_route_question()
        save_consultation_state(
            uid,
            {"dialogue_route": {"pending_mode": "awaiting_choice", "pending_message": msg}},
            subject_id=sid,
        )
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": None,
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "route_clarification_prompt",
            "medical_core_bypassed": True,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": {"suggested_questions": [], "action_sequence": [], "insufficient_data": False},
            "symptom_payload": None,
            "knowledge_context": None,
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": {"suggested_questions": []},
            "response_source": "route_clarification_prompt",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    if _is_acute_injury_bleeding_request(msg):
        response = _acute_injury_bleeding_response(msg)
        structured = _acute_injury_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="acute_injury_voice_turn", complaint=msg, severity="warn")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "acute_injury_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "acute_injury_guard",
            "severity": "YELLOW",
            "red_flags_present": False,
        })

    if _is_food_symptom_super_request(msg):
        super_payload = _food_symptom_super_response(msg)
        response = str(super_payload.get("response") or "")
        structured = dict(super_payload.get("structured") or {})
        red_matches = list(super_payload.get("red_flag_matches") or [])
        urgent = bool(super_payload.get("red_flags_present"))
        source = str(super_payload.get("response_source") or "food_symptom_super_guard")
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="food_symptom_super_voice_turn", complaint=msg, severity="warn" if urgent else "info")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": source,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": source,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
        })

    if _is_upper_abdominal_request(msg):
        response, red_matches, urgent = _upper_abdominal_response(msg)
        structured = _upper_abdominal_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="upper_abdominal_voice_turn", complaint=msg, severity="warn" if urgent else "info")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": "upper_abdominal_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "upper_abdominal_guard",
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
        })

    if _is_postmeal_systemic_request(msg):
        response, red_matches, urgent = _postmeal_systemic_response(msg)
        structured = _postmeal_systemic_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="postmeal_systemic_voice_turn", complaint=msg, severity="warn" if urgent else "info")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": "postmeal_systemic_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "postmeal_systemic_guard",
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
        })

    if _is_postmeal_bloating_request(msg):
        response, red_matches, urgent = _postmeal_bloating_response(msg)
        structured = _postmeal_bloating_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="postmeal_bloating_voice_turn", complaint=msg, severity="warn" if urgent else "info")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
            "red_flag_matches": red_matches,
            "llm_used": False,
            "response_source": "postmeal_bloating_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "postmeal_bloating_guard",
            "severity": "YELLOW" if urgent else "GREEN",
            "red_flags_present": urgent,
        })

    if _is_food_overload_reaction_request(msg):
        response = _food_overload_reaction_response(msg)
        structured = _food_overload_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="food_overload_voice_turn", complaint=msg, severity="info")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "food_overload_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "food_overload_guard",
            "severity": "GREEN",
            "red_flags_present": False,
        })

    if _is_anorectal_bleeding_request(msg):
        response = _anorectal_bleeding_response()
        structured = _anorectal_bleeding_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="anorectal_bleeding_voice_turn", complaint=msg, severity="warn")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "anorectal_bleeding_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "anorectal_bleeding_guard",
            "severity": "YELLOW",
            "red_flags_present": False,
        })

    if _is_headache_autonomic_request(msg):
        response = _headache_autonomic_response()
        structured = _headache_autonomic_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="headache_autonomic_voice_turn", complaint=msg, severity="warn")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "headache_autonomic_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "headache_autonomic_guard",
            "severity": "YELLOW",
            "red_flags_present": True,
        })

    if _is_nosebleed_request(msg):
        response = _nosebleed_response()
        structured = _nosebleed_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="nosebleed_voice_turn", complaint=msg, severity="warn")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "nosebleed_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "nosebleed_guard",
            "severity": "YELLOW",
            "red_flags_present": True,
        })

    if _is_amenorrhea_galactorrhea_concern(msg):
        response = _amenorrhea_galactorrhea_response()
        structured = _amenorrhea_galactorrhea_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="amenorrhea_galactorrhea_voice_turn", complaint=msg, severity="warn")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "amenorrhea_galactorrhea_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "amenorrhea_galactorrhea_guard",
            "severity": "YELLOW",
            "red_flags_present": True,
        })

    if _is_prolonged_appetite_loss_concern(msg):
        response = _prolonged_appetite_loss_response()
        structured = _prolonged_appetite_loss_structured()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="prolonged_appetite_loss_voice_turn", complaint=msg, severity="warn")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "YELLOW",
            "red_flags_present": True,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "prolonged_appetite_loss_guard",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "prolonged_appetite_loss_guard",
            "severity": "YELLOW",
            "red_flags_present": True,
        })

    msg_cq = _strip_dialog_question_prefix(msg)
    phrase_preset = match_user_phrase_preset(msg_cq)
    lookup_query = str(phrase_preset.get("canonical_query") or "").strip() if phrase_preset else msg_cq
    lookup_query = _strip_dialog_question_prefix(lookup_query)
    ab_style = str(phrase_preset.get("ab_style") or "A").strip().upper() if phrase_preset else "A"
    recent_chat_history_v = get_chat_history(uid, subject_id=sid)
    fatigue_probe_v = _user_text_blob_for_constitutional_probe(msg, recent_chat_history_v)
    consultation_state_for_anchor_v = get_consultation_state(uid, subject_id=sid) or {}
    complaint_hits = _search_complaint_candidates(lookup_query, top_k=10)
    if not complaint_hits and lookup_query != msg_cq:
        complaint_hits = _search_complaint_candidates(msg_cq, top_k=10)
    rank_query = lookup_query if phrase_preset and lookup_query else msg_cq
    common_item = _select_best_complaint_hit(rank_query, complaint_hits, chat_history=recent_chat_history_v)
    if common_item and _complaint_library_hit_mismatch_constitutional_fatigue(fatigue_probe_v, common_item):
        common_item = None
    if common_item and _complaint_library_hit_mismatch_pleuritic_chest_dyspnea(fatigue_probe_v, common_item):
        common_item = None
    if common_item and _complaint_library_hit_mismatch_weight_loss_plateau(fatigue_probe_v, common_item):
        common_item = None
    common_item = _maybe_restore_heavy_menses_complaint_item(
        msg_cq,
        chat_history=recent_chat_history_v,
        selected=common_item,
        consultation_state=consultation_state_for_anchor_v,
    )
    if common_item:
        _persist_complaint_library_anchor(uid, sid, common_item)
        use_clarify_v = _should_use_clarify_first_mode(msg, common_item)
        if use_clarify_v:
            q_queue_v = _get_clarify_followup_question_queue(common_item, msg, chat_history=recent_chat_history_v)
            save_consultation_state(
                uid,
                {
                    "clarify_followup": {
                        "active": True,
                        "ab_style": ab_style,
                        "item": common_item,
                        "questions": q_queue_v,
                        "awaiting_question_index": 0,
                        "original_message": msg,
                        "answers": [],
                    }
                },
                subject_id=sid,
            )
        else:
            _clear_clarify_followup_state(uid, sid)
        response = _build_complaint_reference_response(
            common_item,
            msg,
            style_hint=ab_style,
            chat_history=recent_chat_history_v,
        )
        structured = _common_complaint_structured(common_item, user_message=msg, chat_history=recent_chat_history_v)
        structured["ab_style"] = ab_style
        if use_clarify_v:
            structured["clarify_followup"] = {"phase": "question", "step": 1, "total": len(q_queue_v)}
        if "suggested_questions" not in structured:
            structured = {
                **structured,
                "suggested_questions": [],
                "action_sequence": [],
                "insufficient_data": False,
            }
        has_red_flags = bool(common_item.get("red_flags") or common_item.get("red_flags_specific"))
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", response, subject_id=sid)
        _record_voice_quality_event(source="common_complaint_voice_turn", complaint=msg, severity="info")
        return _attach_voice_meta({
            "user_id": uid,
            "response": response,
            "response_simple": response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response) > _RESPONSE_SIMPLE_MAX_CHARS else response,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": "GREEN",
            "red_flags_present": has_red_flags,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "complaint_reference_library_ab_" + ab_style,
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": response,
            "conclusion": False,
            "structured": structured,
            "response_source": "complaint_reference_library_ab_" + ab_style,
            "severity": "GREEN",
            "red_flags_present": has_red_flags,
        })

    intent = detect_intent(msg)
    if intent == "symptom" and msg:
        add_symptom_entry(uid, msg, source="chat", subject_id=sid)

    chat_history = get_chat_history(uid, subject_id=sid)
    if _is_repeat_request(msg):
        last_assistant = _get_last_assistant_message(chat_history)
        if last_assistant:
            append_chat_message(uid, "user", msg, subject_id=sid)
            append_chat_message(uid, "assistant", last_assistant, subject_id=sid)
            return _attach_voice_meta({
                "user_id": uid,
                "response": last_assistant,
                "response_simple": last_assistant[:_RESPONSE_SIMPLE_MAX_CHARS] if len(last_assistant) > _RESPONSE_SIMPLE_MAX_CHARS else None,
                "conclusion": False,
                "report": None,
                "structured": None,
                "suggested_questions": [],
                "llm_used": False,
                "response_source": "repeat",
            }, {
                "response": last_assistant,
                "conclusion": False,
                "structured": {"suggested_questions": []},
                "response_source": "repeat",
                "severity": "GREEN",
                "red_flags_present": False,
            })

    if _is_red_flags_faq_request(msg):
        faq_response = get_red_flags_faq_response()
        append_chat_message(uid, "user", msg, subject_id=sid)
        append_chat_message(uid, "assistant", faq_response, subject_id=sid)
        structured_faq = build_structured_response(msg, faq_response, has_lab_data=len(get_documents(uid, subject_id=sid)) > 0)
        structured_faq["suggested_questions"] = []
        structured_faq["action_sequence"] = []
        return _attach_voice_meta({
            "user_id": uid,
            "response": faq_response,
            "response_simple": faq_response[:_RESPONSE_SIMPLE_MAX_CHARS] if len(faq_response) > _RESPONSE_SIMPLE_MAX_CHARS else None,
            "conclusion": False,
            "report_id": None,
            "report": None,
            "suggest_pdf": False,
            "severity": None,
            "red_flags_present": False,
            "red_flag_matches": [],
            "llm_used": False,
            "response_source": "red_flags_faq",
            "model_used": None,
            "worker_used": False,
            "request_id": None,
            "orchestrator_state": None,
            "consultation_case": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": 0.0,
            "structured": structured_faq,
            "symptom_payload": extract_symptom_payload(msg),
            "knowledge_context": resolve_medical_context(msg, language="ru"),
            "action_sequence": [],
        }, {
            "response": faq_response,
            "conclusion": False,
            "structured": structured_faq,
            "response_source": "red_flags_faq",
            "severity": "YELLOW",
            "red_flags_present": False,
        })

    append_chat_message(uid, "user", msg, subject_id=sid)
    profile = get_profile(uid)
    documents = get_documents(uid, subject_id=sid)
    has_lab_data = len(documents) > 0
    symptom_entries = get_symptom_entries(uid, subject_id=sid)
    chat_history = get_chat_history(uid, subject_id=sid)
    last_assistant_before = _get_last_assistant_message(chat_history)
    settings = get_settings(uid)
    app_mode = (settings.get("mode") or "BASIC").strip() or None
    vitals = get_vitals(uid)
    document_context = get_last_consultation_report_context(uid, subject_id=sid)

    result = await run_consultation_turn(
        user_id=uid,
        user_message=msg,
        profile=profile,
        documents_count=len(documents),
        symptom_entries=symptom_entries,
        chat_history=chat_history,
        app_mode=app_mode,
        vitals=vitals,
        document_context=document_context or None,
        subject_id=sid,
        consultation_mode_hint=str(payload.lookup_mode or "").strip() or None,
    )
    append_chat_message(uid, "assistant", result["response"], subject_id=sid)
    try:
        record_runtime_event(
            source=str(result.get("response_source") or ""),
            llm_used=bool(result.get("llm_used")),
            model_used=result.get("model_used"),
            protocol_source=str((result.get("orchestrator_state") or {}).get("protocol_source") or ""),
            complaint=str((result.get("orchestrator_state") or {}).get("complaint") or ""),
            cluster=str((result.get("orchestrator_state") or {}).get("market_signal_cluster") or ""),
            severity=str(result.get("severity") or ""),
            prompt_chars=int(result.get("prompt_chars") or 0),
            response_chars=int(result.get("response_chars") or 0),
            prompt_tokens=int(result.get("prompt_tokens") or 0),
            completion_tokens=int(result.get("completion_tokens") or 0),
            total_tokens=int(result.get("total_tokens") or 0),
            estimated_cost_usd=float(result.get("estimated_cost_usd") or 0.0),
        )
    except Exception:
        pass
    try:
        record_turn_for_autolearn(msg, result.get("response") or "")
    except Exception:
        pass
    # Голосовые жалобы с ответами не сохраняем в «Анализы — Загруженные документы и отчёты»
    # save_voice_concierge_turn_to_labs(uid, msg, result.get("response") or "")
    if result.get("conclusion") and result.get("response"):
        try:
            capture_learning_candidate(
                user_id=uid,
                question=msg,
                response=result.get("response") or "",
                structured=result.get("structured"),
                orchestrator_state=result.get("orchestrator_state"),
                report=result.get("report"),
                response_source=str(result.get("response_source") or ""),
                llm_used=bool(result.get("llm_used")),
            )
        except Exception:
            pass
    if result.get("conclusion") and result.get("response"):
        add_notification(
            uid,
            "Новая рекомендация по консультации",
            (result.get("response") or "")[:500],
            unread=True,
        )

    response_voice_final = result.get("response") or ""
    structured = build_structured_response(msg, response_voice_final, has_lab_data=has_lab_data)
    suggested = suggest_clarifying_questions(msg, chat_history, has_lab_data=has_lab_data, max_questions=1)
    structured["suggested_questions"] = suggested
    _rotate_followup_if_repeated(structured, previous_voice_state, msg)
    symptom_payload = extract_symptom_payload(msg)
    knowledge_context = resolve_medical_context(msg, language="ru")
    # Модуль «Сила и микробиом» + v1.1 оси и обогащение ответа
    try:
        if not _constitutional_fatigue_thread_active(msg or "", chat_history):
            profile = get_profile(uid) if uid else {}
            profile = profile if isinstance(profile, dict) else {}
            user_age = profile.get("age")
            if user_age is not None and not isinstance(user_age, int):
                try:
                    user_age = int(user_age)
                except (TypeError, ValueError):
                    user_age = None
            low_activity = profile.get("low_activity") if isinstance(profile.get("low_activity"), bool) else None
            gut_muscle = evaluate_gut_muscle_axis(msg, age=user_age, low_activity=low_activity, protein_deficit_hint=False)
            if gut_muscle.get("active"):
                structured.setdefault("insights", [])
                if gut_muscle.get("insight_block") and gut_muscle["insight_block"] not in structured["insights"]:
                    structured["insights"].append(gut_muscle["insight_block"])
                structured["strength_metabolism_block"] = gut_muscle.get("strength_metabolism_block")
                structured["axis"] = "gut_muscle"
                structured["gut_muscle_risk_score"] = gut_muscle.get("risk_score", 0)
                structured["gut_muscle_risk_level"] = gut_muscle.get("risk_level", "low")
            microbiome_result = run_microbiome_engine(
                symptoms_text=msg or "",
                age=user_age,
                low_activity=low_activity,
                poor_diet=None,
            )
            if microbiome_result.get("active"):
                structured["microbiome_report"] = microbiome_result
            # v1.1: оси и обогащение текста блоком «Микробиомный модуль»
            payload = build_microbiome_payload_from_message(msg or "", profile)
            axes = calc_microbiome_axes(payload)
            if axes:
                structured["microbiome_axes_v11"] = [
                    {
                        "axis": a.axis,
                        "score": a.score,
                        "level": a.level,
                        "triggered_by": getattr(a, "triggered_by", []),
                        "insights": getattr(a, "insights", []),
                        "recommendations": getattr(a, "recommendations", []),
                        "cta": getattr(a, "cta", None),
                    }
                    for a in axes
                ]
                enriched = enrich_with_microbiome(payload, [response_voice_final])
                if enriched:
                    response_voice_final = enriched[0]
    except Exception:
        pass
    response_voice_final = _enrich_medical_response(
        response_voice_final,
        structured,
        last_assistant_before or "",
        msg,
        chat_history,
    )
    action_sequence = build_concierge_action_sequence(
        user_message=msg,
        symptom_payload=symptom_payload,
        structured=structured,
        suggested_questions=suggested,
        has_lab_data=has_lab_data,
    )
    save_action_sequence(
        uid,
        action_sequence,
        source_message=msg,
        report_id=result.get("report_id"),
        conclusion=bool(result.get("conclusion")),
    )
    structured["action_sequence"] = action_sequence

    orch_voice = result.get("orchestrator_state") or {}
    topic_voice = str(orch_voice.get("complaint") or msg or "").strip()
    voice_knowledge_enrichment = _run_knowledge_enrichment_followup_api(
        uid=uid,
        sid=sid,
        topic=topic_voice,
        red_flags_present=bool(result.get("red_flags_present")),
        llm_used=bool(result.get("llm_used")),
        response_source=str(result.get("response_source") or "") + "_voice",
    )

    return _attach_voice_meta({
        "user_id": uid,
        "response": response_voice_final,
        "response_simple": result.get("response_simple") or (response_voice_final[:_RESPONSE_SIMPLE_MAX_CHARS] if len(response_voice_final or "") > _RESPONSE_SIMPLE_MAX_CHARS else None),
        "conclusion": result.get("conclusion", False),
        "report_id": result.get("report_id"),
        "report": result.get("report"),
        "suggest_pdf": result.get("suggest_pdf", False),
        "severity": result.get("severity"),
        "red_flags_present": result.get("red_flags_present", False),
        "red_flag_matches": result.get("red_flag_matches") or [],
        "llm_used": result.get("llm_used", False),
        "response_source": result.get("response_source"),
        "model_used": result.get("model_used"),
        "worker_used": result.get("worker_used", False),
        "request_id": result.get("request_id"),
        "orchestrator_state": result.get("orchestrator_state"),
        "consultation_case": result.get("consultation_case"),
        "prompt_tokens": result.get("prompt_tokens", 0),
        "completion_tokens": result.get("completion_tokens", 0),
        "total_tokens": result.get("total_tokens", 0),
        "estimated_cost_usd": result.get("estimated_cost_usd", 0.0),
        "structured": structured,
        "unified_engine_snapshot": (
            structured.get("unified_engine_snapshot")
            if isinstance(structured, dict)
            else None
        ),
        "knowledge_enrichment": voice_knowledge_enrichment,
        "symptom_payload": symptom_payload,
        "knowledge_context": knowledge_context,
        "action_sequence": action_sequence,
    }, {
        "response": response_voice_final,
        "conclusion": bool(result.get("conclusion", False)),
        "structured": structured,
        "response_source": str(result.get("response_source") or ""),
        "severity": result.get("severity") or "YELLOW",
        "red_flags_present": bool(result.get("red_flags_present", False)),
    })


_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_MEDICAL_CORE_CATALOG_PATH = _PROJECT_ROOT / "medical_knowledge" / "medical_core" / "catalog_full_625.json"
_FORUM_GOVERNANCE_PATH = _PROJECT_ROOT / "backend" / "data" / "forum_governance.json"
_FORUM_BRANCH_EXTENSIONS_PATH = _PROJECT_ROOT / "backend" / "data" / "forum_branch_extensions.json"
_FORUM_DEFAULT_RULES = """# Правила форума «За Здоровье»

1. Участники форума — любые зарегистрированные пользователи.
2. Тематических администраторов назначает и утверждает только владелец платформы.
3. Запрещены опасные советы, самолечение без дисклеймера и агрессия.
4. При признаках неотложного состояния направляйте пользователя к очной помощи.
5. Спорные темы фиксируются в модерации и пересматриваются владельцем.
"""


def _read_forum_governance() -> dict[str, Any]:
    try:
        if _FORUM_GOVERNANCE_PATH.exists():
            payload = json.loads(_FORUM_GOVERNANCE_PATH.read_text(encoding="utf-8"))
        else:
            payload = {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("owner_user_id", "")
    payload.setdefault("rules_markdown", _FORUM_DEFAULT_RULES)
    payload.setdefault("thematic_admins", [])
    if not isinstance(payload.get("thematic_admins"), list):
        payload["thematic_admins"] = []
    return payload


def _write_forum_governance(payload: dict[str, Any]) -> None:
    _FORUM_GOVERNANCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FORUM_GOVERNANCE_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_FORUM_GOVERNANCE_PATH)


def _read_forum_branch_extensions() -> list[dict[str, Any]]:
    if not _FORUM_BRANCH_EXTENSIONS_PATH.exists():
        return []
    try:
        payload = json.loads(_FORUM_BRANCH_EXTENSIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    items = payload.get("items") if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for row in items:
        if not isinstance(row, dict):
            continue
        bid = str(row.get("id") or "").strip()
        title = str(row.get("title") or "").strip()
        if not bid or not title:
            continue
        out.append(
            {
                "id": bid,
                "title": title,
                "type": str(row.get("type") or "topic").strip() or "topic",
                "category": str(row.get("category") or "Общая медицина").strip() or "Общая медицина",
                "description": str(row.get("description") or "").strip(),
                "tags": [str(x).strip() for x in (row.get("tags") or []) if str(x).strip()][:18],
            }
        )
    return out


def _write_forum_branch_extensions(items: list[dict[str, Any]]) -> None:
    payload = {"items": items}
    _FORUM_BRANCH_EXTENSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = _FORUM_BRANCH_EXTENSIONS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(_FORUM_BRANCH_EXTENSIONS_PATH)


def _slugify_forum_topic(source: str) -> str:
    s = re.sub(r"[^a-zA-Zа-яА-ЯёЁ0-9]+", "_", str(source or "").strip().lower())
    s = re.sub(r"_+", "_", s).strip("_")
    if not s:
        return "custom_topic"
    return s[:64]


def _ensure_forum_branch_for_query(query: str) -> dict[str, Any]:
    q = str(query or "").strip()
    if len(q) < 2:
        return {}
    ext = _read_forum_branch_extensions()
    qn = q.lower()
    for row in ext:
        hay = " ".join([str(row.get("title") or ""), str(row.get("description") or ""), " ".join(row.get("tags") or [])]).lower()
        if qn in hay:
            return dict(row)
    topic_id = "topic:auto_" + _slugify_forum_topic(q)
    tags = [x for x in re.split(r"[,\s/;:.!?()\[\]\-]+", qn) if x and len(x) >= 3][:8]
    item = {
        "id": topic_id,
        "title": q[:140],
        "type": "topic",
        "category": "Пользовательские запросы",
        "description": "Автосозданная ветка по пользовательскому поисковому запросу. Здесь можно обсуждать симптомы, жалобы и похожие случаи.",
        "tags": tags or [qn[:24]],
    }
    ext.append(item)
    _write_forum_branch_extensions(ext[-500:])
    return item


def _require_forum_owner(admin_user: dict[str, Any]) -> dict[str, Any]:
    gov = _read_forum_governance()
    user_id = str(admin_user.get("user_id") or "").strip()
    if not gov.get("owner_user_id"):
        gov["owner_user_id"] = user_id
        _write_forum_governance(gov)
    if str(gov.get("owner_user_id") or "").strip() != user_id:
        raise HTTPException(status_code=403, detail="Назначение тематических администраторов доступно только владельцу платформы.")
    return gov


def _is_forum_owner(user_id: str) -> bool:
    uid = str(user_id or "").strip()
    if not uid:
        return False
    gov = _read_forum_governance()
    return str(gov.get("owner_user_id") or "").strip() == uid


def _is_thematic_admin_for_branch(user_id: str, branch_id: str) -> bool:
    uid = str(user_id or "").strip()
    bid = str(branch_id or "").strip()
    if not uid or not bid:
        return False
    gov = _read_forum_governance()
    for row in (gov.get("thematic_admins") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("user_id") or "").strip() != uid:
            continue
        if str(row.get("branch_id") or "").strip() != bid:
            continue
        if str(row.get("status") or "").strip().lower() != "approved":
            continue
        return True
    return False


def _can_moderate_for_branch(user: dict[str, Any], branch_id: str) -> bool:
    role = str(user.get("role") or "").strip().lower()
    uid = str(user.get("user_id") or "").strip()
    if role == "admin":
        return True
    if _is_forum_owner(uid):
        return True
    return _is_thematic_admin_for_branch(uid, branch_id)


@lru_cache(maxsize=1)
def _load_medical_core_catalog() -> list[dict[str, Any]]:
    if not _MEDICAL_CORE_CATALOG_PATH.exists():
        return []
    try:
        payload = json.loads(_MEDICAL_CORE_CATALOG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = payload.get("items") if isinstance(payload, dict) else payload
    if not isinstance(items, list):
        return []
    return [x for x in items if isinstance(x, dict)]


def _forum_branch_items() -> list[dict[str, Any]]:
    rows = _load_medical_core_catalog()
    out: list[dict[str, Any]] = []
    mandatory_branches = [
        {
            "id": "topic:prostatitis",
            "title": "Простатит",
            "type": "topic",
            "category": "Урология",
            "description": "Обсуждение симптомов, диагностики, лечения и профилактики простатита.",
            "tags": ["простатит", "урология", "мочеиспускание", "тазовая боль", "профилактика"],
        },
        {
            "id": "topic:hemorrhoids",
            "title": "Геморрой",
            "type": "topic",
            "category": "Проктология",
            "description": "Ветка по геморрою: боль, кровь, обострение, безопасные рекомендации и когда срочно к врачу.",
            "tags": ["геморрой", "кровь", "боль", "проктология", "стул"],
        },
        {
            "id": "topic:sti_std",
            "title": "Венерические болезни (ИППП/ЗППП)",
            "type": "topic",
            "category": "Инфекции",
            "description": "ИППП/ЗППП: симптомы, диагностика, анализы, лечение у врача и профилактика.",
            "tags": ["венерические болезни", "иппп", "зппп", "std", "sti", "хламидиоз", "гонорея", "сифилис"],
        },
        {
            "id": "topic:gilbert_syndrome",
            "title": "Синдром Жильбера и повышенный билирубин",
            "type": "topic",
            "category": "Гастроэнтерология",
            "description": "Синдром Жильбера: эпизоды желтушности, колебания билирубина, триггеры (голод, стресс, инфекция), безопасная тактика и контроль.",
            "tags": [
                "синдром жильбера",
                "жильбер",
                "билирубин",
                "непрямой билирубин",
                "желтушность",
                "печень",
                "гипербилирубинемия",
            ],
        },
        {
            "id": "topic:jaundice_bilirubin",
            "title": "Желтушность, билирубин и печёночные жалобы",
            "type": "topic",
            "category": "Гастроэнтерология",
            "description": "Похожие жалобы: пожелтение склер/кожи, тёмная моча, светлый стул, зуд кожи, тяжесть в правом подреберье. Когда срочно обращаться.",
            "tags": [
                "желтуха",
                "желтушность",
                "билирубин",
                "печеночные пробы",
                "правое подреберье",
                "темная моча",
                "светлый стул",
                "зуд кожи",
            ],
        },
    ]
    for row in rows:
        title = str(row.get("name") or "").strip()
        if not title:
            continue
        entry_type = str(row.get("type") or "").strip() or "topic"
        category = str(row.get("category") or "Общая медицина").strip()
        symptoms = [str(x).strip() for x in (row.get("symptoms") or []) if str(x).strip()]
        search_terms = [str(x).strip() for x in (row.get("search_terms") or []) if str(x).strip()]
        tags: list[str] = []
        for token in [category, entry_type] + symptoms[:6] + search_terms[:8]:
            t = str(token or "").strip()
            if not t:
                continue
            if t.lower() in {x.lower() for x in tags}:
                continue
            tags.append(t)
        raw_desc = re.sub(r"\s+", " ", str(row.get("description") or "").strip())
        if len(raw_desc) > 220:
            raw_desc = raw_desc[:217].rstrip() + "..."
        if not raw_desc:
            raw_desc = f"Профильная ветка: {title}. Здесь обсуждают симптомы, обследования и безопасные шаги."
        out.append(
            {
                "id": str(row.get("entry_id") or row.get("source_id") or title),
                "title": title,
                "type": entry_type,
                "category": category,
                "description": raw_desc,
                "tags": tags[:18],
                "keywords": [x.lower() for x in tags[:18]],
            }
        )
    existing_ids = {str(x.get("id") or "").strip().lower() for x in out if isinstance(x, dict)}
    existing_titles = {str(x.get("title") or "").strip().lower() for x in out if isinstance(x, dict)}
    for item in mandatory_branches:
        bid = str(item.get("id") or "").strip().lower()
        btitle = str(item.get("title") or "").strip().lower()
        if bid in existing_ids or btitle in existing_titles:
            continue
        out.append(
            {
                **item,
                "keywords": [str(x).lower() for x in (item.get("tags") or [])],
            }
        )
    for item in _read_forum_branch_extensions():
        bid = str(item.get("id") or "").strip().lower()
        btitle = str(item.get("title") or "").strip().lower()
        if bid in existing_ids or btitle in existing_titles:
            continue
        out.append({**item, "keywords": [str(x).lower() for x in (item.get("tags") or [])]})
    return out


def _news_seed_items() -> list[dict[str, Any]]:
    return [
        {
            "id": "news-001",
            "title": "Новый режим клинических гипотез в За Здоровье",
            "category": "Система диагностики",
            "summary": "Добавлен вероятностный подход к гипотезам без постановки жёсткого диагноза.",
            "content": "Мы обновили движок консультаций: теперь гипотезы формируются вероятностно, с фокусом на безопасность и обязательные уточняющие вопросы. Это помогает избегать поспешных выводов и строить рекомендации по шагам.",
            "tags": ["гипотезы", "симптомы", "клинический режим", "safety-first"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-002",
            "title": "Обновление triage: ранняя маршрутизация и red flags",
            "category": "Безопасность",
            "summary": "Система раньше определяет уровень помощи и срочность при тревожных признаках.",
            "content": "Усилен блок red flags: при признаках риска система быстрее переводит диалог в срочный контур и подсказывает, куда обращаться. Это снижает задержки в критичных кейсах.",
            "tags": ["triage", "red flags", "срочность", "безопасность"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-003",
            "title": "Портал аналитики: новые отчёты по симптомам и лабораториям",
            "category": "Аналитика",
            "summary": "Доступны расширенные материалы по динамике жалоб, анализов и рекомендаций.",
            "content": "В отчётах появились более удобные сводки по симптомам и анализам с акцентом на динамику и практические шаги. Интерфейс адаптирован для чтения как с телефона, так и с десктопа.",
            "tags": ["аналитика", "лаборатории", "отчёты", "диагностика"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-004",
            "title": "Новые статьи по современным методам диагностики",
            "category": "Статьи",
            "summary": "Подготовлена подборка материалов по лабораторной и инструментальной диагностике.",
            "content": "Добавлены обзорные материалы по современным методам диагностики: когда назначают анализы, как готовиться и на какие результаты обратить внимание до очной консультации.",
            "tags": ["статьи", "диагностика", "анализы", "клиническая практика"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-005",
            "title": "Обновлён блок рекомендаций по лечению и образу жизни",
            "category": "Лечение",
            "summary": "Усилен раздел first-line care, питания, физической активности и профилактики.",
            "content": "Структура рекомендаций стала более практичной: что делать сейчас, чего избегать, какие меры подходят для дома, и когда нужно очное обследование.",
            "tags": ["лечение", "питание", "физическая активность", "профилактика"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-006",
            "title": "Новые клинические протоколы по простатиту",
            "category": "Урология",
            "summary": "Добавлены обновлённые подходы к маршрутизации, обследованию и безопасным рекомендациям по простатиту.",
            "content": "Протоколы по урологическим жалобам доработаны: больше релевантных уточняющих вопросов и более понятная маршрутизация на очную помощь при тревожных симптомах.",
            "tags": ["простатит", "урология", "диагностика", "лечение"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-007",
            "title": "Обновления по теме геморроя и аноректальных кровотечений",
            "category": "Проктология",
            "summary": "Расширены правила triage, red flags и очной маршрутизации для более безопасных рекомендаций.",
            "content": "Ветка проктологии получила более точные правила при кровотечениях и болевом синдроме: ассистент быстрее выделяет случаи, где требуется очный осмотр без промедления.",
            "tags": ["геморрой", "кровотечение", "проктология", "red flags"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-008",
            "title": "ИППП/ЗППП: новые материалы по диагностике и профилактике",
            "category": "Инфекции",
            "summary": "Подборка статей по современным методам обследования, анализов и профилактике венерических заболеваний.",
            "content": "Раздел ИППП/ЗППП дополнен материалами о лабораторной диагностике, сценариях обращения к врачу и шагах профилактики для снижения рисков.",
            "tags": ["иппп", "зппп", "венерические болезни", "std", "sti"],
            "published_at": "2026-04-09",
        },
        {
            "id": "news-ext-001",
            "title": "WHO: новые инструменты диагностики туберкулёза",
            "category": "Мировая медицина",
            "summary": "ВОЗ рекомендовала новые near point-of-care тесты, swab-подходы и pooled-стратегии для более доступной диагностики TB.",
            "content": "Краткий обзор по материалам ВОЗ: обновления направлены на ускорение диагностики в условиях ограниченных ресурсов и раннюю маршрутизацию пациентов. В приложении приведено обзорное описание своими словами; подробности доступны по ссылке на первоисточник.",
            "tags": ["WHO", "туберкулез", "диагностика", "public health"],
            "published_at": "2026-03-24",
            "source_name": "WHO",
            "source_url": "https://apps.who.int/news/item/24-03-2026-who-recommends-new-diagnostic-tools-to-help-end-tb",
        },
        {
            "id": "news-ext-002",
            "title": "CDC: сезонный отчёт по респираторным заболеваниям",
            "category": "Эпидемиология",
            "summary": "CDC опубликовал мартовское обновление по сезону 2025-2026 для гриппа, RSV и COVID-19 с динамикой госпитализаций.",
            "content": "Краткий обзор по данным CDC: сезонный пик госпитализаций пройден в январе, далее наблюдается спад, но отдельные группы риска сохраняют повышенную уязвимость. Это обзорная карточка с ссылкой на официальный источник.",
            "tags": ["CDC", "грипп", "RSV", "COVID-19", "сезонность"],
            "published_at": "2026-03-06",
            "source_name": "CDC",
            "source_url": "https://www.cdc.gov/cfa-qualitative-assessments/php/data-research/season-outlook25-26-mar-update.html",
        },
        {
            "id": "news-ext-003",
            "title": "Nature Medicine: AI triage в скрининге молочной железы",
            "category": "AI в медицине",
            "summary": "Исследование оценило AI-поддержку в маммографии: рост детекции при заметном снижении нагрузки на радиологов.",
            "content": "Краткое обзорное описание по публикации Nature Medicine: AI-поддержка может улучшать выявляемость и перераспределять время врача, при этом важны строгие safety-ограничения и контроль recall-показателей. Подробности в первоисточнике.",
            "tags": ["Nature Medicine", "AI", "mammography", "triage"],
            "published_at": "2026-01-01",
            "source_name": "Nature Medicine",
            "source_url": "http://www.nature.com/articles/s41591-026-04277-x",
        },
        {
            "id": "news-009",
            "title": "Новая ветка форума: синдром Жильбера и повышенный билирубин",
            "category": "Гастроэнтерология",
            "summary": "Добавлены тематические ветки по синдрому Жильбера, желтушности и похожим печёночным жалобам с акцентом на безопасную маршрутизацию.",
            "content": "В форуме появились отдельные темы по синдрому Жильбера и связанным жалобам: колебания билирубина, желтушность, правое подреберье, темная моча, светлый стул, зуд кожи. Добавлены ориентиры, когда можно наблюдать динамику, а когда нужна срочная очная оценка.",
            "tags": ["синдром жильбера", "билирубин", "желтушность", "печень", "форум"],
            "published_at": "2026-04-24",
        },
    ]


def _merged_news_items() -> list[dict[str, Any]]:
    seeds = _news_seed_items()
    custom = news_list_items(limit=1000)
    by_id: dict[str, dict[str, Any]] = {}
    for row in seeds:
        rid = str(row.get("id") or "").strip()
        if not rid:
            continue
        by_id[rid] = dict(row)
    for row in custom:
        rid = str(row.get("id") or "").strip()
        if not rid:
            continue
        if bool(row.get("deleted")):
            by_id.pop(rid, None)
            continue
        merged = dict(by_id.get(rid) or {})
        merged.update(dict(row))
        by_id[rid] = merged
    items = list(by_id.values())
    items.sort(key=lambda x: str(x.get("published_at") or ""), reverse=True)
    return items


@router.get("/user/forum/branches")
async def user_forum_branches_get(
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=300, ge=1, le=1000),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    items = _forum_branch_items()
    auto_created_branch = False
    gov = _read_forum_governance()
    approved: dict[str, list[dict[str, Any]]] = {}
    for row in (gov.get("thematic_admins") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "").strip().lower() != "approved":
            continue
        branch_id = str(row.get("branch_id") or "").strip()
        if not branch_id:
            continue
        approved.setdefault(branch_id, []).append(
            {
                "user_id": str(row.get("user_id") or "").strip(),
                "user_name": str(row.get("user_name") or "").strip(),
            }
        )
    query = (q or "").strip().lower()
    query_variants = {query}
    alias_map = {
        "простата": ["простатит", "урология"],
        "простатит": ["простата", "урология"],
        "гемор": ["геморрой", "проктология", "кровь"],
        "геморрой": ["гемор", "проктология", "кровь"],
        "венер": ["венерические болезни", "иппп", "зппп", "std", "sti"],
        "иппп": ["венерические болезни", "зппп", "std", "sti"],
        "зппп": ["венерические болезни", "иппп", "std", "sti"],
        "std": ["sti", "иппп", "зппп", "венерические болезни"],
        "sti": ["std", "иппп", "зппп", "венерические болезни"],
        "жильбер": ["синдром жильбера", "билирубин", "непрямой билирубин", "желтушность"],
        "синдром жильбера": ["жильбер", "билирубин", "желтушность", "печень"],
        "билирубин": ["жильбер", "синдром жильбера", "желтуха", "печень"],
        "желтуха": ["желтушность", "билирубин", "печень", "правое подреберье"],
    }
    for key, vals in alias_map.items():
        if query and (query == key or query in key or key in query):
            for v in vals:
                query_variants.add(v.lower())
    if query:
        filtered: list[dict[str, Any]] = []
        for it in items:
            hay = " ".join(
                [
                    str(it.get("title") or ""),
                    str(it.get("category") or ""),
                    str(it.get("description") or ""),
                    " ".join(str(x or "") for x in (it.get("tags") or [])),
                ]
            ).lower()
            if any(v in hay for v in query_variants if v):
                filtered.append(it)
        items = filtered
        if not items and len(query) >= 2:
            auto_item = _ensure_forum_branch_for_query(query)
            if auto_item:
                auto_item = dict(auto_item)
                auto_item["keywords"] = [str(x).lower() for x in (auto_item.get("tags") or [])]
                items = [auto_item]
                auto_created_branch = True
    for it in items:
        branch_id = str(it.get("id") or "").strip()
        admins = approved.get(branch_id) or []
        if admins:
            it["thematic_admins"] = admins[:3]
            it["thematic_admins_count"] = len(admins)
    current_user = _get_current_user(authorization) if _bearer_token(authorization or "") else {}
    if isinstance(current_user, dict) and current_user:
        for it in items:
            branch_id = str(it.get("id") or "").strip()
            it["can_moderate"] = _can_moderate_for_branch(current_user, branch_id)
    total = len(items)
    return {"total": total, "items": items[:limit], "auto_created_branch": auto_created_branch}


class ForumThreadCreate(BaseModel):
    branch_id: str
    title: str
    content: str


class ForumCommentCreate(BaseModel):
    content: str


class ForumThreadUpdate(BaseModel):
    title: str
    content: str


class ForumCommentUpdate(BaseModel):
    content: str


class ForumCommentModerationUpdate(BaseModel):
    status: str  # approved | hidden | rejected
    moderation_note: Optional[str] = ""


class ForumProposeKnowledgePayload(BaseModel):
    """Ручное предложение фрагмента форума в очередь глобального ревью знаний (flywheel)."""

    thread_id: str
    comment_id: Optional[str] = None
    moderator_note: Optional[str] = ""


class NewsItemUpsert(BaseModel):
    title: str
    category: Optional[str] = "Новости"
    summary: str
    content: Optional[str] = ""
    tags: Optional[List[str]] = None
    published_at: Optional[str] = ""
    source_url: Optional[str] = ""
    source_name: Optional[str] = ""


@router.get("/user/forum/threads")
async def user_forum_threads_get(
    branch_id: str = Query(..., min_length=1),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    viewer_id = _user_id(x_user_id, authorization)
    user = _get_current_user(authorization) if _bearer_token(authorization or "") else {}
    can_moderate = _can_moderate_for_branch(user or {}, branch_id) if isinstance(user, dict) and user else False
    items = forum_list_threads(
        branch_id=branch_id,
        limit=limit,
        viewer_user_id=viewer_id,
        include_hidden_for_moderator=can_moderate,
    )
    query = (q or "").strip().lower()
    if query:
        items = [
            it
            for it in items
            if query in (" ".join([str(it.get("title") or ""), str(it.get("content") or "")]).lower())
        ]
    for it in items:
        owner_match = viewer_id and viewer_id == str(it.get("created_by_user_id") or "").strip()
        can_manage = bool(can_moderate or owner_match)
        it["can_edit"] = can_manage
        it["can_delete"] = can_manage
    return {"total": len(items), "items": items[:limit], "query": q or ""}


@router.post("/user/forum/threads")
async def user_forum_thread_create(payload: ForumThreadCreate, user: dict = Depends(_get_current_user)):
    branch_id = str(payload.branch_id or "").strip()
    title = str(payload.title or "").strip()
    content = str(payload.content or "").strip()
    if not branch_id or not title or not content:
        raise HTTPException(status_code=400, detail="Укажите branch_id, title и content.")
    if len(title) < 5:
        raise HTTPException(status_code=400, detail="Заголовок слишком короткий.")
    if len(content) < 5:
        raise HTTPException(status_code=400, detail="Текст темы слишком короткий.")
    known_branch_ids = {str(x.get("id") or "") for x in _forum_branch_items()}
    if branch_id not in known_branch_ids:
        raise HTTPException(status_code=404, detail="Ветка форума не найдена.")
    item = forum_create_thread(
        branch_id=branch_id,
        title=title,
        content=content,
        created_by_user_id=str(user.get("user_id") or "").strip(),
        created_by_name=str(user.get("name") or user.get("login") or "").strip(),
        status="approved",
    )
    log_audit_event(
        action="forum.thread.create",
        target_type="forum_thread",
        target_id=str(item.get("id") or ""),
        actor_user_id=str(user.get("user_id") or ""),
        actor_role=str(user.get("role") or "user"),
        metadata={"branch_id": branch_id, "title": title[:120]},
    )
    return {"ok": True, "item": item}


@router.get("/user/forum/threads/{thread_id}")
async def user_forum_thread_get(
    thread_id: str,
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    item = forum_get_thread(thread_id)
    if not item:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    status = str(item.get("status") or "approved").strip().lower()
    if status != "approved":
        user = _get_current_user(authorization) if _bearer_token(authorization or "") else {}
        uid_raw = str(uid or "").strip()
        if not (
            (isinstance(user, dict) and _can_moderate_for_branch(user, str(item.get("branch_id") or "")))
            or (uid_raw and uid_raw == str(item.get("created_by_user_id") or ""))
        ):
            raise HTTPException(status_code=404, detail="Тема не найдена.")
    viewer_id = _user_id(x_user_id, authorization)
    user = _get_current_user(authorization) if _bearer_token(authorization or "") else {}
    can_moderate = _can_moderate_for_branch(user or {}, str(item.get("branch_id") or "")) if isinstance(user, dict) and user else False
    owner_match = str(viewer_id or "").strip() == str(item.get("created_by_user_id") or "").strip()
    item["can_edit"] = bool(can_moderate or owner_match)
    item["can_delete"] = bool(can_moderate or owner_match)
    return {"item": item}


@router.get("/user/forum/threads/{thread_id}/comments")
async def user_forum_thread_comments_get(
    thread_id: str,
    limit: int = Query(default=300, ge=1, le=1000),
    x_user_id: Optional[str] = Header(None, alias="X-User-Id"),
    authorization: Optional[str] = Header(None, alias="Authorization"),
):
    thread = forum_get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    viewer_id = _user_id(x_user_id, authorization)
    user = _get_current_user(authorization) if _bearer_token(authorization or "") else {}
    can_moderate = _can_moderate_for_branch(user or {}, str(thread.get("branch_id") or "")) if isinstance(user, dict) and user else False
    items = forum_list_comments(
        thread_id=thread_id,
        limit=limit,
        viewer_user_id=str(viewer_id or "").strip(),
        include_hidden_for_moderator=can_moderate,
    )
    for it in items:
        owner_match = viewer_id and viewer_id == str(it.get("created_by_user_id") or "").strip()
        can_manage = bool(can_moderate or owner_match)
        it["can_edit"] = can_manage
        it["can_delete"] = can_manage
    return {"total": len(items), "items": items}


@router.post("/user/forum/threads/{thread_id}/comments")
async def user_forum_thread_comment_create(
    thread_id: str,
    payload: ForumCommentCreate,
    user: dict = Depends(_get_current_user),
):
    thread = forum_get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    content = str(payload.content or "").strip()
    if len(content) < 2:
        raise HTTPException(status_code=400, detail="Комментарий слишком короткий.")
    item = forum_create_comment(
        thread_id=thread_id,
        branch_id=str(thread.get("branch_id") or ""),
        content=content,
        created_by_user_id=str(user.get("user_id") or "").strip(),
        created_by_name=str(user.get("name") or user.get("login") or "").strip(),
        status="approved",
    )
    log_audit_event(
        action="forum.comment.create",
        target_type="forum_comment",
        target_id=str(item.get("id") or ""),
        actor_user_id=str(user.get("user_id") or ""),
        actor_role=str(user.get("role") or "user"),
        metadata={"thread_id": thread_id},
    )
    return {"ok": True, "item": item}


@router.patch("/user/forum/threads/{thread_id}")
async def user_forum_thread_patch(thread_id: str, payload: ForumThreadUpdate, user: dict = Depends(_get_current_user)):
    thread = forum_get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    branch_id = str(thread.get("branch_id") or "").strip()
    uid = str(user.get("user_id") or "").strip()
    owner_match = uid and uid == str(thread.get("created_by_user_id") or "").strip()
    if not (_can_moderate_for_branch(user, branch_id) or owner_match):
        raise HTTPException(status_code=403, detail="Нет прав на редактирование темы.")
    title = str(payload.title or "").strip()
    content = str(payload.content or "").strip()
    if len(title) < 5:
        raise HTTPException(status_code=400, detail="Заголовок слишком короткий.")
    if len(content) < 5:
        raise HTTPException(status_code=400, detail="Текст темы слишком короткий.")
    item = forum_update_thread(thread_id=thread_id, title=title, content=content)
    if not item:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    log_audit_event(
        action="forum.thread.edit.save",
        target_type="forum_thread",
        target_id=thread_id,
        actor_user_id=str(user.get("user_id") or ""),
        actor_role=str(user.get("role") or "user"),
        metadata={"branch_id": branch_id, "title": title[:120]},
    )
    return {"ok": True, "item": item}


@router.post("/user/forum/threads/{thread_id}/edit")
async def user_forum_thread_edit_post(thread_id: str, payload: ForumThreadUpdate, user: dict = Depends(_get_current_user)):
    return await user_forum_thread_patch(thread_id, payload, user)


@router.delete("/user/forum/threads/{thread_id}")
async def user_forum_thread_delete(thread_id: str, user: dict = Depends(_get_current_user)):
    thread = forum_get_thread(thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    branch_id = str(thread.get("branch_id") or "").strip()
    uid = str(user.get("user_id") or "").strip()
    owner_match = uid and uid == str(thread.get("created_by_user_id") or "").strip()
    if not (_can_moderate_for_branch(user, branch_id) or owner_match):
        raise HTTPException(status_code=403, detail="Нет прав на удаление темы.")
    ok = forum_delete_thread(thread_id=thread_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    log_audit_event(
        action="forum.thread.delete",
        target_type="forum_thread",
        target_id=thread_id,
        actor_user_id=str(user.get("user_id") or ""),
        actor_role=str(user.get("role") or "user"),
        metadata={"branch_id": branch_id},
    )
    return {"ok": True, "removed": thread_id}


@router.patch("/user/forum/comments/{comment_id}")
async def user_forum_comment_patch(comment_id: str, payload: ForumCommentUpdate, user: dict = Depends(_get_current_user)):
    comment = forum_get_comment(comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден.")
    branch_id = str(comment.get("branch_id") or "").strip()
    uid = str(user.get("user_id") or "").strip()
    owner_match = uid and uid == str(comment.get("created_by_user_id") or "").strip()
    if not (_can_moderate_for_branch(user, branch_id) or owner_match):
        raise HTTPException(status_code=403, detail="Нет прав на редактирование комментария.")
    content = str(payload.content or "").strip()
    if len(content) < 2:
        raise HTTPException(status_code=400, detail="Комментарий слишком короткий.")
    item = forum_update_comment(comment_id=comment_id, content=content)
    if not item:
        raise HTTPException(status_code=404, detail="Комментарий не найден.")
    log_audit_event(
        action="forum.comment.edit.save",
        target_type="forum_comment",
        target_id=comment_id,
        actor_user_id=str(user.get("user_id") or ""),
        actor_role=str(user.get("role") or "user"),
        metadata={"thread_id": str(comment.get("thread_id") or "")},
    )
    return {"ok": True, "item": item}


@router.post("/user/forum/comments/{comment_id}/edit")
async def user_forum_comment_edit_post(comment_id: str, payload: ForumCommentUpdate, user: dict = Depends(_get_current_user)):
    return await user_forum_comment_patch(comment_id, payload, user)


@router.delete("/user/forum/comments/{comment_id}")
async def user_forum_comment_delete(comment_id: str, user: dict = Depends(_get_current_user)):
    comment = forum_get_comment(comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден.")
    branch_id = str(comment.get("branch_id") or "").strip()
    uid = str(user.get("user_id") or "").strip()
    owner_match = uid and uid == str(comment.get("created_by_user_id") or "").strip()
    if not (_can_moderate_for_branch(user, branch_id) or owner_match):
        raise HTTPException(status_code=403, detail="Нет прав на удаление комментария.")
    ok = forum_delete_comment(comment_id=comment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Комментарий не найден.")
    log_audit_event(
        action="forum.comment.delete",
        target_type="forum_comment",
        target_id=comment_id,
        actor_user_id=str(user.get("user_id") or ""),
        actor_role=str(user.get("role") or "user"),
        metadata={"thread_id": str(comment.get("thread_id") or "")},
    )
    return {"ok": True, "removed": comment_id}


@router.get("/user/forum/moderation/comments")
async def user_forum_moderation_comments_get(
    branch_id: str = Query(..., min_length=1),
    status: str = Query(default="approved"),
    limit: int = Query(default=300, ge=1, le=1000),
    user: dict = Depends(_get_current_user),
):
    if not _can_moderate_for_branch(user, branch_id):
        raise HTTPException(status_code=403, detail="Нет прав модерации для этой ветки.")
    items = forum_list_comments_for_moderation(
        status=status,
        branch_id=branch_id,
        limit=limit,
    )
    return {"total": len(items), "items": items}


@router.patch("/user/forum/moderation/comments/{comment_id}")
async def user_forum_moderation_comment_patch(
    comment_id: str,
    payload: ForumCommentModerationUpdate,
    user: dict = Depends(_get_current_user),
):
    status = str(payload.status or "").strip().lower()
    if status not in {"approved", "hidden", "rejected"}:
        raise HTTPException(status_code=400, detail="status должен быть: approved, hidden или rejected.")
    comment = forum_get_comment(comment_id)
    if not comment:
        raise HTTPException(status_code=404, detail="Комментарий не найден.")
    branch_id = str(comment.get("branch_id") or "").strip()
    if not _can_moderate_for_branch(user, branch_id):
        raise HTTPException(status_code=403, detail="Нет прав модерации для этой ветки.")
    item = forum_moderate_comment(
        comment_id=comment_id,
        status=status,
        moderation_note=str(payload.moderation_note or "").strip(),
        moderated_by=str(user.get("user_id") or "").strip(),
    )
    if not item:
        raise HTTPException(status_code=404, detail="Комментарий не найден.")
    return {"ok": True, "item": item}


@router.post("/user/forum/moderation/propose-for-knowledge")
async def user_forum_moderation_propose_for_knowledge(
    payload: ForumProposeKnowledgePayload,
    user: dict = Depends(_get_current_user),
):
    """
    Тематический модератор или админ отправляет снимок темы (и при необходимости одного комментария)
    в `/review/learning-candidates`. Автозахвата нет — только явное действие, с дедупом.
    """
    from app.services.forum_knowledge_capture import propose_forum_content_for_knowledge

    thread = forum_get_thread(str(payload.thread_id or "").strip())
    if not thread:
        raise HTTPException(status_code=404, detail="Тема не найдена.")
    branch_id = str(thread.get("branch_id") or "").strip()
    if not _can_moderate_for_branch(user, branch_id):
        raise HTTPException(status_code=403, detail="Нет прав модерации для этой ветки.")

    out = propose_forum_content_for_knowledge(
        thread_id=str(payload.thread_id or "").strip(),
        comment_id=str(payload.comment_id or "").strip() or None,
        proposed_by_user_id=str(user.get("user_id") or ""),
        moderator_note=str(payload.moderator_note or ""),
    )
    if not out.get("ok"):
        reason = str(out.get("reason") or "failed")
        if reason == "thread_not_found":
            raise HTTPException(status_code=404, detail="Тема не найдена.")
        if reason in {"comment_not_found", "comment_thread_mismatch", "comment_branch_mismatch"}:
            raise HTTPException(status_code=404, detail="Комментарий не найден или не относится к теме.")
        if reason in {"thread_not_approved", "comment_not_approved"}:
            raise HTTPException(status_code=400, detail="Можно предлагать только одобренный контент.")
        if reason == "content_too_short":
            mc = out.get("min_chars")
            raise HTTPException(
                status_code=400,
                detail=f"Слишком мало текста для снимка (минимум {mc} символов).",
            )
        if reason == "already_queued_or_promoted":
            raise HTTPException(
                status_code=409,
                detail="Этот материал уже в очереди на ревью или ранее принят (отклоните запись в flywheel, чтобы поставить снова).",
            )
        raise HTTPException(status_code=400, detail=reason)
    return out


@router.get("/admin/forum/branches")
async def admin_forum_branches_get(
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=2000),
    _: dict = Depends(_require_admin),
):
    return await user_forum_branches_get(q=q, limit=limit)


class ForumRulesUpdate(BaseModel):
    rules_markdown: str


@router.get("/admin/forum/governance")
async def admin_forum_governance_get(admin_user: dict = Depends(_require_admin)):
    gov = _read_forum_governance()
    if not gov.get("owner_user_id"):
        gov["owner_user_id"] = str(admin_user.get("user_id") or "").strip()
        _write_forum_governance(gov)
    return {
        "owner_user_id": str(gov.get("owner_user_id") or ""),
        "is_owner": str(gov.get("owner_user_id") or "") == str(admin_user.get("user_id") or ""),
        "rules_markdown": str(gov.get("rules_markdown") or _FORUM_DEFAULT_RULES),
        "thematic_admins": list(gov.get("thematic_admins") or []),
    }


@router.patch("/admin/forum/governance/rules")
async def admin_forum_governance_rules_patch(payload: ForumRulesUpdate, admin_user: dict = Depends(_require_admin)):
    gov = _require_forum_owner(admin_user)
    rules = str(payload.rules_markdown or "").strip()
    if not rules:
        raise HTTPException(status_code=400, detail="Текст правил не может быть пустым.")
    gov["rules_markdown"] = rules
    gov["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_forum_governance(gov)
    return {"ok": True, "rules_markdown": rules}


class ForumThematicAdminUpsert(BaseModel):
    branch_id: str
    user_id: str
    status: Optional[str] = "approved"  # approved | probation | revoked
    note: Optional[str] = ""


@router.post("/admin/forum/governance/thematic-admins")
async def admin_forum_thematic_admin_upsert(payload: ForumThematicAdminUpsert, admin_user: dict = Depends(_require_admin)):
    gov = _require_forum_owner(admin_user)
    branch_id = str(payload.branch_id or "").strip()
    target_user_id = str(payload.user_id or "").strip()
    if not branch_id or not target_user_id:
        raise HTTPException(status_code=400, detail="Укажите branch_id и user_id.")

    normalized_status = str(payload.status or "approved").strip().lower()
    if normalized_status not in {"approved", "probation", "revoked"}:
        raise HTTPException(status_code=400, detail="status должен быть: approved, probation или revoked.")

    branch_title = ""
    for b in _forum_branch_items():
        if str(b.get("id") or "") == branch_id:
            branch_title = str(b.get("title") or "").strip()
            break
    if not branch_title:
        raise HTTPException(status_code=404, detail="Ветка форума не найдена.")

    accounts = list_accounts()
    account = None
    for it in accounts:
        if str((it or {}).get("id") or "").strip() == target_user_id:
            account = it
            break
    if not account:
        raise HTTPException(status_code=404, detail="Пользователь не найден.")

    now_iso = datetime.now(timezone.utc).isoformat()
    rows = [x for x in (gov.get("thematic_admins") or []) if isinstance(x, dict)]
    existing_idx = -1
    for idx, row in enumerate(rows):
        if str(row.get("branch_id") or "") == branch_id and str(row.get("user_id") or "") == target_user_id:
            existing_idx = idx
            break

    record = {
        "id": str(uuid.uuid4()),
        "branch_id": branch_id,
        "branch_title": branch_title,
        "user_id": target_user_id,
        "user_login": str(account.get("login") or "").strip(),
        "user_name": str(account.get("name") or "").strip(),
        "status": normalized_status,
        "note": str(payload.note or "").strip(),
        "assigned_by": str(admin_user.get("user_id") or "").strip(),
        "approved_by": str(admin_user.get("user_id") or "").strip(),
        "created_at": now_iso,
        "updated_at": now_iso,
    }
    if existing_idx >= 0:
        prev = rows[existing_idx]
        record["id"] = str(prev.get("id") or record["id"])
        record["created_at"] = str(prev.get("created_at") or now_iso)
        rows[existing_idx] = record
    else:
        rows.append(record)

    gov["thematic_admins"] = rows
    gov["updated_at"] = now_iso
    _write_forum_governance(gov)
    return {"ok": True, "item": record, "total": len(rows)}


@router.delete("/admin/forum/governance/thematic-admins/{assignment_id}")
async def admin_forum_thematic_admin_delete(assignment_id: str, admin_user: dict = Depends(_require_admin)):
    gov = _require_forum_owner(admin_user)
    key = str(assignment_id or "").strip()
    rows = [x for x in (gov.get("thematic_admins") or []) if isinstance(x, dict)]
    next_rows = [x for x in rows if str(x.get("id") or "").strip() != key]
    if len(next_rows) == len(rows):
        raise HTTPException(status_code=404, detail="Назначение не найдено.")
    gov["thematic_admins"] = next_rows
    gov["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_forum_governance(gov)
    return {"ok": True, "removed": assignment_id, "total": len(next_rows)}


@router.get("/user/news/portal")
async def user_news_portal_get(
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
):
    items = _merged_news_items()
    query = (q or "").strip().lower()
    if query:
        def _match(item: dict[str, Any]) -> bool:
            hay = " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("category") or ""),
                    str(item.get("summary") or ""),
                    str(item.get("content") or ""),
                    " ".join(str(x or "") for x in (item.get("tags") or [])),
                ]
            ).lower()
            return query in hay

        items = [x for x in items if _match(x)]
    return {"total": len(items), "items": items[:limit]}


@router.get("/admin/news/items")
async def admin_news_items_get(
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=500, ge=1, le=2000),
    _: dict = Depends(_get_current_user),
):
    return await user_news_portal_get(q=q, limit=limit)


@router.post("/admin/news/items")
async def admin_news_item_create(payload: NewsItemUpsert, admin_user: dict = Depends(_get_current_user)):
    title = str(payload.title or "").strip()
    summary = str(payload.summary or "").strip()
    if len(title) < 4:
        raise HTTPException(status_code=400, detail="Слишком короткий заголовок новости.")
    if len(summary) < 8:
        raise HTTPException(status_code=400, detail="Слишком короткий анонс новости.")
    item = news_upsert_item(
        news_id=None,
        title=title,
        category=str(payload.category or "Новости").strip(),
        summary=summary,
        content=str(payload.content or "").strip(),
        tags=list(payload.tags or []),
        published_at=str(payload.published_at or datetime.now(timezone.utc).date().isoformat()).strip(),
        source_url=str(payload.source_url or "").strip(),
        source_name=str(payload.source_name or "").strip(),
        updated_by=str(admin_user.get("user_id") or "").strip(),
    )
    log_audit_event(
        action="news.item.create.save",
        target_type="news_item",
        target_id=str(item.get("id") or ""),
        actor_user_id=str(admin_user.get("user_id") or ""),
        actor_role=str(admin_user.get("role") or "user"),
        metadata={"title": str(item.get("title") or "")[:120], "source_url": str(item.get("source_url") or "")[:500]},
    )
    return {"ok": True, "item": item}


@router.patch("/admin/news/items/{news_id}")
async def admin_news_item_patch(news_id: str, payload: NewsItemUpsert, admin_user: dict = Depends(_get_current_user)):
    title = str(payload.title or "").strip()
    summary = str(payload.summary or "").strip()
    if len(title) < 4:
        raise HTTPException(status_code=400, detail="Слишком короткий заголовок новости.")
    if len(summary) < 8:
        raise HTTPException(status_code=400, detail="Слишком короткий анонс новости.")
    item = news_upsert_item(
        news_id=news_id,
        title=title,
        category=str(payload.category or "Новости").strip(),
        summary=summary,
        content=str(payload.content or "").strip(),
        tags=list(payload.tags or []),
        published_at=str(payload.published_at or datetime.now(timezone.utc).date().isoformat()).strip(),
        source_url=str(payload.source_url or "").strip(),
        source_name=str(payload.source_name or "").strip(),
        updated_by=str(admin_user.get("user_id") or "").strip(),
    )
    log_audit_event(
        action="news.item.edit.save",
        target_type="news_item",
        target_id=news_id,
        actor_user_id=str(admin_user.get("user_id") or ""),
        actor_role=str(admin_user.get("role") or "user"),
        metadata={"title": str(item.get("title") or "")[:120], "source_url": str(item.get("source_url") or "")[:500]},
    )
    return {"ok": True, "item": item}


@router.delete("/admin/news/items/{news_id}")
async def admin_news_item_delete(news_id: str, _: dict = Depends(_get_current_user)):
    ok = news_delete_item(news_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Новость не найдена в пользовательском каталоге.")
    log_audit_event(
        action="news.item.delete",
        target_type="news_item",
        target_id=news_id,
        actor_user_id=str(_.get("user_id") or ""),
        actor_role=str(_.get("role") or "user"),
    )
    return {"ok": True, "removed": news_id}
