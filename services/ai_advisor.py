import asyncio
from datetime import datetime, date
from typing import List, Optional, Tuple

from loguru import logger
from openai import OpenAI

from config import settings


def _get_openai_client() -> Optional[OpenAI]:
    """Создаём клиента OpenAI/OpenRouter, если задан ключ. Иначе возвращаем None (модуль будет неактивен)."""
    api_key = settings.openai_api_key
    if not api_key:
        logger.warning("OPENAI_API_KEY is not configured; AI advisor is disabled")
        return None
    # Если указан кастомный base_url (например, OpenRouter) — используем его
    if settings.openai_base_url:
        return OpenAI(api_key=api_key, base_url=settings.openai_base_url)
    return OpenAI(api_key=api_key)


# Статический список праздников (минимальный набор для MVP)
class Holiday:
    def __init__(self, month: int, day: int, title: str, tags: Optional[List[str]] = None):
        self.month = month
        self.day = day
        self.title = title
        self.tags = tags or []

    def date_for_year(self, year: int) -> date:
        return date(year, self.month, self.day)


HOLIDAYS: List[Holiday] = [
    # Гос праздники
    Holiday(1, 1, "Новый год"),
    Holiday(2, 23, "День защитника Отечества"),
    Holiday(3, 8, "Международный женский день"),
    Holiday(5, 1, "Праздник Весны и Труда"),
    Holiday(5, 9, "День Победы"),
    Holiday(6, 12, "День России"),
    Holiday(11, 4, "День народного единства"),
    # Отраслевые (примеры)
    Holiday(8, 11, "День строителя (второе воскресенье августа, дата условная)", tags=["строительство"]),
    Holiday(8, 6, "День железнодорожника (первое воскресенье августа, дата условная)", tags=["транспорт", "жд"]),
    Holiday(10, 15, "День работника дорожного хозяйства (третье воскресенье октября, дата условная)", tags=["дороги"]),
]


def get_near_holidays(target: date, window_days: int = 7) -> List[str]:
    """Вернуть список праздников в окне +/- window_days от заданной даты."""
    res: List[str] = []
    year = target.year
    for h in HOLIDAYS:
        h_date = h.date_for_year(year)
        delta = abs((h_date - target).days)
        if delta <= window_days:
            res.append(f"{h.title} ({h_date.strftime('%d.%m')})")
    return res


def safe_float(value: Optional[str]) -> float:
    if not value:
        return 0.0
    try:
        # Убираем пробелы и символы валют, если они есть, но обычно DataNewton шлет чистые числа или строки
        clean = str(value).replace(" ", "").replace("\xa0", "").replace(",", ".")
        return float(clean)
    except ValueError:
        return 0.0


