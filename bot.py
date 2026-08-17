import asyncio
import json
import os
import time
import discord
from discord import app_commands
from discord.ext import commands, tasks

# --- НАСТРОЙКА ПРАВ (INTENTS) ---
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
intents.voice_states = True
TOKEN = os.getenv("BOT_TOKEN")
bot = commands.Bot(command_prefix="!", intents=intents)

# --- ID СЕРВЕРА ---
GUILD_ID = 1383467290703429714  # ID вашего сервера для синхронизации команд

# --- ID РОЛЕЙ СЕРВЕРА ---
SUPPORT_ROLE_ID = 1384218263583723591  # Роль Саппорта (доступ к /verify)
REMOVE_ROLE_ID = 1384932729186947145   # Роль, которая снимается при верификации
PINK_ROLE_ID = 1384932536089837628     # Роль за розовое сердце 🩷
BLUE_ROLE_ID = 1384933783085514943     # Роль за синее сердце 💙

MOD_ROLE_ID = 1384231152612540486     # Роль модератора (доступ к /nakazanie)
MUTE_ROLE_ID = 1384939305666875505    # Роль Мьюта
BAN_ROLE_ID = 1405247527309152318     # Роль Бана

MARRY_ROLE_ID = 1383917749209927740   # Роль Брака 💍

# --- ID ДЛЯ LOVE ROOM ---
JOIN_VOICE_ID = 1538705285823209493       # ID триггерного голосового канала
TARGET_CATEGORY_ID = 1383467290703429714  # ID категории для создания Love Room

# Динамические пути к файлам в папке скрипта
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PUNISHMENTS_FILE = os.path.join(BASE_DIR, "punishments.json")
MARRIAGES_FILE = os.path.join(BASE_DIR, "marriages.json")

# Хранилище ID созданных временных каналов Love Room
temp_love_channels = set()


# ==========================================
# 1. РАБОТА С ФАЙЛАМИ JSON
# ==========================================

