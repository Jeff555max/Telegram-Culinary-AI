import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from services.recipe_generator import RecipeGenerationError, RecipeGenerator
from services.memory import ConversationMemory
from services.storage import RecipeRepository
from utils.image_tools import telephoto_to_base64
from utils.recipes import publish_recipes

router = Router(name="image-ingredients")
LOGGER = logging.getLogger(__name__)


class PhotoFlow(StatesGroup):
    waiting_choice = State()


def _photo_mode_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🧺 Это ингредиенты", callback_data="photo:ingredients"),
                InlineKeyboardButton(text="🍽️ Готовое блюдо", callback_data="photo:dish"),
            ]
        ]
    )


@router.message(F.photo)
async def ask_photo_context(message: Message, state: FSMContext) -> None:
    """Ask the user to clarify what the uploaded photo represents."""

    file_id = message.photo[-1].file_id
    await state.set_state(PhotoFlow.waiting_choice)
    await state.update_data(file_id=file_id)

    await message.answer(
        "Что изображено на фото? Выбери подходящий сценарий.",
        reply_markup=_photo_mode_keyboard(),
    )


@router.callback_query(F.data == "photo:ingredients")
async def process_ingredient_photo(
    callback: CallbackQuery,
    state: FSMContext,
    recipe_generator: RecipeGenerator,
    conversation_memory: ConversationMemory,
    recipe_repository: RecipeRepository,
) -> None:
    """Handle ingredient scenario after the user presses the button."""

    await callback.answer()
    data = await state.get_data()
    file_id = data.get("file_id")

    if not file_id:
        await callback.message.answer("Фото не найдено. Отправь снимок повторно.")
        return

    await callback.message.edit_reply_markup()
    chat_id = callback.message.chat.id
    await callback.bot.send_chat_action(chat_id=chat_id, action="typing")
    history = conversation_memory.format_history(chat_id)

    try:
        image_data = await telephoto_to_base64(callback.bot, file_id)
        recipes = await recipe_generator.from_ingredient_photo(
            image_data,
            history or None,
        )
    except RecipeGenerationError:
        LOGGER.exception("Ingredient photo processing failed")
        await callback.message.answer(
            "⚠️ Не удалось обработать ингредиенты. Попробуй другое фото."
        )
        return

    if not recipes:
        await callback.message.answer("⚠️ Модель не смогла предложить блюда. Попробуй новое фото.")
        return

    await state.clear()
    conversation_memory.add(chat_id, "user", "[Фото ингредиентов]")
    await publish_recipes(
        callback.message.answer,
        chat_id,
        recipes,
        source="Фото ингредиентов",
        recipe_repository=recipe_repository,
        conversation_memory=conversation_memory,
    )

