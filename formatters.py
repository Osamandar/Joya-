from datetime import datetime
from aiogram.types import Message
from config import DEVELOPER_CHAT_ID
from google_sheets import ADMIN_ROLE_ADMIN, ADMIN_ROLE_OWNER

ADMIN_ROLE_LABELS = {
    ADMIN_ROLE_ADMIN: "админ",
    ADMIN_ROLE_OWNER: "владелец",
}


def fmt_date(iso_str: str) -> str:
    """Converts YYYY-MM-DD (storage) → DD-MM-YYYY (display)."""
    if not iso_str:
        return iso_str
    try:
        return datetime.strptime(iso_str, "%Y-%m-%d").strftime("%d-%m-%Y")
    except ValueError:
        return iso_str


def pd_consent_value() -> str:
    return f"да {datetime.now().strftime('%Y-%m-%d')}"


def admin_role_label(role: str) -> str:
    return ADMIN_ROLE_LABELS.get(role, role or "—")


def user_display_name(message: Message) -> str:
    return message.from_user.full_name or "Без имени"


def user_username(message: Message) -> str:
    return message.from_user.username or ""


def actor_identity(message: Message) -> str:
    username = f" @{message.from_user.username}" if message.from_user.username else ""
    return f"{message.from_user.id}{username}"


def admin_status_text(admin: dict | None, user_id: int) -> str:
    if DEVELOPER_CHAT_ID and user_id == DEVELOPER_CHAT_ID:
        return "активен (владелец через .env)"
    if not admin:
        return "доступ не выдан"
    if admin["state"] == "pending":
        return "заявка ожидает подтверждения"
    if admin["state"] == "inactive":
        return "доступ отключен"
    return f"активен ({admin_role_label(admin['role'])})"


def admin_card(admin: dict) -> str:
    username = f"@{admin['username']}" if admin.get("username") else "—"
    subdivision = admin.get("subdivision") or "все подразделения"
    request_date = admin.get("requested_at") or "—"
    grant_date = admin.get("granted_at") or "—"
    return (
        f"{admin['chat_id']} | {admin.get('fio') or '—'}\n"
        f"Username: {username}\n"
        f"Роль: {admin_role_label(admin['role'])}\n"
        f"Подразделение: {subdivision}\n"
        f"Статус: {admin_status_text(admin, admin['chat_id'])}\n"
        f"Дата запроса: {request_date}\n"
        f"Дата выдачи: {grant_date}"
    )


def employee_status_text(employee: dict) -> str:
    expiry_str = (employee.get("Дата окончания") or "").strip()
    status_marker = (employee.get("Статус уведомлений") or "").strip().lower()
    if status_marker == "в процессе":
        return "🟡 В процессе"
    if not expiry_str:
        return "❓ Дата не указана"
    try:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except ValueError:
        return f"❓ Некорректная дата: {expiry_str}"
    delta = (expiry - datetime.now().date()).days
    if delta < 0:
        return f"🔴 Просрочена на {abs(delta)} дн."
    if delta == 0:
        return "🔴 Истекает сегодня"
    if delta == 1:
        return "🟠 Истекает завтра"
    if delta <= 7:
        return f"🟠 Истекает через {delta} дн."
    return f"✅ Активна (до {fmt_date(expiry_str)})"


def employee_card(employee: dict) -> str:
    fio = employee.get("ФИО") or "—"
    phone = employee.get("Телефон") or "—"
    position = employee.get("Должность") or "—"
    expiry = fmt_date(employee.get("Дата окончания") or "") or "—"
    chat_id = employee.get("Chat ID") or "—"
    sub = employee.get("Подразделение") or "—"
    in_main = employee.get("В главной группе") or "—"
    in_sub = employee.get("В группе подразделения") or "—"
    status = employee_status_text(employee)
    return (
        f"👤 {fio}\n"
        f"📱 Телефон: {phone}\n"
        f"💼 Должность: {position}\n"
        f"🏢 Подразделение: {sub}\n"
        f"📅 Дата окончания: {expiry}\n"
        f"Статус: {status}\n"
        f"Chat ID: {chat_id}\n"
        f"В главной группе: {in_main}\n"
        f"В группе подразделения: {in_sub}"
    )
