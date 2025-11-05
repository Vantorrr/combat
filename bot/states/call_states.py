from aiogram.fsm.state import State, StatesGroup


class NewCallStates(StatesGroup):
    """Состояния для нового звонка"""
    waiting_for_inn = State()
    confirm_inn = State()
    waiting_for_contact_name = State()
    waiting_for_phone = State()
    waiting_for_email = State()
    waiting_for_comment = State()
    waiting_for_next_call_date = State()


class RepeatCallStates(StatesGroup):
    """Состояния для повторного звонка"""
    waiting_for_inn = State()
    confirm_company = State()
    waiting_for_comment = State()
    waiting_for_next_call_date = State()


class AdminStates(StatesGroup):
    """Состояния для административных функций"""
    waiting_for_manager_id = State()
    waiting_for_manager_name = State()
    # Состояния для импорта CSV
    waiting_for_csv_manager = State()
    waiting_for_csv_file = State()
