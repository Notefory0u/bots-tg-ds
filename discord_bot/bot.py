import discord
from discord.ext import commands, tasks
from discord import ui, app_commands
import os
import asyncio
from dotenv import load_dotenv

# Memory storage for 2-step verification codes
verification_codes = {}
from datetime import datetime, timedelta
import random
import re

# Import site models and utilities
from app import create_app, db
from app.models import Product, User, LoyaltyLevel, Game, DiscordGameNotification, Giveaway, Key, OrderItem

import logging

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('DarkZoneBot')

# Initialize Flask App Context for DB operations
flask_app = create_app()

# --- UI COMPONENTS FOR TICKETS ---

class CloseTicketView(ui.View):
    """View with a button to close the ticket."""
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🔒 Закрыть тикет", style=discord.ButtonStyle.danger, custom_id="close_ticket")
    async def close_callback(self, interaction: discord.Interaction, button: ui.Button):
        try:
            await interaction.response.send_message("⏳ Тикет будет закрыт через 5 секунд...")
            await asyncio.sleep(5)
            await interaction.channel.delete()
        except Exception as e:
            logger.error(f"Error closing ticket: {e}")

class TicketView(ui.View):
    """View with buttons to open different types of tickets."""
    def __init__(self):
        super().__init__(timeout=None) # Persistent view

    async def create_ticket(self, interaction: discord.Interaction, ticket_type: str, color: discord.Color):
        guild = interaction.guild
        user = interaction.user

        prefix = {
            "general": "gen",
            "tech": "tech",
            "media": "media"
        }.get(ticket_type, "ticket")

        # Check for existing open ticket for this user to prevent duplicates (debounce)
        existing_channel = discord.utils.get(guild.text_channels, name=f"{prefix}-{user.name[:10]}".lower())
        if existing_channel:
            await interaction.response.send_message(f"⚠️ У вас уже есть открытый тикет: {existing_channel.mention}", ephemeral=True)
            return

        # Create channel name
        channel_name = f"{prefix}-{user.name[:10]}"
        
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True)
        }

        # Try to find a Support role
        support_role = discord.utils.get(guild.roles, name="SUPPORT") or discord.utils.get(guild.roles, name="MODERATOR")
        if support_role:
            overwrites[support_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        category = discord.utils.get(guild.categories, name="TICKETS")
        if not category:
            category = await guild.create_category("TICKETS")

        ticket_channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            overwrites=overwrites,
            topic=f"Тикет ({ticket_type}) от {user.name} (ID: {user.id})"
        )

        descriptions = {
            "general": "Здесь вы можете задать любой общий вопрос по работе сервиса или покупке.",
            "tech": "Опишите вашу техническую проблему, прикрепите скриншоты ошибки и укажите название софта.",
            "media": "Прикрепите ссылку на ваш канал и скриншот статистики за последние 28 дней."
        }

        embed = discord.Embed(
            title=f"🎫 Тикет: {ticket_type.capitalize()}",
            description=f"Привет {user.mention}! {descriptions.get(ticket_type)}\nНаш персонал скоро свяжется с вами.",
            color=color
        )
        
        await ticket_channel.send(
            content=f"{user.mention} | {support_role.mention if support_role else ''}", 
            embed=embed, 
            view=CloseTicketView()
        )
        await interaction.response.send_message(f"✅ Ваш тикет открыт: {ticket_channel.mention}", ephemeral=True)

    @ui.button(label="📩 Общие вопросы", style=discord.ButtonStyle.primary, custom_id="ticket_general")
    async def general_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self.create_ticket(interaction, "general", discord.Color.blue())

    @ui.button(label="⚙️ Тех. поддержка", style=discord.ButtonStyle.secondary, custom_id="ticket_tech")
    async def tech_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self.create_ticket(interaction, "tech", discord.Color.orange())

    @ui.button(label="🎬 Стать медиа", style=discord.ButtonStyle.success, custom_id="ticket_media")
    async def media_ticket(self, interaction: discord.Interaction, button: ui.Button):
        await self.create_ticket(interaction, "media", discord.Color.magenta())

# --- BOT CLASS ---

class DarkZoneBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.members = True 
        intents.message_content = True
        intents.presences = True # Needed for online stats
        super().__init__(command_prefix="!", intents=intents)
        
        # Channel IDs
        self.status_channel_id = self._get_env_int('DISCORD_STATUS_CHANNEL_ID')
        self.log_channel_id = self._get_env_int('DISCORD_LOG_CHANNEL_ID')
        self.welcome_channel_id = self._get_env_int('DISCORD_WELCOME_CHANNEL_ID')
        self.rules_channel_id = self._get_env_int('DISCORD_RULES_CHANNEL_ID')
        self.link_channel_id = self._get_env_int('DISCORD_LINK_CHANNEL_ID')
        self.media_channel_id = self._get_env_int('DISCORD_MEDIA_CHANNEL_ID')
        self.support_channel_id = self._get_env_int('DISCORD_SUPPORT_CHANNEL_ID')
        
        # Stats IDs
        self.stats_category_id = self._get_env_int('DISCORD_STATS_CATEGORY_ID')
        self.stats_members_id = self._get_env_int('DISCORD_STATS_MEMBERS_ID')
        self.stats_online_id = self._get_env_int('DISCORD_STATS_ONLINE_ID')
        self.stats_voice_id = self._get_env_int('DISCORD_STATS_VOICE_ID')
        self.stats_working_id = self._get_env_int('DISCORD_STATS_WORKING_ID')
        
        # Cache for status tracking
        self.status_cache = {} # {product_id: status}

    def get_status_info(self, status_name):
        """Get icon and display text for a status name."""
        # Mapping for both legacy and manual statuses
        mapping = {
            # Legacy/Internal keys
            'UnDetect': {'icon': '🟢', 'text': 'Working (UD)', 'color': discord.Color.green()},
            'Detect': {'icon': '🔴', 'text': 'Detected', 'color': discord.Color.red()},
            'Update': {'icon': '🟠', 'text': 'Updating', 'color': discord.Color.orange()},
            'Zone': {'icon': '🟡', 'text': 'Risk / Zone', 'color': discord.Color.gold()},
            'Maintenance': {'icon': '🔵', 'text': 'Maintenance', 'color': discord.Color.blue()},
            
            # Common manual names (English)
            'Undetected': {'icon': '🟢', 'text': 'Undetected', 'color': discord.Color.green()},
            'Detected': {'icon': '🔴', 'text': 'Detected', 'color': discord.Color.red()},
            'Updating': {'icon': '🟠', 'text': 'Updating', 'color': discord.Color.orange()},
            'On Maintenance': {'icon': '🔵', 'text': 'Maintenance', 'color': discord.Color.blue()},
            
            # Common manual names (Russian)
            'Работает': {'icon': '🟢', 'text': 'Работает (UD)', 'color': discord.Color.green()},
            'Детект': {'icon': '🔴', 'text': 'Детект', 'color': discord.Color.red()},
            'Обновление': {'icon': '🟠', 'text': 'На обновлении', 'color': discord.Color.orange()},
            'Тех. работы': {'icon': '🔵', 'text': 'Тех. работы', 'color': discord.Color.blue()},
            'Риск': {'icon': '🟡', 'text': 'Риск / Использовать осторожно', 'color': discord.Color.gold()},
        }
        
        # Try exact match
        info = mapping.get(status_name)
        if info:
            return info
            
        # Try case-insensitive and partial match
        name_lower = status_name.lower()
        if 'undetect' in name_lower or 'работает' in name_lower or 'ud' in name_lower:
            return {'icon': '🟢', 'text': status_name, 'color': discord.Color.green()}
        if 'detect' in name_lower or 'детект' in name_lower:
            return {'icon': '🔴', 'text': status_name, 'color': discord.Color.red()}
        if 'update' in name_lower or 'обновлен' in name_lower:
            return {'icon': '🟠', 'text': status_name, 'color': discord.Color.orange()}
        if 'maintenance' in name_lower or 'тех' in name_lower:
            return {'icon': '🔵', 'text': status_name, 'color': discord.Color.blue()}
        if 'risk' in name_lower or 'zone' in name_lower or 'риск' in name_lower:
            return {'icon': '🟡', 'text': status_name, 'color': discord.Color.gold()}
            
        # Default fallback
        return {'icon': '⚪', 'text': status_name, 'color': discord.Color.light_grey()}

    def _get_env_int(self, key):
        val = os.environ.get(key)
        return int(val) if val and val.isdigit() else None

    async def setup_hook(self):
        self.update_status_loop.start()
        self.update_stats_loop.start()
        self.sync_roles_loop.start()
        self.check_giveaways_loop.start()
        self.check_expiring_keys_loop.start()
        # Add persistent views
        self.add_view(TicketView())
        self.add_view(CloseTicketView())
        try:
            synced = await self.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")
        print("Bot setup hook completed.")

    async def on_ready(self):
        print(f'Logged in as {self.user} (ID: {self.user.id})')
        print('------')

    # --- EVENTS ---

    async def on_member_join(self, member):
        """Welcome new members and give USER role."""
        # 1. Give USER role
        user_role = discord.utils.get(member.guild.roles, name="USER")
        if user_role:
            try:
                await member.add_roles(user_role)
            except Exception as e:
                logger.error(f"Failed to add USER role to {member.name}: {e}")

        # 2. Welcome message
        if not self.welcome_channel_id:
            return
        channel = self.get_channel(self.welcome_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title=f"👋 Добро пожаловать, {member.name}!",
            description=f"Рады видеть тебя на сервере **DarkZone**!\nЗагляни в <#{self.status_channel_id}>, чтобы узнать статус софта.",
            color=discord.Color.green()
        )
        if member.avatar:
            embed.set_thumbnail(url=member.avatar.url)
        embed.set_footer(text=f"Ты наш {member.guild.member_count}-й участник!")
        
        await channel.send(content=member.mention, embed=embed)

    async def on_message_delete(self, message):
        """Log deleted messages."""
        if message.author.bot or not self.log_channel_id:
            return
        channel = self.get_channel(self.log_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title="🗑️ Сообщение удалено",
            description=f"**Автор:** {message.author.mention} ({message.author.id})\n**Канал:** {message.channel.mention}",
            color=discord.Color.red(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Контент:", value=message.content[:1024] or "[Без текста]", inline=False)
        await channel.send(embed=embed)

    async def on_message_edit(self, before, after):
        """Log edited messages."""
        if before.author.bot or before.content == after.content or not self.log_channel_id:
            return
        channel = self.get_channel(self.log_channel_id)
        if not channel:
            return

        embed = discord.Embed(
            title="📝 Сообщение изменено",
            description=f"**Автор:** {before.author.mention} ({before.author.id})\n**Канал:** {before.channel.mention}",
            color=discord.Color.orange(),
            timestamp=datetime.utcnow()
        )
        embed.add_field(name="Было:", value=before.content[:1024] or "[Без текста]", inline=False)
        embed.add_field(name="Стало:", value=after.content[:1024] or "[Без текста]", inline=False)
        await channel.send(embed=embed)

    # --- TASKS ---

    @tasks.loop(minutes=10)
    async def update_status_loop(self):
        """Update product status in Discord channel."""
        if not self.status_channel_id:
            logger.warning("DISCORD_STATUS_CHANNEL_ID not set!")
            return
        
        channel = self.get_channel(self.status_channel_id)
        if not channel:
            logger.warning(f"Channel {self.status_channel_id} not found!")
            return

        try:
            with flask_app.app_context():
                products = Product.query.filter_by(status='active').order_by(Product.game_id).all()
                if not products:
                    logger.info("No active products found")
                    return
                
                logger.info(f"Updating status for {len(products)} products")
                
                # Extract all data we need while still in the app context
                products_data = []
                for p in products:
                    game_name = p.game.name if p.game else "Прочее"
                    # Use display_status property to prioritize manual status
                    current_status = p.display_status['name']
                    products_data.append({
                        'name': p.name,
                        'product_status': current_status,
                        'game_name': game_name,
                        'id': p.id
                    })

            embed = discord.Embed(
                title="🟢 DARKZONE | СТАТУС ТОВАРОВ",
                description=f"Актуальное состояние программного обеспечения на {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                color=discord.Color.from_rgb(46, 196, 182)
            )


            games = {}
            for p_data in products_data:
                game_name = p_data['game_name']
                if game_name not in games:
                    games[game_name] = []
                games[game_name].append(p_data)

            # Split games into chunks of 20 to avoid Discord's 25 fields limit
            game_list = list(games.items())
            chunk_size = 20
            chunks = [game_list[i:i + chunk_size] for i in range(0, len(game_list), chunk_size)]

            # Find and update existing messages or send new ones
            channel_messages = []
            async for message in channel.history(limit=10):
                if message.author == self.user and message.embeds and "СТАТУС ТОВАРОВ" in message.embeds[0].title:
                    channel_messages.append(message)
            
            # Sort messages by ID to ensure oldest (first) message gets the first chunk
            channel_messages.sort(key=lambda m: m.id)

            for chunk_idx, chunk in enumerate(chunks):
                embed = discord.Embed(
                    title="🟢 DARKZONE | СТАТУС ТОВАРОВ",
                    description=f"Актуальное состояние программного обеспечения на {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\nЧасть {chunk_idx + 1} из {len(chunks)}",
                    color=discord.Color.from_rgb(46, 196, 182)
                )

                for game_name, game_products in chunk:
                    value = ""
                    for p_data in game_products:
                        status_info = self.get_status_info(p_data['product_status'])
                        status_text = f"{status_info['icon']} {status_info['text']}"
                        value += f"**{p_data['name']}** — {status_text}\n"
                    embed.add_field(name=f"🎮 {game_name}", value=value, inline=False)

                # Update existing message or send new one
                if chunk_idx < len(channel_messages):
                    await channel_messages[chunk_idx].edit(embed=embed)
                else:
                    await channel.send(embed=embed)

            logger.info(f"Status embed updated successfully ({len(chunks)} message(s))")
            await self.check_status_changes(products_data)
            
        except Exception as e:
            logger.error(f"Error in update_status_loop: {e}", exc_info=True)

    async def check_status_changes(self, products_data):
        """Notify subscribers and post globally if a product status changes."""
        for p_data in products_data:
            old_status = self.status_cache.get(p_data['id'])
            if old_status and old_status != p_data['product_status']:
                # Post global update to status channel
                try:
                    channel = self.get_channel(self.status_channel_id)
                    if channel:
                        old_info = self.get_status_info(old_status)
                        new_info = self.get_status_info(p_data['product_status'])
                        
                        embed = discord.Embed(
                            title=f"🔄 ОБНОВЛЕНИЕ СТАТУСА: {p_data['name']}",
                            description=(
                                f"Статус товара **{p_data['name']}** был изменен!\n\n"
                                f"**БЫЛО:** {old_info['icon']} {old_info['text']}\n"
                                f"**СТАЛО:** {new_info['icon']} {new_info['text']}"
                            ),
                            color=new_info['color'],
                            timestamp=datetime.utcnow()
                        )
                        await channel.send(embed=embed)
                except Exception as e:
                    logger.error(f"Error posting status update to channel: {e}")

                # Notify subscribers
                await self.notify_subscribers(p_data, old_status)
            self.status_cache[p_data['id']] = p_data['product_status']

    async def notify_subscribers(self, p_data, old_status):
        """Send notification to all discord users subscribed to this game."""
        try:
            with flask_app.app_context():
                product = Product.query.get(p_data['id'])
                if not product or not product.game_id:
                    return
                
                # Get all subscribers for this game
                subs = DiscordGameNotification.query.filter_by(game_id=product.game_id).all()
                if not subs:
                    return
                
                logger.info(f"Notifying {len(subs)} subscribers about {p_data['name']} status change")
                
                old_info = self.get_status_info(old_status)
                new_info = self.get_status_info(p_data['product_status'])
                
                embed = discord.Embed(
                    title=f"🔔 Обновление статуса: {p_data['name']}",
                    description=(
                        f"Статус товара **{p_data['name']}** изменился!\n\n"
                        f"**БЫЛО:** {old_info['icon']} {old_info['text']}\n"
                        f"**СТАЛО:** {new_info['icon']} {new_info['text']}"
                    ),
                    color=new_info['color'],
                    timestamp=datetime.utcnow()
                )
                embed.set_footer(text="Вы получили это сообщение, так как подписаны на обновления этой игры.")
                
                for sub in subs:
                    user = self.get_user(sub.discord_id)
                    if not user:
                        try:
                            user = await self.fetch_user(sub.discord_id)
                        except:
                            continue
                    
                    if user:
                        try:
                            await user.send(embed=embed)
                            logger.info(f"Sent notification to {user.name} ({user.id})")
                        except discord.Forbidden:
                            logger.warning(f"Could not send DM to {sub.discord_id} (DMs closed)")
                        except Exception as e:
                            logger.error(f"Error sending DM to {sub.discord_id}: {e}")
        except Exception as e:
            logger.error(f"Error in notify_subscribers: {e}", exc_info=True)

    @update_status_loop.before_loop
    async def before_update_status_loop(self):
        await self.wait_until_ready()

    @tasks.loop(minutes=10)
    async def update_stats_loop(self):
        """Update server statistics in the sidebar."""
        guild_id = os.environ.get('DISCORD_GUILD_ID')
        if not guild_id:
            return
        guild = self.get_guild(int(guild_id))
        if not guild:
            return

        # Fetch data
        total_members = guild.member_count
        online_members = sum(1 for m in guild.members if m.status != discord.Status.offline)
        voice_members = sum(len(vc.members) for vc in guild.voice_channels)
        
        with flask_app.app_context():
            # Count working cheats using display_status (manual or legacy)
            all_active_products = Product.query.filter_by(status='active').all()
            working_cheats = 0
            for p in all_active_products:
                status_name = p.display_status['name']
                info = self.get_status_info(status_name)
                if info['icon'] == '🟢': # Working status
                    working_cheats += 1

        # Update channels
        stats_map = {
            self.stats_members_id: f"👤 Участников: {total_members}",
            self.stats_online_id: f"🌐 Онлайн: {online_members}",
            self.stats_voice_id: f"🔈 В войсе: {voice_members}",
            self.stats_working_id: f"✅ Читов работает: {working_cheats}"
        }

        for channel_id, new_name in stats_map.items():
            if channel_id:
                channel = self.get_channel(channel_id)
                if channel and channel.name != new_name:
                    try:
                        await channel.edit(name=new_name)
                    except Exception as e:
                        logger.error(f"Failed to update stat channel {channel_id}: {e}")

    @update_stats_loop.before_loop
    async def before_update_stats_loop(self):
        await self.wait_until_ready()

    @tasks.loop(hours=1)
    async def sync_roles_loop(self):
        """Periodically sync roles for all linked users in the guild."""
        guild_id = os.environ.get('DISCORD_GUILD_ID')
        if not guild_id:
            return
        guild = self.get_guild(int(guild_id))
        if not guild:
            return

        with flask_app.app_context():
            # Get all users with a linked Discord ID
            linked_users = User.query.filter(User.discord_id != None).all()
            for website_user in linked_users:
                member = guild.get_member(website_user.discord_id)
                if member:
                    await self.sync_user_roles(member, website_user)
        
    @sync_roles_loop.before_loop
    async def before_sync_roles_loop(self):
        await self.wait_until_ready()

    async def sync_user_roles(self, member, website_user):
        """Assign Discord roles based on website loyalty level."""
        if not website_user.loyalty_level_id:
            return

        with flask_app.app_context():
            level = LoyaltyLevel.query.get(website_user.loyalty_level_id)
            if not level:
                return
            
            level_name = level.name
            
        # Role mapping
        # Гость -> USER
        # Пользователь -> CUSTOMER
        # VIP -> VIP
        # VVIP -> VVIP
        
        target_role_name = "USER"
        if level_name == 'Пользователь':
            target_role_name = "CUSTOMER"
        elif level_name == 'VIP':
            target_role_name = "VIP"
        elif level_name == 'VVIP':
            target_role_name = "VVIP"
            
        guild = member.guild
        target_role = discord.utils.get(guild.roles, name=target_role_name)
        
        if not target_role:
            logger.warning(f"Role {target_role_name} not found in guild.")
            return

        # Check if user already has the role
        if target_role not in member.roles:
            try:
                # Optional: Remove other loyalty roles first? 
                # For now just add the new one.
                loyalty_roles = ["USER", "CUSTOMER", "VIP", "VVIP"]
                roles_to_remove = [r for r in member.roles if r.name in loyalty_roles and r.name != target_role_name]
                if roles_to_remove:
                    await member.remove_roles(*roles_to_remove)
                
                await member.add_roles(target_role)
                logger.info(f"Synced roles for {member.name}: Added {target_role_name}")
            except Exception as e:
                logger.error(f"Failed to sync roles for {member.name}: {e}")

    @tasks.loop(minutes=1)
    async def check_giveaways_loop(self):
        """Check for ended giveaways and pick winners."""
        try:
            with flask_app.app_context():
                now = datetime.utcnow()
                active_giveaways = Giveaway.query.filter(Giveaway.end_time <= now, Giveaway.is_ended == False).all()
                
                for ga in active_giveaways:
                    channel = self.get_channel(ga.channel_id)
                    if not channel:
                        continue
                    
                    try:
                        message = await channel.fetch_message(ga.message_id)
                        # Pick winner from reactions
                        reaction = discord.utils.get(message.reactions, emoji="🎉")
                        if not reaction:
                            await channel.send(f"❌ Розыгрыш **{ga.prize}** окончен, но никто не участвовал.")
                            ga.is_ended = True
                            db.session.commit()
                            continue
                        
                        users = [u async for u in reaction.users() if not u.bot]
                        if not users:
                            await channel.send(f"❌ Розыгрыш **{ga.prize}** окончен, но победители не найдены.")
                        else:
                            winners = random.sample(users, min(len(users), ga.winners_count))
                            winner_mentions = ", ".join([w.mention for w in winners])
                            
                            embed = discord.Embed(
                                title="🎉 РОЗЫГРЫШ ЗАВЕРШЕН!",
                                description=f"Приз: **{ga.prize}**\nПобедители: {winner_mentions}",
                                color=discord.Color.green()
                            )
                            await channel.send(content=winner_mentions, embed=embed)
                            
                        ga.is_ended = True
                        db.session.commit()
                    except Exception as e:
                        logger.error(f"Error finishing giveaway {ga.id}: {e}")
        except Exception as e:
            logger.error(f"Giveaway loop error: {e}")

    @check_giveaways_loop.before_loop
    async def before_check_giveaways_loop(self):
        await self.wait_until_ready()

    @tasks.loop(hours=12)
    async def check_expiring_keys_loop(self):
        """Check for keys expiring in 24 hours and notify users."""
        from datetime import timedelta
        try:
            with flask_app.app_context():
                now = datetime.utcnow()
                tomorrow = now + timedelta(days=1)
                
                # Get order items and filter by expiration manually since OrderItem.expires_at is a method, not a column
                # Narrow down by created_at to avoid loading thousands of old orders
                recent_items = OrderItem.query.filter(
                    OrderItem.created_at > now - timedelta(days=400)
                ).all()
                
                expiring_items = []
                for item in recent_items:
                    expires_at = item.get_expires_at()
                    if expires_at and tomorrow - timedelta(hours=12) < expires_at <= tomorrow:
                        expiring_items.append(item)
                
                for item in expiring_items:
                    user_site = User.query.get(item.order.user_id)
                    if user_site and user_site.discord_id:
                        discord_user = self.get_user(user_site.discord_id)
                        if discord_user:
                            expires_at = item.get_expires_at()
                            embed = discord.Embed(
                                title="⌛ СРОК ПОДПИСКИ ИСТЕКАЕТ",
                                description=(
                                    f"Ваша подписка на **{item.product_item.product.name}** закончится менее чем через 24 часа.\n"
                                    f"Истекает: {expires_at.strftime('%d.%m.%Y %H:%M') if expires_at else 'N/A'}\n\n"
                                    "Не забудьте продлить доступ на сайте!"
                                ),
                                color=discord.Color.red()
                            )
                            try:
                                await discord_user.send(embed=embed)
                            except:
                                pass
        except Exception as e:
            logger.error(f"Expiring keys loop error: {e}")

    @check_expiring_keys_loop.before_loop
    async def before_check_expiring_keys_loop(self):
        await self.wait_until_ready()

# --- COMMANDS ---

bot = DarkZoneBot()

@bot.tree.command(name="verify", description="Пройти двухэтапную верификацию / Pass two-step verification")
@app_commands.describe(vcode="Уникальный код (оставьте пустым для получения кода)")
async def verify_command(interaction: discord.Interaction, vcode: str = None):
    user_id = interaction.user.id
    
    if not vcode:
        # Step 1: Generate and provide code
        code = str(random.randint(100000, 999999))
        verification_codes[user_id] = code
        
        embed = discord.Embed(
            title="🔐 Шаг 1: Код верификации",
            description=f"Ваш уникальный код: **`{code}`**\n\nСкопируйте его и введите команду еще раз, передав этот код как аргумент `vcode`.\nПример: `/verify vcode:{code}`",
            color=discord.Color.blue()
        )
        embed.set_footer(text="Этот код действителен, пока бот включен и привязан к вашему аккаунту.")
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        # Step 2: Validate code
        expected_code = verification_codes.get(user_id)
        if not expected_code:
            await interaction.response.send_message("❌ У вас нет активного кода верификации. Сначала введите `/verify` без параметров.", ephemeral=True)
            return
            
        if str(vcode).strip() == expected_code:
            # Code matches! Clear from memory
            del verification_codes[user_id]
            
            # Give USER role
            user_role = discord.utils.get(interaction.guild.roles, name="USER")
            if user_role:
                try:
                    await interaction.user.add_roles(user_role)
                    await interaction.response.send_message("✅ **Верификация успешно пройдена!** Вы получили роль USER и доступ к серверу.", ephemeral=True)
                except Exception as e:
                    logger.error(f"Failed to add USER role in verification: {e}")
                    await interaction.response.send_message("⚠️ Пройден успешный этап верификации, но у бота не хватает прав для выдачи роли.", ephemeral=True)
            else:
                await interaction.response.send_message("✅ **Верификация успешно пройдена!** (Роль USER не найдена на сервере)", ephemeral=True)
        else:
            await interaction.response.send_message("❌ **Неверный код.** Попробуйте еще раз или запросите новый код, введя `/verify`.", ephemeral=True)

@bot.command(name="setup_stats")
@commands.has_permissions(administrator=True)
async def setup_stats(ctx):
    """Automatically creates the statistics category and channels."""
    guild = ctx.guild
    
    # 1. Create Category
    category = discord.utils.get(guild.categories, name="📊 СТАТИСТИКА")
    if not category:
        category = await guild.create_category("📊 СТАТИСТИКА", position=0)

    # Overwrites (Nobody can connect, everyone can see)
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(connect=False, view_channel=True)
    }

    # 2. Create Channels
    chan_names = ["👤 Участников: ...", "🌐 Онлайн: ...", "🔈 В войсе: ...", "✅ Читов работает: ..."]
    created_ids = []
    
    for name in chan_names:
        chan = await guild.create_voice_channel(name=name, category=category, overwrites=overwrites)
        created_ids.append(chan.id)

    # 3. Update Environment
    env_vars = {
        "DISCORD_STATS_CATEGORY_ID": category.id,
        "DISCORD_STATS_MEMBERS_ID": created_ids[0],
        "DISCORD_STATS_ONLINE_ID": created_ids[1],
        "DISCORD_STATS_VOICE_ID": created_ids[2],
        "DISCORD_STATS_WORKING_ID": created_ids[3]
    }
    
    # Manually append to .env for now
    with open(".env", "a", encoding="utf-8") as f:
        f.write("\n# Discord Statistics Channels\n")
        for k, v in env_vars.items():
            f.write(f"{k}={v}\n")
    
    # Update current bot instance
    bot.stats_category_id = category.id
    bot.stats_members_id = created_ids[0]
    bot.stats_online_id = created_ids[1]
    bot.stats_voice_id = created_ids[2]
    bot.stats_working_id = created_ids[3]

    await ctx.send("✅ Категория статистики создана и ID сохранены в .env! Статистика обновится в течение 10 минут.")

@bot.command(name="setup_support")
@commands.has_permissions(administrator=True)
async def setup_support(ctx):
    """Sends the support ticket panel with descriptions."""
    embed = discord.Embed(
        title="📩 Центр поддержки DarkZone",
        description=(
            "Выберите интересующую вас категорию, нажав на соответствующую кнопку ниже:\n\n"
            "📩 **Общие вопросы**\n"
            "Для вопросов по покупке, оплате или работе сайта.\n\n"
            "⚙️ **Тех. поддержка**\n"
            "Если у вас возникли проблемы с запуском или работой ПО.\n\n"
            "🎬 **Стать медиа**\n"
            "Подача заявки на сотрудничество для стримеров и блогеров."
        ),
        color=discord.Color.blue()
    )
    await ctx.send(embed=embed, view=TicketView())
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="create_roles")
@commands.has_permissions(administrator=True)
async def create_roles(ctx):
    """Automatically creates all necessary server roles with colors."""
    guild = ctx.guild
    
    # Define roles: (Name, Color, Permissions, Hoist)
    roles_data = [
        ("OWNER / ADMIN", discord.Color.red(), discord.Permissions(administrator=True), True),
        ("SUPPORT", discord.Color.blue(), discord.Permissions(manage_messages=True, manage_threads=True), True),
        ("MODERATOR", discord.Color.green(), discord.Permissions(manage_messages=True, kick_members=True, ban_members=True), True),
        ("VVIP", discord.Color.purple(), discord.Permissions(change_nickname=True), True),
        ("VIP", discord.Color.gold(), discord.Permissions(change_nickname=True), True),
        ("CUSTOMER", discord.Color.light_grey(), discord.Permissions(change_nickname=True), True),
        ("ELITE PARTNER", discord.Color.from_rgb(255, 20, 147), discord.Permissions(change_nickname=True), True),
        ("ADVANCED MEDIA", discord.Color.from_rgb(255, 105, 180), discord.Permissions(change_nickname=True), True),
        ("STARTER MEDIA", discord.Color.from_rgb(255, 182, 193), discord.Permissions(change_nickname=True), True),
        ("USER", discord.Color.default(), discord.Permissions(change_nickname=True), True),
    ]
    
    created_names = []
    
    for name, color, perms, hoist in roles_data:
        # Check if role already exists
        existing_role = discord.utils.get(guild.roles, name=name)
        if not existing_role:
            await guild.create_role(name=name, color=color, permissions=perms, hoist=hoist)
            created_names.append(name)
        else:
            # Update existing role if needed (optional, just logic here)
            pass

    if created_names:
        await ctx.send(f"✅ Успешно созданы роли: {', '.join(created_names)}")
    else:
        # If roles already exist, let's make sure they are hoisted
        for name, color, perms, hoist in roles_data:
            role = discord.utils.get(guild.roles, name=name)
            if role and not role.hoist:
                await role.edit(hoist=True)
        await ctx.send("ℹ️ Все роли настроены (отображаются отдельно).")

