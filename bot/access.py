from db.models import User


def check_access(user: User) -> tuple[bool, str]:
    """Проверяет доступ. Только бан — без лимитов на количество файлов."""
    if user.is_banned:
        return False, "banned"
    return True, ""


def get_limit_message(reason: str) -> str:
    messages = {
        "banned": "Ваш аккаунт заблокирован. Напишите в @txt2voice.",
    }
    return messages.get(reason, "Доступ ограничен.")
