from __future__ import annotations

from typing import Dict, Optional

EN: Dict[str, str] = {
    'back': '← Back',
    'home': 'Home',
    'agree': 'I agree',
    'consent_needed': 'Please press the button to continue.',
    'invalid_email': 'That does not look like an email address. Please try again.',
    'invalid_phone': 'Please send a phone number, for example +79001234567.',
    'invalid_number': 'Please send a number.',
    'invalid_choice': 'Please choose one of the options.',
    'invalid_regex': 'That answer is not in the expected format. Please try again.',
    'use_buttons': 'Please use the buttons.',
    'choose_method': 'Choose a payment method for <b>{product}</b>:',
    'pay_stars': 'Telegram Stars — {amount}',
    'pay_telegram': 'Bank card — {amount}',
    'pay_yookassa': 'YooKassa — {amount}',
    'pay_crypto': 'Crypto — {amount}',
    'pay_manual': 'Bank transfer — {amount}',
    'pay_test': 'Test payment (admin) — {amount}',
    'pay_now': 'Pay now — {amount}',
    'pay_check': 'I have paid',
    'pay_waiting': 'Waiting for the payment. If you have paid, it will be confirmed automatically in a moment.',
    'pay_failed': 'The payment was not completed. You can try again.',
    'pay_expired': 'This payment link has expired. Please start again.',
    'pay_no_method': 'Payment is not available for this product right now.',
    'paid_thanks': 'Payment received. Thank you!',
    'manual_instructions': '{instructions}\n\nAfter paying, send a screenshot of the payment here as a photo.',
    'manual_received': 'Thank you! A manager will confirm your payment shortly.',
    'manual_approved': 'Your payment is confirmed.',
    'manual_rejected': 'We could not confirm your payment. Please contact support.',
    'access_channel': 'Your access to <b>{product}</b> is active{until}.\nRequest to join here: {link}',
    'access_renewed': 'Your access to <b>{product}</b> is extended{until}.',
    'access_until': ' until {date}',
    'access_expired': 'Your access to <b>{product}</b> has ended.',
    'access_reminder': 'Your access to <b>{product}</b> ends in {days} day(s).',
    'renew': 'Renew access',
    'join_approved': 'Welcome! Your access is confirmed.',
    'join_declined': 'No active access was found for your account. Please open the bot and buy access first.',
    'manager_called': 'A manager has been notified and will write to you here.',
    'help': 'Use the buttons to move through the bot.\n/paysupport — help with a payment\n/terms — terms\n/deleteme — erase my data\n/stop — stop promotional messages',
    'terms': 'The terms of use are provided by the bot owner.',
    'paysupport': 'For payment questions please contact the bot owner. Mention this bot and the time of your payment.',
    'deleted': 'Your data has been erased.',
    'deleteme_ask': 'Erase all your data? Your access to paid content will end.',
    'yes': 'Yes, erase',
    'no': 'Cancel',
    'contact_manager': 'Contact a manager',
    'stopped': 'Promotional messages are off. Notices about your access still arrive. Send /resume to turn them on again.',
    'resumed': 'Promotional messages are on.',
}

RU: Dict[str, str] = {
    'back': '← Назад',
    'home': 'В начало',
    'agree': 'Согласен',
    'consent_needed': 'Нажмите кнопку, чтобы продолжить.',
    'invalid_email': 'Похоже, это не email. Попробуйте ещё раз.',
    'invalid_phone': 'Пришлите номер телефона, например +79001234567.',
    'invalid_number': 'Пришлите число.',
    'invalid_choice': 'Выберите один из вариантов.',
    'invalid_regex': 'Ответ не в нужном формате. Попробуйте ещё раз.',
    'use_buttons': 'Пользуйтесь кнопками.',
    'choose_method': 'Выберите способ оплаты для <b>{product}</b>:',
    'pay_stars': 'Telegram Stars — {amount}',
    'pay_telegram': 'Картой — {amount}',
    'pay_yookassa': 'ЮKassa — {amount}',
    'pay_crypto': 'Криптой — {amount}',
    'pay_manual': 'Переводом — {amount}',
    'pay_test': 'Тестовая оплата (админ) — {amount}',
    'pay_now': 'Оплатить — {amount}',
    'pay_check': 'Я оплатил',
    'pay_waiting': 'Ждём оплату. Если вы уже оплатили, она подтвердится автоматически через несколько секунд.',
    'pay_failed': 'Оплата не завершена. Можно попробовать снова.',
    'pay_expired': 'Ссылка на оплату просрочена. Начните заново.',
    'pay_no_method': 'Оплата этого товара сейчас недоступна.',
    'paid_thanks': 'Оплата получена. Спасибо!',
    'manual_instructions': '{instructions}\n\nПосле оплаты пришлите сюда скриншот платёжа фотографией.',
    'manual_received': 'Спасибо! Менеджер скоро подтвердит оплату.',
    'manual_approved': 'Оплата подтверждена.',
    'manual_rejected': 'Не удалось подтвердить оплату. Напишите в поддержку.',
    'access_channel': 'Доступ к <b>{product}</b> активен{until}.\nПодайте заявку на вступление: {link}',
    'access_renewed': 'Доступ к <b>{product}</b> продлён{until}.',
    'access_until': ' до {date}',
    'access_expired': 'Доступ к <b>{product}</b> завершён.',
    'access_reminder': 'Доступ к <b>{product}</b> заканчивается через {days} дн.',
    'renew': 'Продлить доступ',
    'join_approved': 'Добро пожаловать! Доступ подтверждён.',
    'join_declined': 'Активный доступ для вашего аккаунта не найден. Откройте бота и сначала оплатите доступ.',
    'manager_called': 'Менеджер получил уведомление и напишет вам здесь.',
    'help': 'Пользуйтесь кнопками.\n/paysupport — помощь с оплатой\n/terms — условия\n/deleteme — удалить мои данные\n/stop — отключить рекламные сообщения',
    'terms': 'Условия использования предоставляет владелец бота.',
    'paysupport': 'По вопросам оплаты обратитесь к владельцу бота, укажите время платежа.',
    'deleted': 'Ваши данные удалены.',
    'deleteme_ask': 'Удалить все ваши данные? Доступ к платному контенту будет закрыт.',
    'yes': 'Да, удалить',
    'no': 'Отмена',
    'contact_manager': 'Связаться с менеджером',
    'stopped': 'Рекламные сообщения отключены. Уведомления о доступе продолжат приходить. Чтобы включить снова, отправьте /resume.',
    'resumed': 'Рекламные сообщения включены.',
}

KEYS = tuple(EN)

TABLES = {"en": EN, "ru": RU}


class Texts:
    def __init__(self, language: str = "ru", overrides: Optional[Dict[str, str]] = None):
        self.table = dict(TABLES.get(language, EN))
        self.table.update(overrides or {})

    def __call__(self, key: str, **values: object) -> str:
        template = self.table.get(key) or EN[key]
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            return template