@bot.command(name="lock_channels")
@commands.has_permissions(administrator=True)
async def lock_channels(ctx):
    """Restricts writing in all channels except General and Media."""
    guild = ctx.guild
    allowed_channels = ['💬│general', '🎥│media-content']
    
    locked_count = 0
    for channel in guild.text_channels:
        if channel.name not in allowed_channels:
            # Set @everyone to not send messages
            await channel.set_permissions(guild.default_role, send_messages=False)
            locked_count += 1
            
    await ctx.send(f"🔒 Настройки доступа обновлены! Заблокировано каналов: {locked_count}.\nПисать можно только в: {', '.join(allowed_channels)}")

@bot.command(name="clear")
@commands.has_permissions(manage_messages=True)
async def clear(ctx, amount: int = 5):
    """Clear messages."""
    await ctx.channel.purge(limit=amount + 1)
    msg = await ctx.send(f"✅ Удалено {amount} сообщений.", delete_after=3)

@bot.command(name="catalog")
async def catalog(ctx):
    with flask_app.app_context():
        categories = db.session.query(Product.category).distinct().filter(Product.status == 'active').all()
        categories = [c[0] for c in categories if c[0]]
        if not categories:
            await ctx.send("Каталог пуст.")
            return
        embed = discord.Embed(title="📦 DarkZone Catalog", color=discord.Color.orange())
        for cat in categories:
            prods = Product.query.filter_by(category=cat, status='active').limit(5).all()
            prod_names = ", ".join([p.name for p in prods])
            embed.add_field(name=cat, value=f"Товары: {prod_names}...", inline=False)
        await ctx.send(embed=embed)

