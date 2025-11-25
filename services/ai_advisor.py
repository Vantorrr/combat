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
    credit_str: Optional[str]
) -> str:
    """
    Рассчитать финансовые показатели и вернуть текстовый блок с выводами.
    """
    rev = safe_float(revenue_str)
    cap = safe_float(capital_str)
    deb = safe_float(debit_str)
    cred = safe_float(credit_str)

    if rev <= 0:
        return "Недостаточно данных по выручке для расчёта фин. показателей."

    # 1. Максимальная сумма гарантии = Выручка годовая / 12
    max_guarantee = rev / 12
    
    # 2. Ориентировочный размер лимита = Выручка годовая / 4
    limit_size = rev / 4

    # 3. Соотношение дебиторской/кредиторской к выручке
    # "соотношение дебеторской и кредиторской задолженности отдельно к выручке"
    # Интерпретация: считаем по отдельности.
    deb_ratio = deb / rev
    cred_ratio = cred / rev
    
    # Оценка фин состояния (по худшему показателю или суммарно? Возьмем по худшему из двух для консерватизма)
    # "если меньше 1-го то отличный показатель, если больше 1,5 то оценка фин состояния = средняя, 
    # если более 2,5 = фин состояние неудовлетворительное"
    max_debt_ratio = max(deb_ratio, cred_ratio)
    
    if max_debt_ratio < 1.0:
        fin_state = "Отличное"
    elif max_debt_ratio <= 1.5:  # Уточнение диапазона (1.0 - 1.5 не описано явно, отнесем к норме/среднему)
        fin_state = "Среднее (ближе к норме)"
    elif max_debt_ratio <= 2.5:
        fin_state = "Среднее"
    else:
        fin_state = "Неудовлетворительное"

    # 4. Оценка капитала
    # "Максимальную сумму гарантии расчитанную выше / на капитал"
    # 0,8-1,2 - норма, < 0,8 неудовл, > 1,2 высокая
    cap_assessment = "Не рассчитано (нет капитала)"
    if cap > 0:
        cap_ratio = max_guarantee / cap
        if cap_ratio < 0.8:
            cap_assessment = "Неудовлетворительный (капитал слишком велик относительно гарантии?)" 
            # Примечание: тут возможна путаница в ТЗ (обычно ratio < 0.8 значит гарантия меньше капитала -> капитал большой -> это хорошо).
            # Но делаем строго по ТЗ: "менее 0,8 капитал неудовлетсворительный"
        elif 0.8 <= cap_ratio <= 1.2:
            cap_assessment = "Капитал в норме"
        else:
            # > 1.2
            cap_assessment = "Высокая оценка капитала"
    
    # Формируем текст
    # Выручка и прочее у нас обычно в тысячах. Если max_guarantee в тысячах, то добавим "тыс. руб."
    # Предполагаем, что входные данные в ТЫСЯЧАХ (как в таблице).
    
    lines = []
    lines.append(f"• Макс. сумма гарантии (Выручка/12): {max_guarantee:,.0f} тыс. ₽")
    lines.append(f"• Ориентировочный лимит (Выручка/4): {limit_size:,.0f} тыс. ₽")
    lines.append(f"• Долговая нагрузка (Долг/Выручка): Деб={deb_ratio:.2f}, Кред={cred_ratio:.2f}. Оценка: {fin_state}")
    lines.append(f"• Оценка капитала (Макс.гарантия/Капитал): {cap_assessment}")
    
    return "\n".join(lines)


async def generate_ai_notification(
    *,
    inn: str,
    company_name: str,
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
            f"3. Анализ истории общения — модуль AI пока не подключён."
        )

    near_holidays = get_near_holidays(base_date)

    all_comments_joined = "\n".join(all_comments) if all_comments else last_comment
    okved_part = f"{okved_code} — {okved_name}" if okved_code or okved_name else "неизвестно"
    region_part = region or "регион не указан"
    holidays_text = "; ".join(near_holidays) if near_holidays else "нет общероссийских праздников рядом"

    # Расчет финансовых показателей (Python)
    fin_analysis_text = calculate_financial_analysis(revenue, capital, debit, credit)

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
        "2. [ПРАЗДНИКИ]: Если для отрасли (по ОКВЭД) существует профессиональный праздник в пределах +/- 2 дней от "
        f"{base_date.strftime('%d.%m')}, укажи ТОЛЬКО его. Если отраслевых праздников рядом нет, "
        "перечисли общероссийские праздники из предоставленного списка или напиши 'Нет значимых праздников'.\n"
        "3. [АНАЛИЗ КЛИЕНТА]: Сделай сводный вывод на основе ИСТОРИИ КОММЕНТАРИЕВ (динамика, обещания, переносы) "
        "и РАСЧЁТНЫХ ФИНАНСОВЫХ ПОКАЗАТЕЛЕЙ (гарантии, лимиты, оценка капитала). "
        "Прямо упомяни 'Макс. сумму гарантии', если она рассчитана. Предложи конкретную стратегию входа (SPIN/Challenger).\n\n"
        "Стиль общения: деловой, сухой, конкретный."
    )

    user_content = (
        f"ИНН: {inn}\n"
        f"Компания: {company_name}\n"
        f"ОКВЭД: {okved_part}\n"
        f"Регион: {region_part}\n"
        f"Планируемая дата звонка: {base_date.strftime('%d.%m.%Y')}\n"
        f"Список общероссийских праздников рядом: {holidays_text}\n"
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
        content = await asyncio.to_thread(_call_openai)
        return content
    except Exception as e:
        logger.error(f"Error while calling OpenAI for AI notification: {e}")
        return (
            f"Звонок сегодня\n"
            f"ИНН: {inn}\n"
            f"Название: {company_name}\n"
            f"Последний звонок: {last_call_str} — {last_comment}\n\n"
            f"Ошибка генерации AI-совета. Проверьте настройки API."
        )