def calculate_financial_analysis(
    revenue_str: Optional[str],
    capital_str: Optional[str],
    debit_str: Optional[str],
    credit_str: Optional[str],
    net_profit_str: Optional[str] = None,
    arbitration_sum_str: Optional[str] = None
) -> str:
    """
    Рассчитать финансовые показатели и вернуть текстовый блок с выводами.
    """
    rev = safe_float(revenue_str) # тыс. руб.
    cap = safe_float(capital_str) # тыс. руб.
    deb = safe_float(debit_str)   # тыс. руб.
    cred = safe_float(credit_str) # тыс. руб.
    net_profit = safe_float(net_profit_str) # тыс. руб.
    
    # Арбитражи обычно возвращаются в рублях, а не тысячах.
    # Если revenue в тысячах, то rev * 1000 = выручка в рублях.
    arb_sum_rub = safe_float(arbitration_sum_str)

    if rev <= 0:
        return "Недостаточно данных по выручке для расчёта фин. показателей."

    # 1. Максимальная сумма гарантии = Выручка годовая / 12
    max_guarantee_th = rev / 12
    
    # ЛОГИКА 1: Если чистая прибыль < 0, лимит режется до 10 млн руб (10,000 тыс)
    profit_warning = ""
    if net_profit_str and net_profit < 0:
        limit_cap_th = 10_000 # 10 млн руб
        if max_guarantee_th > limit_cap_th:
            max_guarantee_th = limit_cap_th
            profit_warning = " (Ограничено до 10 млн ₽ из-за убытка)"

    # Форматирование строки макс гарантии
    if max_guarantee_th >= 1_000_000:
        mg_str = f"{max_guarantee_th / 1_000_000:.1f} млрд ₽{profit_warning}"
    elif max_guarantee_th >= 1_000:
        mg_str = f"{max_guarantee_th / 1_000:.1f} млн ₽{profit_warning}"
    else:
        mg_str = f"{max_guarantee_th:,.0f} тыс. ₽{profit_warning}"

    # 2. Ориентировочный размер лимита = Выручка годовая / 4
    limit_size_th = rev / 4
    
    # Применяем то же ограничение по убытку и к лимиту (логично)
    if net_profit_str and net_profit < 0:
        limit_cap_th = 10_000
        if limit_size_th > limit_cap_th:
            limit_size_th = limit_cap_th

    if limit_size_th >= 1_000_000:
        ls_str = f"{limit_size_th / 1_000_000:.1f} млрд ₽"
    elif limit_size_th >= 1_000:
        ls_str = f"{limit_size_th / 1_000:.1f} млн ₽"
    else:
        ls_str = f"{limit_size_th:,.0f} тыс. ₽"

    # 3. Соотношение дебиторской/кредиторской к выручке
    deb_ratio = deb / rev
    cred_ratio = cred / rev
    max_debt_ratio = max(deb_ratio, cred_ratio)
    
    if max_debt_ratio < 1.0:
        fin_state = "Отличное"
    elif max_debt_ratio <= 1.5:
        fin_state = "Среднее (ближе к норме)"
    elif max_debt_ratio <= 2.5:
        fin_state = "Среднее"
    else:
        fin_state = "Неудовлетворительное"

    # 4. Оценка капитала
    cap_assessment = "Не рассчитано (нет капитала)"
    if cap > 0:
        cap_ratio = max_guarantee_th / cap
        if cap_ratio < 0.8:
            cap_assessment = "Отличная, капитал существенно превышает потенциально возможную сумму гарантии, что говорит о возможном индивидуальном согласовании"
        elif 0.8 <= cap_ratio <= 1.2:
            cap_assessment = "Нормальная"
        else:
            cap_assessment = "Низкая (капитал меньше требуемой гарантии)"
    
    # ЛОГИКА 2: Арбитражи
    # Порог = Выручка / 24. Сравниваем в одной валюте (рубли)
    revenue_rub = rev * 1000
    arb_threshold = revenue_rub / 24
    arb_warning = ""
    
    if arb_sum_rub > arb_threshold:
        arb_warning = "\n⚠️ ВНИМАНИЕ: Сумма активных арбитражей высока! Необходимо проверить текущее состояние судебных разбирательств."

    # Формируем текст
    lines = []
    lines.append(f"• Макс. сумма гарантии (Выручка/12): {mg_str}")
    lines.append(f"• Ориентировочный лимит (Выручка/4): {ls_str}")
    lines.append(f"• Долговая нагрузка: {fin_state}")
    lines.append(f"• Оценка капитала: {cap_assessment}")
    if arb_warning:
        lines.append(arb_warning)
    
    return "\n".join(lines)