@bot.command(name="sync")
async def sync(ctx, code: str):
    """Link Discord account to website profile using sync code."""
    with flask_app.app_context():
        user = User.query.filter_by(discord_sync_code=code.upper()).first()
        
        if not user:
            await ctx.send("❌ **Неверный код синхронизации.** Проверьте код в профиле на сайте.")
            return
        
        if user.discord_id:
            if user.discord_id == ctx.author.id:
                await ctx.send("ℹ️ **Ваш аккаунт уже привязан к этому профилю.**")
            else:
                await ctx.send("⚠️ **Этот профиль уже привязан к другому Discord аккаунту.**")
            return

        # Check if this Discord ID is already linked to another website user
        existing_link = User.query.filter_by(discord_id=ctx.author.id).first()
        if existing_link:
            await ctx.send(f"⚠️ **Ваш Discord аккаунт уже привязан к профилю `{existing_link.username}`.**")
            return

        # Link account
        user.discord_id = ctx.author.id
        db.session.commit()
        
        await ctx.send(f"✅ **Успешно!** Аккаунт привязан к профилю `{user.username}` на сайте.\nВаша статистика и роли будут синхронизированы.")
        
        # Trigger immediate role sync
        await bot.sync_user_roles(ctx.author, user)

@bot.command(name="profile", aliases=["me"])
async def profile(ctx):
    """Show website profile statistics in private messages."""
    try:
        with flask_app.app_context():
            user = User.query.filter_by(discord_id=ctx.author.id).first()
            
            if not user:
                await ctx.author.send(f"❌ **Аккаунт не привязан.**\nИспользуйте `!sync <code>`, чтобы привязать профиль с сайта.\nКод можно найти в настройках профиля на https://darkzonecheats.ru/profile")
                if ctx.guild:
                    await ctx.send(f"{ctx.author.mention}, я отправил вам информацию о синхронизации в личные сообщения.")
                return

            level_name = "Гость"
            if user.loyalty_level_id:
                level = LoyaltyLevel.query.get(user.loyalty_level_id)
                if level:
                    level_name = level.name

            embed = discord.Embed(title=f"👤 Профиль: {user.username}", color=discord.Color.blue())
            if ctx.author.display_avatar:
                embed.set_thumbnail(url=ctx.author.display_avatar.url)
            
            embed.add_field(name="💰 Баланс", value=f"{user.balance} ₽", inline=True)
            embed.add_field(name="🛒 Потрачено", value=f"{user.total_spent} ₽", inline=True)
            embed.add_field(name="⭐ Статус", value=level_name, inline=True)
            
            # Check active keys (status 'sold' means issued to user)
            from app.models import Order, OrderItem, Key
            try:
                active_keys_count = db.session.query(Key).join(OrderItem).join(Order).filter(
                    Order.user_id == user.id,
                    Key.status == 'sold'
                ).count()
                
                if active_keys_count > 0:
                    embed.add_field(name="🔑 Активные подписки", value=f"{active_keys_count}", inline=False)
            except Exception as e:
                logger.error(f"Error querying active keys: {e}")
                
            embed.set_footer(text="DarkZone | darkzonecheats.ru")
            
            try:
                await ctx.author.send(embed=embed)
                if ctx.guild:
                    await ctx.send(f"✅ {ctx.author.mention}, ваша статистика отправлена вам в личные сообщения.", delete_after=10)
            except discord.Forbidden:
                await ctx.send(f"❌ {ctx.author.mention}, я не могу отправить вам сообщение (личка закрыта).")
    except Exception as e:
        logger.error(f"Unhandled error in profile command: {e}")
        await ctx.send("🚨 Произошла ошибка при получении профиля. Разработчик уведомлен.")