# --- Наказания ---
def load_punishments():
    if not os.path.exists(PUNISHMENTS_FILE):
        return []
    try:
        with open(PUNISHMENTS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_punishments(data):
    with open(PUNISHMENTS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def add_punishment(guild_id: int, user_id: int, role_id: int, unpunish_time: float, saved_roles: list = None):
    data = load_punishments()
    data.append({
        "guild_id": guild_id,
        "user_id": user_id,
        "role_id": role_id,
        "unpunish_time": unpunish_time,
        "saved_roles": saved_roles or []
    })
    save_punishments(data)

def remove_punishment_entry(guild_id: int, user_id: int, role_id: int):
    data = load_punishments()
    data = [item for item in data if not (item["guild_id"] == guild_id and item["user_id"] == user_id and item["role_id"] == role_id)]
    save_punishments(data)

# --- Браки ---
def load_marriages():
    if not os.path.exists(MARRIAGES_FILE):
        return {}
    try:
        with open(MARRIAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_marriages(data):
    with open(MARRIAGES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def get_marriage_info(user_id: int):
    data = load_marriages()
    entry = data.get(str(user_id))
    if isinstance(entry, int):
        return {"spouse_id": entry, "custom_name": None}
    elif isinstance(entry, dict):
        return entry
    return None

def get_spouse_id(user_id: int):
    info = get_marriage_info(user_id)
    return info["spouse_id"] if info else None

def set_marriage(user1_id: int, user2_id: int):
    data = load_marriages()
    data[str(user1_id)] = {"spouse_id": user2_id, "custom_name": None}
    data[str(user2_id)] = {"spouse_id": user1_id, "custom_name": None}
    save_marriages(data)

def remove_marriage(user_id: int):
    data = load_marriages()
    info = get_marriage_info(user_id)
    if info:
        spouse_id = info["spouse_id"]
        data.pop(str(user_id), None)
        data.pop(str(spouse_id), None)
        save_marriages(data)
        return spouse_id
    return None

def set_custom_room_name(user_id: int, custom_name: str):
    data = load_marriages()
    info = get_marriage_info(user_id)
    if info:
        spouse_id = info["spouse_id"]
        data[str(user_id)] = {"spouse_id": spouse_id, "custom_name": custom_name}
        data[str(spouse_id)] = {"spouse_id": user_id, "custom_name": custom_name}
        save_marriages(data)


# ==========================================
# 2. ИНТЕРФЕЙС И ЛОГИКА /verify
# ==========================================

class SupportView(discord.ui.View):
    def __init__(self, target_member: discord.Member, author: discord.Member):
        super().__init__(timeout=180)
        self.target_member = target_member
        self.author = author

    async def handle_role_swap(self, interaction: discord.Interaction, new_role_id: int):
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Это не ваше меню управления!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        guild = interaction.guild
        target = self.target_member

        remove_role = guild.get_role(REMOVE_ROLE_ID)
        add_role = guild.get_role(new_role_id)

        try:
            if remove_role and remove_role in target.roles:
                await target.remove_roles(remove_role)

            if add_role:
                await target.add_roles(add_role)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Ошибка: У бота недостаточно прав! Поднимите роль бота ВЫШЕ всех управляемых ролей.",
                ephemeral=True
            )
            return

        for child in self.children:
            child.disabled = True

        await interaction.followup.send(
            content=f"✅ Успешно обновлены роли для {target.mention}!\n"
                    f"• Снята роль: <@&{REMOVE_ROLE_ID}>\n"
                    f"• Выдана роль: <@&{new_role_id}>",
            ephemeral=True
        )

    @discord.ui.button(emoji="🩷", style=discord.ButtonStyle.secondary)
    async def pink_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_swap(interaction, PINK_ROLE_ID)

    @discord.ui.button(emoji="💙", style=discord.ButtonStyle.secondary)
    async def blue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.handle_role_swap(interaction, BLUE_ROLE_ID)


# ==========================================
# 3. ИНТЕРФЕЙС И ЛОГИКА /nakazanie
# ==========================================

class TimeInputModal(discord.ui.Modal):
    def __init__(self, target_member: discord.Member, role_id: int, action_name: str):
        super().__init__(title=f"Наказание: {action_name}")
        self.target_member = target_member
        self.role_id = role_id
        self.action_name = action_name

        self.minutes_input = discord.ui.TextInput(
            label="Длительность наказания (в минутах)",
            placeholder="Введите число, например: 10",
            min_length=1,
            max_length=5,
            required=True
        )
        self.add_item(self.minutes_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.minutes_input.value.isdigit():
            await interaction.response.send_message("❌ Ошибка: Введите корректное число минут!", ephemeral=True)
            return

        minutes = int(self.minutes_input.value)
        if minutes <= 0:
            await interaction.response.send_message("❌ Время должно быть больше 0 минут!", ephemeral=True)
            return

        role = interaction.guild.get_role(self.role_id)
        if not role:
            await interaction.response.send_message("❌ Ошибка: Роль наказания не найдена на сервере!", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        saved_roles_ids = []

        if self.role_id == BAN_ROLE_ID:
            bot_top_role = interaction.guild.me.top_role
            roles_to_remove = [
                r for r in self.target_member.roles 
                if not r.is_default() and not r.is_premium_subscriber() and r < bot_top_role
            ]
            saved_roles_ids = [r.id for r in roles_to_remove]

            for r in roles_to_remove:
                try:
                    await self.target_member.remove_roles(r)
                except Exception as e:
                    print(f"Ошибка при снятии роли {r.name}: {e}")

        try:
            await self.target_member.add_roles(role)
        except discord.Forbidden:
            await interaction.followup.send("❌ Ошибка прав! Роль бота должна быть ВЫШЕ роли бана/мьюта.", ephemeral=True)
            return

        unpunish_time = time.time() + (minutes * 60)
        add_punishment(interaction.guild.id, self.target_member.id, self.role_id, unpunish_time, saved_roles_ids)

        await interaction.followup.send(
            content=f"✅ Пользователю {self.target_member.mention} выдан **{self.action_name}** на **{minutes} мин.**",
            ephemeral=True
        )


class PunishView(discord.ui.View):
    def __init__(self, target_member: discord.Member, author: discord.Member):
        super().__init__(timeout=180)
        self.target_member = target_member
        self.author = author

        mute_role = target_member.guild.get_role(MUTE_ROLE_ID)
        is_muted = mute_role in target_member.roles if mute_role else False

        if is_muted:
            unmute_button = discord.ui.Button(label="Размутить", emoji="🔊", style=discord.ButtonStyle.success)
            unmute_button.callback = self.unmute_button_callback
            self.add_item(unmute_button)
        else:
            mute_button = discord.ui.Button(label="Мьют", emoji="🔇", style=discord.ButtonStyle.danger)
            mute_button.callback = self.mute_button_callback
            self.add_item(mute_button)

        ban_button = discord.ui.Button(label="Бан", emoji="🔨", style=discord.ButtonStyle.danger)
        ban_button.callback = self.ban_button_callback
        self.add_item(ban_button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Это не ваше меню управления!", ephemeral=True)
            return False
        return True

    async def mute_button_callback(self, interaction: discord.Interaction):
        modal = TimeInputModal(target_member=self.target_member, role_id=MUTE_ROLE_ID, action_name="Мьют")
        await interaction.response.send_modal(modal)

    async def unmute_button_callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        mute_role = interaction.guild.get_role(MUTE_ROLE_ID)

        try:
            if mute_role and mute_role in self.target_member.roles:
                await self.target_member.remove_roles(mute_role)
            remove_punishment_entry(interaction.guild.id, self.target_member.id, MUTE_ROLE_ID)

            await interaction.followup.send(
                content=f"🔊 Пользователь {self.target_member.mention} был досрочно **размучен**!",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.followup.send("❌ Ошибка: недостаточно прав для снятия роли!", ephemeral=True)

    async def ban_button_callback(self, interaction: discord.Interaction):
        modal = TimeInputModal(target_member=self.target_member, role_id=BAN_ROLE_ID, action_name="Бан")
        await interaction.response.send_modal(modal)


# ==========================================
# 4. ИНТЕРФЕЙС И ЛОГИКА /marry И /marry_manage
# ==========================================

class ProposalView(discord.ui.View):
    def __init__(self, author: discord.Member, target: discord.Member, guild_id: int):
        super().__init__(timeout=300)
        self.author = author
        self.target = target
        self.guild_id = guild_id

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, emoji="🩷")
    async def accept_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return

        await interaction.response.defer()
        set_marriage(self.author.id, self.target.id)

        # Выдача ролей на сервере (работает из ЛС благодаря сохраненному guild_id)
        guild = bot.get_guild(self.guild_id)
        if guild:
            marry_role = guild.get_role(MARRY_ROLE_ID)
            if marry_role:
                author_member = guild.get_member(self.author.id) or await guild.fetch_member(self.author.id)
                target_member = guild.get_member(self.target.id) or await guild.fetch_member(self.target.id)

                try:
                    if author_member:
                        await author_member.add_roles(marry_role)
                    if target_member:
                        await target_member.add_roles(marry_role)
                except discord.Forbidden:
                    print(f"Ошибка: Недостаточно прав для выдачи роли брака {MARRY_ROLE_ID}! Поднимите роль бота выше.")
                except Exception as e:
                    print(f"Ошибка при выдаче роли брака: {e}")

        for child in self.children:
            child.disabled = True

        await interaction.edit_original_response(
            content=f"💖 Вы приняли предложение от {self.author.mention}! Теперь вы состоите в браке и вам выдана роль <@&{MARRY_ROLE_ID}>.\n"
                    f"Чтобы создать вашу Love Room, зайдите в специальный голосовой канал!",
            view=self
        )

        try:
            await self.author.send(f"🎉 {self.target.mention} принял(а) ваше предложение! Вы официально соединены 💞")
        except discord.Forbidden:
            pass

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, emoji="💔")
    async def decline_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            return

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(content="💔 Вы отклонили предложение.", view=self)

        try:
            await self.author.send(f"💔 К сожалению, {self.target.mention} отклонил(а) ваше предложение.")
        except discord.Forbidden:
            pass


class RenameRoomModal(discord.ui.Modal):
    def __init__(self):
        super().__init__(title="Переименование Love Room")

        self.room_name_input = discord.ui.TextInput(
            label="Новое название вашей комнаты",
            placeholder="Например: Уголок Любви 💞",
            min_length=1,
            max_length=50,
            required=True
        )
        self.add_item(self.room_name_input)

    async def on_submit(self, interaction: discord.Interaction):
        new_name = self.room_name_input.value.strip()
        set_custom_room_name(interaction.user.id, new_name)

        await interaction.response.send_message(
            f"✅ Новое название для вашей Love Room установлено: **{new_name}**!\n"
            f"Оно будет использоваться при следующем входе в голосовой канал.",
            ephemeral=True
        )


class MarryManageView(discord.ui.View):
    def __init__(self, author: discord.Member):
        super().__init__(timeout=180)
        self.author = author

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message("❌ Это не ваше меню управления!", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Развод", style=discord.ButtonStyle.danger, emoji="💔")
    async def divorce_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        spouse_id = remove_marriage(interaction.user.id)

        guild = interaction.guild
        if guild:
            marry_role = guild.get_role(MARRY_ROLE_ID)
            if marry_role:
                # Снимаем роль у инициатора развода
                if marry_role in interaction.user.roles:
                    try:
                        await interaction.user.remove_roles(marry_role)
                    except discord.Forbidden:
                        pass

                # Снимаем роль у второго супруга
                if spouse_id:
                    spouse = guild.get_member(spouse_id)
                    if not spouse:
                        try:
                            spouse = await guild.fetch_member(spouse_id)
                        except Exception:
                            spouse = None

                    if spouse and marry_role in spouse.roles:
                        try:
                            await spouse.remove_roles(marry_role)
                        except discord.Forbidden:
                            pass

        for child in self.children:
            child.disabled = True

        await interaction.response.edit_message(
            content=f"💔 Ваш брак официально расторгнут. Роль <@&{MARRY_ROLE_ID}> была снята.",
            view=self
        )

        if spouse_id:
            spouse = guild.get_member(spouse_id) if guild else None
            if spouse:
                try:
                    await spouse.send(f"💔 {interaction.user.mention} расторг(ла) ваш брак.")
                except discord.Forbidden:
                    pass

    @discord.ui.button(label="Переименовать лавруму", style=discord.ButtonStyle.primary, emoji="✏️")
    async def rename_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = RenameRoomModal()
        await interaction.response.send_modal(modal)


# ==========================================
# 5. ФОНОВЫЙ ТАЙМЕР НАКАЗАНИЙ
# ==========================================

@tasks.loop(seconds=15)
async def check_punishments():
    punishments = load_punishments()
    if not punishments:
        return

    current_time = time.time()
    updated_punishments = []

    for item in punishments:
        if current_time >= item["unpunish_time"]:
            guild = bot.get_guild(item["guild_id"])
            if guild:
                member = guild.get_member(item["user_id"])
                if not member:
                    try:
                        member = await guild.fetch_member(item["user_id"])
                    except Exception:
                        member = None

                if member:
                    role = guild.get_role(item["role_id"])
                    if role and role in member.roles:
                        try:
                            await member.remove_roles(role)
                        except discord.Forbidden:
                            print(f"Не удалось снять роль наказания с {member.id}: нет прав.")

                    saved_roles = [guild.get_role(rid) for rid in item.get("saved_roles", []) if guild.get_role(rid) is not None]
                    for r in saved_roles:
                        try:
                            await member.add_roles(r)
                        except Exception as e:
                            print(f"Ошибка при возврате роли {r.name}: {e}")
        else:
            updated_punishments.append(item)

    save_punishments(updated_punishments)


# ==========================================
# 6. СОБЫТИЯ И СЛЭШ-КОМАНДЫ
# ==========================================

@bot.event
async def on_ready():
    # Глобальная синхронизация команд (не вызывает ошибку 403 при неверном GUILD_ID)
    try:
        synced = await bot.tree.sync()
        print(f"✅ Команды синхронизированы глобально! Всего: {len(synced)}")
    except Exception as e:
        print(f" Ошибка синхронизации: {e}")

    if not check_punishments.is_running():
        check_punishments.start()
    print(f"✅ Бот {bot.user.name} успешно запущен!")


@bot.tree.command(name="verify", description="Выдать роль подопечному через верификацию")
@app_commands.describe(member="Выберите пользователя (подопечного)")
async def verify_command(interaction: discord.Interaction, member: discord.Member):
    support_role = interaction.guild.get_role(SUPPORT_ROLE_ID)
    if support_role not in interaction.user.roles:
        await interaction.response.send_message("❌ У вас нет роли Саппорта для выполнения этой команды!", ephemeral=True)
        return

    view = SupportView(target_member=member, author=interaction.user)
    await interaction.response.send_message(
        content=f"Выберите роль для пользователя {member.mention}:",
        view=view,
        ephemeral=True
    )


@bot.tree.command(name="nakazanie", description="Выдать наказание плохишу")
@app_commands.describe(member="Выберите пользователя (или введите его ID)")
async def nakazanie_command(interaction: discord.Interaction, member: discord.Member):
    mod_role = interaction.guild.get_role(MOD_ROLE_ID)
    if mod_role not in interaction.user.roles:
        await interaction.response.send_message("❌ У вас нет доступа к этой команде!", ephemeral=True)
        return

    view = PunishView(target_member=member, author=interaction.user)
    await interaction.response.send_message(
        content=f"Какое наказание дать плохишу {member.mention}?",
        view=view,
        ephemeral=True
    )


@bot.tree.command(name="marry", description="Сделать предложение человеку")
@app_commands.describe(user="Выберите человека, которому хотите сделать предложение")
async def marry_command(interaction: discord.Interaction, user: discord.Member):
    if user.id == interaction.user.id:
        await interaction.response.send_message("❌ Вы не можете сделать предложение самому себе!", ephemeral=True)
        return

    if user.bot:
        await interaction.response.send_message("❌ Нельзя сделать предложение боту!", ephemeral=True)
        return

    if get_spouse_id(interaction.user.id):
        await interaction.response.send_message("❌ Вы уже состоите в браке!", ephemeral=True)
        return

    if get_spouse_id(user.id):
        await interaction.response.send_message(f"❌ Пользователь {user.mention} уже состоит в браке!", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    try:
        view = ProposalView(author=interaction.user, target=user, guild_id=interaction.guild.id)
        await user.send(
            content=f"💍 **{interaction.user.mention}** предлагает вам вступить в брак на сервере **{interaction.guild.name}**!\n"
                    f"Принимаете ли вы предложение?",
            view=view
        )
        await interaction.followup.send(f"💌 Предложение отправлено в ЛС пользователю {user.mention}!", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(f"❌ У пользователя {user.mention} закрыты личные сообщения!", ephemeral=True)


@bot.tree.command(name="marry_manage", description="Управление браком и названием Love Room")
async def marry_manage_command(interaction: discord.Interaction):
    info = get_marriage_info(interaction.user.id)
    if not info:
        await interaction.response.send_message("❌ Вы не состоите в браке!", ephemeral=True)
        return

    spouse = interaction.guild.get_member(info["spouse_id"])
    spouse_name = spouse.mention if spouse else f"ID: {info['spouse_id']}"
    custom_name = info.get("custom_name") or "По умолчанию ((Имя 1) 💞 (Имя 2))"

    view = MarryManageView(author=interaction.user)
    await interaction.response.send_message(
        content=f"💕 **Управление браком**\n"
                f"• Ваш партнер: {spouse_name}\n"
                f"• Название комнаты: **{custom_name}**\n\n"
                f"Выберите действие:",
        view=view,
        ephemeral=True
    )


# ==========================================
# 7. АВТО-СОЗДАНИЕ И УДАЛЕНИЕ LOVE ROOM
# ==========================================

@bot.event
async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
    guild = member.guild

    if after.channel and after.channel.id == JOIN_VOICE_ID:
        info = get_marriage_info(member.id)
        if not info:
            return

        spouse_id = info["spouse_id"]
        spouse = guild.get_member(spouse_id)
        if not spouse:
            try:
                spouse = await guild.fetch_member(spouse_id)
            except Exception:
                spouse = None

        spouse_name = spouse.display_name if spouse else "Партнер"
        member_name = member.display_name

        category = guild.get_channel(TARGET_CATEGORY_ID)
        if not category or not isinstance(category, discord.CategoryChannel):
            print("Ошибка: Категория для Love Room не найдена!")
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True),
            member: discord.PermissionOverwrite(connect=True, view_channel=True, speak=True),
            guild.me: discord.PermissionOverwrite(connect=True, view_channel=True, manage_channels=True, move_members=True)
        }
        if spouse:
            overwrites[spouse] = discord.PermissionOverwrite(connect=True, view_channel=True, speak=True)

        if info.get("custom_name"):
            channel_name = info["custom_name"]
        else:
            channel_name = f"{member_name} 💞 {spouse_name}"

        try:
            love_channel = await guild.create_voice_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites
            )

            temp_love_channels.add(love_channel.id)
            await member.move_to(love_channel)

        except Exception as e:
            print(f"Ошибка при создании Love Room: {e}")

    if before.channel and before.channel.id in temp_love_channels:
        if len(before.channel.members) == 0:
            temp_love_channels.remove(before.channel.id)
            try:
                await before.channel.delete()
            except Exception as e:
                print(f"Ошибка при удалении Love Room: {e}")


# --- ЗАПУСК БОТА ---
bot.run(TOKEN)
