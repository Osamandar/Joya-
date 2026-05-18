from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import re

from commands import set_user_commands

from google_sheets import (
    ADMIN_ROLE_ADMIN,
    ADMIN_ROLE_OWNER,
    find_employee_by_fio_phone,
    find_employee_by_chat_id,
    find_employee_by_phone,
    create_or_update_admin_request,
    approve_admin_access,
    get_admin_record,
    get_admin_rows,
    search_employees,
    get_cell,
    get_employee_row_dict,
    get_employee_rows,
    get_subdivision_names,
    get_all_employees,
    add_employee_row,
    clear_employee_status,
    complete_employee_registration,
    get_notification_admin_ids,
    get_owner_admin_ids,
    has_admin_access,
    has_owner_access,
    revoke_admin_access,
    set_employee_status,
    set_row_default,
    set_row_red,
    update_employee_cell,
)
from config import (
    COL_EXPIRY,
    COL_IN_MAIN,
    COL_IN_SUB,
    COL_PHONE,
    COL_POSITION,
    COL_CHAT_ID,
    DEVELOPER_CHAT_ID,
    COL_STATUS,
    COL_SUBDIVISION,
    POSITIONS,
    POSITION_TO_SUBDIVISION,
    PD_CONSENT_TEXT,
)

router = Router()

CONSENT_YES = "✅ Согласен на обработку ПДн"
CONSENT_NO = "❌ Не согласен"


class Registration(StatesGroup):
    waiting_consent = State()
    waiting_fio = State()
    waiting_phone = State()
    waiting_position = State()
    waiting_subdivision = State()


EDIT_FIELD_ALIASES = {
    "date": "expiry",
    "expiry": "expiry",
    "дата": "expiry",
    "срок": "expiry",
    "position": "position",
    "должность": "position",
    "subdivision": "subdivision",
    "подразделение": "subdivision",
    "main": "main_group",
    "главная": "main_group",
    "maingroup": "main_group",
    "sub": "sub_group",
    "subgroup": "sub_group",
    "группа": "sub_group",
    "подгруппа": "sub_group",
    "phone": "phone",
    "телефон": "phone",
}
ADMIN_ROLE_ALIASES = {
    "admin": ADMIN_ROLE_ADMIN,
    "админ": ADMIN_ROLE_ADMIN,
    "owner": ADMIN_ROLE_OWNER,
    "владелец": ADMIN_ROLE_OWNER,
}
ADMIN_ROLE_LABELS = {
    ADMIN_ROLE_ADMIN: "админ",
    ADMIN_ROLE_OWNER: "владелец",
}


def consent_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CONSENT_YES)], [KeyboardButton(text=CONSENT_NO)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📱 Отправить номер из Telegram", request_contact=True)],
        ],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def position_keyboard() -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=p)] for p in POSITIONS]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


def subdivision_keyboard(names: list[str]) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=name)] for name in names]
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, one_time_keyboard=True)


# --- Admin panel: keyboards and simple dialog states ---
class AdminActions(StatesGroup):
    waiting_check = State()
    waiting_edit = State()
    waiting_approve = State()
    waiting_revoke = State()


def get_admin_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Статус"), KeyboardButton(text="📋 Список на 7 дней")],
            [KeyboardButton(text="🔍 Проверить"), KeyboardButton(text="✏️ Редактировать")],
            [KeyboardButton(text="❌ Закрыть меню")],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )


def get_owner_keyboard() -> ReplyKeyboardMarkup:
    kb = get_admin_keyboard()
    kb.keyboard.insert(
        2, [KeyboardButton(text="👥 Администраторы"), KeyboardButton(text="✔️ Одобрить")]
    )
    kb.keyboard.insert(3, [KeyboardButton(text="🚫 Отозвать"), KeyboardButton(text="❌ Закрыть меню")])
    return kb


@router.message(F.text.startswith("/admin_panel"))
async def cmd_admin_panel(message: Message, state: FSMContext):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав для панели администратора.")
        return

    kb = get_owner_keyboard() if is_owner_user(message.from_user.id) else get_admin_keyboard()
    await state.clear()
    await message.answer("Панель администратора — выберите действие:", reply_markup=kb)