@bot.command(name="notify")
async def notify(ctx, *, game_name: str = None):
    """Subscribe to game status updates."""
    if not game_name:
        await ctx.send("❓ Укажите название игры. Пример: `!notify Rust`")
        return

    with flask_app.app_context():
        game = Game.query.filter(Game.name.ilike(f"%{game_name}%")).first()
        if not game:
            await ctx.send(f"❌ Игра **{game_name}** не найдена в базе.")
            return

        # Check existing
        existing = DiscordGameNotification.query.filter_by(discord_id=ctx.author.id, game_id=game.id).first()
        if existing:
            await ctx.send(f"ℹ️ Вы уже подписаны на обновления **{game.name}**.")
            return

        # Link website user if synced
        website_user = User.query.filter_by(discord_id=ctx.author.id).first()
        
        sub = DiscordGameNotification(
            discord_id=ctx.author.id,
            game_id=game.id,
            user_id=website_user.id if website_user else None
        )
        db.session.add(sub)
        db.session.commit()
        
        await ctx.send(f"✅ Успешно! Теперь вы будете получать уведомления при изменении статуса **{game.name}** в ЛС.")

@bot.command(name="unnotify")
async def unnotify(ctx, *, game_name: str = None):
    """Unsubscribe from game status updates."""
    if not game_name:
        await ctx.send("❓ Укажите название игры. Пример: `!unnotify Rust`")
        return

    with flask_app.app_context():
        game = Game.query.filter(Game.name.ilike(f"%{game_name}%")).first()
        if not game:
            await ctx.send(f"❌ Игра **{game_name}** не найдена.")
            return

        sub = DiscordGameNotification.query.filter_by(discord_id=ctx.author.id, game_id=game.id).first()
        if not sub:
            await ctx.send(f"❌ Вы не подписаны на обновления **{game.name}**.")
            return

        db.session.delete(sub)
        db.session.commit()
        await ctx.send(f"🔕 Вы отписались от уведомлений **{game.name}**.")