async def generate_ai_notification(
    *,
    inn: str,
    company_name: str,
    contact_name: str | None = None, # Added contact_name for Name Day check
    last_comment: str,
    last_call_date: Optional[datetime],
    all_comments: List[str],
    okved_code: str | None,
    okved_name: str | None,
    region: str | None,
    revenue: str | None = None,
    revenue_previous: str | None = None,
    net_profit: str | None = None,
    capital: str | None = None,
    assets: str | None = None,
    debit: str | None = None,
    credit: str | None = None,
    gov_contracts: str | None = None,
    arbitration_open_count: str | None = None,
    arbitration_open_sum: str | None = None,
    arbitration_last_doc_date: str | None = None,
    planned_call_date: Optional[datetime] = None,
) -> str:
    """
    Сгенерировать полный текст уведомления в формате, который просил заказчик.
    """
    client = _get_openai_client()
    # Дата, относительно которой считаем праздники
    base_date = planned_call_date.date() if planned_call_date else date.today()
    last_call_str = last_call_date.strftime("%d.%m.%y") if last_call_date else "неизвестно"

    if client is None:
        # Фоллбек: простой текст без нейросети
        logger.warning("AI notification requested, but OpenAI client is not configured")
        return (
            f"Звонок сегодня\n"
            f"ИНН: {inn}\n"
            f"Название: {company_name}\n"
            f"Последний звонок: {last_call_str} — {last_comment}\n\n"
            f"Инфоповоды для звонка:\n"
            f"1. Новости отрасли и региона — модуль AI пока не подключён.\n"
            f"2. Праздники ±7 дней — модуль AI пока не подключён.\n"
            f"3. Анализ истории общения — модуль AI пока не подключён.\n"
            f"4. Финансовая справка — модуль AI пока не подключён."
        )

    near_holidays = get_near_holidays(base_date)

    all_comments_joined = "\n".join(all_comments) if all_comments else last_comment
    okved_part = f"{okved_code} — {okved_name}" if okved_code or okved_name else "неизвестно"
    region_part = region or "регион не указан"
    holidays_text = "; ".join(near_holidays) if near_holidays else "нет общероссийских праздников рядом"
    contact_name_text = contact_name or "Имя ЛПР не указано"

    # Расчет финансовых показателей (Python)
    fin_analysis_text = calculate_financial_analysis(
        revenue, capital, debit, credit, net_profit, arbitration_open_sum
    )

    # Собираем факты по финансам / госконтрактам / арбитражам в текстовый блок для контекста AI
    metrics_lines: List[str] = []
    metrics_lines.append("=== РАСЧЁТНЫЕ ФИНАНСОВЫЕ ПОКАЗАТЕЛИ ===")
    metrics_lines.append(fin_analysis_text)
    metrics_lines.append("=== ИСХОДНЫЕ ДАННЫЕ ===")
    
    if revenue or revenue_previous:
        metrics_lines.append(
            f"- Выручка: прошлый год = {revenue or '0'}, позапрошлый = {revenue_previous or '0'} (тыс. руб.)"
        )
    if net_profit:
        metrics_lines.append(f"- Чистая прибыль за прошлый год: {net_profit} тыс. руб.")
    if capital:
        metrics_lines.append(f"- Капитал и резервы: {capital} тыс. руб.")
    if assets:
        metrics_lines.append(f"- Основные средства: {assets} тыс. руб.")
    if debit or credit:
        metrics_lines.append(
            f"- Баланс расчётов: дебиторка = {debit or '0'}, кредиторка = {credit or '0'} тыс. руб."
        )
    if gov_contracts:
        metrics_lines.append(f"- Сумма госконтрактов (поставщик/заказчик): {gov_contracts} руб.")
    if arbitration_open_count or arbitration_open_sum:
        metrics_lines.append(
            f"- Открытые арбитражные дела: количество = {arbitration_open_count or '0'}, "
            f"сумма исков ≈ {arbitration_open_sum or '0'} руб."
        )
    if arbitration_last_doc_date:
        metrics_lines.append(f"- Последнее движение по арбитражу: {arbitration_last_doc_date}")
    
    metrics_text = "\n".join(metrics_lines)

    system_prompt = (
        "Ты эксперт-аналитик для B2B-менеджеров. "
        "Твоя задача — составить план звонка, используя жесткую структуру и предоставленные данные.\n\n"
        "СТРУКТУРА ОТВЕТА (СТРОГО СОБЛЮДАЙ ЕЁ):\n"
        "Звонок сегодня\n"
        "ИНН: ...\n"
        "Название: ...\n"
        "Последний звонок: ДД.ММ.ГГ — ТЕКСТ ПОСЛЕДНЕГО КОММЕНТАРИЯ\n"
        "\n"
        "Инфоповоды для звонка:\n"
        "1. [НОВОСТИ ОТРАСЛИ]: Найди тему, связывающую указанный РЕГИОН и ТЕМУ ЗАКУПОК/ТЕНДЕРОВ в отрасли компании. "
        "Если точных данных нет, сформулируй гипотезу о региональных закупках в этой сфере. "
        "Не выдумывай конкретные заголовки новостей, говори о трендах.\n"
        "2. [ПРАЗДНИКИ]: \n"
        "   - Если есть профессиональный праздник отрасли (по ОКВЭД) в пределах +/- 2 дней: укажи его и поздравь.\n"
        "   - ПРОВЕРЬ ИМЕНИНЫ: Если имя ЛПР указано, проверь, есть ли сегодня (или рядом) именины (день ангела) для этого имени. Если есть - напиши об этом.\n"
        "   - Если отраслевых праздников и именин нет: НАЙДИ В СВОЕЙ БАЗЕ ЗНАНИЙ 2-3 интересных международных, народных или необычных праздника ИМЕННО НА ЭТУ ДАТУ (например, 'День денежного дерева', 'День сапожника' и т.п.). Задача — дать менеджеру повод для легкого разговора (small talk).\n"
        "3. [ИСТОРИЯ ОБЩЕНИЯ]: Проанализируй историю комментариев менеджера (динамика, обещания, переносы). "
        "Предложи стратегию поведения (давление, выяснение потребностей, пауза).\n"
        "4. [ФИНАНСЫ]: Используй данные из блока 'РАСЧЁТНЫЕ ФИНАНСОВЫЕ ПОКАЗАТЕЛИ'. "
        "Приведи рассчитанные цифры (гарантия, лимит, оценка). "
        "ОБЯЗАТЕЛЬНО ДОБАВЬ 'ВЫВОД:': Напиши текстовое резюме. Оцени риски (убытки, суды, капитал) и дай рекомендацию: перспективный клиент или проблемный.\n\n"
        "Стиль общения: деловой, сухой, конкретный."
    )

    user_content = (
        f"ИНН: {inn}\n"
        f"Компания: {company_name}\n"
        f"ЛПР: {contact_name_text}\n"
        f"ОКВЭД: {okved_part}\n"
        f"Регион: {region_part}\n"
        f"Планируемая дата звонка: {base_date.strftime('%d.%m.%Y')}\n"
        f"Список общероссийских праздников (из базы): {holidays_text}\n"
        f"\n"
        f"БЛОК ФИНАНСОВ И АРБИТРАЖЕЙ:\n"
        f"{metrics_text}\n"
        f"\n"
        f"Последний звонок: {last_call_str} — {last_comment}\n"
        f"\n"
        f"История всех комментариев (анализируй паттерны поведения):\n"
        f"{all_comments_joined}\n"
    )

    def _call_openai() -> str:
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            temperature=0.5, # Чуть строже
            max_tokens=800,
        )
        return completion.choices[0].message.content.strip()

    try:
        return await asyncio.to_thread(_call_openai)
    except Exception as e:
        logger.error(f"AI generation error: {e}")
        if "insufficient_quota" in str(e) or "rate_limit_exceeded" in str(e):
            return "⚠️ Ошибка: Закончились средства на счету OpenAI или превышен лимит запросов."
        raise e