@router.message(F.text == "❌ Закрыть меню")
async def btn_close_menu(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Меню закрыто.", reply_markup=ReplyKeyboardRemove())


@router.message(F.text == "📊 Статус")
async def btn_status(message: Message):
    await cmd_status(message)


@router.message(F.text == "📋 Список на 7 дней")
async def btn_list_7(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав.")
        return

    from datetime import timedelta

    days = 7
    today = datetime.now().date()
    cutoff_date = today + timedelta(days=days)
    employees = get_all_employees()
    expiring = []
    for e in employees:
        try:
            expiry = datetime.strptime(e.get("Дата окончания", ""), "%Y-%m-%d").date()
            if today <= expiry <= cutoff_date:
                expiring.append(e)
        except Exception:
            continue
    if not expiring:
        await message.answer(f"Нет сотрудников с окончанием в течение {days} дн.")
    else:
        reply = "\n".join(
            [
                f"{e['ФИО']} ({e.get('Должность') or '—'}, {e.get('Подразделение') or '—'}) - {fmt_date(e['Дата окончания'])}"
                for e in expiring
            ]
        )
        await message.answer(reply)


@router.message(F.text == "🔍 Проверить")
async def btn_start_check(message: Message, state: FSMContext):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return
    await state.set_state(AdminActions.waiting_check)
    await message.answer("Введите ФИО или телефон для поиска:", reply_markup=ReplyKeyboardRemove())


@router.message(AdminActions.waiting_check)
async def action_check(message: Message, state: FSMContext):
    query = (message.text or "").strip()
    if not query:
        await message.answer("Пустой запрос. Введите ФИО или телефон.")
        return
    found = search_employees(query.lower())
    if not found:
        await message.answer("Сотрудник не найден.")
    else:
        if len(found) > 5:
            await message.answer("Найдено слишком много совпадений. Уточните ФИО или добавьте номер телефона.")
            await state.clear()
            await message.answer("Возвращаю в меню.", reply_markup=get_owner_keyboard() if is_owner_user(message.from_user.id) else get_admin_keyboard())
            return
        await message.answer("\n\n".join(employee_card(emp) for emp in found))

    await state.clear()
    kb = get_owner_keyboard() if is_owner_user(message.from_user.id) else get_admin_keyboard()
    await message.answer("Выберите действие:", reply_markup=kb)


@router.message(F.text == "✏️ Редактировать")
async def btn_start_edit(message: Message, state: FSMContext):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return
    await state.set_state(AdminActions.waiting_edit)
    await message.answer(
        "Введите изменение в формате: поле | ФИО или телефон | значение\n"
        "Примеры:\n"
        "дата | Иванов Иван | 31-12-2026\n"
        "телефон | Иванов Иван | +79161234567",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AdminActions.waiting_edit)
async def action_edit(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) != 3 or not all(parts):
        await message.answer("Нужен формат: поле | поиск | значение")
        return

    field = resolve_edit_field(parts[0])
    if not field:
        await message.answer("Неизвестное поле. Доступно: дата, телефон, должность, подразделение, главная, подгруппа.")
        return

    employee, error_text = find_single_employee(parts[1])
    if error_text:
        await message.answer(error_text)
        return

    assert employee is not None
    edit_error = _apply_employee_edit(employee["row_number"], field, parts[2])
    if edit_error:
        await message.answer(edit_error)
        return

    await message.answer("Данные сотрудника обновлены:\n\n" + employee_card(get_employee_row_dict(employee["row_number"])))
    await state.clear()
    kb = get_owner_keyboard() if is_owner_user(message.from_user.id) else get_admin_keyboard()
    await message.answer("Возвращаю в меню:", reply_markup=kb)


@router.message(F.text == "👥 Администраторы")
async def btn_admins(message: Message):
    await cmd_admins(message)


@router.message(F.text == "✔️ Одобрить")
async def btn_start_approve(message: Message, state: FSMContext):
    if not is_owner_user(message.from_user.id):
        await message.answer("Только владелец может выдавать доступ.")
        return
    await state.set_state(AdminActions.waiting_approve)
    await message.answer("Введите Chat ID и опционально роль (admin/owner), например:\n123456789 owner", reply_markup=ReplyKeyboardRemove())


@router.message(AdminActions.waiting_approve)
async def action_approve(message: Message, state: FSMContext):
    raw = (message.text or "").strip()
    parts = raw.split()
    if len(parts) not in {1, 2}:
        await message.answer("Нужно: ChatID [role]. Пример: 123456789 owner")
        return
    chat_id_raw = parts[0].strip()
    if not chat_id_raw.lstrip("-").isdigit():
        await message.answer("Chat ID должен быть числом.")
        return
    role = ADMIN_ROLE_ADMIN
    if len(parts) == 2:
        role = resolve_admin_role(parts[1]) or ""
        if not role:
            await message.answer("Роль должна быть admin или owner.")
            return
    target_chat_id = int(chat_id_raw)
    admin = approve_admin_access(chat_id=target_chat_id, granted_by=actor_identity(message), role=role)
    await set_user_commands(message.bot, target_chat_id, admin["role"])
    await message.answer(f"Доступ выдан.\n\n{admin_card(admin)}")
    try:
        kb = get_owner_keyboard() if admin["role"] == ADMIN_ROLE_OWNER else get_admin_keyboard()
        await message.bot.send_message(
            target_chat_id,
            "Вам выдан админ-доступ в боте.\n"
            f"Роль: {admin_role_label(admin['role'])}\n"
            "Нажмите / чтобы увидеть доступные команды.",
            reply_markup=kb,
        )
    except Exception:
        pass
    await state.clear()
    await message.answer("Возвращаю в меню.", reply_markup=get_owner_keyboard())


@router.message(F.text == "🚫 Отозвать")
async def btn_start_revoke(message: Message, state: FSMContext):
    if not is_owner_user(message.from_user.id):
        await message.answer("Только владелец может отзывать админ-доступ.")
        return
    await state.set_state(AdminActions.waiting_revoke)
    await message.answer("Введите Chat ID администратора для отзыва:", reply_markup=ReplyKeyboardRemove())


@router.message(AdminActions.waiting_revoke)
async def action_revoke(message: Message, state: FSMContext):
    chat_id_raw = (message.text or "").strip()
    if not chat_id_raw.lstrip("-").isdigit():
        await message.answer("Chat ID должен быть числом.")
        return
    target_chat_id = int(chat_id_raw)
    if DEVELOPER_CHAT_ID and target_chat_id == DEVELOPER_CHAT_ID:
        await message.answer("Основного владельца из .env отключить этой командой нельзя.")
        return
    admin = revoke_admin_access(target_chat_id)
    if not admin:
        await message.answer("Админ с таким Chat ID не найден.")
        await state.clear()
        await message.answer("Возвращаю в меню.", reply_markup=get_owner_keyboard())
        return
    await set_user_commands(message.bot, target_chat_id, "default")
    await message.answer(f"Доступ отключен.\n\n{admin_card(admin)}")
    try:
        await message.bot.send_message(target_chat_id, "Ваш админ-доступ в боте отключён.")
    except Exception:
        pass
    await state.clear()
    await message.answer("Возвращаю в меню.", reply_markup=get_owner_keyboard())


# --- end admin panel additions ---

def normalize_phone_input(phone_raw: str) -> str | None:
    phone_clean = re.sub(r"[^\d+]", "", phone_raw.strip())
    if re.match(r"^\+7\d{10}$", phone_clean):
        return phone_clean
    digits = re.sub(r"\D", "", phone_raw)
    if len(digits) == 11 and digits.startswith("8"):
        return f"+7{digits[1:]}"
    if len(digits) == 11 and digits.startswith("7"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+7{digits}"
    return None


def resolve_subdivision(position: str) -> str | None:
    sub = POSITION_TO_SUBDIVISION.get(position, "").strip()
    active = get_subdivision_names()
    if sub and sub in active:
        return sub
    return None


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


def is_admin_user(user_id: int) -> bool:
    return has_admin_access(user_id)


def is_owner_user(user_id: int) -> bool:
    return has_owner_access(user_id)


def parse_yes_no(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized in {"да", "yes", "y", "1", "true"}:
        return "да"
    if normalized in {"нет", "no", "n", "0", "false"}:
        return "нет"
    return None


def resolve_edit_field(raw_field: str) -> str | None:
    return EDIT_FIELD_ALIASES.get(raw_field.strip().lower())


def resolve_admin_role(raw_role: str) -> str | None:
    return ADMIN_ROLE_ALIASES.get(raw_role.strip().lower())


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
    if not expiry_str:
        return "дата не указана"
    try:
        expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
    except ValueError:
        return f"некорректная дата: {expiry_str}"

    delta = (expiry - datetime.now().date()).days
    if status_marker == "expired" or delta < 0:
        if delta < 0:
            return f"просрочена на {abs(delta)} дн."
        return "истекает сегодня"
    if delta == 0:
        return "истекает сегодня"
    if delta == 1:
        return "истекает завтра"
    return f"истекает через {delta} дн."


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
    service_status = employee.get("Статус уведомлений") or "—"
    return (
        f"{fio}\n"
        f"Телефон: {phone}\n"
        f"Должность: {position}\n"
        f"Подразделение: {sub}\n"
        f"Дата окончания: {expiry}\n"
        f"Статус: {status}\n"
        f"Chat ID: {chat_id}\n"
        f"В главной группе: {in_main}\n"
        f"В группе подразделения: {in_sub}\n"
        f"Служебный статус: {service_status}"
    )


def find_single_employee(query: str) -> tuple[dict | None, str | None]:
    matches = search_employees(query)
    if not matches:
        return None, "Сотрудник не найден."
    if len(matches) > 1:
        lines = [
            f"{emp['ФИО']} | {emp.get('Телефон') or '—'} | {emp.get('Должность') or '—'}"
            for emp in matches[:10]
        ]
        suffix = ""
        if len(matches) > 10:
            suffix = f"\n\nНайдено {len(matches)} совпадений. Уточните ФИО или номер телефона."
        return None, "Найдено несколько сотрудников:\n" + "\n".join(lines) + suffix
    return matches[0], None


def _apply_employee_edit(row_number: int, field: str, new_value: str) -> str | None:
    """Applies one field update. Returns an error string if validation fails, None on success."""
    if field == "expiry":
        try:
            expiry_date = datetime.strptime(new_value, "%d-%m-%Y").date()
        except ValueError:
            return "Дата должна быть в формате ДД-ММ-ГГГГ, например 31-12-2026."
        update_employee_cell(row_number, COL_EXPIRY, expiry_date.isoformat())
        delta = (expiry_date - datetime.now().date()).days
        if delta <= 0:
            set_row_red(row_number)
            set_employee_status(row_number, "expired")
        else:
            set_row_default(row_number)
            clear_employee_status(row_number)
    elif field == "phone":
        normalized_phone = normalize_phone_input(new_value)
        if not normalized_phone:
            return "Телефон должен быть в формате +79161234567."
        update_employee_cell(row_number, COL_PHONE, normalized_phone)
    elif field == "position":
        update_employee_cell(row_number, COL_POSITION, new_value)
    elif field == "subdivision":
        subdivisions = get_subdivision_names()
        normalized_sub = "" if new_value in {"-", "пусто", "none"} else new_value
        if subdivisions and normalized_sub and normalized_sub not in subdivisions:
            names_text = "\n".join(f"• {name}" for name in subdivisions)
            return f"Такого подразделения нет в листе «Группы». Доступные варианты:\n\n{names_text}"
        update_employee_cell(row_number, COL_SUBDIVISION, normalized_sub)
    elif field == "main_group":
        parsed = parse_yes_no(new_value)
        if not parsed:
            return "Для поля «главная» используй значение да или нет."
        update_employee_cell(row_number, COL_IN_MAIN, parsed)
    elif field == "sub_group":
        parsed = parse_yes_no(new_value)
        if not parsed:
            return "Для поля «подгруппа» используй значение да или нет."
        update_employee_cell(row_number, COL_IN_SUB, parsed)
    return None


async def notify_admins(message: Message, text: str):
    for admin_id in get_notification_admin_ids():
        try:
            await message.bot.send_message(admin_id, text)
        except Exception:
            pass


async def finish_registration(message: Message, state: FSMContext, row_num: int | None, is_new: bool):
    data = await state.get_data()
    fio = data["fio"]
    phone = data["phone"]
    position = data["position"]
    subdivision = data["subdivision"]
    consent = data["consent"]
    chat_id = message.from_user.id

    if is_new:
        add_employee_row(
            fio=fio,
            phone=phone,
            position=position,
            chat_id=chat_id,
            subdivision=subdivision,
            pd_consent=consent,
        )
    else:
        complete_employee_registration(
            row_num,
            chat_id=chat_id,
            position=position,
            subdivision=subdivision,
            pd_consent=consent,
            phone=phone,
        )

    await message.answer(
        "Регистрация завершена!\n\n"
        f"ФИО: {fio}\n"
        f"Телефон: {phone}\n"
        f"Должность: {position}\n"
        f"Подразделение: {subdivision}\n\n"
        "Напоминания о медкнижке начнут приходить после того, как администратор "
        "укажет дату окончания в таблице.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await notify_admins(
        message,
        f"🆕 Новая регистрация:\n{fio}\n{phone}\n{position} — {subdivision}",
    )
    await state.clear()


@router.message(F.text == "/start")
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    if is_admin_user(message.from_user.id):
        kb = get_owner_keyboard() if is_owner_user(message.from_user.id) else get_admin_keyboard()
        await message.answer("Панель администратора — выберите действие:", reply_markup=kb)
        return

    row = find_employee_by_chat_id(message.from_user.id)
    if row:
        fio = get_cell(row, 1)
        pos = get_cell(row, 3)
        sub = get_cell(row, COL_SUBDIVISION) or "—"
        await message.answer(
            f"Вы уже зарегистрированы.\n\n"
            f"ФИО: {fio}\n"
            f"Должность: {pos}\n"
            f"Подразделение: {sub}\n\n"
            "Чтобы изменить данные — обратитесь к администратору.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    await state.set_state(Registration.waiting_consent)
    await message.answer(PD_CONSENT_TEXT, reply_markup=consent_keyboard())


@router.message(Registration.waiting_consent)
async def process_consent(message: Message, state: FSMContext):
    if message.text.strip() != CONSENT_YES:
        await message.answer(
            "Без согласия на обработку персональных данных регистрация невозможна.\n"
            "Если передумаете — снова нажмите /start",
            reply_markup=ReplyKeyboardRemove(),
        )
        await state.clear()
        return

    await state.update_data(consent=pd_consent_value())
    await state.set_state(Registration.waiting_fio)
    await message.answer(
        "Спасибо! Введите ваши ФИО полностью (Фамилия Имя Отчество).",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(Registration.waiting_fio)
async def process_fio(message: Message, state: FSMContext):
    fio = message.text.strip()
    if len(fio.split()) < 2:
        await message.answer("Введите минимум фамилию и имя (два слова).")
        return
    await state.update_data(fio=fio)
    await state.set_state(Registration.waiting_phone)
    await message.answer(
        "Укажите номер телефона.\n\n"
        "Рекомендуем нажать кнопку ниже — номер подставится из Telegram автоматически.\n"
        "Или введите вручную: +79161234567",
        reply_markup=phone_keyboard(),
    )


@router.message(Registration.waiting_phone, F.contact)
async def process_phone_contact(message: Message, state: FSMContext):
    if not message.contact or message.contact.user_id != message.from_user.id:
        await message.answer("Отправьте свой номер через кнопку, а не чужой контакт.")
        return
    phone = normalize_phone_input(message.contact.phone_number or "")
    if not phone:
        await message.answer("Не удалось прочитать номер. Введите вручную: +79161234567")
        return
    await _after_phone(message, state, phone)


@router.message(Registration.waiting_phone)
async def process_phone_text(message: Message, state: FSMContext):
    phone = normalize_phone_input(message.text or "")
    if not phone:
        await message.answer(
            "Неверный формат. Нажмите «Отправить номер из Telegram» или введите +79161234567",
            reply_markup=phone_keyboard(),
        )
        return
    await _after_phone(message, state, phone)


async def _after_phone(message: Message, state: FSMContext, phone: str):
    existing_phone_row = find_employee_by_phone(phone)
    if existing_phone_row:
        existing_chat = get_cell(existing_phone_row, 5)
        if existing_chat and existing_chat != str(message.from_user.id):
            await message.answer(
                "Этот номер уже зарегистрирован на другой аккаунт. Обратитесь к администратору.",
                reply_markup=ReplyKeyboardRemove(),
            )
            await state.clear()
            return

    data = await state.get_data()
    fio = data["fio"]
    pre_row = find_employee_by_fio_phone(fio, phone)

    await state.update_data(phone=phone, pre_row=pre_row)
    await state.set_state(Registration.waiting_position)
    await message.answer(
        "Выберите вашу должность:",
        reply_markup=position_keyboard(),
    )


@router.message(Registration.waiting_position)
async def process_position(message: Message, state: FSMContext):
    position = message.text.strip()
    if position not in POSITIONS:
        await message.answer("Выберите должность кнопкой из списка.", reply_markup=position_keyboard())
        return

    await state.update_data(position=position)
    subdivisions = get_subdivision_names()
    auto_sub = resolve_subdivision(position)

    if auto_sub:
        await state.update_data(subdivision=auto_sub)
        data = await state.get_data()
        await finish_registration(message, state, data.get("pre_row"), is_new=data.get("pre_row") is None)
        return

    if not subdivisions:
        await state.update_data(subdivision="")
        data = await state.get_data()
        await finish_registration(message, state, data.get("pre_row"), is_new=data.get("pre_row") is None)
        return

    await state.set_state(Registration.waiting_subdivision)
    names_text = "\n".join(f"• {n}" for n in subdivisions)
    await message.answer(
        f"Выберите подразделение:\n\n{names_text}",
        reply_markup=subdivision_keyboard(subdivisions),
    )


@router.message(Registration.waiting_subdivision)
async def process_subdivision(message: Message, state: FSMContext):
    choice = message.text.strip()
    subdivisions = get_subdivision_names()
    if choice not in subdivisions:
        names_text = "\n".join(f"• {n}" for n in subdivisions)
        await message.answer(
            f"Выберите подразделение кнопкой:\n\n{names_text}",
            reply_markup=subdivision_keyboard(subdivisions),
        )
        return

    await state.update_data(subdivision=choice)
    data = await state.get_data()
    await finish_registration(message, state, data.get("pre_row"), is_new=data.get("pre_row") is None)


@router.message(F.text == "/whoami")
async def cmd_whoami(message: Message):
    admin = get_admin_record(message.from_user.id)
    username = f"@{message.from_user.username}" if message.from_user.username else "—"
    role = admin_role_label(admin["role"]) if admin else ("владелец" if message.from_user.id == DEVELOPER_CHAT_ID else "—")
    subdivision = admin.get("subdivision") if admin else ""
    await message.answer(
        "Ваш профиль:\n"
        f"Имя: {user_display_name(message)}\n"
        f"Username: {username}\n"
        f"Chat ID: {message.from_user.id}\n"
        f"Доступ: {admin_status_text(admin, message.from_user.id)}\n"
        f"Роль: {role}\n"
        f"Подразделение: {subdivision or '—'}"
    )


@router.message(F.text == "/request_admin")
async def cmd_request_admin(message: Message):
    status = create_or_update_admin_request(
        chat_id=message.from_user.id,
        fio=user_display_name(message),
        username=user_username(message),
    )

    if status == "active":
        await message.answer("У вас уже есть активный админ-доступ.")
        return
    if status == "pending":
        await message.answer("Заявка уже отправлена и ожидает подтверждения.")
        return

    username_text = f"@{message.from_user.username}" if message.from_user.username else "—"
    request_text = (
        "Новая заявка на админ-доступ:\n"
        f"Имя: {user_display_name(message)}\n"
        f"Username: {username_text}\n"
        f"Chat ID: {message.from_user.id}\n\n"
        f"Одобрить: /approve_admin {message.from_user.id}"
    )

    for owner_id in get_owner_admin_ids():
        if owner_id == message.from_user.id:
            continue
        try:
            await message.bot.send_message(owner_id, request_text)
        except Exception:
            pass

    await message.answer(
        "Заявка на админ-доступ отправлена. Когда владелец подтвердит её, вам откроются команды администратора."
    )


@router.message(F.text == "/admins")
async def cmd_admins(message: Message):
    if not is_owner_user(message.from_user.id):
        await message.answer("Только владелец может смотреть список админов.")
        return

    admins = get_admin_rows(with_row_numbers=False)
    active = [admin for admin in admins if admin["state"] == "active"]
    pending = [admin for admin in admins if admin["state"] == "pending"]

    parts = ["Администраторы:"]
    if active:
        parts.append(
            "\nАктивные:\n" + "\n\n".join(admin_card(admin) for admin in active)
        )
    else:
        parts.append("\nАктивные:\nНет активных админов в таблице.")

    if pending:
        parts.append(
            "\nЗаявки:\n" + "\n\n".join(admin_card(admin) for admin in pending)
        )

    await message.answer("\n".join(parts))


@router.message(F.text.startswith("/approve_admin"))
async def cmd_approve_admin(message: Message):
    if not is_owner_user(message.from_user.id):
        await message.answer("Только владелец может выдавать админ-доступ.")
        return

    args = message.text.split()
    if len(args) not in {2, 3}:
        await message.answer(
            "Использование:\n"
            "/approve_admin 123456789\n"
            "/approve_admin 123456789 owner"
        )
        return

    chat_id_raw = args[1].strip()
    if not chat_id_raw.lstrip("-").isdigit():
        await message.answer("Chat ID должен быть числом.")
        return

    role = ADMIN_ROLE_ADMIN
    if len(args) == 3:
        role = resolve_admin_role(args[2]) or ""
        if not role:
            await message.answer("Роль должна быть `admin` или `owner`.")
            return

    target_chat_id = int(chat_id_raw)
    admin = approve_admin_access(
        chat_id=target_chat_id,
        granted_by=actor_identity(message),
        role=role,
    )
    await set_user_commands(message.bot, target_chat_id, admin["role"])
    await message.answer(
        f"Доступ выдан.\n\n{admin_card(admin)}"
    )
    try:
        await message.bot.send_message(
            target_chat_id,
            "Вам выдан админ-доступ в боте.\n"
            f"Роль: {admin_role_label(admin['role'])}\n"
            "Нажмите / чтобы увидеть доступные команды."
        )
    except Exception:
        pass


@router.message(F.text.startswith("/revoke_admin"))
async def cmd_revoke_admin(message: Message):
    if not is_owner_user(message.from_user.id):
        await message.answer("Только владелец может отзывать админ-доступ.")
        return

    args = message.text.split()
    if len(args) != 2:
        await message.answer("Использование: /revoke_admin 123456789")
        return

    chat_id_raw = args[1].strip()
    if not chat_id_raw.lstrip("-").isdigit():
        await message.answer("Chat ID должен быть числом.")
        return

    target_chat_id = int(chat_id_raw)
    if DEVELOPER_CHAT_ID and target_chat_id == DEVELOPER_CHAT_ID:
        await message.answer("Основного владельца из .env отключить этой командой нельзя.")
        return

    admin = revoke_admin_access(target_chat_id)
    if not admin:
        await message.answer("Админ с таким Chat ID не найден.")
        return
    await set_user_commands(message.bot, target_chat_id, "default")
    await message.answer(
        f"Доступ отключен.\n\n{admin_card(admin)}"
    )
    try:
        await message.bot.send_message(
            target_chat_id,
            "Ваш админ-доступ в боте отключён."
        )
    except Exception:
        pass


@router.message(F.text.startswith("/check"))
async def cmd_check(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав для этой команды.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Использование: /check ФИО")
        return
    name = args[1].strip().lower()
    found = search_employees(name)
    if not found:
        await message.answer("Сотрудник не найден.")
    else:
        if len(found) > 5:
            await message.answer(
                "Найдено слишком много совпадений. Уточните ФИО или добавьте номер телефона."
            )
            return
        await message.answer("\n\n".join(employee_card(emp) for emp in found))


@router.message(F.text.startswith("/list"))
async def cmd_list(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав.")
        return

    args = message.text.split()
    days = 7
    if len(args) > 1 and args[1].isdigit():
        days = int(args[1])

    from datetime import timedelta

    today = datetime.now().date()
    cutoff_date = today + timedelta(days=days)
    employees = get_all_employees()
    expiring = []
    for e in employees:
        try:
            expiry = datetime.strptime(e["Дата окончания"], "%Y-%m-%d").date()
            if today <= expiry <= cutoff_date:
                expiring.append(e)
        except Exception:
            continue
    if not expiring:
        await message.answer(f"Нет сотрудников с окончанием в течение {days} дн.")
    else:
        reply = "\n".join(
            [
                f"{e['ФИО']} ({e['Должность']}, {e.get('Подразделение') or '—'}) - {fmt_date(e['Дата окончания'])}"
                for e in expiring
            ]
        )
        await message.answer(reply)


@router.message(F.text == "/status")
async def cmd_status(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав.")
        return

    employees = get_employee_rows(include_without_chat=True, require_expiry=False)
    total = len(employees)
    no_chat = 0
    no_expiry = 0
    expired = []
    today = []
    soon_1_3 = []
    soon_4_7 = []

    for employee in employees:
        if not (employee.get("Chat ID") or "").strip():
            no_chat += 1

        expiry_str = (employee.get("Дата окончания") or "").strip()
        if not expiry_str:
            no_expiry += 1
            continue

        try:
            expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date()
        except ValueError:
            continue

        delta = (expiry - datetime.now().date()).days
        line = f"{employee['ФИО']} - {fmt_date(expiry_str)}"
        if delta < 0:
            expired.append(line)
        elif delta == 0:
            today.append(line)
        elif delta <= 3:
            soon_1_3.append(line)
        elif delta <= 7:
            soon_4_7.append(line)

    parts = [
        "Сводка по таблице:",
        f"Всего сотрудников: {total}",
        f"Без Chat ID: {no_chat}",
        f"Без даты окончания: {no_expiry}",
        f"Просрочено: {len(expired)}",
        f"Истекает сегодня: {len(today)}",
        f"Истекает через 1-3 дня: {len(soon_1_3)}",
        f"Истекает через 4-7 дней: {len(soon_4_7)}",
    ]

    if expired:
        parts.append("\nПросрочено:\n" + "\n".join(expired[:10]))
    if today:
        parts.append("\nСегодня:\n" + "\n".join(today[:10]))

    await message.answer("\n".join(parts))


@router.message(F.text.startswith("/edit"))
async def cmd_edit(message: Message):
    if not is_admin_user(message.from_user.id):
        await message.answer("У вас нет прав.")
        return

    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "Использование:\n"
            "/edit дата | Иванов Иван | 31-12-2026\n"
            "/edit телефон | Иванов Иван | +79161234567\n"
            "/edit подразделение | Иванов Иван | Кухня\n"
            "/edit главная | Иванов Иван | нет"
        )
        return

    parts = [part.strip() for part in args[1].split("|")]
    if len(parts) != 3 or not all(parts):
        await message.answer(
            "Нужен формат: /edit поле | поиск | значение\n"
            "Пример: /edit дата | Иванов Иван | 31-12-2026"
        )
        return

    field = resolve_edit_field(parts[0])
    if not field:
        await message.answer(
            "Неизвестное поле. Доступно: дата, телефон, должность, подразделение, главная, подгруппа."
        )
        return

    employee, error_text = find_single_employee(parts[1])
    if error_text:
        await message.answer(error_text)
        return

    assert employee is not None
    edit_error = _apply_employee_edit(employee["row_number"], field, parts[2])
    if edit_error:
        await message.answer(edit_error)
        return

    await message.answer("Данные сотрудника обновлены:\n\n" + employee_card(get_employee_row_dict(employee["row_number"])))