@bot.command(name="giveaway")
@commands.has_permissions(administrator=True)
async def giveaway(ctx, duration: str, winners: int, *, prize: str):
    """Start a giveaway. Example: !giveaway 1h 2 VIP Key"""
    # Parse duration (e.g. 1h, 10m, 1d)
    match = re.match(r"(\d+)([smhd])", duration.lower())
    if not match:
        await ctx.send("❌ Неверный формат времени! Используйте: 1m, 1h, 1d.")
        return

    amount = int(match.group(1))
    unit = match.group(2)
    
    delta = {
        's': timedelta(seconds=amount),
        'm': timedelta(minutes=amount),
        'h': timedelta(hours=amount),
        'd': timedelta(days=amount)
    }[unit]

    end_time = datetime.utcnow() + delta
    
    embed = discord.Embed(
        title="🎁 НОВЫЙ РОЗЫГРЫШ!",
        description=(
            f"Приз: **{prize}**\n"
            f"Победителей: **{winners}**\n"
            f"Заканчивается: <t:{int(end_time.timestamp())}:R>\n\n"
            "Нажмите 🎉 чтобы участвовать!"
        ),
        color=discord.Color.blue()
    )
    embed.set_footer(text=f"Завершение: {end_time.strftime('%d.%m.%Y %H:%M')}")
    
    message = await ctx.send(embed=embed)
    await message.add_reaction("🎉")
    
    # Save to DB
    with flask_app.app_context():
        ga = Giveaway(
            message_id=message.id,
            channel_id=ctx.channel.id,
            prize=prize,
            winners_count=winners,
            end_time=end_time
        )
        db.session.add(ga)
        db.session.commit()
    
    try:
        await ctx.message.delete()
    except:
        pass