async def generate_daily_plan(calls_data: List[dict]) -> str:
    """
    Генерирует план прозвона на день, разбивая клиентов на группы приоритета.
    """
    client = _get_openai_client()
    if client is None:
        return "❌ AI модуль не настроен. Не могу сгенерировать план."

    # Формируем список для промпта
    calls_list_str = ""
    for call in calls_data:
        name = call.get('company_name', 'Неизвестно')
        inn = call.get('inn', '')
        revenue = call.get('revenue', '0')
        gov = call.get('gov_contracts', '0')
        comment = call.get('comment', 'Нет')[:100] # Обрезаем комментарий для экономии токенов
        
        calls_list_str += (
            f"- {name} (ИНН {inn}): Выручка={revenue}, Госконтракты={gov}. "
            f"Коммент: {comment}\n"
        )

    system_prompt = (
        "Ты опытный РОП (Руководитель отдела продаж) в сфере финансовых услуг (банковские гарантии, кредитование, тендеры). "
        "Твоя задача — проанализировать список клиентов на сегодня и составить план атаки.\n\n"
        "Разбей клиентов на 3 группы приоритетности:\n"
        "1) Ядро «гос/строй/повторы» (самые жирные) — компании с большими госконтрактами, строители, или те, кто уже брал (видно по комментариям 'брали', 'повтор'). Это приоритет №1.\n"
        "2) Большая выручка — компании с большими оборотами (>1 млрд), но, возможно, сложные или 'холодные'. Лимиты, регулярка.\n"
        "3) Быстрые деньги / «прямо сейчас есть повод» — компании, где в комментариях видна срочная потребность, предложение конкурентов или конкретная заявка.\n\n"
        "Если компания не подходит явно никуда, отнеси в наиболее подходящую по смыслу (обычно 'Большая выручка' или 'Ядро'). Не теряй клиентов.\n\n"
        "ФОРМАТ ОТВЕТА (строго такой):\n\n"
        "1) Ядро “гос/строй/повторы” (самые жирные)\n"
        " • НАЗВАНИЕ КОМПАНИИ — ключевые цифры (выручка/гос) → Краткая стратегия (до 10 слов, например: 'Брали ранее, предложить расширение лимита').\n\n"
        "2) Большая выручка = возможны лимиты и регулярка\n"
        " ...\n\n"
        "3) Быстрые деньги / “прямо сейчас есть повод”\n"
        " ...\n"
    )

    def _call_openai() -> str:
        completion = client.chat.completions.create(
            model=settings.openai_model, # gpt-4o-mini или gpt-3.5-turbo идеально подойдет
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Вот список клиентов на сегодня:\n\n{calls_list_str}"},
            ],
            temperature=0.4,
            max_tokens=1500,
        )
        return completion.choices[0].message.content.strip()

    try:
        content = await asyncio.to_thread(_call_openai)
        return content
    except Exception as e:
        logger.error(f"Error generating daily plan: {e}")
        return "❌ Не удалось сгенерировать план. Попробуйте позже."


async def ask_ai_advisor(question: str, context_data: str) -> str:
    """
    Отвечает на произвольный вопрос пользователя в контексте компании.
    """
    client = _get_openai_client()
    if client is None:
        return "AI модуль отключен."

    system_prompt = (
        "Ты опытный бизнес-ассистент и консультант по продажам. "
        "Пользователь задает вопрос о компании, с которой работает. "
        "У тебя есть контекст (данные компании, финансы, история). "
        "Отвечай кратко, по делу и с точки зрения продаж (как продать, как говорить, на что надавить). "
        "Не лей воду."
    )

    def _call_openai() -> str:
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"КОНТЕКСТ КОМПАНИИ:\n{context_data}\n\nВОПРОС ПОЛЬЗОВАТЕЛЯ:\n{question}"},
            ],
            temperature=0.7,
            max_tokens=500,
        )
        return completion.choices[0].message.content.strip()

    try:
        return await asyncio.to_thread(_call_openai)
    except Exception as e:
        logger.error(f"AI chat error: {e}")
        return f"Ошибка при обращении к AI: {str(e)[:100]}"
