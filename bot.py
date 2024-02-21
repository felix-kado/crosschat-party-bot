import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiogram.utils.markdown import hbold
from aiogram.filters.command import Command
from aiogram.enums.chat_member_status import ChatMemberStatus

from sqlalchemy.orm import sessionmaker
from models import User, Chat, Party, engine

from credentials import TOKEN

Session = sessionmaker(bind=engine)


# All handlers should be attached to the Router (or Dispatcher)
dp = Dispatcher()
bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
session = Session()


async def is_chat_member(chat_id: int, user_id: int) -> bool:
    user_status = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    return user_status.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR, ChatMemberStatus.MEMBER)


async def update_user(message: Message) -> list[str]:
    user = session.query(User).filter(User.user_id == message.from_user.id).first()

    # create new user if it doesn't exist
    if not user:
        user = User(user_id=message.from_user.id, full_name=message.from_user.full_name)
        session.add(user)
        session.commit()
        logging.info(f"User added to the database: {user.user_id}, {user.full_name}")

    chats = session.query(Chat).all()

    # check all chats and add them to the user if the user is member
    for chat in chats:
        if await is_chat_member(chat.chat_id, user.user_id):
            if chat not in user.chats:
                user.chats.append(chat)
                logging.info(
                    f"Chat added to the user: {user.user_id}, {user.full_name} -- {chat.chat_id}, {chat.title}"
                )

    # remove chats from the user if the user is not member anymore
    for chat in user.chats:
        if not await is_chat_member(chat.chat_id, user.user_id):
            user.chats.remove(chat)
            logging.info(
                f"User is not member of the chat anymore: {user.user_id}, {user.full_name} -- {chat.chat_id}, {chat.title}"
            )

    user_chats = [chat.title for chat in user.chats]

    session.commit()

    return user_chats


async def update_chat(message: Message) -> list[str]:
    chat = session.query(Chat).filter(Chat.chat_id == message.chat.id).first()

    # create new chat if it doesn't exist
    if not chat:
        chat = Chat(chat_id=message.chat.id, title=message.chat.title)
        session.add(chat)
        session.commit()
        logging.info(f"Chat added to the database: {chat.chat_id}, {chat.title}")

    # check all users and add them to the chat if the user is member
    users = session.query(User).all()
    for user in users:
        if await is_chat_member(chat.chat_id, user.user_id):
            if user not in chat.members:
                chat.members.append(user)
                session.commit()
                logging.info(
                    f"User added to the chat: {chat.chat_id}, {chat.title} -- {user.user_id}, {user.full_name}"
                )

    # remove users from the chat if the user is not member anymore
    for user in chat.members:
        if not await is_chat_member(chat.chat_id, user.user_id):
            chat.members.remove(user)
            session.commit()
            logging.info(
                f"User is not member of the chat anymore: {user.user_id}, {user.full_name} -- {chat.chat_id}, {chat.title}"
            )

    chat_members = [user.full_name for user in chat.members]

    return chat_members


@dp.message(Command("update"))
@dp.message(CommandStart())
async def command_start_handler(message: Message) -> None:
    # update database for users and chats
    if message.chat.type == "private":
        logging.info(
            f"User {message.from_user.id}, {message.from_user.full_name} updated database"
        )
        user_chats = "\n".join(await update_user(message))
        await bot.send_message(
            message.chat.id, f"Привет, ты состоишь в чатах:\n{user_chats}!"
        )

    else:
        logging.info(f"Chat {message.chat.id}, {message.chat.title} updated database")
        chat_members = "\n".join(await update_chat(message))
        await bot.send_message(
            message.chat.id,
            f"Привет, вот зарегистрированне пользователи этого чата:\n{chat_members}",
        )


async def create_party_poll(message: types.Message, description: str) -> Party:
    announcement = await message.answer_poll(
        question=description,
        options=["Я пойду", "Я пока не уверен", "Я не пойду"],
        is_anonymous=False,
    )

    party = Party(
        description=description,
        from_who_name=message.from_user.full_name,
        from_who_tg=message.from_user.username,
        poll_chat_id=announcement.chat.id,
        poll_message_id=announcement.message_id,
    )
    session.add(party)
    session.commit()
    logging.info(
        f"Party added to the database: {party.description}, {party.poll_chat_id}, {party.poll_message_id}"
    )

    return party


async def notify_users_about_party(party: Party, chat: Chat) -> None:
    for user in chat.members:
        if user not in party.notified:
            await bot.send_message(
                user.user_id, f"Встреча от {party.from_who_name} (@{party.from_who_tg})\n"
            )
            await bot.forward_message(
                chat_id=user.user_id,
                from_chat_id=party.poll_chat_id,
                message_id=party.poll_message_id,
            )
            logging.info(
                f"User {user.user_id}, {user.full_name} was notified about the party {party.party_id}"
            )
            party.notified.append(user)

    session.commit()


async def check_rules(message: types.Message) -> bool:
    if message.chat.type == "private":
        await bot.send_message(
            message.chat.id, "Нельзя создавать встречи в личных чатах"
        )
        logging.error(
            f"User {message.from_user.id}, {message.from_user.full_name} tried to create a party in private chat"
        )
        return False

    description = message.text.split("/party", 1)[1].strip()

    if description == "":
        await message.answer("Описание не может быть пустым")
        logging.error(
            f"User {message.from_user.id}, {message.from_user.full_name} tried to create a party with an empty description"
        )
        return False
    if len(description) >= 300:
        await message.answer(
            "В описание опроса нельзя такое длинное описание поместить, попробуй написать лаконичнее"
        )
        logging.error(
            f"User {message.from_user.id} tried to create a party with a too long description"
        )
        return False

    return True


@dp.message(Command("party"))
async def handle_party_command(message: types.Message) -> None:
    if not await check_rules(message):
        return

    await update_chat(message)

    description = message.text.split("/party", 1)[1].strip()
    party = session.query(Party).filter(Party.description == description).first()

    if not party:
        party = await create_party_poll(message, description)
    else:
        await bot.forward_message(
            chat_id=message.chat.id,
            from_chat_id=party.poll_chat_id,
            message_id=party.poll_message_id,
        )
        logging.info(
            f"User {message.from_user.id} tried to create a party with an already existing description, used forwarded message"
        )

    chat = session.query(Chat).filter(Chat.chat_id == message.chat.id).first()
    await notify_users_about_party(party, chat)

    session.commit()
    
@dp.message(Command("info"))
async def handle_party_command(message: types.Message) -> None:
    await bot.send_message(
        message.chat.id, """ Привет, я бот для создания встреч. 

Моя задачи: 
- Уведомлять пользователей о намечающихся встречах
- Создавать и прокидывать опрос со сбором участников между чатами

Чтобы подписаться на уведомления, просто перейдите в чат с ботом @party_flex_bot и отправьте команду /start.

Для создания опроса о встрече напишите команду /party, за которой следует описание мероприятия в одном сообщении. Например:
<pre>/party Боулинг в четверг в 13:00. Торговый центр "Маяк"</pre>
<i>Старайтесь писать небольшое, но исчерпывабщее описание. Пользователь в личке увидит только его.</i>


Если вы хотите пригласить участников из другого чата, где также есть этот бот, просто отправьте ту же команду с таким же описанием. Бот передаст уже существующий опрос, а уведомления получат только те пользователи, которых не было в предыдущих встречах.

Для обновления базы данных можно использовать команду /update (понадобиться не должно, на всякий случай)
"""
    
    )

async def main() -> None:
    await dp.start_polling(bot)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )
    asyncio.run(main())