@bot.command(name="ping")
async def ping(ctx):
    await ctx.send(f"🏓 Pong! Latency: {round(bot.latency * 1000)}ms")

@bot.command(name="setup_info")
@commands.has_permissions(administrator=True)
async def setup_info(ctx):
    """Sends server information to their respective channels."""
    
    # 1. RULES
    if bot.rules_channel_id:
        rules_chan = bot.get_channel(bot.rules_channel_id)
        if rules_chan:
            rules_embed = discord.Embed(
                title="🌑 DarkZone | Основные правила",
                description=(
                    "1. **Безопасность прежде всего.** Запрещено распространение вредоносного ПО.\n"
                    "2. **Уважение.** Оскорбления и токсичность в сторону администрации или участников караются баном.\n"
                    "3. **Запрет перепродажи.** Попытка перепродать наши ключи или аккаунты приведет к блокировке.\n"
                    "4. **Актуальность.** Всегда проверяйте статус товара в канале <#" + str(bot.status_channel_id if bot.status_channel_id else '1492198671435956415') + "> перед использованием."
                ),
                color=discord.Color.red()
            )
            rules_embed.set_footer(text="Ваша покупка — ваше согласие с правилами.")
            await rules_chan.send(embed=rules_embed)

    # 2. MEDIA (MEDIA-NET)
    if bot.media_channel_id:
        media_chan = bot.get_channel(bot.media_channel_id)
        if media_chan:
            media_embed = discord.Embed(
                title="🎬 DarkZone Media-Net | Программа лояльности",
                description="Мы ищем талантливых контент-мейкеров (TikTok, YouTube, Twitch) для развития сообщества.",
                color=discord.Color.from_rgb(255, 20, 147)
            )
            media_embed.add_field(
                name="📊 Уровень: Starter",
                value=(
                    "• TikTok: 20k+ просмотров/мес\n"
                    "• YouTube: 100+ сабов / 5k+ просмотров\n"
                    "🎁 **Награда:** Ключи 1-7 дней + роль + реферальный % = 10."
                ),
                inline=False
            )
            media_embed.add_field(
                name="🔥 Уровень: Advanced",
                value=(
                    "• TikTok: 50k+ просмотров/мес\n"
                    "• YouTube: 500+ сабов / 15k+ просмотров\n"
                    "🎁 **Награда:** Ключи 1-30 дней + спуффер + личный промокод + реферальный % = 15."
                ),
                inline=False
            )
            media_embed.add_field(
                name="💎 Уровень: Elite",
                value=(
                    "• TikTok: 200k+ просмотров/мес\n"
                    "• YouTube: 5k+ сабов / 50k+ просмотров\n"
                    "🎁 **Награда:** Выплаты 15% от продаж + приоритетная поддержка + личный промокод + ключи (на любой софт), аккаунты, спуффер + фиксированная зарплата (дополнительная) + всесторонняя поддержка с нашей стороны."
                ),
                inline=False
            )
            media_embed.set_footer(text="Подать заявку можно в тикетах поддержки.")
            await media_chan.send(embed=media_embed)

    # 3. LINKS & SUPPORT 
    if bot.link_channel_id:
        link_chan = bot.get_channel(bot.link_channel_id)
        if link_chan:
            links_embed = discord.Embed(
                title="🔗 Полезные ссылки",
                description=(
                    "🌐 **Сайт:** https://darkzonecheats.ru/\n"
                    "💬 **Telegram канал:** https://t.me/DarkZone_offshop\n\n"
                    f"Нужна помощь? Создайте тикет в канале <#{bot.support_channel_id if bot.support_channel_id else '1492202685040922624'}> для связи с нами."
                ),
                color=discord.Color.blue()
            )
            await link_chan.send(embed=links_embed)

    # 4. SUPPORT PANEL (AUTO-SEND)
    if bot.support_channel_id:
        support_chan = bot.get_channel(bot.support_channel_id)
        if support_chan:
            panel_embed = discord.Embed(
                title="🎫 Поддержка DarkZone",
                description=(
                    "Выберите нужную категорию тикета ниже, чтобы получить помощь.\n\n"
                    "⚙️ **Тех. поддержка** — проблемы с софтом или запуском.\n"
                    "📩 **Общие вопросы** — по поводу покупки, оплаты или сайта.\n"
                    "🎬 **Стать медиа** — подача заявки в Media-Net."
                ),
                color=discord.Color.blue()
            )
            await support_chan.send(embed=panel_embed, view=TicketView())

    await ctx.send("✅ Все информационные каналы обновлены!", delete_after=5)
    try:
        await ctx.message.delete()
    except:
        pass

async def main():
    token = os.environ.get('DISCORD_BOT_TOKEN')
    if not token or token in ['your-discord-bot-token', '']:
        logger.error("DISCORD_BOT_TOKEN is not set in .env")
        return
    async with bot:
        logger.info("Starting bot...")
        await bot.start(token)

if __name__ == '__main__':
    asyncio.run(main())
