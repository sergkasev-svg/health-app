"""Live AI: анализ маркеров и симптомов → гипотезы, план, upsell. Premium: генерация PDF и pdf_url."""
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps_auth import get_optional_access_context
from app.database import get_db
from app.models import User
from app.services.auth_models import AccessContext
from app.services.master_engine import run_master_engine
from app.services.multi_lab_engine import run_universal_multi_lab_engine
from app.services.report_service import save_report
from app.services.memory_service import save_analysis_with_memory
from app.services.subscription_service import can_access_premium, get_user_tier
from app.services.final_relevance_gate import apply_analysis_relevance_gate

router = APIRouter(prefix="/api", tags=["ai"])

# Директория для сохранения premium PDF (по ссылке). Fallback: backend/data/reports_pdf
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
REPORTS_PDF_DIR = _BACKEND_DIR / "data" / "reports_pdf"


def add_upsell(result: dict, tier: str) -> dict:
    """Добавляет продающий блок в текст ответа для free tier."""
    if tier == "free":
        text = result.get("text") or ""
        text += (
            "\n\n💡 Вижу, что здесь не один показатель, а система факторов.\n"
            "Могу собрать для вас полный персональный план:\n"
            "- что делать в первую очередь\n"
            "- что убрать, чтобы не мешать восстановлению\n"
            "- как восстановить энергию\n\n"
            "👉 Разблокировать полный план"
        )
        result["text"] = text
    return result


def _get_or_create_db_user(db: Session, ctx: AccessContext) -> Optional[User]:
    """Получить или создать User в БД из AccessContext."""
    if not ctx.user_id or ctx.user_id == "default":
        return None
    user = db.query(User).filter(User.id == int(ctx.user_id) if ctx.user_id.isdigit() else None).first()
    if not user:
        # Создать нового пользователя (без email/password, только ID)
        try:
            user_id_int = int(ctx.user_id) if ctx.user_id.isdigit() else None
            if user_id_int:
                user = User(id=user_id_int)
                db.add(user)
                db.commit()
                db.refresh(user)
        except Exception:
            return None
    return user


@router.post("/ai/analyze")
def analyze(
    payload: dict,
    ctx: AccessContext = Depends(get_optional_access_context),
    db: Session = Depends(get_db),
):
    """Анализ маркеров/симптомов → гипотезы, план, upsell. Сохраняет отчёт в БД если есть user_id.
    Если в payload есть raw_text или lab_markers — используется универсальный multi-lab движок (lipid, CBC, ОАМ, печень, биохимия, органические кислоты)."""
    use_multi_lab = bool(payload.get("raw_text") or (isinstance(payload.get("lab_markers"), dict) and payload.get("lab_markers")))
    if use_multi_lab:
        result = run_universal_multi_lab_engine(payload)
        # Нормальная клиническая структура
        findings = result.get("findings") or []
        tests = result.get("tests") or []
        text = result.get("text") or ""
        # гипотезы — не просто строки, а смысл
        result["hypotheses"] = [
            {
                "id": result.get("report_type", ""),
                "label": f,
                "meaning": "требует клинической оценки в контексте пациента",
            }
            for f in findings[:6]
        ]
        # план — разделяем приоритеты
        result["plan"] = {
            "priority_1": findings[:3],
            "priority_2": findings[3:6],
            "tests": tests[:5],
        }
        # не теряем текст (он продаёт)
        result["text"] = text
    else:
        result = run_master_engine(payload)

    # Final anti-drift check for uploaded analyses before persistence/response.
    try:
        result = apply_analysis_relevance_gate(payload, result)
    except Exception:
        pass

    # Сохранить отчёт в БД если есть пользователь
    user = _get_or_create_db_user(db, ctx)
    if user:
        try:
            save_report(db, user.id, payload, result)
        except Exception:
            pass  # не падаем если сохранение не удалось
        # Memory: история анализов, маркеры и напоминания (для подписки — динамика, «Михаил помнит»)
        try:
            save_analysis_with_memory(
                db=db,
                user_id=user.id,
                payload=payload,
                result=result,
                source_name=payload.get("source_name"),
            )
        except Exception:
            pass

    # Добавить информацию о подписке и блокировку для free
    tier = "free"
    if user:
        tier = get_user_tier(db, user.id)
    if not (user and can_access_premium(db, user.id)):
        # free: показываем только 1 пункт плана, остальное под 🔒
        if "plan" in result:
            result["plan"] = {
                "priority_1": result["plan"].get("priority_1", [])[:1],
                "priority_2": [],
                "tests": [],
            }
        result["locked"] = True
        result["pdf_url"] = None
    else:
        result["locked"] = False
        # Premium: генерируем PDF и отдаём ссылку на скачивание
        try:
            from app.services.pdf_generator import build_premium_pdf_bytes
            REPORTS_PDF_DIR.mkdir(parents=True, exist_ok=True)
            filename = f"{uuid4().hex}.pdf"
            out_path = REPORTS_PDF_DIR / filename
            meta = {
                "date": "",
                "patient": getattr(user, "email", None) or (str(user.id) if user else "—"),
                "title": "За Здоровье - Premium PDF отчёт",
                "subtitle": f"Тип анализа: {result.get('report_type') or 'лабораторный'}",
            }
            pdf_bytes = build_premium_pdf_bytes(result, meta)
            if pdf_bytes:
                out_path.write_bytes(pdf_bytes)
                result["pdf_url"] = f"/api/reports/{filename}"
            else:
                result["pdf_url"] = None
        except Exception:
            result["pdf_url"] = None

    result["tier"] = tier
    result = add_upsell(result, tier)
    return result


@router.get("/reports/{filename}")
def serve_report_pdf(filename: str):
    """Отдаёт сгенерированный premium PDF по имени файла (uuid.pdf). Только безопасные имена."""
    if not filename or ".." in filename or not filename.endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Invalid filename")
    safe = "".join(c for c in filename if c.isalnum() or c in "._-")
    if safe != filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = REPORTS_PDF_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(path, media_type="application/pdf")
